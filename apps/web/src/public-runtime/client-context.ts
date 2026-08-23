export type ClientContextLevel = "off" | "standard" | "enhanced" | "fingerprint";

type ExtendedNavigator = Navigator & { deviceMemory?: number };

export function collectClientContext(
  level: ClientContextLevel | undefined,
): Record<string, unknown> | undefined {
  if (level === "off") return undefined;
  const context: Record<string, unknown> = {
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    viewport: [innerWidth, innerHeight],
    screen: [screen.width, screen.height],
    pixelRatio: devicePixelRatio,
    touchPoints: navigator.maxTouchPoints || 0,
  };
  if (level === "enhanced") {
    const extended = navigator as ExtendedNavigator;
    Object.assign(context, {
      hardwareConcurrency: navigator.hardwareConcurrency || null,
      deviceMemory: extended.deviceMemory || null,
      colorDepth: screen.colorDepth || null,
    });
  }
  return context;
}

export function withClientContext(
  metadata: Record<string, unknown>,
  clientContext: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const result = { ...metadata };
  delete result.requestContext;
  delete result.clientContext;
  if (clientContext) result.clientContext = clientContext;
  return result;
}
