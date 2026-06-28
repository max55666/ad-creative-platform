import { aiRouter } from "@/lib/ai/router";
import { getStorage } from "@/lib/storage";

export async function generateAndSaveImage({
  prompt,
  prefix,
  size = "1024x1024",
  referenceImageUrls = []
}: {
  prompt: string;
  prefix: string;
  size?: "1024x1024" | "1024x1536" | "1536x1024";
  referenceImageUrls?: string[];
}) {
  const result = await generateAndSaveImageFile({ prompt, prefix, size, referenceImageUrls });
  return result.fileUrl;
}

export async function generateAndSaveImageFile({
  prompt,
  prefix,
  size = "1024x1024",
  referenceImageUrls = []
}: {
  prompt: string;
  prefix: string;
  size?: "1024x1024" | "1024x1536" | "1536x1024";
  referenceImageUrls?: string[];
}) {
  const referenceImagePaths = referenceImageUrls
    .map((url) => {
      try {
        return getStorage().getLocalPath(url);
      } catch {
        return "";
      }
    })
    .filter(Boolean);

  const result = await aiRouter.generateImage({
    prompt,
    size,
    referenceImagePaths
  });

  const fileName = `${Date.now()}-${prefix}-${crypto.randomUUID()}.png`;
  const stored = await getStorage().put(result.buffer, {
    directory: "generated",
    fileName,
    contentType: "image/png"
  });

  return {
    fileUrl: stored.url,
    filePath: stored.path || getStorage().getLocalPath(stored.key),
    storageKey: stored.key,
    model: result.model,
    size: result.size
  };
}

export function imageSizeForAspectRatio(aspectRatio?: string) {
  if (aspectRatio === "1:1") return "1024x1024" as const;
  if (aspectRatio === "4:5" || aspectRatio === "9:16") return "1024x1536" as const;
  return "1024x1024" as const;
}

export function targetDimensionsForAspectRatio(aspectRatio?: string) {
  if (aspectRatio === "1:1") return { width: 1080, height: 1080 };
  if (aspectRatio === "4:5") return { width: 1080, height: 1350 };
  if (aspectRatio === "9:16") return { width: 1080, height: 1920 };
  return null;
}

export function buildStaticCreativeImagePrompt({
  project,
  creative
}: {
  project: any;
  creative: any;
}) {
  const referenceBrief = buildReferenceAssetBrief(project.assets);
  return [
    "Create a realistic ecommerce advertising visual concept for an internal creative brief.",
    "No readable text, no logos, no fake UI, no watermark. Leave clean negative space for text overlays.",
    "Use polished commercial photography, natural lighting, and modern Taiwanese ecommerce aesthetics.",
    "The image should clearly communicate the product use case and visual direction.",
    "The main product must match the uploaded reference image. Do not invent a different hero product, package, color, shape, logo placement, buttons, screen, or material.",
    "If additional reference objects are provided, keep each object visually consistent with its reference and do not replace them with generic alternatives.",
    `Product name: ${project.productName}.`,
    project.productDescription ? `Product description: ${project.productDescription}.` : "",
    project.price ? `Price range: ${project.price}.` : "",
    project.targetMarket ? `Target market: ${project.targetMarket}.` : "",
    referenceBrief ? `Reference asset lock:\n${referenceBrief}` : "",
    `Creative theme: ${creative.title}.`,
    `Headline intent: ${creative.headline}.`,
    creative.subHeadline ? `Sub headline intent: ${creative.subHeadline}.` : "",
    `Visual direction: ${creative.visualDirection}.`,
    `Target audience: ${creative.targetAudience}.`
  ]
    .filter(Boolean)
    .join("\n");
}

