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
    type: JOB_TYPES.RENDER_VIDEO,
    projectId: id,
    userId: script.project.userId,
    inputPayload: {
      scriptId,
      audioUrl: body.audioUrl,
      imageUrls: body.imageUrls,
      subtitles: body.subtitles,
      secondsPerImage: body.secondsPerImage || settings.output.secondsPerImage || 3,
      subtitleStyle: body.subtitleStyle || settings.output.subtitleStyle || "default",
      aspectRatio: body.aspectRatio || settings.output.defaultAspectRatio || "9:16",
      autoGenerateAssets: body.autoGenerateAssets ?? settings.workflow.autoGenerateStoryboard,
      autoGenerateVoiceover: body.autoGenerateVoiceover ?? settings.workflow.autoGenerateVoiceover,
      maxFrames: body.maxFrames || settings.workflow.maxStoryboardFrames || 5,
      language: body.language || settings.providers.voiceover.defaultLanguage || "zh",
      gender: body.gender || settings.providers.voiceover.defaultGender || "female",
      motionStyle: body.motionStyle || "subtle",
      renderMode: body.renderMode || settings.providers.video.defaultMode || "static",
      clipDurationSec: body.clipDurationSec || settings.providers.video.clipDurationSec || 5
    }
  });

  return NextResponse.json({ jobId: job.id, job }, { status: 202 });
}
