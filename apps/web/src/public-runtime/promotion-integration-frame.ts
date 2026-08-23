import {
  collectDeviceFingerprint,
  type DeviceFingerprintPayload,
} from "./device-fingerprint";
import { collectClientContext, withClientContext } from "./client-context";

type IntegrationRuntimeConfig = {
  integration: { id: string; key: string; version: string };
  channel: {
    id: string;
    slug: string;
    countryCode: string;
    trafficSource: "direct" | "fission";
  };
  template: { id: string; version: string };
  eventUrl: string;
  sessionToken: string;
  sessionExpiresAt: number;
  deviceSignals: "off" | "standard" | "enhanced" | "fingerprint";
  fingerprintEnabled: boolean;
  events: string[];
  visitorStorageKey: string;
};

type IntegrationBridge = {
  version: string;
  ready(): Promise<IntegrationRuntimeConfig>;
  report(eventType: string, metadata?: Record<string, unknown>): Promise<Response>;
};

declare global {
  interface Window {
    PromotionIntegrationBridge?: IntegrationBridge;
  }
}

const script = document.currentScript as HTMLScriptElement | null;
const integrationId = script?.dataset.integrationId || "";
const fragment = new URLSearchParams(location.hash.replace(/^#/, ""));
const embedToken = fragment.get("parloqEmbedToken") || "";

if (integrationId && embedToken) {
  try {
    history.replaceState(null, "", `${location.pathname}${location.search}`);
  } catch {
    // The token remains usable only for its short server-side lifetime.
  }

  const identifier = () =>
    crypto.randomUUID?.() ||
      `${Date.now().toString(36)}-${crypto.getRandomValues(new Uint32Array(2)).join("-")}`;

  let resolvedConfig: IntegrationRuntimeConfig | undefined;
  let resolvedClientContext: Record<string, unknown> | undefined;
  let clientContextResolved = false;
  const clientContext = (config: IntegrationRuntimeConfig) => {
    if (!clientContextResolved) {
      resolvedClientContext = collectClientContext(config.deviceSignals);
      clientContextResolved = true;
    }
    return resolvedClientContext;
  };
  const configPromise = fetch(
    `/api/public/promotion/integrations/${encodeURIComponent(integrationId)}/runtime`,
    {
      headers: { Authorization: `Bearer ${embedToken}` },
      cache: "no-store",
    },
  ).then(async (response) => {
    if (!response.ok) throw new Error("integration_runtime_unavailable");
    const payload = (await response.json()) as {
      data?: IntegrationRuntimeConfig;
    };
    if (!payload.data?.eventUrl || !payload.data.sessionToken) {
      throw new Error("integration_runtime_invalid");
    }
    resolvedConfig = payload.data;
    return payload.data;
  });

  let resolvedVisitorId = "";
  let visitorPromise: Promise<string> | undefined;
  const visitorId = () =>
    (visitorPromise ||= configPromise.then((config) => {
      const generated = identifier();
      try {
        const stored = localStorage.getItem(config.visitorStorageKey);
        if (stored) {
          resolvedVisitorId = stored;
          return stored;
        }
        localStorage.setItem(config.visitorStorageKey, generated);
      } catch {
        // A stable ID is best effort when iframe storage is unavailable.
      }
      resolvedVisitorId = generated;
      return generated;
    }));

  let fingerprintPromise: Promise<DeviceFingerprintPayload | undefined> | undefined;
  const fingerprint = () =>
    (fingerprintPromise ||= configPromise.then((config) =>
      config.fingerprintEnabled
        ? collectDeviceFingerprint().catch(() => undefined)
        : undefined,
    ));

  const eventBody = async (
    config: IntegrationRuntimeConfig,
    eventType: string,
    idempotencyKey: string,
    metadata: Record<string, unknown>,
    deviceFingerprint?: DeviceFingerprintPayload,
  ) =>
    JSON.stringify({
      eventType,
      idempotencyKey,
      visitorId: await visitorId(),
      sessionToken: config.sessionToken,
      occurredAt: new Date().toISOString(),
      metadata: withClientContext(metadata, clientContext(config)),
      ...(deviceFingerprint ? { deviceFingerprint } : {}),
    });

  const send = async (
    eventType: string,
    metadata: Record<string, unknown> = {},
    idempotencyKey = identifier(),
    deviceFingerprint?: DeviceFingerprintPayload,
  ) => {
    const config = await configPromise;
    if (!config.events.includes(eventType)) {
      throw new Error("integration_event_not_declared");
    }
    return fetch(config.eventUrl, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: await eventBody(
        config,
        eventType,
        idempotencyKey,
        metadata,
        deviceFingerprint,
      ),
      keepalive: true,
    });
  };

  window.PromotionIntegrationBridge = {
    version: "promotion-integration-bridge/v1",
    ready: () => configPromise,
    report: async (eventType, metadata = {}) => {
      const deviceFingerprint = await Promise.race([
        fingerprint(),
        new Promise<undefined>((resolve) => window.setTimeout(resolve, 800)),
      ]);
      return send(eventType, metadata, identifier(), deviceFingerprint);
    },
  };

  const startedAt = Date.now();
  void configPromise
    .then(async () => {
      const pageEventId = identifier();
      const metadata = {};
      await send("page_view", metadata, pageEventId).catch(() => undefined);
      const deviceFingerprint = await fingerprint();
      if (deviceFingerprint) {
        await send(
          "page_view",
          metadata,
          pageEventId,
          deviceFingerprint,
        ).catch(() => undefined);
      }
    })
    .catch(() => undefined);

  addEventListener("pagehide", () => {
    if (
      !resolvedConfig ||
      !resolvedVisitorId ||
      !resolvedConfig.events.includes("visit_end")
    ) {
      return;
    }
    navigator.sendBeacon(
      resolvedConfig.eventUrl,
      new Blob(
        [
          JSON.stringify({
            eventType: "visit_end",
            idempotencyKey: identifier(),
            visitorId: resolvedVisitorId,
            sessionToken: resolvedConfig.sessionToken,
            occurredAt: new Date().toISOString(),
            metadata: withClientContext(
              { durationMs: Math.max(0, Date.now() - startedAt) },
              clientContext(resolvedConfig),
            ),
          }),
        ],
        { type: "text/plain;charset=UTF-8" },
      ),
    );
  });
}

export {};
