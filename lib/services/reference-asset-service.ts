import { readFile } from "fs/promises";
import path from "path";
import type { ProductAsset } from "@prisma/client";
import { prisma } from "@/lib/db";
import { getOpenAIClient } from "@/lib/ai/providers/openai";
import { getStorage } from "@/lib/storage";

export type ReferenceAssetMeta = {
  role?: "product" | "reference" | "storyboard" | "other";
  label?: string;
  referenceKey?: string;
  visualDescription?: string;
  mustPreserve?: string[];
  avoidChanges?: string[];
  usage?: string;
  viewAngle?: string;
  notes?: string;
  analyzedAt?: string;
  originalName?: string;
  mimeType?: string;
  size?: number;
  [key: string]: unknown;
};

export function normalizeReferenceKey(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s/\\]+/g, "_")
    .replace(/[^a-z0-9_\-\u4e00-\u9fa5]+/g, "")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}

export function readAssetMeta(asset: Pick<ProductAsset, "meta">): ReferenceAssetMeta {
  return asset.meta && typeof asset.meta === "object" && !Array.isArray(asset.meta) ? (asset.meta as ReferenceAssetMeta) : {};
}

export async function analyzeAndUpdateReferenceAsset(assetId: string) {
  const asset = await prisma.productAsset.findUnique({ where: { id: assetId }, include: { project: true } });
  if (!asset || asset.type !== "image" || !asset.fileUrl) return null;

  const meta = readAssetMeta(asset);
  const visual = await describeReferenceImage({
    fileUrl: asset.fileUrl,
    label: String(meta.label || asset.project.productName || "reference asset"),
    role: String(meta.role || "reference"),
    usage: String(meta.usage || "visual reference"),
    viewAngle: String(meta.viewAngle || ""),
    notes: String(meta.notes || "")
  });

  return prisma.productAsset.update({
    where: { id: asset.id },
    data: {
      content: visual.description,
      meta: {
        ...meta,
        role: meta.role || "reference",
        label: meta.label || asset.project.productName,
        referenceKey: meta.referenceKey || normalizeReferenceKey(String(meta.label || asset.project.productName || "reference")),
        visualDescription: visual.description,
        mustPreserve: visual.mustPreserve,
        avoidChanges: visual.avoidChanges,
        analyzedAt: new Date().toISOString()
      }
    }
  });
}

async function describeReferenceImage({
  fileUrl,
  label,
  role,
  usage,
  viewAngle,
  notes
}: {
  fileUrl: string;
  label: string;
  role: string;
  usage: string;
  viewAngle: string;
  notes: string;
}) {
  const fallback = {
    description: `${label} reference image for ${usage}. Preserve the exact product/object identity from the uploaded image.`,
    mustPreserve: ["overall shape", "main color", "visible details", "relative proportions"],
    avoidChanges: ["do not replace with a generic substitute", "do not invent different logo or packaging"]
  };

  const openai = getOpenAIClient();
  if (!openai) return fallback;

  try {
    const filePath = getStorage().getLocalPath(fileUrl);
    const buffer = await readFile(filePath);
    const mimeType = mimeTypeFromPath(filePath);
    const imageUrl = `data:${mimeType};base64,${buffer.toString("base64")}`;
    const completion = await openai.chat.completions.create({
      model: process.env.OPENAI_VISION_MODEL || process.env.OPENAI_MODEL || "gpt-4o-mini",
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: "You describe reference images for ecommerce ad generation. Return strict JSON only."
        },
        {
          role: "user",
          content: [
            {
              type: "text",
              text: [
                `Reference label: ${label}`,
                `Reference role: ${role}`,
                `Reference usage: ${usage}`,
                viewAngle ? `View angle: ${viewAngle}` : "",
                notes ? `User notes: ${notes}` : "",
                "Describe the exact visual identity that an image generation model must preserve.",
                "Return JSON with description, mustPreserve array, avoidChanges array.",
                "Focus on shape, color, material, proportions, logo/mark placement if visible, distinctive details, and what must not change."
              ].join("\n")
            },
            { type: "image_url", image_url: { url: imageUrl } }
          ]
        }
      ]
    });
    const content = completion.choices[0]?.message?.content;
    if (!content) return fallback;
    const parsed = JSON.parse(content);
    return {
      description: typeof parsed.description === "string" ? parsed.description : fallback.description,
      mustPreserve: Array.isArray(parsed.mustPreserve) ? parsed.mustPreserve.map(String) : fallback.mustPreserve,
      avoidChanges: Array.isArray(parsed.avoidChanges) ? parsed.avoidChanges.map(String) : fallback.avoidChanges
    };
  } catch {
    return fallback;
  }
}

function mimeTypeFromPath(filePath: string) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  return "image/png";
}
