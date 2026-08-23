export function collectClientContext(): Record<string, unknown> {
  return {
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    viewport: [innerWidth, innerHeight],
    screen: [screen.width, screen.height],
    pixelRatio: devicePixelRatio,
    touchPoints: navigator.maxTouchPoints || 0,
  };
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
