import { fal } from "@fal-ai/client";

let configured = false;

export const FAL_FLUX_LORA_TRAINING_ENDPOINT =
  process.env.FAL_FLUX_LORA_TRAINING_ENDPOINT || "fal-ai/flux-lora-fast-training";

export function getFalClient() {
  const credentials = process.env.FAL_KEY || process.env.FAL_API_KEY;
  if (!credentials) {
    throw new Error("FAL_KEY or FAL_API_KEY is not configured.");
  }

  if (!configured) {
    fal.config({ credentials });
    configured = true;
  }

  return fal;
}

export function falFileUrl(value: unknown) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object" && "url" in value) return String((value as { url?: unknown }).url || "");
  return "";
}
