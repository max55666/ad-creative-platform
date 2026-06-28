import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(value: string | Date) {
  return new Intl.DateTimeFormat("zh-TW", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function truncate(value: string | null | undefined, length = 120) {
  if (!value) return "";
  return value.length > length ? `${value.slice(0, length)}...` : value;
}

export async function copyText(value: string) {
  await navigator.clipboard.writeText(value);
}
