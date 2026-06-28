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

  const job = await enqueueGenerationJob({
    type: JOB_TYPES.VOICEOVER,
    projectId: id,
    userId: script.project.userId,
    inputPayload: {
      scriptId,
      language: body.language || settings.providers.voiceover.defaultLanguage || "zh",
      gender: body.gender || settings.providers.voiceover.defaultGender || "female",
      voiceId: body.voiceId,
      text: body.text
    }
  });

  return NextResponse.json({ jobId: job.id, job }, { status: 202 });
}
