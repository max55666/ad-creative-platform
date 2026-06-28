import { existsSync } from "fs";
import { readFile } from "fs/promises";
import path from "path";
import sharp from "sharp";
import { toFile } from "openai";
import { getOpenAIClient } from "@/lib/ai/providers/openai";
import { ImageGenerationRequest, ImageGenerationResponse } from "@/lib/ai/types";
import { getSystemSettings } from "@/lib/settings";

export async function generateOpenAIImage({
  prompt,
  size,
  referenceImagePaths = []
}: ImageGenerationRequest): Promise<ImageGenerationResponse> {
  const openai = getOpenAIClient();
  if (!openai) throw new Error("OPENAI_API_KEY is not configured.");
  const settings = await getSystemSettings();

  const model = settings.providers.image.model || process.env.OPENAI_IMAGE_MODEL || "gpt-image-1";
  const referenceLimit = positiveInt(process.env.OPENAI_IMAGE_REFERENCE_LIMIT, 3);
  const validReferencePaths = referenceImagePaths
    .filter((filePath) => filePath && existsSync(filePath) && supportedImageMimeType(filePath))
    .slice(0, referenceLimit);
  const referenceFiles = await createReferenceImageFiles(validReferencePaths);

  const response = await withOpenAIImageRateLimitRetry(() => {
    if (referenceFiles.length) {
      return openai.images.edit({
        model,
        image: referenceFiles,
        prompt,
        size,
        quality: settings.providers.image.quality
      });
    }

    return openai.images.generate({
      model,
      prompt,
      size,
      quality: settings.providers.image.quality,
      output_format: "png"
    });
  });

  const image = response.data?.[0];
  if (!image?.b64_json && !image?.url) throw new Error("OpenAI did not return an image.");

  const buffer = image.b64_json
    ? Buffer.from(image.b64_json, "base64")
    : Buffer.from(await (await fetch(image.url as string)).arrayBuffer());

  return { buffer, model, size };
}

async function createReferenceImageFiles(filePaths: string[]) {
  const files = [];
  for (const filePath of filePaths) {
    try {
      const buffer = await readAndOptimizeReference(filePath);
      files.push(await toFile(buffer, normalizedImageName(filePath), { type: "image/jpeg" }));
    } catch {
      // Skip a bad reference instead of failing the whole generation job.
    }
  }
  return files;
}

async function readAndOptimizeReference(filePath: string) {
  const buffer = await readFile(filePath);
  const maxWidth = positiveInt(process.env.OPENAI_IMAGE_REFERENCE_MAX_WIDTH, 1400);
  const quality = positiveInt(process.env.OPENAI_IMAGE_REFERENCE_QUALITY, 80);

  return sharp(buffer, { animated: false })
    .rotate()
    .resize({ width: maxWidth, height: maxWidth, fit: "inside", withoutEnlargement: true })
    .jpeg({ quality, mozjpeg: true })
    .toBuffer();
}

function supportedImageMimeType(filePath: string) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  return "";
}

function normalizedImageName(filePath: string) {
  const baseName = path.basename(filePath, path.extname(filePath)).replace(/[^a-zA-Z0-9-_]+/g, "-") || "reference";
  return `${baseName}.jpg`;
}

async function withOpenAIImageRateLimitRetry<T>(operation: () => Promise<T>) {
  const maxAttempts = positiveInt(process.env.OPENAI_IMAGE_MAX_RETRIES, 4);
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (!isRateLimitError(error) || attempt === maxAttempts) break;
      await sleep(getRetryDelayMs(error, attempt));
    }
  }

  throw toFriendlyImageError(lastError);
}

function isRateLimitError(error: unknown) {
  const anyError = error as { status?: number; code?: string; message?: string };
  const message = String(anyError?.message || "");
  return anyError?.status === 429 || anyError?.code === "rate_limit_exceeded" || message.includes("Rate limit");
}

function getRetryDelayMs(error: unknown, attempt: number) {
  const anyError = error as { headers?: Headers | Record<string, string>; message?: string };
  const headerValue =
    typeof anyError?.headers?.get === "function"
      ? anyError.headers.get("retry-after")
      : anyError?.headers && "retry-after" in anyError.headers
        ? anyError.headers["retry-after"]
        : undefined;
  const headerSeconds = Number(headerValue);
  if (Number.isFinite(headerSeconds) && headerSeconds > 0) return Math.min((headerSeconds + 2) * 1000, 90000);

  const message = String(anyError?.message || "");
  const match = message.match(/try again in\s+([\d.]+)s/i);
  if (match) return Math.min((Number(match[1]) + 2) * 1000, 90000);

  return Math.min(15000 * attempt, 90000);
}

function toFriendlyImageError(error: unknown) {
  if (!isRateLimitError(error)) return error;
  const message = error instanceof Error ? error.message : String(error || "");
  return new Error(
    [
      "OpenAI 圖片生成目前達到速率限制。",
      "系統已自動等待並重試，但仍未成功。請稍後再按重試，或降低一次產生的素材數量。",
      message
    ].join("\n")
  );
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function positiveInt(value: string | undefined, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}
