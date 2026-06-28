import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { enqueueGenerationJob } from "@/lib/jobs/queue";
import { JOB_TYPES } from "@/lib/jobs/types";

type Params = {
  params: Promise<{ id: string }>;
};

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const project = await prisma.project.findUnique({ where: { id }, include: { assets: true } });

  if (!project) {
    return NextResponse.json({ message: "Project not found" }, { status: 404 });
  }

  const inputUrl = body.inputUrl || project.assets.find((asset) => asset.type === "video")?.fileUrl || "";
  if (!inputUrl) {
    return NextResponse.json({ message: "inputUrl is required" }, { status: 400 });
  }

  const job = await enqueueGenerationJob({
    type: JOB_TYPES.EXTRACT_FRAMES,
    projectId: id,
    userId: project.userId,
    inputPayload: { inputUrl, fps: Number(body.fps || 0.2) }
  });

  return NextResponse.json({ jobId: job.id, job }, { status: 202 });
}
