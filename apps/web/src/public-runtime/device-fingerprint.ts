import { Thumbmark } from "@thumbmarkjs/thumbmarkjs";

export const FINGERPRINT_STORAGE_KEY = "_fp";

const THUMBMARK_PATTERN = /^[0-9a-f]{32}$/;
const FALLBACK_PATTERN = /^fb_[a-z0-9]+_[0-9]{10,16}$/;

function storedFingerprint(): string | undefined {
  try {
    const value = localStorage.getItem(FINGERPRINT_STORAGE_KEY) || "";
    return THUMBMARK_PATTERN.test(value) || FALLBACK_PATTERN.test(value)
      ? value
      : undefined;
  } catch {
    return undefined;
  }
}

function saveFingerprint(value: string): void {
  try {
    localStorage.setItem(FINGERPRINT_STORAGE_KEY, value);
  } catch {
    // Persistence is best effort when browser storage is unavailable.
  }
}

function fallbackFingerprint(): string {
  return `fb_${Math.random().toString(36).slice(2)}_${Date.now()}`;
}

export async function collectDeviceFingerprint(): Promise<string> {
  const cached = storedFingerprint();
  if (cached) return cached;

  let fingerprint: string;
  try {
    const result = await new Thumbmark({ logging: false }).get();
    if (!THUMBMARK_PATTERN.test(result.thumbmark)) {
      throw new Error("empty_thumbmark");
    }
    fingerprint = result.thumbmark;
  } catch {
    fingerprint = fallbackFingerprint();
  }

  saveFingerprint(fingerprint);
  return fingerprint;
}
