import { spawn } from "child_process";
import { existsSync } from "fs";
import { mkdir } from "fs/promises";
import path from "path";
import { optionalImport } from "@/lib/services/runtime-import";
import { getStorage } from "@/lib/storage";

type FfmpegStaticModule = string | { default?: string };

export type MediaJobResult = {
  fileUrl: string;
  filePath: string;
  meta?: Record<string, unknown>;
};

export async function getFfmpegPath() {
  const configuredPath = cleanEnvPath(process.env.FFMPEG_PATH);
  if (configuredPath) {
    const resolved = await resolveConfiguredFfmpegPath(configuredPath);
    if (resolved) return resolved;
    throw new Error(buildFfmpegNotFoundMessage(`FFMPEG_PATH 已設定但無法執行：${configuredPath}`));
  }

  const ffmpegStatic = await optionalImport<FfmpegStaticModule>("ffmpeg-static");
  const staticPath = typeof ffmpegStatic === "string" ? ffmpegStatic : ffmpegStatic?.default;
  if (staticPath && existsSync(staticPath)) return staticPath;

  const systemPath = await findFfmpegInSystemPath();
  if (systemPath) return systemPath;

  throw new Error(buildFfmpegNotFoundMessage("找不到 FFmpeg 執行檔。"));
}

export function publicUrlToPath(fileUrl: string) {
  return getStorage().getLocalPath(fileUrl);
}

export async function extractAudio({
  inputUrl,
  projectId
}: {
  inputUrl: string;
  projectId: string;
}): Promise<MediaJobResult> {
  const outputName = `${Date.now()}-audio.mp3`;
  const target = await getStorage().createWriteTarget({
    directory: `processed/${projectId}`,
    fileName: outputName,
    contentType: "audio/mpeg"
  });

  await runFfmpeg([
    "-y",
    "-i",
    publicUrlToPath(inputUrl),
    "-vn",
    "-acodec",
    "libmp3lame",
    "-ar",
    "44100",
    "-ac",
    "2",
    target.path
  ]);

  return {
    filePath: target.path,
    fileUrl: target.url,
    meta: { codec: "mp3" }
  };
}

export async function extractKeyframes({
  inputUrl,
  projectId,
  fps = 0.2
}: {
  inputUrl: string;
  projectId: string;
  fps?: number;
}): Promise<MediaJobResult[]> {
  const frameDir = `frames-${Date.now()}`;
  const outputDir = getStorage().getLocalPath(`processed/${projectId}/${frameDir}`);
  await mkdir(outputDir, { recursive: true });
  const pattern = path.join(outputDir, "frame-%03d.jpg");

  await runFfmpeg([
    "-y",
    "-i",
    publicUrlToPath(inputUrl),
    "-vf",
    `fps=${fps},scale=720:-1`,
    "-q:v",
    "3",
    pattern
  ]);

  const { readdir } = await import("fs/promises");
  const files = await readdir(outputDir);
  return files
    .filter((file) => file.endsWith(".jpg"))
    .sort()
    .map((file) => ({
      filePath: path.join(outputDir, file),
      fileUrl: getStorage().getPublicUrl(`processed/${projectId}/${frameDir}/${file}`),
      meta: { fps }
    }));
}

