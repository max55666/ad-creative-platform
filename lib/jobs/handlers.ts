import { prisma } from "@/lib/db";
import { createCreativeVersion } from "@/lib/creative-versioning";
import {
  buildStaticCreativeImagePrompt,
  buildStoryboardFramePrompt,
  generateAndSaveImageFile,
  getReferenceImageUrls,
  imageSizeForAspectRatio,
  targetDimensionsForAspectRatio
} from "@/lib/image-generation";
import { fallbackViralAnalysis } from "@/lib/fallbacks";
import { runJsonPrompt } from "@/lib/openai";
import { viralVideoAnalysisPrompt } from "@/lib/prompts";
import { processImage } from "@/lib/services/image-processing";
import { transcribeAudioFile } from "@/lib/services/openai-media";
import { aiRouter } from "@/lib/ai/router";
import { getStorage } from "@/lib/storage";
import { publicUrlToPath, extractAudio, extractKeyframes, composeVideoFromImagesAudioSubtitles, composeVideoFromClipsAudioSubtitles } from "@/lib/services/video-processing";
import { generateElevenLabsVoiceover, type VoiceGender, type VoiceLanguage } from "@/lib/services/elevenlabs";
import { scrapeProductPage } from "@/lib/services/web-scraper";
import { JOB_TYPES, JobContext } from "@/lib/jobs/types";

export async function runJobHandler(context: JobContext) {
  switch (context.input?.type || context.input?.jobType || context.input?.taskType || context.input?.kind || "") {
    default:
      break;
  }

  const job = await prisma.generationJob.findUnique({ where: { id: context.jobId } });
  if (!job) throw new Error("Job not found");

  switch (job.type) {
    case JOB_TYPES.STATIC_CREATIVE_IMAGE:
      return handleStaticCreativeImage(context);
    case JOB_TYPES.STORYBOARD_IMAGES:
      return handleStoryboardImages(context);
    case JOB_TYPES.VOICEOVER:
      return handleVoiceover(context);
    case JOB_TYPES.RENDER_VIDEO:
      return handleRenderVideo(context);
    case JOB_TYPES.EXTRACT_AUDIO:
      return handleExtractAudio(context);
    case JOB_TYPES.EXTRACT_FRAMES:
      return handleExtractFrames(context);
    case JOB_TYPES.PROCESS_IMAGE:
      return handleProcessImage(context);
    case JOB_TYPES.SCRAPE_PRODUCT:
      return handleScrapeProduct(context);
    case JOB_TYPES.VIRAL_ANALYSIS:
      return handleViralAnalysis(context);
    default:
      throw new Error(`Unsupported job type: ${job.type}`);
  }
}

