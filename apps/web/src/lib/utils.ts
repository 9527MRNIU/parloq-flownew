import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Keep protocol/storage values in E.164, but never show the leading plus. */
export function formatPhoneDisplay(value: unknown) {
  return String(value ?? "").trim().replace(/^\++/, "");
}
