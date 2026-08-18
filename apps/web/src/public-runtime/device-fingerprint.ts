export const FINGERPRINT_VERSION = "device-fingerprint/v1" as const;

type FingerprintProfile =
  | "chromium"
  | "brave"
  | "firefox"
  | "safari"
  | "other";

type Availability = "ok" | "unavailable" | "timeout" | "error";

export type DeviceFingerprintPayload = {
  version: typeof FINGERPRINT_VERSION;
  profile: FingerprintProfile;
  components: Record<string, string>;
  availability: Record<string, Availability>;
  elapsedMs: number;
};

type ExtendedNavigator = Navigator & {
  brave?: { isBrave?: () => Promise<boolean> };
  deviceMemory?: number;
};

type WebkitWindow = Window &
  typeof globalThis & {
    webkitOfflineAudioContext?: typeof OfflineAudioContext;
  };

const COMPONENT_TIMEOUT_MS = 700;
const TOTAL_TIMEOUT_MS = 1_200;
const FONT_CANDIDATES = [
  "Arial",
  "Arial Black",
  "Calibri",
  "Cambria",
  "Candara",
  "Comic Sans MS",
  "Courier New",
  "DejaVu Sans",
  "Futura",
  "Geneva",
  "Georgia",
  "Helvetica",
  "Impact",
  "Liberation Sans",
  "Lucida Console",
  "Menlo",
  "Microsoft Sans Serif",
  "Monaco",
  "Noto Sans",
  "Palatino",
  "Roboto",
  "Segoe UI",
  "Tahoma",
  "Times New Roman",
  "Trebuchet MS",
  "Ubuntu",
  "Verdana",
  "Wingdings",
] as const;