export function buildStoryboardFramePrompt({
  project,
  script,
  shot,
  index
}: {
  project: any;
  script: any;
  shot: any;
  index: number;
}) {
  if (typeof shot?.imagePrompt === "string" && shot.imagePrompt.trim()) {
    return appendReferenceGuard(shot.imagePrompt.trim(), project.assets, shot);
  }

  const referenceBrief = buildReferenceAssetBrief(project.assets, extractShotReferenceKeys(shot));
  return [
    "Create one vertical 9:16 storyboard frame for a short-form ecommerce video ad.",
    "No readable text, no subtitles, no watermark. Leave safe blank space for captions to be overlaid by the app.",
    "Use realistic commercial video still style, clear human action, product visible when relevant, modern Taiwan lifestyle setting.",
    "The product and every uploaded reference object must stay faithful to the reference images. Do not change the main product into a generic object.",
    `Product name: ${project.productName}.`,
    project.productDescription ? `Product description: ${project.productDescription}.` : "",
    project.price ? `Price range: ${project.price}.` : "",
    referenceBrief ? `Reference asset lock:\n${referenceBrief}` : "",
    `Video title: ${script.title}.`,
    `Platform: ${script.platform}. Style: ${script.style || "short video ad"}.`,
    `Shot number: ${index + 1}. Time: ${shot.time || "unknown"}.`,
    `Scene: ${shot.scene || ""}.`,
    `Visual instruction: ${shot.visual || ""}.`,
    `Purpose of this shot: ${shot.purpose || ""}.`,
    `Voiceover meaning: ${shot.voiceover || ""}.`
  ]
    .filter(Boolean)
    .join("\n");
}

export function getReferenceImageUrls(project: any, referenceKeys?: string[]) {
  const limit = positiveInt(process.env.OPENAI_IMAGE_REFERENCE_LIMIT, 3);
  const assets = Array.isArray(project?.assets) ? project.assets : [];
  const wanted = new Set((referenceKeys || []).map((key) => String(key).trim()).filter(Boolean));
  const imageAssets = assets.filter((asset: any) => asset?.type === "image" && asset?.fileUrl);
  const productAssets = imageAssets.filter((asset: any) => readMeta(asset).role === "product" || readMeta(asset).referenceKey === "main_product");
  const objectAssets = imageAssets.filter((asset: any) => {
    const meta = readMeta(asset);
    return wanted.size ? wanted.has(meta.referenceKey) || wanted.has(meta.label) : meta.role === "reference";
  });
  return [...productAssets, ...objectAssets, ...imageAssets]
    .map((asset: any) => String(asset.fileUrl))
    .filter((url, index, urls) => url && urls.indexOf(url) === index)
    .slice(0, limit);
}

function appendReferenceGuard(prompt: string, assets: unknown, shot: unknown) {
  const brief = buildReferenceAssetBrief(assets, extractShotReferenceKeys(shot));
  if (!brief) return prompt;
  return [
    prompt,
    "",
    "Reference asset lock:",
    brief,
    "Strictly preserve the uploaded main product and referenced objects. Do not generate a generic substitute."
  ].join("\n");
}

function buildReferenceAssetBrief(assets: unknown, referenceKeys?: string[]) {
  if (!Array.isArray(assets)) return "";
  const wanted = new Set((referenceKeys || []).map((key) => String(key).trim()).filter(Boolean));
  return assets
    .filter((asset: any) => asset?.type === "image")
    .map((asset: any) => {
      const meta = readMeta(asset);
      const shouldInclude =
        meta.role === "product" ||
        meta.referenceKey === "main_product" ||
        !wanted.size ||
        wanted.has(meta.referenceKey) ||
        wanted.has(meta.label);
      if (!shouldInclude) return "";
      const description = meta.visualDescription || asset.content || "Uploaded reference image.";
      const usage = meta.usage ? ` Usage: ${meta.usage}.` : "";
      const viewAngle = meta.viewAngle ? ` View angle: ${meta.viewAngle}.` : "";
      const notes = meta.notes ? ` User notes: ${meta.notes}.` : "";
      return `- ${meta.referenceKey || meta.label || "reference"} (${meta.role || "reference"}):${usage}${viewAngle}${notes} ${description}`;
    })
    .filter(Boolean)
    .join("\n");
}

function extractShotReferenceKeys(shot: unknown) {
  if (!shot || typeof shot !== "object") return [];
  const record = shot as Record<string, unknown>;
  const values = [
    record.requiredReferenceKeys,
    record.referenceKeys,
    record.sceneObjects
  ];
  return values.flatMap((value) => {
    if (Array.isArray(value)) {
      return value.map((item) => {
        if (item && typeof item === "object") {
          const object = item as Record<string, unknown>;
          return String(object.referenceKey || object.key || object.label || object.name || "");
        }
        return String(item || "");
      });
    }
    return typeof value === "string" ? value.split(/[,，、\n]/) : [];
  }).map((item) => item.trim()).filter(Boolean);
}

function readMeta(asset: any) {
  return asset?.meta && typeof asset.meta === "object" && !Array.isArray(asset.meta) ? asset.meta as Record<string, string> : {};
}

function positiveInt(value: string | undefined, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}
