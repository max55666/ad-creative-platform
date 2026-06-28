import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { enqueueGenerationJob } from "@/lib/jobs/queue";
import { JOB_TYPES } from "@/lib/jobs/types";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const analyses = await prisma.viralVideoAnalysis.findMany({
    where: { projectId: id },
    orderBy: { createdAt: "desc" }
  });

  return NextResponse.json({ analyses });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const project = await prisma.project.findUnique({
    where: { id },
    include: {
      assets: true,
      analyses: { orderBy: { createdAt: "desc" }, take: 1 }
    }
  });

  if (!project) {
    return NextResponse.json({ message: "Project not found" }, { status: 404 });
  }

  const videoUrl =
    body.videoUrl ||
    project.assets.find((asset: any) => asset.type === "video")?.fileUrl ||
    "";

  if (!videoUrl) {
    return NextResponse.json({ message: "videoUrl is required" }, { status: 400 });
  }

  const job = await enqueueGenerationJob({
    type: JOB_TYPES.VIRAL_ANALYSIS,
    projectId: id,
    userId: project.userId,
    inputPayload: {
      videoUrl,
      transcript: body.transcript,
      notes: body.notes
    }
  });

  return NextResponse.json({ jobId: job.id, job }, { status: 202 });
}