export async function composeVideoFromImagesAudioSubtitles({
  imageUrls,
  audioUrl,
  subtitles,
  projectId,
  secondsPerImage = 3,
  aspectRatio = "9:16",
  subtitleStyle = "default"
}: {
  imageUrls: string[];
  audioUrl?: string;
  subtitles?: string[];
  projectId: string;
  secondsPerImage?: number;
  aspectRatio?: string;
  subtitleStyle?: string;
}): Promise<MediaJobResult> {
  if (!imageUrls.length) throw new Error("至少需要一張圖片才能合成影片。");

  const outputDir = getStorage().getLocalPath(`renders/${projectId}`);
  await mkdir(outputDir, { recursive: true });
  const timestamp = Date.now();
  const listPath = path.join(outputDir, `${timestamp}-images.txt`);
  const subtitlePath = path.join(outputDir, `${timestamp}-captions.srt`);
  const outputName = `${timestamp}-render.mp4`;
  const outputPath = path.join(outputDir, outputName);
  const { writeFile } = await import("fs/promises");

  const concatList = [
    ...imageUrls.flatMap((url) => [`file '${publicUrlToPath(url).replace(/\\/g, "/")}'`, `duration ${secondsPerImage}`]),
    `file '${publicUrlToPath(imageUrls[imageUrls.length - 1]).replace(/\\/g, "/")}'`
  ].join("\n");
  await writeFile(listPath, concatList, "utf8");

  const subtitleLines = buildSrt(subtitles || [], secondsPerImage);
  if (subtitleLines) await writeFile(subtitlePath, subtitleLines, "utf8");

  const dimensions = dimensionsForAspectRatio(aspectRatio);
  const videoFilter = [
    `scale=${dimensions.width}:${dimensions.height}:force_original_aspect_ratio=decrease`,
    `pad=${dimensions.width}:${dimensions.height}:(ow-iw)/2:(oh-ih)/2`,
    "format=yuv420p",
    subtitleLines ? buildSubtitleFilter(subtitlePath, subtitleStyle) : ""
  ].filter(Boolean).join(",");

  const args = ["-y", "-f", "concat", "-safe", "0", "-i", listPath];
  if (audioUrl) args.push("-i", publicUrlToPath(audioUrl));
  args.push("-vf", videoFilter, "-r", "30", "-shortest", outputPath);

  await runFfmpeg(args);
  return {
    filePath: outputPath,
    fileUrl: getStorage().getPublicUrl(`renders/${projectId}/${outputName}`),
    meta: { imageCount: imageUrls.length, audioUrl, subtitles, aspectRatio, subtitleStyle }
  };
}

export async function composeVideoFromClipsAudioSubtitles({
  clipUrls,
  audioUrl,
  subtitles,
  projectId,
  aspectRatio = "9:16",
  subtitleStyle = "default",
  secondsPerClip = 5
}: {
  clipUrls: string[];
  audioUrl?: string;
  subtitles?: string[];
  projectId: string;
  aspectRatio?: string;
  subtitleStyle?: string;
  secondsPerClip?: number;
}): Promise<MediaJobResult> {
  if (!clipUrls.length) throw new Error("至少需要一段影片才能合成。");

  const outputDir = getStorage().getLocalPath(`renders/${projectId}`);
  await mkdir(outputDir, { recursive: true });
  const timestamp = Date.now();
  const listPath = path.join(outputDir, `${timestamp}-clips.txt`);
  const subtitlePath = path.join(outputDir, `${timestamp}-clip-captions.srt`);
  const outputName = `${timestamp}-motion-render.mp4`;
  const outputPath = path.join(outputDir, outputName);
  const { writeFile } = await import("fs/promises");

  const concatList = clipUrls
    .map((url) => `file '${publicUrlToPath(url).replace(/\\/g, "/")}'`)
    .join("\n");
  await writeFile(listPath, concatList, "utf8");

  const subtitleLines = buildSrt(subtitles || [], secondsPerClip);
  if (subtitleLines) await writeFile(subtitlePath, subtitleLines, "utf8");

  const dimensions = dimensionsForAspectRatio(aspectRatio);
  const videoFilter = [
    `scale=${dimensions.width}:${dimensions.height}:force_original_aspect_ratio=decrease`,
    `pad=${dimensions.width}:${dimensions.height}:(ow-iw)/2:(oh-ih)/2`,
    "format=yuv420p",
    subtitleLines ? buildSubtitleFilter(subtitlePath, subtitleStyle) : ""
  ].filter(Boolean).join(",");

  const args = ["-y", "-f", "concat", "-safe", "0", "-i", listPath];
  if (audioUrl) args.push("-i", publicUrlToPath(audioUrl));
  args.push(
    "-vf",
    videoFilter,
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "23",
    "-r",
    "30",
    ...(audioUrl ? ["-shortest"] : []),
    outputPath
  );

  await runFfmpeg(args);
  return {
    filePath: outputPath,
    fileUrl: getStorage().getPublicUrl(`renders/${projectId}/${outputName}`),
    meta: { clipCount: clipUrls.length, audioUrl, subtitles, aspectRatio, subtitleStyle, secondsPerClip }
  };
}

function buildSrt(subtitles: string[], secondsPerSubtitle: number) {
  const clean = subtitles.map((subtitle) => subtitle.trim()).filter(Boolean);
  if (!clean.length) return "";

  return clean
    .map((subtitle, index) => {
      const start = index * secondsPerSubtitle;
      const end = start + secondsPerSubtitle;
      return `${index + 1}\n${formatSrtTime(start)} --> ${formatSrtTime(end)}\n${subtitle}\n`;
    })
    .join("\n");
}

