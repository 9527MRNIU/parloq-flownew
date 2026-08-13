import { useMemo, type CSSProperties } from "react";

const DEFAULT_COLORS = ["#6D87CD", "#6366F1", "#22D3EE", "#F59E0B", "#EC4899"];

type BoringAvatarProps = {
  name?: string | null;
  size?: number | string;
  square?: boolean;
  colors?: string[];
  className?: string;
  style?: CSSProperties;
};

function hashSeed(seed: string) {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = ((hash << 5) - hash + seed.charCodeAt(index)) | 0;
  }
  return Math.abs(hash);
}

function pickColor(colors: string[], hash: number, offset = 0) {
  return colors[(hash + offset) % colors.length];
}

function buildAvatarSvg(seed: string, colors: string[], square: boolean) {
  const hash = hashSeed(seed);
  const background = pickColor(colors, hash);
  const shapeA = pickColor(colors, hash, 2);
  const shapeB = pickColor(colors, hash, 4);
  const shapeC = pickColor(colors, hash, 1);
  const radius = square ? 12 : 80;
  const rotation = hash % 360;

  return `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" role="img">
      <rect width="80" height="80" rx="${radius}" fill="${background}" />
      <circle cx="${18 + (hash % 18)}" cy="${20 + (hash % 14)}" r="${24 + (hash % 8)}" fill="${shapeA}" opacity="0.88" />
      <path d="M58 4 C76 18 79 43 66 62 C53 79 28 78 18 61 C8 44 13 22 31 11 C39 6 49 3 58 4Z" fill="${shapeB}" opacity="0.72" transform="rotate(${rotation} 40 40)" />
      <circle cx="${54 - (hash % 10)}" cy="${55 - (hash % 12)}" r="${18 + (hash % 7)}" fill="${shapeC}" opacity="0.78" />
    </svg>
  `;
}

export function BoringAvatar({
  name,
  size = 32,
  square = true,
  colors = DEFAULT_COLORS,
  className,
  style,
}: BoringAvatarProps) {
  const seed = (name || "user").trim() || "user";
  const src = useMemo(
    () =>
      `data:image/svg+xml;utf8,${encodeURIComponent(buildAvatarSvg(seed, colors, square))}`,
    [colors, seed, square],
  );

  return (
    <img
      src={src}
      alt={seed}
      className={className}
      draggable={false}
      decoding="async"
      style={{
        width: size,
        height: size,
        borderRadius: square ? 12 : "50%",
        ...style,
      }}
    />
  );
}
