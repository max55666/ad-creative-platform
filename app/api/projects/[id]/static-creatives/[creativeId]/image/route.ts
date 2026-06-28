import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { enqueueGenerationJob } from "@/lib/jobs/queue";
import { JOB_TYPES } from "@/lib/jobs/types";

type Params = {
  params: Promise<{ id: string; creativeId: string }>;
};

export async function POST(request: NextRequest, { params }: Params) {
  const { id, creativeId } = await params;
  const body = await request.json().catch(() => ({}));
  const creative = await prisma.staticCreativeSuggestion.findFirst({
    where: { id: creativeId, projectId: id },
    include: { project: true }
  });

  if (!creative) {
    return NextResponse.json({ message: "Creative not found" }, { status: 404 });
  }

  await prisma.staticCreativeSuggestion.update({
    where: { id: creative.id },
    data: { imageStatus: "queued" }
  });

  const job = await enqueueGenerationJob({
    type: JOB_TYPES.STATIC_CREATIVE_IMAGE,
    projectId: id,
    userId: creative.project.userId,
    inputPayload: {
      creativeId,
      aspectRatio: body.aspectRatio || "1:1"
    }
  });

  return NextResponse.json({ jobId: job.id, job }, { status: 202 });
}
