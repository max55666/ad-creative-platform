import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { enqueueGenerationJob } from "@/lib/jobs/queue";
import { JOB_TYPES } from "@/lib/jobs/types";
import { getSystemSettings } from "@/lib/settings";

type Params = {
  params: Promise<{ id: string; scriptId: string }>;
};

export async function POST(request: NextRequest, { params }: Params) {
  const { id, scriptId } = await params;
  const body = await request.json().catch(() => ({}));
  const settings = await getSystemSettings();
  const script = await prisma.videoScript.findFirst({
    where: { id: scriptId, projectId: id },
    include: { project: true }
  });

  if (!script) {
    return NextResponse.json({ message: "Script not found" }, { status: 404 });
  }

  await prisma.videoScript.update({
    where: { id: script.id },
    data: { imageStatus: "queued" }
  });

  const job = await enqueueGenerationJob({
    type: JOB_TYPES.STORYBOARD_IMAGES,
    projectId: id,
    userId: script.project.userId,
    inputPayload: {
      scriptId,
      maxFrames: Math.min(Number(body.maxFrames || settings.workflow.maxStoryboardFrames || 5), 8)
    }
  });

  return NextResponse.json({ jobId: job.id, job }, { status: 202 });
}
