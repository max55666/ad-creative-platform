import { readFile } from "fs/promises";
import { VideoClipGenerationRequest, VideoClipGenerationResponse } from "@/lib/ai/types";
import { getSystemSettings } from "@/lib/settings";

type KlingTaskResponse = {
  id?: string;
  task_id?: string;
  request_id?: string;
  data?: any;
  output?: any;
  status?: string;
  task_status?: string;
  error?: string;
  message?: string;
};

export async function generateKlingVideoClip({
  imagePath,
  prompt,
  durationSec = 5,
  aspectRatio = "9:16",
  motionStyle = "subtle"
}: VideoClipGenerationRequest): Promise<VideoClipGenerationResponse> {
  const apiKey = process.env.KLING_API_KEY;
  if (!apiKey) throw new Error("KLING_API_KEY is not configured.");
  const settings = await getSystemSettings();

  const baseUrl = (process.env.KLING_API_BASE_URL || "https://api.klingai.com").replace(/\/$/, "");
  const model = settings.providers.video.model || process.env.KLING_MODEL || "kling-v1-6";
  const imageBuffer = await readFile(imagePath);
  const imageBase64 = imageBuffer.toString("base64");
  const promptWithMotion = [
    prompt,
    motionStylePrompt(motionStyle),
    "Keep the product visually consistent. Avoid warped text, distorted hands, flicker, or random logos."
  ].filter(Boolean).join("\n");

  const createResponse = await fetch(`${baseUrl}${process.env.KLING_IMAGE_TO_VIDEO_PATH || "/v1/videos/image2video"}`, {
    method: "POST",
    headers: buildKlingHeaders(apiKey),
    body: JSON.stringify({
      model_name: model,
      model,
      prompt: promptWithMotion,
      image: imageBase64,
      image_base64: imageBase64,
      duration: String(durationSec),
      duration_sec: durationSec,
      aspect_ratio: aspectRatio,
      mode: settings.providers.video.klingMode || process.env.KLING_MODE || "std",
      cfg_scale: Number(settings.providers.video.klingCfgScale || process.env.KLING_CFG_SCALE || 0.5)
    })
  });

  const created = await parseKlingResponse(createResponse, "create Kling image-to-video task");
  const taskId = pickTaskId(created);
  const directUrl = pickVideoUrl(created);
  const remoteUrl = directUrl || (taskId ? await pollKlingTask({ baseUrl, apiKey, taskId }) : "");

  if (!remoteUrl) {
    throw new Error(`Kling did not return a video URL. Raw response: ${JSON.stringify(created).slice(0, 1200)}`);
  }

  const videoResponse = await fetch(remoteUrl);
  if (!videoResponse.ok) {
    throw new Error(`Failed to download Kling video: ${videoResponse.status} ${await videoResponse.text()}`);
  }

  return {
    buffer: Buffer.from(await videoResponse.arrayBuffer()),
    provider: "kling",
    model,
    durationSec,
    remoteUrl,
    taskId
  };
}

function buildKlingHeaders(apiKey: string) {
  return {
    "content-type": "application/json",
    authorization: `Bearer ${apiKey}`,
    "x-api-key": apiKey
  };
}

async function pollKlingTask({
  baseUrl,
  apiKey,
  taskId
}: {
  baseUrl: string;
  apiKey: string;
  taskId: string;
}) {
  const pathTemplate = process.env.KLING_TASK_STATUS_PATH || "/v1/videos/image2video/{taskId}";
  const statusUrl = `${baseUrl}${pathTemplate.replace("{taskId}", taskId)}`;
  const settings = await getSystemSettings();
  const timeoutMs = Number(settings.providers.video.timeoutMs || process.env.KLING_TIMEOUT_MS || 10 * 60 * 1000);
  const intervalMs = Number(settings.providers.video.pollIntervalMs || process.env.KLING_POLL_INTERVAL_MS || 8000);
  const started = Date.now();

  while (Date.now() - started < timeoutMs) {
    await delay(intervalMs);
    const response = await fetch(statusUrl, { headers: buildKlingHeaders(apiKey) });
    const data = await parseKlingResponse(response, "poll Kling image-to-video task");
    const status = String(data.status || data.task_status || data.data?.status || data.data?.task_status || "").toLowerCase();
    const videoUrl = pickVideoUrl(data);
    if (videoUrl) return videoUrl;
    if (["failed", "failure", "error", "rejected"].includes(status)) {
      throw new Error(`Kling task failed: ${JSON.stringify(data).slice(0, 1200)}`);
    }
  }

  throw new Error(`Kling task timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
}

async function parseKlingResponse(response: Response, action: string): Promise<KlingTaskResponse> {
  const text = await response.text();
  let data: KlingTaskResponse = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { message: text };
  }

  if (!response.ok) {
    const friendly = getFriendlyKlingError(response.status, data, text);
    if (friendly) throw new Error(friendly);
    throw new Error(`Failed to ${action}: ${response.status} ${text}`);
  }

  return data;
}

function getFriendlyKlingError(status: number, data: KlingTaskResponse, rawText: string) {
  const message = String(data?.message || data?.error || rawText || "");
  const code = String((data as any)?.code || data?.data?.code || "");

  if (status === 429 && /balance|not enough|insufficient/i.test(message)) {
    return [
      "Kling 動態影片生成失敗：帳號餘額或點數不足。",
      "請到 Kling API 後台儲值、購買點數，或確認目前使用的 API key 是否綁定到有餘額的帳號。",
      `Kling 回傳代碼：${code || status}`
    ].join("\n");
  }

  if (status === 401 || status === 403) {
    return "Kling API 驗證失敗：請確認 KLING_API_KEY 是否正確，或這把 key 是否有 image-to-video 權限。";
  }

  if (status === 404) {
    return "Kling API endpoint 找不到：請確認 KLING_API_BASE_URL、KLING_IMAGE_TO_VIDEO_PATH、KLING_TASK_STATUS_PATH 是否符合你的供應商文件。";
  }

  return "";
}

function pickTaskId(data: any): string {
  return String(
    data?.task_id ||
    data?.id ||
    data?.data?.task_id ||
    data?.data?.id ||
    data?.output?.task_id ||
    ""
  );
}

function pickVideoUrl(data: any): string {
  const candidates = [
    data?.video_url,
    data?.url,
    data?.data?.video_url,
    data?.data?.url,
    data?.data?.task_result?.videos?.[0]?.url,
    data?.task_result?.videos?.[0]?.url,
    data?.output?.video_url,
    data?.output?.url
  ];
  return String(candidates.find(Boolean) || "");
}

function motionStylePrompt(style: string) {
  if (style === "product-demo") return "Animate a clean product demonstration with gentle camera movement and realistic hand interaction.";
  if (style === "scene-action") return "Animate natural lifestyle action in the scene with smooth motion and clear product focus.";
  if (style === "dramatic") return "Animate with cinematic push-in, dynamic lighting, and stronger emotional pacing.";
  return "Animate with subtle camera push-in, slight parallax, and stable product detail.";
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
