import { prisma } from "@/lib/db";

export async function createCreativeVersion({
  projectId,
  userId,
  type,
  title,
  sourceRefId,
  kind,
  prompt,
  model,
  provider,
  generationParams,
  content,
  assets
}: {
  projectId: string;
  userId?: string | null;
  type: string;
  title: string;
  sourceRefId?: string | null;
  kind: string;
  prompt?: string | null;
  model?: string | null;
  provider?: string | null;
  generationParams?: unknown;
  content?: unknown;
  assets?: Array<{
    type: string;
    url: string;
    storageKey?: string | null;
    mimeType?: string | null;
    meta?: unknown;
  }>;
}) {
  const existing = sourceRefId
    ? await prisma.creative.findFirst({ where: { projectId, sourceRefId } })
    : null;
  const creative = existing || await prisma.creative.create({
    data: {
      projectId,
      userId: userId || null,
      type,
      title,
      sourceRefId: sourceRefId || null
    }
  });

  const latest = await prisma.creativeVersion.findFirst({
    where: { creativeId: creative.id },
    orderBy: { version: "desc" }
  });

  const createdVersion = await prisma.creativeVersion.create({
    data: {
      creativeId: creative.id,
      version: (latest?.version || 0) + 1,
      kind,
      prompt,
      model,
      provider,
      generationParams: generationParams as any,
      content: content as any
    },
    include: { creative: true }
  });

  if (assets?.length) {
    await prisma.creativeAsset.createMany({
      data: assets.map((asset) => ({
        creativeId: creative.id,
        versionId: createdVersion.id,
        type: asset.type,
        url: asset.url,
        storageKey: asset.storageKey || null,
        mimeType: asset.mimeType || null,
        meta: asset.meta as any
      }))
    });
  }

  return prisma.creativeVersion.findUnique({
    where: { id: createdVersion.id },
    include: { assets: true, creative: true }
  });
}
