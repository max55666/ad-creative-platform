import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fallbackKolAnalysis } from "@/lib/kol-fallbacks";
import { KolAnalysisInput, KolVideoInput, kolAnalysisPrompt } from "@/lib/kol-prompts";
import { runJsonPrompt } from "@/lib/openai";
import { getDemoUser } from "@/lib/projects";

function asString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeTags(value: unknown) {
  if (Array.isArray(value)) return value.map(asString).filter(Boolean);
  return asString(value)
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeVideos(value: unknown): KolVideoInput[] {
  if (!Array.isArray(value)) return [];
  const videos: KolVideoInput[] = [];

  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const video = {
      videoUrl: asString(record.videoUrl) || null,
      fileUrl: asString(record.fileUrl) || null,
      title: asString(record.title) || null,
      sponsoredBrand: asString(record.sponsoredBrand) || null,
      sponsoredProduct: asString(record.sponsoredProduct) || null,
      notes: asString(record.notes) || null
    };
    if (video.videoUrl || video.fileUrl || video.notes || video.title) videos.push(video);
  }

  return videos;
}

async function buildInput(body: Record<string, unknown>, projectId?: string | null): Promise<KolAnalysisInput> {
  const project = projectId
    ? await prisma.project.findUnique({
        where: { id: projectId },
        include: { analyses: { orderBy: { createdAt: "desc" }, take: 1 } }
      })
    : null;

  return {
    name: asString(body.name) || "未命名 KOL",
    platform: asString(body.platform) || "TikTok / Instagram",
    profileUrl: asString(body.profileUrl),
    description: asString(body.description) || null,
    followerCount: asString(body.followerCount) || null,
    avgViews: asString(body.avgViews) || null,
    avgEngagement: asString(body.avgEngagement) || null,
    tags: normalizeTags(body.tags),
    videos: normalizeVideos(body.videos),
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
      : null
  };
}

async function createUsageLog({
  userId,
  projectId,
  usage,
  status,
  errorMessage
}: {
  userId: string;
  projectId?: string | null;
  usage?: { provider?: string; model?: string; inputTokens?: number; outputTokens?: number };
  status: string;
  errorMessage?: string;
}) {
  await prisma.providerUsageLog.create({
    data: {
      provider: usage?.provider || "openai",
      model: usage?.model,
      userId,
      projectId: projectId || null,
      inputTokens: usage?.inputTokens,
      outputTokens: usage?.outputTokens,
      status,
      errorMessage
    }
  });
}

export async function GET() {
  const user = await getDemoUser();
  const profiles = await prisma.kolProfile.findMany({
    where: { userId: user.id },
    orderBy: { updatedAt: "desc" },
    include: {
      project: true,
      videos: { orderBy: { createdAt: "desc" }, take: 3 },
      analyses: { orderBy: { createdAt: "desc" }, take: 1 },
      scripts: { orderBy: { createdAt: "desc" }, take: 3 },
      _count: { select: { videos: true, analyses: true, scripts: true } }
    }
  });

  return NextResponse.json({ profiles });
}

export async function POST(request: NextRequest) {
  const user = await getDemoUser();
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const projectId = asString(body.projectId) || null;
  const profileUrl = asString(body.profileUrl);

  if (!profileUrl) {
    return NextResponse.json({ message: "請先填入 KOL 網址。" }, { status: 400 });
  }

  const project = projectId ? await prisma.project.findFirst({ where: { id: projectId, userId: user.id } }) : null;
  if (projectId && !project) {
    return NextResponse.json({ message: "找不到指定產品專案。" }, { status: 404 });
  }

  const input = await buildInput(body, project?.id);
  const videos = input.videos || [];

  const profile = await prisma.kolProfile.create({
    data: {
      userId: user.id,
      projectId: project?.id || null,
      name: input.name,
      platform: input.platform,
      profileUrl: input.profileUrl,
      description: input.description,
      followerCount: input.followerCount,
      avgViews: input.avgViews,
      avgEngagement: input.avgEngagement,
      tags: input.tags || [],
      videos: {
        create: videos.map((video) => ({
          videoUrl: video.videoUrl || null,
          fileUrl: video.fileUrl || null,
          title: video.title || null,
          sponsoredBrand: video.sponsoredBrand || null,
          sponsoredProduct: video.sponsoredProduct || null,
          notes: video.notes || null
        }))
      }
    }
  });

  const result = await runJsonPrompt({
    prompt: kolAnalysisPrompt(input),
    fallback: () => fallbackKolAnalysis(input),
    temperature: 0.35
  });
  const data = result.data as ReturnType<typeof fallbackKolAnalysis>;

  const analysis = await prisma.kolAnalysis.create({
    data: {
      kolProfileId: profile.id,
      userId: user.id,
      projectId: project?.id || null,
      persona: data.persona,
      contentStyle: data.contentStyle,
      audienceProfile: data.audienceProfile,
      brandFit: data.brandFit,
      productFit: data.productFit,
      sponsoredVideoInsights: data.sponsoredVideoInsights,
      suitableProducts: data.suitableProducts,
      riskAssessment: data.riskAssessment,
      recommendations: data.recommendations,
      rawOutput: {
        source: result.source,
        warning: result.warning,
        kolSummary: data.kolSummary,
        data
      }
    }
  });

  await createUsageLog({
    userId: user.id,
    projectId: project?.id,
    usage: result.usage,
    status: result.source === "openai" ? "completed" : "fallback",
    errorMessage: result.warning
  });

  const fullProfile = await prisma.kolProfile.findUnique({
    where: { id: profile.id },
    include: {
      project: true,
      videos: { orderBy: { createdAt: "desc" } },
      analyses: { orderBy: { createdAt: "desc" }, take: 1 },
      scripts: { orderBy: { createdAt: "desc" } },
      _count: { select: { videos: true, analyses: true, scripts: true } }
    }
  });

  return NextResponse.json({ profile: fullProfile, analysis, data, source: result.source, warning: result.warning });
}