const delay = (milliseconds: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
    .join(",")}}`;
}

async function sha256(value: unknown): Promise<string> {
  if (!crypto.subtle) throw new Error("unavailable");
  const bytes = new TextEncoder().encode(stableJson(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function canvasSignal(): unknown {
  const canvas = document.createElement("canvas");
  canvas.width = 240;
  canvas.height = 80;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("unavailable");

  const gradient = context.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, "#f00");
  gradient.addColorStop(0.25, "#ff0");
  gradient.addColorStop(0.5, "#0f0");
  gradient.addColorStop(0.75, "#0ff");
  gradient.addColorStop(1, "#00f");
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.globalCompositeOperation = "multiply";
  context.fillStyle = "#f4f";
  context.font = "23.123px Arial";
  context.textBaseline = "alphabetic";
  context.fillText("Random Text WMwmil10Oo", 4, 38);
  context.globalCompositeOperation = "source-over";
  context.strokeStyle = "#fff";
  context.lineWidth = 1.25;
  context.beginPath();
  context.moveTo(2, 72);
  for (let x = 2; x < 238; x += 7) {
    context.lineTo(x, 58 + Math.sin(x / 9) * 13);
  }
  context.stroke();

  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const grid: string[] = [];
  const cellWidth = canvas.width / 20;
  const cellHeight = canvas.height / 20;
  for (let row = 0; row < 20; row += 1) {
    for (let column = 0; column < 20; column += 1) {
      const colors = new Map<string, number>();
      const startX = Math.floor(column * cellWidth);
      const endX = Math.floor((column + 1) * cellWidth);
      const startY = Math.floor(row * cellHeight);
      const endY = Math.floor((row + 1) * cellHeight);
      for (let y = startY; y < endY; y += 1) {
        for (let x = startX; x < endX; x += 1) {
          const offset = (y * canvas.width + x) * 4;
          const color = `${pixels[offset] >> 3}.${pixels[offset + 1] >> 3}.${pixels[offset + 2] >> 3}.${pixels[offset + 3] >> 4}`;
          colors.set(color, (colors.get(color) || 0) + 1);
        }
      }
      let common = "";
      let count = -1;
      for (const [color, occurrences] of colors) {
        if (occurrences > count || (occurrences === count && color < common)) {
          common = color;
          count = occurrences;
        }
      }
      grid.push(common);
    }
  }
  return grid;
}

function compileShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("unavailable");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    throw new Error("unavailable");
  }
  return shader;
}

function webglSignal(): unknown {
  const canvas = document.createElement("canvas");
  canvas.width = 96;
  canvas.height = 64;
  const gl = canvas.getContext("webgl", {
    antialias: true,
    preserveDrawingBuffer: true,
  });
  if (!gl) throw new Error("unavailable");

  const vertex = compileShader(
    gl,
    gl.VERTEX_SHADER,
    "attribute vec2 p;varying vec2 v;void main(){v=p;gl_Position=vec4(p,0.,1.);}",
  );
  const fragment = compileShader(
    gl,
    gl.FRAGMENT_SHADER,
    "precision mediump float;varying vec2 v;void main(){gl_FragColor=vec4(fract(sin(v.x*91.7)*431.2),abs(v.y),.37,1.);}",
  );
  const program = gl.createProgram();
  if (!program) throw new Error("unavailable");
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("unavailable");
  gl.useProgram(program);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
    gl.STATIC_DRAW,
  );
  const position = gl.getAttribLocation(program, "p");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.drawArrays(gl.TRIANGLES, 0, 6);
  const pixels = new Uint8Array(canvas.width * canvas.height * 4);
  gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  const sampled: number[] = [];
  for (let index = 0; index < pixels.length; index += 97) sampled.push(pixels[index]);

  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  const parameter = (name: number) => {
    try {
      return gl.getParameter(name);
    } catch {
      return null;
    }
  };
  return {
    vendor: debug ? parameter(debug.UNMASKED_VENDOR_WEBGL) : parameter(gl.VENDOR),
    renderer: debug
      ? parameter(debug.UNMASKED_RENDERER_WEBGL)
      : parameter(gl.RENDERER),
    version: parameter(gl.VERSION),
    shading: parameter(gl.SHADING_LANGUAGE_VERSION),
    maxTexture: parameter(gl.MAX_TEXTURE_SIZE),
    maxViewport: parameter(gl.MAX_VIEWPORT_DIMS),
    colorBits: [
      parameter(gl.RED_BITS),
      parameter(gl.GREEN_BITS),
      parameter(gl.BLUE_BITS),
      parameter(gl.ALPHA_BITS),
    ],
    pixels: sampled,
  };
}

async function audioSignal(): Promise<unknown> {
  const AudioContext =
    window.OfflineAudioContext ||
    (window as WebkitWindow).webkitOfflineAudioContext;
  if (!AudioContext) throw new Error("unavailable");
  const context = new AudioContext(1, 5_000, 44_100);
  const oscillator = context.createOscillator();
  const compressor = context.createDynamicsCompressor();
  oscillator.type = "triangle";
  oscillator.frequency.value = 1_000;
  compressor.threshold.value = -50;
  compressor.knee.value = 40;
  compressor.ratio.value = 12;
  compressor.attack.value = 0;
  compressor.release.value = 0.25;
  oscillator.connect(compressor);
  compressor.connect(context.destination);
  oscillator.start(0);
  const buffer = await context.startRendering();
  const samples = buffer.getChannelData(0);
  const quantized: number[] = [];
  for (let index = 0; index < samples.length; index += 5) {
    quantized.push(Math.round(samples[index] * 1_000_000));
  }
  return {
    sampleRate: buffer.sampleRate,
    length: buffer.length,
    maxChannelCount: context.destination.maxChannelCount,
    channelCountMode: context.destination.channelCountMode,
    samples: quantized,
  };
}

function fontSignal(): unknown {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) throw new Error("unavailable");
  const sample = "mmmmmmmmmmlliWW0123456789";
  const bases = ["monospace", "sans-serif", "serif"] as const;
  const baseline = Object.fromEntries(
    bases.map((base) => {
      context.font = `72px ${base}`;
      return [base, context.measureText(sample).width];
    }),
  );
  const detected: string[] = [];
  for (const font of FONT_CANDIDATES) {
    if (
      bases.some((base) => {
        context.font = `72px ${JSON.stringify(font)},${base}`;
        return Math.abs(context.measureText(sample).width - baseline[base]) > 0.01;
      })
    ) {
      detected.push(font);
    }
  }
  return detected;
}

function hardwareSignal(): unknown {
  const extended = navigator as ExtendedNavigator;
  return {
    platform: navigator.platform || "",
    cores: navigator.hardwareConcurrency || null,
    memory: extended.deviceMemory || null,
    touchPoints: navigator.maxTouchPoints || 0,
    architecture:
      (navigator as Navigator & { userAgentData?: { architecture?: string } })
        .userAgentData?.architecture || null,
  };
}

function localeSignal(): unknown {
  const resolved = Intl.DateTimeFormat().resolvedOptions();
  return {
    language: navigator.language,
    languages: navigator.languages,
    locale: resolved.locale,
    calendar: resolved.calendar,
    numberingSystem: resolved.numberingSystem,
  };
}

function mathSignal(): unknown {
  return [
    Math.acos(0.5),
    Math.asin(0.5),
    Math.atan(2),
    Math.cos(1e20),
    Math.exp(1),
    Math.log1p(10),
    Math.sin(-1e20),
    Math.sinh(1),
    Math.tan(-1e20),
  ].map((value) => value.toPrecision(18));
}

function screenSignal(): unknown {
  return {
    width: screen.width,
    height: screen.height,
    availableWidth: screen.availWidth,
    availableHeight: screen.availHeight,
    colorDepth: screen.colorDepth,
    pixelDepth: screen.pixelDepth,
    pixelRatio: devicePixelRatio,
    orientation: screen.orientation?.type || null,
  };
}

function systemSignal(): unknown {
  return {
    cookieEnabled: navigator.cookieEnabled,
    doNotTrack: navigator.doNotTrack,
    pdfViewerEnabled:
      (navigator as Navigator & { pdfViewerEnabled?: boolean }).pdfViewerEnabled ??
      null,
    webdriver: navigator.webdriver,
    vendor: navigator.vendor,
    productSub: navigator.productSub,
    userAgent: navigator.userAgent,
  };
}

function timezoneSignal(): unknown {
  const now = new Date();
  return {
    zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    offset: now.getTimezoneOffset(),
    january: new Date(now.getFullYear(), 0, 1).getTimezoneOffset(),
    july: new Date(now.getFullYear(), 6, 1).getTimezoneOffset(),
  };
}

function pluginSignal(): unknown {
  return Array.from(navigator.plugins || [], (plugin) => ({
    name: plugin.name,
    filename: plugin.filename,
    types: Array.from(plugin, (mime) => mime.type),
  }));
}

async function speechSignal(): Promise<unknown> {
  if (!("speechSynthesis" in window)) throw new Error("unavailable");
  let voices = speechSynthesis.getVoices();
  if (!voices.length) {
    await Promise.race([
      new Promise<void>((resolve) => {
        const listener = () => {
          speechSynthesis.removeEventListener("voiceschanged", listener);
          resolve();
        };
        speechSynthesis.addEventListener("voiceschanged", listener, { once: true });
      }),
      delay(180),
    ]);
    voices = speechSynthesis.getVoices();
  }
  if (!voices.length) throw new Error("unavailable");
  return voices.map((voice) => [voice.name, voice.lang, voice.localService]);
}

async function fingerprintProfile(): Promise<FingerprintProfile> {
  const extended = navigator as ExtendedNavigator;
  try {
    if (await extended.brave?.isBrave?.()) return "brave";
  } catch {
    // Browser-family detection is only a stability hint.
  }
  const userAgent = navigator.userAgent;
  if (/Firefox\//i.test(userAgent)) return "firefox";
  if (/Safari\//i.test(userAgent) && !/(Chrome|Chromium|CriOS|Edg)\//i.test(userAgent)) {
    return "safari";
  }
  if (/(Chrome|Chromium|CriOS|Edg)\//i.test(userAgent)) return "chromium";
  return "other";
}

async function collectOne(
  name: string,
  collector: () => unknown | Promise<unknown>,
  components: Record<string, string>,
  availability: Record<string, Availability>,
): Promise<void> {
  try {
    const value = await Promise.race([
      Promise.resolve().then(collector),
      delay(COMPONENT_TIMEOUT_MS).then(() => {
        throw new Error("timeout");
      }),
    ]);
    components[name] = await sha256(value);
    availability[name] = "ok";
  } catch (error) {
    availability[name] =
      error instanceof Error && error.message === "timeout"
        ? "timeout"
        : error instanceof Error && error.message === "unavailable"
          ? "unavailable"
          : "error";
  }
}

export async function collectDeviceFingerprint(): Promise<DeviceFingerprintPayload> {
  const startedAt = performance.now();
  const components: Record<string, string> = {};
  const availability: Record<string, Availability> = {};
  const collectors: Array<[string, () => unknown | Promise<unknown>]> = [
    ["audio", audioSignal],
    ["canvas", canvasSignal],
    ["fonts", fontSignal],
    ["hardware", hardwareSignal],
    ["locales", localeSignal],
    ["math", mathSignal],
    ["plugins", pluginSignal],
    ["screen", screenSignal],
    ["speech", speechSignal],
    ["system", systemSignal],
    ["timezone", timezoneSignal],
    ["webgl", webglSignal],
  ];
  const tasks = collectors.map(([name, collector]) =>
    collectOne(name, collector, components, availability),
  );
  await Promise.race([Promise.all(tasks), delay(TOTAL_TIMEOUT_MS)]);
  for (const [name] of collectors) availability[name] ||= "timeout";
  return {
    version: FINGERPRINT_VERSION,
    profile: await fingerprintProfile(),
    components: { ...components },
    availability: { ...availability },
    elapsedMs: Math.min(Math.round(performance.now() - startedAt), 5_000),
  };
}
