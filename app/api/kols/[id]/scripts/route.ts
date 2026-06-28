import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fallbackKolScripts } from "@/lib/kol-fallbacks";
import { KolScriptInput, kolScriptPrompt } from "@/lib/kol-prompts";
import { runJsonPrompt } from "@/lib/openai";
import { getDemoUser } from "@/lib/projects";

type Params = {
  params: Promise<{ id: string }>;
};

function asString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function arrayOrEmpty(value: unknown) {
  return Array.isArray(value) ? value : [];
}

export async function GET(_request: Request, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const profile = await prisma.kolProfile.findFirst({ where: { id, userId: user.id } });

  if (!profile) {
    return NextResponse.json({ message: "KOL profile not found" }, { status: 404 });
  }

  const scripts = await prisma.kolScript.findMany({
    where: { kolProfileId: profile.id },
    orderBy: { createdAt: "desc" },
    include: { project: true }
  });

  return NextResponse.json({ scripts });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const projectId = asString(body.projectId) || null;
  const profile = await prisma.kolProfile.findFirst({
    where: { id, userId: user.id },
    include: {
      videos: { orderBy: { createdAt: "desc" } },
      analyses: { orderBy: { createdAt: "desc" }, take: 1 }
    }
  });

  if (!profile) {
    return NextResponse.json({ message: "KOL profile not found" }, { status: 404 });
  }

  const project = projectId
    ? await prisma.project.findFirst({
        where: { id: projectId, userId: user.id },
        include: { analyses: { orderBy: { createdAt: "desc" }, take: 1 } }
      })
    : profile.projectId
      ? await prisma.project.findFirst({
          where: { id: profile.projectId, userId: user.id },
          include: { analyses: { orderBy: { createdAt: "desc" }, take: 1 } }
        })
      : null;

  if (projectId && !project) {
    return NextResponse.json({ message: "找不到指定產品專案。" }, { status: 404 });
  }

  const input: KolScriptInput = {
    name: profile.name,
    platform: profile.platform,
    profileUrl: profile.profileUrl,
    description: profile.description,
    followerCount: profile.followerCount,
    avgViews: profile.avgViews,
    avgEngagement: profile.avgEngagement,
    tags: Array.isArray(profile.tags) ? (profile.tags as string[]) : [],
    videos: profile.videos.map((video) => ({
      videoUrl: video.videoUrl,
      fileUrl: video.fileUrl,
      title: video.title,
      sponsoredBrand: video.sponsoredBrand,
      sponsoredProduct: video.sponsoredProduct,
      notes: video.notes
    })),
    product: project
      ? {
          id: project.id,
          productName: project.productName,
          productDescription: project.productDescription,
          productUrl: project.productUrl,
          targetMarket: project.targetMarket,
          price: project.price,
          specs: project.specs,
          mainUseCase: project.mainUseCase,
          competitors: project.competitors
        }
      : null,
    latestAnalysis: profile.analyses[0]?.rawOutput || profile.analyses[0] || null,
    objective: asString(body.objective) || "導購轉換",
    duration: asString(body.duration) || "30秒",
    platformTarget: asString(body.platformTarget) || profile.platform,
    style: asString(body.style) || "真實分享"
  };

  const fallback = fallbackKolScripts(input);
  const result = await runJsonPrompt({
    prompt: kolScriptPrompt(input),
    fallback: () => fallback,
    temperature: 0.45
  });

  const aiScripts = Array.isArray((result.data as any).scripts) ? (result.data as any).scripts : [];
  const scripts = [...aiScripts, ...fallback.scripts].slice(0, Math.max(3, aiScripts.length));

  const created = await prisma.$transaction(
    scripts.map((script: any) =>
      prisma.kolScript.create({
        data: {
          kolProfileId: profile.id,
          userId: user.id,
          projectId: project?.id || null,
          title: asString(script.title) || `${profile.name} 專屬業配腳本`,
          platform: asString(script.platform) || input.platformTarget || profile.platform,
          objective: asString(script.objective) || input.objective || "導購轉換",
          duration: asString(script.duration) || input.duration || "30秒",
          hook: asString(script.hook) || "用 KOL 的真實使用情境開場。",
          storyline: arrayOrEmpty(script.storyline),
          captions: arrayOrEmpty(script.captions),
          voiceover: arrayOrEmpty(script.voiceover),
          shotList: arrayOrEmpty(script.shotList),
          cta: asString(script.cta) || "點連結看更多資訊。",
          adUsageNotes: script.adUsageNotes && typeof script.adUsageNotes === "object" ? script.adUsageNotes : {},
          rawOutput: {
            source: result.source,
            warning: result.warning,
            script
          }
        }
      })
    )
  );

  await prisma.providerUsageLog.create({
    data: {
      provider: result.usage?.provider || "openai",
      model: result.usage?.model,
      userId: user.id,
      projectId: project?.id || null,
      inputTokens: result.usage?.inputTokens,
      outputTokens: result.usage?.outputTokens,
      status: result.source === "openai" ? "completed" : "fallback",
      errorMessage: result.warning
    }
  });

  return NextResponse.json({ scripts: created, source: result.source, warning: result.warning });
}
