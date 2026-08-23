import { collectDeviceFingerprint } from "./device-fingerprint";
import { collectClientContext, withClientContext } from "./client-context";

type IntegrationRuntimeConfig = {
  integration: { id: string };
  channel: {
    slug: string;
    trafficSource: "direct" | "fission";
  };
  eventUrl: string;
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
const channelSlug = fragment.get("parloqChannel") || "";
const requestedTrafficSource = fragment.get("parloqTrafficSource");
const trafficSource = requestedTrafficSource === "fission" ? "fission" : "direct";

if (integrationId && channelSlug) {
  try {
    history.replaceState(null, "", `${location.pathname}${location.search}`);
  } catch {
    // Fragment context is non-secret and can safely remain when history is locked.
  }

  const eventUrl =
    `/api/public/promotion/integrations/${encodeURIComponent(integrationId)}` +
    `/channels/${encodeURIComponent(channelSlug)}` +
    `${trafficSource === "fission" ? "/fission" : ""}/events`;
  const config: IntegrationRuntimeConfig = {
    integration: { id: integrationId },
    channel: { slug: channelSlug, trafficSource },
    eventUrl,
  };
  const configPromise = Promise.resolve(config);
  const clientContext = collectClientContext();
  let resolvedFingerprint = "";
  const fingerprintPromise = collectDeviceFingerprint().then((value) => {
    resolvedFingerprint = value;
    return value;
  });

  const eventBody = (
    eventType: string,
    metadata: Record<string, unknown>,
    deviceFingerprint: string,
  ) =>
    JSON.stringify({
      eventType,
      deviceFingerprint,
      occurredAt: new Date().toISOString(),
      metadata: withClientContext(metadata, clientContext),
    });

  const send = async (
    eventType: string,
    metadata: Record<string, unknown> = {},
  ) =>
    fetch(eventUrl, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: eventBody(eventType, metadata, await fingerprintPromise),
      keepalive: true,
    });

  window.PromotionIntegrationBridge = {
    version: "promotion-integration-bridge/v2",
    ready: () => configPromise,
    report: send,
  };

  const startedAt = Date.now();
  void send("page_view").catch(() => undefined);

  addEventListener("pagehide", () => {
    if (!resolvedFingerprint) return;
    navigator.sendBeacon(
      eventUrl,
      new Blob(
        [
          eventBody(
            "visit_end",
            { durationMs: Math.max(0, Date.now() - startedAt) },
            resolvedFingerprint,
          ),
        ],
        { type: "text/plain;charset=UTF-8" },
      ),
    );
  });
}

export {};
