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
  const project = await prisma.project.findUnique({ where: { id } });

  if (!project) {
    return NextResponse.json({ message: "Project not found" }, { status: 404 });
  }

  if (!body.inputUrl) {
    return NextResponse.json({ message: "inputUrl is required" }, { status: 400 });
  }

  const job = await enqueueGenerationJob({
    type: JOB_TYPES.PROCESS_IMAGE,
    projectId: id,
    userId: project.userId,
    inputPayload: body
  });

  return NextResponse.json({ jobId: job.id, job }, { status: 202 });
}
