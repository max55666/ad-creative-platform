import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { syncProductLoraTraining } from "@/lib/services/product-lora-training";

type Params = {
  params: Promise<{ id: string; modelId: string }>;
};

export async function POST(_request: Request, { params }: Params) {
  const { id, modelId } = await params;
  const model = await prisma.productLoraModel.findFirst({
    where: { id: modelId, projectId: id }
  });
  if (!model) return NextResponse.json({ message: "LoRA model not found" }, { status: 404 });

  try {
    const updated = await syncProductLoraTraining(modelId);
    return NextResponse.json({ model: updated });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to sync LoRA training status.";
    const updated = await prisma.productLoraModel.update({
      where: { id: modelId },
      data: { errorMessage: message }
    });
    return NextResponse.json({ model: updated, message }, { status: 500 });
  }
}
