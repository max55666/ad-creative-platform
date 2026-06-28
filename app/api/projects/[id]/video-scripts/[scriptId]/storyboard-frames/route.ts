import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getSystemSettings } from "@/lib/settings";
import { normalizeStoryboardShot } from "@/lib/video-script-utils";

type Params = {
  params: Promise<{ id: string; scriptId: string }>;
};

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id, scriptId } = await params;
  const body = await request.json().catch(() => ({}));
  const settings = await getSystemSettings();
  const index = Number(body.index);

  if (!Number.isInteger(index) || index < 0) {
    return NextResponse.json({ message: "index must be a non-negative integer" }, { status: 400 });
  }

  const script = await prisma.videoScript.findFirst({
    where: { id: scriptId, projectId: id },
    include: { project: true }
  });

  if (!script) {
    return NextResponse.json({ message: "Script not found" }, { status: 404 });
  }

  const storyboard = Array.isArray(script.storyboard) ? [...script.storyboard] : [];
  if (!storyboard[index]) {
    return NextResponse.json({ message: "Storyboard frame not found" }, { status: 404 });
  }

  const currentShot = storyboard[index] && typeof storyboard[index] === "object" ? storyboard[index] as any : {};
  const nextShot = normalizeStoryboardShot({
    project: script.project,
    script,
    index,
    shot: {
      ...currentShot,
      ...(body.patch && typeof body.patch === "object" ? body.patch : {}),
      imageUrl: body.imageUrl ?? currentShot.imageUrl,
      imageSource: body.imageSource || currentShot.imageSource || "manual_upload",
      imageLocked: typeof body.imageLocked === "boolean" ? body.imageLocked : settings.workflow.keepUploadedStoryboardLocked,
      uploadedAt: body.imageUrl ? new Date().toISOString() : currentShot.uploadedAt
    }
  });

  storyboard[index] = nextShot;
  const updated = await prisma.videoScript.update({
    where: { id: script.id },
    data: {
      storyboard,
      storyboardImages: storyboard
        .map((shot: any, shotIndex: number) => shot?.imageUrl ? {
          index: shotIndex,
          imageUrl: shot.imageUrl,
          prompt: shot.imagePrompt || "",
          source: shot.imageSource || "unknown",
          locked: Boolean(shot.imageLocked)
        } : null)
        .filter(Boolean) as any,
      imageStatus: storyboard.some((shot: any) => shot?.imageUrl) ? "ready" : script.imageStatus
    }
  });

  return NextResponse.json({ script: updated, shot: nextShot });
}
