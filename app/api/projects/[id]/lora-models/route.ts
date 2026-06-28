import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { enqueueGenerationJob } from "@/lib/jobs/queue";
import { JOB_TYPES } from "@/lib/jobs/types";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const models = await prisma.productLoraModel.findMany({
    where: { projectId: id },
    orderBy: { createdAt: "desc" }
  });
  return NextResponse.json({ models });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const project = await prisma.project.findUnique({
    where: { id },
    include: { assets: true }
  });
  if (!project) return NextResponse.json({ message: "Project not found" }, { status: 404 });

  const triggerWord = normalizeTriggerWord(body.triggerWord || project.productName);
  if (!triggerWord) {
    return NextResponse.json({ message: "請填寫 trigger word。" }, { status: 400 });
  }

  const assetIds = Array.isArray(body.assetIds) ? body.assetIds.map(String).filter(Boolean) : [];
  const imageCount = assetIds.length || project.assets.filter((asset) => asset.type === "image" && asset.fileUrl).length;
  if (imageCount < 4) {
    return NextResponse.json({ message: "LoRA 訓練至少需要 4 張產品圖片，建議 15-30 張。" }, { status: 400 });
  }

  const model = await prisma.productLoraModel.create({
    data: {
      projectId: id,
      userId: project.userId,
      name: String(body.name || `${project.productName} LoRA`).trim(),
      triggerWord,
      status: "queued",
      trainingImageCount: imageCount,
      assetIds,
      samplePrompt: `${triggerWord}, premium ecommerce product photo, clean studio lighting`,
      input: {
        steps: Number(body.steps || 1000),
        createMasks: body.createMasks !== false,
        assetIds
      } as any
    }
  });

  const job = await enqueueGenerationJob({
    type: JOB_TYPES.PRODUCT_LORA_TRAINING,
    projectId: id,
    userId: project.userId,
    inputPayload: {
      modelId: model.id,
      triggerWord,
      steps: Number(body.steps || 1000),
      createMasks: body.createMasks !== false,
      assetIds
    }
  });

  return NextResponse.json({ model, jobId: job.id, job }, { status: 202 });
}

function normalizeTriggerWord(value: unknown) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
}