async function handleStaticCreativeImage({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  const aspectRatio = ["1:1", "4:5", "9:16"].includes(input.aspectRatio) ? input.aspectRatio : "1:1";
  const creative = await prisma.staticCreativeSuggestion.findFirst({
    where: { id: input.creativeId, projectId },
    include: { project: { include: { assets: true } } }
  });
  if (!creative) throw new Error("Creative not found");

  await progress(10);
  await prisma.staticCreativeSuggestion.update({ where: { id: creative.id }, data: { imageStatus: "generating" } });

  const prompt = buildStaticCreativeImagePrompt({ project: creative.project, creative });
  const generated = await generateAndSaveImageFile({
    prompt,
    prefix: "creative",
    size: imageSizeForAspectRatio(aspectRatio),
    referenceImageUrls: getReferenceImageUrls(creative.project)
  });
  await progress(70);

  let imageUrl = generated.fileUrl;
  let processingWarning: string | null = null;
  const target = targetDimensionsForAspectRatio(aspectRatio);
  if (target) {
    try {
      const processed = await processImage({
        inputPath: generated.filePath,
        projectId,
        width: target.width,
        height: target.height,
        format: "png",
        quality: 92
      });
      imageUrl = processed.fileUrl;
    } catch (error) {
      processingWarning = error instanceof Error ? error.message : "Image processing skipped.";
    }
  }

  const updated = await prisma.staticCreativeSuggestion.update({
    where: { id: creative.id },
    data: { previewImageUrl: imageUrl, imagePrompt: prompt, imageStatus: "ready" }
  });
  const generatedImage = await prisma.generatedImage.create({
    data: {
      projectId,
      creativeId: creative.id,
      type: "static_creative",
      aspectRatio,
      prompt,
      imageUrl,
      model: generated.model,
      meta: { sourceUrl: generated.fileUrl, sourceSize: generated.size, processingWarning } as any
    }
  });
  const version = await createCreativeVersion({
    projectId,
    userId,
    type: "static",
    title: creative.title,
    sourceRefId: creative.id,
    kind: "image",
    prompt,
    model: generated.model,
    provider: "openai",
    generationParams: { aspectRatio, size: generated.size },
    content: updated,
    assets: [{ type: "image", url: imageUrl, mimeType: "image/png", meta: { generatedImageId: generatedImage.id } }]
  });
  await logUsage({ provider: "openai", model: generated.model, projectId, userId, jobId, imageCount: 1, status: "completed" });

  return { creative: updated, generatedImage, version, warning: processingWarning };
}

async function handleStoryboardImages({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  const maxFrames = Math.min(Number(input.maxFrames || 4), 6);
  const script = await prisma.videoScript.findFirst({
    where: { id: input.scriptId, projectId },
    include: { project: { include: { assets: true } } }
  });
  if (!script) throw new Error("Script not found");
  const storyboard = Array.isArray(script.storyboard) ? script.storyboard : [];
  if (!storyboard.length) throw new Error("Storyboard is empty");

  await prisma.videoScript.update({ where: { id: script.id }, data: { imageStatus: "generating" } });
  const generated = [];
  const nextStoryboard = [...storyboard];

  for (const [index, shot] of storyboard.slice(0, maxFrames).entries()) {
    const shotObject = shot && typeof shot === "object" && !Array.isArray(shot) ? shot as any : {};
    if (shotObject.imageUrl && shotObject.imageLocked) {
      generated.push({
        index,
        imageUrl: shotObject.imageUrl,
        prompt: shotObject.imagePrompt || "",
        source: shotObject.imageSource || "locked"
      });
      await progress(15 + Math.round(((index + 1) / maxFrames) * 70));
      continue;
    }
    const prompt = buildStoryboardFramePrompt({ project: script.project, script, shot, index });
    const file = await generateAndSaveImageFile({
      prompt,
      prefix: `storyboard-${index + 1}`,
      size: "1024x1536",
      referenceImageUrls: getReferenceImageUrls(script.project, extractShotReferenceKeys(shotObject))
    });
    nextStoryboard[index] = { ...shotObject, imageUrl: file.fileUrl, imagePrompt: prompt };
    generated.push({ index, imageUrl: file.fileUrl, prompt });
    await prisma.generatedImage.create({
      data: {
        projectId,
        videoScriptId: script.id,
        type: "storyboard_frame",
        aspectRatio: "9:16",
        prompt,
        imageUrl: file.fileUrl,
        model: file.model,
        meta: { shotIndex: index, sourceSize: file.size } as any
      }
    });
    await progress(15 + Math.round(((index + 1) / maxFrames) * 70));
  }

  const updated = await prisma.videoScript.update({
    where: { id: script.id },
    data: { storyboard: nextStoryboard, storyboardImages: generated, imageStatus: "ready" }
  });
  const version = await createCreativeVersion({
    projectId,
    userId,
    type: "video_script",
    title: script.title,
    sourceRefId: script.id,
    kind: "storyboard_images",
    provider: "openai",
    model: process.env.OPENAI_IMAGE_MODEL || "gpt-image-1",
    generationParams: { maxFrames, aspectRatio: "9:16" },
    content: updated,
    assets: generated.map((item) => ({ type: "image", url: item.imageUrl, mimeType: "image/png", meta: { index: item.index } }))
  });
  await logUsage({ provider: "openai", model: process.env.OPENAI_IMAGE_MODEL || "gpt-image-1", projectId, userId, jobId, imageCount: generated.length, status: "completed" });

  return { script: updated, generated, version };
}

function extractShotReferenceKeys(shot: any) {
  const values = [shot?.requiredReferenceKeys, shot?.referenceKeys, shot?.sceneObjects];
  return values.flatMap((value) => {
    if (Array.isArray(value)) {
      return value.map((item) => {
        if (item && typeof item === "object") return String(item.referenceKey || item.key || item.label || item.name || "");
        return String(item || "");
      });
    }
    return typeof value === "string" ? value.split(/[,，、\n]/) : [];
  }).map((item) => item.trim()).filter(Boolean);
}

function flattenText(value: unknown): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(flattenText).filter(Boolean).join("\n");
  if (typeof value === "object") return Object.values(value).map(flattenText).filter(Boolean).join("\n");
  return String(value);
}

async function handleVoiceover({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  const script = await prisma.videoScript.findFirst({ where: { id: input.scriptId, projectId } });
  if (!script) throw new Error("Script not found");
  const language = (["zh", "ja", "en"].includes(input.language) ? input.language : "zh") as VoiceLanguage;
  const gender = (["male", "female"].includes(input.gender) ? input.gender : "female") as VoiceGender;
  const text = String(input.text || flattenText(script.voiceover) || script.hook || "").trim();
  if (!text) throw new Error("No voiceover text found");

  await progress(20);
  const voiceover = await generateElevenLabsVoiceover({ text, language, gender, projectId, voiceId: input.voiceId });
  const asset = await prisma.voiceoverAsset.create({
    data: {
      projectId,
      videoScriptId: script.id,
      language,
      gender,
      voiceId: voiceover.voiceId,
      text,
      audioUrl: voiceover.fileUrl,
      meta: { provider: "elevenlabs", model: voiceover.model } as any
    }
  });
  const version = await createCreativeVersion({
    projectId,
    userId,
    type: "video_script",
    title: script.title,
    sourceRefId: script.id,
    kind: "voiceover",
    provider: "elevenlabs",
    model: voiceover.model,
    generationParams: { language, gender, voiceId: voiceover.voiceId },
    content: { text },
    assets: [{ type: "audio", url: voiceover.fileUrl, mimeType: "audio/mpeg", meta: { voiceoverAssetId: asset.id } }]
  });
  await logUsage({ provider: "elevenlabs", model: voiceover.model, projectId, userId, jobId, audioSeconds: estimateAudioSeconds(text), status: "completed" });
  return { voiceover: asset, version };
}

function collectStoryboardImages(storyboard: unknown) {
  if (!Array.isArray(storyboard)) return [];
  return storyboard.map((shot) => (shot && typeof shot === "object" && "imageUrl" in shot ? String((shot as any).imageUrl || "") : "")).filter(Boolean);
}

function collectCaptions(captions: unknown) {
  if (!captions) return [];
  if (typeof captions === "string") return [captions];
  if (Array.isArray(captions)) return captions.map(String);
  if (typeof captions === "object") return Object.values(captions).map(String);
  return [String(captions)];
}

async function handleRenderVideo({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  let script = await prisma.videoScript.findFirst({ where: { id: input.scriptId, projectId } });
  if (!script) throw new Error("Script not found");

  let imageUrls = Array.isArray(input.imageUrls) && input.imageUrls.length
    ? input.imageUrls.map(String).filter(Boolean)
    : collectStoryboardImages(script.storyboard);

  if (!imageUrls.length && input.autoGenerateAssets !== false) {
    await progress(8);
    await handleStoryboardImages({
      jobId,
      projectId,
      userId,
      input: {
        scriptId: script.id,
        maxFrames: input.maxFrames || 4
      },
      progress: async (value) => progress(8 + Math.round(value * 0.35))
    });
    script = await prisma.videoScript.findFirst({ where: { id: input.scriptId, projectId } });
    if (!script) throw new Error("Script not found after storyboard generation");
    imageUrls = collectStoryboardImages(script.storyboard);
  }

  if (!imageUrls.length) {
    throw new Error("No storyboard images found. Enable autoGenerateAssets or generate storyboard images first.");
  }

  let latestVoiceover = input.audioUrl ? null : await prisma.voiceoverAsset.findFirst({
    where: { projectId, videoScriptId: script.id },
    orderBy: { createdAt: "desc" }
  });

  if (!input.audioUrl && !latestVoiceover && input.autoGenerateVoiceover !== false && input.autoGenerateAssets !== false) {
    await progress(48);
    const voiceResult = await handleVoiceover({
      jobId,
      projectId,
      userId,
      input: {
        scriptId: script.id,
        language: input.language || "zh",
        gender: input.gender || "female",
        voiceId: input.voiceId,
        text: input.voiceoverText
      },
      progress: async (value) => progress(48 + Math.round(value * 0.2))
    });
    latestVoiceover = voiceResult.voiceover;
  }

  const audioUrl = input.audioUrl || latestVoiceover?.audioUrl || undefined;
  const subtitles = Array.isArray(input.subtitles) ? input.subtitles : collectCaptions(script.captions);
  const render = await prisma.videoRender.create({
    data: { projectId, videoScriptId: script.id, status: "processing", input: { imageUrls, audioUrl, subtitles, renderMode: input.renderMode || "static" } as any }
  });
  await progress(72);
  const renderMode = input.renderMode || "static";
  const motionClips = renderMode === "ai-motion"
    ? await generateMotionClipsForStoryboard({
        jobId,
        projectId,
        userId,
        script,
        imageUrls,
        durationSec: Number(input.clipDurationSec || input.secondsPerImage || 5),
        aspectRatio: input.aspectRatio || "9:16",
        motionStyle: input.motionStyle || "subtle",
        progress
      })
    : [];
  const result = motionClips.length
    ? await composeVideoFromClipsAudioSubtitles({
        clipUrls: motionClips.map((clip) => clip.fileUrl),
        audioUrl,
        subtitles,
        projectId,
        aspectRatio: input.aspectRatio || "9:16",
        subtitleStyle: input.subtitleStyle || "default",
        secondsPerClip: Number(input.clipDurationSec || input.secondsPerImage || 5)
      })
    : await composeVideoFromImagesAudioSubtitles({
        imageUrls,
        audioUrl,
        subtitles,
        projectId,
        secondsPerImage: Number(input.secondsPerImage || 3),
        aspectRatio: input.aspectRatio || "9:16",
        subtitleStyle: input.subtitleStyle || "default"
      });
  const updated = await prisma.videoRender.update({
    where: { id: render.id },
    data: { status: "ready", videoUrl: result.fileUrl, meta: result.meta as any }
  });
  const version = await createCreativeVersion({
    projectId,
    userId,
    type: "video_script",
    title: script.title,
    sourceRefId: script.id,
    kind: "rendered_video",
    provider: "ffmpeg",
    generationParams: {
      secondsPerImage: Number(input.secondsPerImage || 3),
      subtitleStyle: input.subtitleStyle,
      aspectRatio: input.aspectRatio || "9:16",
      autoGenerateAssets: input.autoGenerateAssets !== false,
      motionStyle: input.motionStyle || "subtle",
      renderMode,
      motionClips,
      audioUrl
    },
    content: updated,
    assets: [{ type: "video", url: result.fileUrl, mimeType: "video/mp4", meta: { videoRenderId: updated.id } }]
  });
  await logUsage({ provider: "ffmpeg", projectId, userId, jobId, videoSeconds: imageUrls.length * Number(input.secondsPerImage || 3), status: "completed" });
  return { render: updated, version, imageUrls, audioUrl, motionClips, renderMode };
}

async function generateMotionClipsForStoryboard({
  jobId,
  projectId,
  userId,
  script,
  imageUrls,
  durationSec,
  aspectRatio,
  motionStyle,
  progress
}: {
  jobId: string;
  projectId: string;
  userId?: string | null;
  script: any;
  imageUrls: string[];
  durationSec: number;
  aspectRatio: string;
  motionStyle: string;
  progress: (progress: number) => Promise<void>;
}) {
  const clips = [];
  const storyboard = Array.isArray(script.storyboard) ? script.storyboard : [];

  for (const [index, imageUrl] of imageUrls.entries()) {
    const shot = storyboard[index] || {};
    const prompt = typeof shot.motionPrompt === "string" && shot.motionPrompt.trim()
      ? shot.motionPrompt.trim()
      : [
          `Product video ad shot ${index + 1}.`,
          shot.visual || shot.scene || script.title,
          shot.purpose ? `Purpose: ${shot.purpose}` : "",
          shot.voiceover ? `Voiceover meaning: ${shot.voiceover}` : "",
          shot.cameraMovement ? `Camera movement: ${shot.cameraMovement}` : "",
          shot.productPlacement ? `Product placement: ${shot.productPlacement}` : "",
          "Create smooth realistic motion, preserve product identity, no readable text."
        ].filter(Boolean).join("\n");

    const clip = await aiRouter.generateVideoClip({
      imagePath: publicUrlToPath(imageUrl),
      prompt,
      durationSec,
      aspectRatio,
      motionStyle,
      projectId,
      userId: userId || undefined,
      jobId
    });
    const fileName = `${Date.now()}-kling-${index + 1}-${crypto.randomUUID()}.mp4`;
    const stored = await getStorage().put(clip.buffer, {
      directory: `generated-video/${projectId}`,
      fileName,
      contentType: "video/mp4"
    });

    clips.push({
      index,
      fileUrl: stored.url,
      storageKey: stored.key,
      provider: clip.provider,
      model: clip.model,
      remoteUrl: clip.remoteUrl,
      taskId: clip.taskId
    });
    await logUsage({
      provider: clip.provider,
      model: clip.model,
      projectId,
      userId,
      jobId,
      videoSeconds: durationSec,
      status: "completed"
    });
    await progress(72 + Math.round(((index + 1) / imageUrls.length) * 18));
  }

  return clips;
}

async function handleExtractAudio({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  const inputUrl = input.inputUrl;
  if (!inputUrl) throw new Error("inputUrl is required");
  const audio = await extractAudio({ inputUrl, projectId });
  await progress(80);
  const media = await prisma.processedMedia.create({
    data: { projectId, sourceUrl: inputUrl, type: "extracted_audio", fileUrl: audio.fileUrl, meta: audio.meta as any }
  });
  await logUsage({ provider: "ffmpeg", projectId, userId, jobId, status: "completed" });
  return { media, audio };
}

async function handleExtractFrames({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  const inputUrl = input.inputUrl;
  if (!inputUrl) throw new Error("inputUrl is required");
  const frames = await extractKeyframes({ inputUrl, projectId, fps: Number(input.fps || 0.2) });
  const media = await prisma.$transaction(frames.map((frame) => prisma.processedMedia.create({
    data: { projectId, sourceUrl: inputUrl, type: "keyframe", fileUrl: frame.fileUrl, meta: frame.meta as any }
  })));
  await progress(90);
  await logUsage({ provider: "ffmpeg", projectId, userId, jobId, status: "completed" });
  return { media, frames };
}

async function handleProcessImage({ projectId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  if (!input.inputUrl) throw new Error("inputUrl is required");
  const processed = await processImage({
    inputPath: publicUrlToPath(String(input.inputUrl)),
    projectId,
    width: input.width ? Number(input.width) : undefined,
    height: input.height ? Number(input.height) : undefined,
    format: input.format === "png" || input.format === "jpeg" || input.format === "webp" ? input.format : "webp",
    quality: input.quality ? Number(input.quality) : 86,
    logoPath: input.logoUrl ? publicUrlToPath(String(input.logoUrl)) : undefined
  });
  await progress(80);
  const media = await prisma.processedMedia.create({
    data: { projectId, sourceUrl: String(input.inputUrl), type: "processed_image", fileUrl: processed.fileUrl, meta: processed.meta as any }
  });
  return { media, processed };
}

async function handleScrapeProduct({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  const project = await prisma.project.findUnique({ where: { id: projectId } });
  const url = input.url || project?.productUrl;
  if (!url) throw new Error("url is required");
  const scrape = await scrapeProductPage({ url, projectId });
  await progress(80);
  const asset = await prisma.productAsset.create({
    data: {
      projectId,
      type: "url",
      fileUrl: scrape.screenshotUrl,
      content: `${scrape.title}\n\n${scrape.text}`,
      meta: { url, title: scrape.title, images: scrape.images, screenshotUrl: scrape.screenshotUrl } as any
    }
  });
  await logUsage({ provider: "playwright", projectId, userId, jobId, status: "completed" });
  return { scrape, asset };
}

async function handleViralAnalysis({ jobId, projectId, userId, input, progress }: JobContext) {
  if (!projectId) throw new Error("projectId is required");
  const project = await prisma.project.findUnique({
    where: { id: projectId },
    include: { assets: true, analyses: { orderBy: { createdAt: "desc" }, take: 1 } }
  });
  if (!project) throw new Error("Project not found");
  const videoUrl = input.videoUrl || project.assets.find((asset) => asset.type === "video")?.fileUrl || "";
  if (!videoUrl) throw new Error("videoUrl is required");

  const processingWarnings: string[] = [];
  let extractedAudio: { fileUrl: string; filePath: string; meta?: Record<string, unknown> } | null = null;
  let keyframes: Array<{ fileUrl: string; filePath: string; meta?: Record<string, unknown> }> = [];
  let transcript = input.transcript ? { text: input.transcript, source: "manual" } : null;

  try {
    if (String(videoUrl).startsWith("/uploads/")) {
      extractedAudio = await extractAudio({ inputUrl: videoUrl, projectId });
      await prisma.processedMedia.create({ data: { projectId, sourceUrl: videoUrl, type: "viral_audio", fileUrl: extractedAudio.fileUrl, meta: extractedAudio.meta as any } });
      if (!transcript) transcript = { source: "openai", ...(await transcribeAudioFile(extractedAudio.filePath)) } as any;
      await progress(35);
      keyframes = await extractKeyframes({ inputUrl: videoUrl, projectId, fps: 0.2 });
      await prisma.$transaction(keyframes.map((frame) => prisma.processedMedia.create({ data: { projectId, sourceUrl: videoUrl, type: "viral_keyframe", fileUrl: frame.fileUrl, meta: frame.meta as any } })));
    }
  } catch (error) {
    processingWarnings.push(error instanceof Error ? error.message : "Media preprocessing skipped.");
  }

  const context = {
    project,
    latestAnalysis: project.analyses[0] || null,
    videoUrl,
    transcript,
    notes: input.notes || null,
    extractedAudioUrl: extractedAudio?.fileUrl || null,
    keyframeUrls: keyframes.map((frame) => frame.fileUrl),
    processingWarnings
  };
  const result = await runJsonPrompt({
    prompt: viralVideoAnalysisPrompt(context),
    fallback: () => fallbackViralAnalysis({ ...project, videoUrl, transcript: input.transcript })
  });
  await progress(80);
  const data = result.data as ReturnType<typeof fallbackViralAnalysis>;
  const analysis = await prisma.viralVideoAnalysis.create({
    data: {
      projectId,
      videoUrl,
      transcript: (data as any).transcript || transcript,
      segmentBreakdown: data.segmentBreakdown,
      structureAnalysis: data.structureAnalysis,
      captionAnalysis: data.captionAnalysis,
      voiceAnalysis: data.voiceAnalysis,
      musicAnalysis: data.musicAnalysis,
      emotionAnalysis: data.emotionAnalysis,
      viralReason: data.viralReason,
      reusableTemplate: data.reusableTemplate,
      rewrittenScripts: data.rewrittenScripts || null
    }
  });
  const viralVideo = await createViralDetailModels({ projectId, videoUrl, transcript, analysisId: analysis.id, data, keyframes });
  await logUsage({ provider: "openai", model: process.env.OPENAI_MODEL || "gpt-5.5", projectId, userId, jobId, status: result.source === "openai" ? "completed" : "fallback", errorMessage: result.warning });
  return {
    analysis,
    viralVideo,
    data,
    source: result.source,
    warning: result.warning,
    processingWarnings,
    extractedAudioUrl: extractedAudio?.fileUrl || null,
    keyframeUrls: keyframes.map((frame) => frame.fileUrl)
  };
}

async function createViralDetailModels({ projectId, videoUrl, transcript, analysisId, data, keyframes }: any) {
  const viralVideo = await prisma.viralVideo.create({
    data: {
      projectId,
      sourceUrl: videoUrl,
      transcript,
      analysisId,
      hookType: data.openingHook || data.structureAnalysis?.framework || null,
      firstThreeSec: Array.isArray(data.segmentBreakdown) ? data.segmentBreakdown[0]?.visual || data.segmentBreakdown[0]?.caption || null : null,
      paceSummary: data.structureAnalysis?.rhythm || data.musicAnalysis?.editingTempo || null,
      captionStrategy: data.captionAnalysis?.captionRole || null,
      productExposure: data.structureAnalysis?.productExposure ? { value: data.structureAnalysis.productExposure } : undefined,
      painPointArc: data.emotionAnalysis || undefined,
      cta: data.structureAnalysis?.ctaDesign ? { value: data.structureAnalysis.ctaDesign } : undefined
    }
  });

  await prisma.$transaction([
    ...keyframes.slice(0, 12).map((frame: any, index: number) => prisma.viralFrame.create({
      data: {
        viralVideoId: viralVideo.id,
        frameUrl: frame.fileUrl,
        timestampSec: index * 5,
        meta: frame.meta as any
      }
    })),
    ...(Array.isArray(data.segmentBreakdown) ? data.segmentBreakdown.map((segment: any) => prisma.viralSegment.create({
      data: {
        viralVideoId: viralVideo.id,
        role: segment.function,
        hookType: segment.time?.includes("0-3") ? data.openingHook : null,
        visual: segment.visual,
        caption: segment.caption,
        voiceover: segment.voiceover,
        pace: segment.pace,
        emotion: segment.tone,
        productExposure: data.structureAnalysis?.productExposure
      }
    })) : []),
    ...(data.viralReason?.hypotheses || []).map((hypothesis: string) => prisma.viralPattern.create({
      data: { viralVideoId: viralVideo.id, type: "viral_reason", name: hypothesis }
    })),
    prisma.viralTemplate.create({
      data: {
        viralVideoId: viralVideo.id,
        name: data.reusableTemplate?.templateName || "Reusable viral template",
        template: data.reusableTemplate as any,
        rewrittenScripts: data.rewrittenScripts as any,
        bestFitProducts: data.reusableTemplate?.bestFitProducts as any
      }
    })
  ]);

  return prisma.viralVideo.findUnique({
    where: { id: viralVideo.id },
    include: { frames: true, segments: true, patterns: true, templates: true }
  });
}

function estimateAudioSeconds(text: string) {
  return Math.max(1, Math.round(text.length / 4));
}

async function logUsage(data: {
  provider: string;
  model?: string | null;
  projectId?: string | null;
  userId?: string | null;
  jobId?: string | null;
  inputTokens?: number;
  outputTokens?: number;
  imageCount?: number;
  audioSeconds?: number;
  videoSeconds?: number;
  estimatedCostUsd?: number;
  status: string;
  errorMessage?: string | null;
}) {
  await prisma.providerUsageLog.create({
    data: {
      provider: data.provider,
      model: data.model || null,
      projectId: data.projectId || null,
      userId: data.userId || null,
      jobId: data.jobId || null,
      inputTokens: data.inputTokens,
      outputTokens: data.outputTokens,
      imageCount: data.imageCount,
      audioSeconds: data.audioSeconds,
      videoSeconds: data.videoSeconds,
      estimatedCostUsd: data.estimatedCostUsd,
      status: data.status,
      errorMessage: data.errorMessage || null
    }
  });
}