function formatSrtTime(seconds: number) {
  const whole = Math.floor(seconds);
  const ms = Math.round((seconds - whole) * 1000);
  const s = whole % 60;
  const m = Math.floor(whole / 60) % 60;
  const h = Math.floor(whole / 3600);
  return `${pad(h)}:${pad(m)}:${pad(s)},${String(ms).padStart(3, "0")}`;
}

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function dimensionsForAspectRatio(aspectRatio: string) {
  if (aspectRatio === "1:1") return { width: 1080, height: 1080 };
  if (aspectRatio === "4:5") return { width: 1080, height: 1350 };
  return { width: 1080, height: 1920 };
}

function buildSubtitleFilter(subtitlePath: string, subtitleStyle: string) {
  const styles: Record<string, string> = {
    default: "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=92",
    bold: "FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=120",
    clean: "FontName=Arial,FontSize=17,PrimaryColour=&H00FFFFFF,OutlineColour=&H60000000,BorderStyle=1,Outline=1,Shadow=0,Alignment=2,MarginV=84",
    "bottom-heavy": "FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,BackColour=&HAA000000,BorderStyle=4,Outline=1,Shadow=0,Alignment=2,MarginV=64"
  };
  return `subtitles='${escapeFilterPath(subtitlePath)}':force_style='${styles[subtitleStyle] || styles.default}'`;
}

function escapeFilterPath(filePath: string) {
  return filePath.replace(/\\/g, "/").replace(/:/g, "\\:").replace(/'/g, "\\'");
}

async function runFfmpeg(args: string[]) {
  const ffmpegPath = await getFfmpegPath();

  await new Promise<void>((resolve, reject) => {
    const child = spawn(ffmpegPath, args, { windowsHide: true });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") reject(new Error(buildFfmpegNotFoundMessage(`無法啟動 FFmpeg：${ffmpegPath}`)));
      else reject(error);
    });
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(stderr || `ffmpeg exited with code ${code}`));
    });
  });
}

function cleanEnvPath(value?: string) {
  return value?.trim().replace(/^["']|["']$/g, "");
}

async function resolveConfiguredFfmpegPath(value: string) {
  if (path.isAbsolute(value)) {
    if (!existsSync(value)) return null;
    return value;
  }

  return (await canExecute(value, ["-version"])) ? value : null;
}

async function findFfmpegInSystemPath() {
  const lookup = process.platform === "win32"
    ? { command: "where.exe", args: ["ffmpeg"] }
    : { command: "which", args: ["ffmpeg"] };

  const result = await runLookupCommand(lookup.command, lookup.args);
  const firstLine = result
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);

  if (firstLine) return firstLine;
  return (await canExecute("ffmpeg", ["-version"])) ? "ffmpeg" : null;
}

async function canExecute(command: string, args: string[]) {
  try {
    await new Promise<void>((resolve, reject) => {
      const child = spawn(command, args, { windowsHide: true });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0) resolve();
        else reject(new Error(`${command} exited with code ${code}`));
      });
    });
    return true;
  } catch {
    return false;
  }
}

async function runLookupCommand(command: string, args: string[]) {
  try {
    return await new Promise<string>((resolve, reject) => {
      const child = spawn(command, args, { windowsHide: true });
      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk.toString();
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0) resolve(stdout);
        else reject(new Error(stderr || `${command} exited with code ${code}`));
      });
    });
  } catch {
    return "";
  }
}

function buildFfmpegNotFoundMessage(reason: string) {
  return [
    reason,
    "請在 .env.local 設定 FFMPEG_PATH，指向 ffmpeg.exe 的完整路徑，例如：",
    'FFMPEG_PATH="C:\\\\ffmpeg\\\\bin\\\\ffmpeg.exe"',
    "設定後請重新啟動 Next.js 開發伺服器。也可以在終端機執行 ffmpeg -version 確認系統 PATH 是否可用。",
    `platform=${process.platform}`,
    `FFMPEG_PATH=${process.env.FFMPEG_PATH || "(not set)"}`,
    `PATH=${process.env.PATH || "(empty)"}`,
    `Path=${process.env.Path || "(empty)"}`
  ].join("\n");
}
