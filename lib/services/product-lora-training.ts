import { readFile } from "fs/promises";
import path from "path";
import JSZip from "jszip";
import type { ProductAsset, Project } from "@prisma/client";
import { prisma } from "@/lib/db";
import { FAL_FLUX_LORA_TRAINING_ENDPOINT, falFileUrl, getFalClient } from "@/lib/ai/providers/fal";
import { getStorage } from "@/lib/storage";

type ProjectWithAssets = Project & { assets: ProductAsset[] };

export async function submitProductLoraTraining({
  modelId,
  project,
  assetIds,
  triggerWord,
  steps = 1000,
  createMasks = true
}: {
  modelId: string;
  project: ProjectWithAssets;
  assetIds?: string[];
  triggerWord: string;
  steps?: number;
  createMasks?: boolean;
}) {
  const assets = selectTrainingAssets(project, assetIds);
  if (assets.length < 4) {
    throw new Error("LoRA 訓練至少需要 4 張產品圖片，建議 15-30 張。");
  }

  const archive = await buildTrainingZip({ project, assets, triggerWord });
  const falClient = getFalClient();
  const archiveBlob = new Blob([Buffer.from(archive)], { type: "application/zip" });
  const archiveUrl = await falClient.storage.upload(archiveBlob, {
    lifecycle: { expiresIn: "30d" }
  });

  const input = {
    images_data_url: archiveUrl,
    trigger_word: triggerWord,
    create_masks: createMasks,
    steps,
    is_style: false
  };

  const queued = await falClient.queue.submit(FAL_FLUX_LORA_TRAINING_ENDPOINT as any, {
    input,
    logs: true
  } as any);

  return prisma.productLoraModel.update({
    where: { id: modelId },
    data: {
      status: "training",
      endpoint: FAL_FLUX_LORA_TRAINING_ENDPOINT,
      requestId: queued.request_id,
      dataArchiveUrl: archiveUrl,
      trainingImageCount: assets.length,
      assetIds: assets.map((asset) => asset.id),
      input: {
        ...input,
        images_data_url: archiveUrl,
        selectedAssetIds: assets.map((asset) => asset.id)
      } as any,
      errorMessage: null
    }
  });
}

export async function syncProductLoraTraining(modelId: string) {
  const model = await prisma.productLoraModel.findUnique({ where: { id: modelId } });
  if (!model?.requestId) throw new Error("This LoRA model has no fal request id yet.");

  const falClient = getFalClient();
  const status = await falClient.queue.status(model.endpoint, { requestId: model.requestId, logs: true });

  const queueStatus = String(status.status);
  if (queueStatus !== "COMPLETED") {
    const failed = queueStatus === "FAILED" || queueStatus === "ERROR";
    return prisma.productLoraModel.update({
      where: { id: modelId },
      data: {
        status: failed ? "failed" : "training",
        errorMessage: failed ? JSON.stringify(status) : null,
        output: status as any
      }
    });
  }

  const result = await falClient.queue.result(model.endpoint as any, { requestId: model.requestId });
  const data = (result as any).data || result;
  const diffusersLoraUrl = falFileUrl(data.diffusers_lora_file);
  const configFileUrl = falFileUrl(data.config_file);
  const debugPreprocessedUrl = falFileUrl(data.debug_preprocessed_output);

  return prisma.productLoraModel.update({
    where: { id: modelId },
    data: {
      status: diffusersLoraUrl ? "ready" : "completed",
      diffusersLoraUrl,
      configFileUrl,
      debugPreprocessedUrl,
      output: data as any,
      completedAt: new Date(),
      errorMessage: null
    }
  });
}

function selectTrainingAssets(project: ProjectWithAssets, assetIds?: string[]) {
  const wanted = new Set((assetIds || []).filter(Boolean));
  const imageAssets = project.assets.filter((asset) => asset.type === "image" && asset.fileUrl);
  const selected = wanted.size ? imageAssets.filter((asset) => wanted.has(asset.id)) : imageAssets;
  return selected.slice(0, 40);
}

async function buildTrainingZip({
  project,
  assets,
  triggerWord
}: {
  project: ProjectWithAssets;
  assets: ProductAsset[];
  triggerWord: string;
}) {
  const zip = new JSZip();
  for (const [index, asset] of assets.entries()) {
    if (!asset.fileUrl) continue;
    const filePath = getStorage().getLocalPath(asset.fileUrl);
    const ext = normalizeImageExtension(filePath);
    const baseName = `product-${String(index + 1).padStart(2, "0")}`;
    const buffer = await readFile(filePath);
    zip.file(`${baseName}${ext}`, buffer);
    zip.file(`${baseName}.txt`, buildCaption({ project, asset, triggerWord }));
  }

  return zip.generateAsync({ type: "uint8array", compression: "DEFLATE" });
}

function buildCaption({
  project,
  asset,
  triggerWord
}: {
  project: ProjectWithAssets;
  asset: ProductAsset;
  triggerWord: string;
}) {
  const meta = asset.meta && typeof asset.meta === "object" && !Array.isArray(asset.meta) ? asset.meta as Record<string, unknown> : {};
  const notes = [meta.usage, meta.viewAngle, meta.notes, meta.visualDescription, asset.content]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(", ");

  return [
    triggerWord,
    project.productName,
    "ecommerce product photo",
    notes
  ].filter(Boolean).join(", ");
}

function normalizeImageExtension(filePath: string) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return ".jpg";
  if (ext === ".webp") return ".webp";
  if (ext === ".png") return ".png";
  return ".jpg";
}
