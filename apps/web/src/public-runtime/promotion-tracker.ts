import {
  collectDeviceFingerprint,
} from "./device-fingerprint";
import {
  collectClientContext,
  withClientContext,
} from "./client-context";

type RuntimeConfig = {
  eventUrl: string;
  pairingStartUrl: string;
  metaDomainReportUrl?: string;
  inAppBrowserMode?: "allow" | "guide_external";
  meta?: {
    datasetId?: string;
    browserEnabled?: boolean;
    eventMapping?: Record<string, string>;
  };
};

type EventExtra = {
  phone?: string;
  metadata?: Record<string, unknown>;
};

type PairingHandle = {
  statusToken: string;
  statusUrl: string;
  cancelUrl: string;
};

type BridgeError = Error & {
  code?: string;
  retryable?: boolean;
  status?: number;
};

type MetaPixelFunction = ((...args: unknown[]) => void) & {
  callMethod?: (...args: unknown[]) => void;
  queue: unknown[][];
  push: (...args: unknown[]) => void;
  loaded: boolean;
  version: string;
};

declare global {
  interface Window {
    PromotionBridge?: {
      version: string;
      submitPhone(phone: string, metadata?: Record<string, unknown>): Promise<Response>;
      getPairingStatus(pairing: PairingHandle): Promise<Response>;
      cancelPairing(pairing: PairingHandle): Promise<Response>;
    };
    fbq?: MetaPixelFunction;
    _fbq?: MetaPixelFunction;
    __promotionInspectionBlocked?: boolean;
  }
}

const configNode = document.getElementById("promotion-runtime-config");
if (configNode) {
  let config: RuntimeConfig | undefined;
  try {
    config = JSON.parse(configNode.textContent || "{}") as RuntimeConfig;
  } catch {
    config = undefined;
  }

  if (config?.eventUrl && config.pairingStartUrl) {
    const startedAt = Date.now();
    const meta = config.meta || {};
    let resolvedFingerprint = "";
    const fingerprintPromise: Promise<string> = new Promise((resolve) => {
      const collect = () =>
        void collectDeviceFingerprint().then((value) => {
          resolvedFingerprint = value;
          resolve(value);
        });
      if ("requestIdleCallback" in window) {
        window.requestIdleCallback(collect, { timeout: 250 });
      } else {
        globalThis.setTimeout(collect, 0);
      }
    });

    const seenMeta = (eventId: string) => {
      const key = `promotion_meta_event:${eventId}`;
      try {
        if (sessionStorage.getItem(key)) return true;
        sessionStorage.setItem(key, "1");
      } catch {
        // Pixel de-duplication is best effort when storage is unavailable.
      }
      return false;
    };

    if (
      meta.browserEnabled &&
      meta.datasetId &&
      /^[A-Za-z0-9_.:-]{1,120}$/.test(meta.datasetId)
    ) {
      if (config.metaDomainReportUrl) {
        const originalConsoleError = console.error;
        let domainUnavailableReported = false;
        console.error = (...args: unknown[]) => {
          originalConsoleError.apply(console, args);
          if (domainUnavailableReported) return;
          const message = args
            .map((value) =>
              typeof value === "string" ? value : String(value),
            )
            .join(" ");
          if (
            message.toLowerCase().includes("[meta pixel]") &&
            message.includes(meta.datasetId || "") &&
            message.toLowerCase().includes("is unavailable")
          ) {
            domainUnavailableReported = true;
            void fetch(config.metaDomainReportUrl || "", {
              method: "POST",
              headers: { "Content-Type": "text/plain;charset=UTF-8" },
              body: JSON.stringify({
                datasetId: meta.datasetId,
              }),
              keepalive: true,
            }).catch(() => undefined);
          }
        };
      }
      const pixel = function (...args: unknown[]) {
        if (pixel.callMethod) pixel.callMethod(...args);
        else pixel.queue.push(args);
      } as MetaPixelFunction;
      if (!window._fbq) window._fbq = pixel;
      window.fbq = pixel;
      pixel.push = (...args: unknown[]) => pixel(...args);
      pixel.loaded = true;
      pixel.version = "2.0";
      pixel.queue = [];
      const script = document.createElement("script");
      script.async = true;
      script.src = "https://connect.facebook.net/en_US/fbevents.js";
      document.head.appendChild(script);
      pixel("init", meta.datasetId);
    }

    const clientContext = collectClientContext();
    const body = (
      eventType: string,
      deviceFingerprint: string,
      extra: EventExtra = {},
    ) =>
      JSON.stringify({
        eventType,
        deviceFingerprint,
        ...extra,
        metadata: withClientContext(extra.metadata || {}, clientContext),
      });

    const send = async (eventType: string, extra: EventExtra = {}) =>
      fetch(config.eventUrl, {
        method: "POST",
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
        body: body(eventType, await fingerprintPromise, extra),
        keepalive: true,
      });

    const readResponseData = async (response: Response) => {
      try {
        return (await response.clone().json()) as {
          data?: {
            metaEvent?: { name?: string; eventId?: string };
          };
        };
      } catch {
        return {};
      }
    };

    const readMetaEvent = async (response: Response) => {
      const value = await readResponseData(response);
      const event = value.data?.metaEvent;
      if (
        event?.name &&
        event.eventId &&
        !seenMeta(event.eventId) &&
        window.fbq
      ) {
        window.fbq("track", event.name, {}, { eventID: event.eventId });
      }
      return response;
    };

    const fail = async (response: Response, fallback: string): Promise<never> => {
      let value: {
        error?: { message?: string; code?: string; retryable?: boolean };
        detail?: string;
      } = {};
      try {
        value = (await response.clone().json()) as typeof value;
      } catch {
        // Use the stable fallback below.
      }
      const info = value.error || {};
      const error = new Error(info.message || value.detail || fallback) as BridgeError;
      error.name = "AccountLinkError";
      error.code = info.code || fallback;
      error.retryable = Boolean(info.retryable);
      error.status = response.status;
      throw error;
    };

    const pairingHeaders = (pairing: PairingHandle) => ({
      Authorization: `Bearer ${pairing.statusToken}`,
    });
    const bridge = (window.PromotionBridge ||= {} as NonNullable<
      Window["PromotionBridge"]
    >);
    bridge.version = "promotion-browser-bridge/v2";
    bridge.submitPhone = async (
      phone: string,
      metadata: Record<string, unknown> = {},
    ) => {
        if (window.__promotionInspectionBlocked) throw new Error("inspection_blocked");
        const deviceFingerprint = await fingerprintPromise;
        const paired = await fetch(config.pairingStartUrl, {
          method: "POST",
          headers: { "Content-Type": "text/plain;charset=UTF-8" },
          body: JSON.stringify({
            phone,
            deviceFingerprint,
            metadata: withClientContext(metadata, clientContext),
          }),
        });
        if (!paired.ok) return fail(paired, "pairing_start_failed");
        return readMetaEvent(paired);
    };
    bridge.getPairingStatus = async (pairing: PairingHandle) =>
      readMetaEvent(
        await fetch(pairing.statusUrl, {
          method: "GET",
          headers: pairingHeaders(pairing),
          cache: "no-store",
        }),
      );
    bridge.cancelPairing = (pairing: PairingHandle) =>
      fetch(pairing.cancelUrl, {
        method: "POST",
        headers: pairingHeaders(pairing),
      });

    void send("page_view").then(readMetaEvent).catch(() => undefined);

    if (
      config.inAppBrowserMode === "guide_external" &&
      /(FBAN|FBAV|Instagram)/i.test(navigator.userAgent)
    ) {
      dispatchEvent(
        new CustomEvent("promotion:in-app-browser", {
          detail: { mode: "guide_external" },
        }),
      );
    }
    addEventListener("promotion:inspection-detected", (event) => {
      const detail = event instanceof CustomEvent ? event.detail : {};
      void send("inspection_detected", { metadata: detail || {} }).catch(
        () => undefined,
      );
    });
    document.addEventListener("submit", (event) => {
      if (!(event.target instanceof HTMLFormElement)) return;
      if (event.target.matches("form[data-promotion-manual]")) return;
      const phone = event.target.querySelector<HTMLInputElement>(
        'input[type="tel"],input[name*="phone" i]',
      );
      if (phone?.value) void bridge.submitPhone(phone.value).catch(() => undefined);
    });
    addEventListener("pagehide", () => {
      if (!resolvedFingerprint) return;
      navigator.sendBeacon(
        config.eventUrl,
        new Blob(
          [
            body("visit_end", resolvedFingerprint, {
              metadata: { durationMs: Math.max(0, Date.now() - startedAt) },
            }),
          ],
          { type: "text/plain;charset=UTF-8" },
        ),
      );
    });
  }
}
