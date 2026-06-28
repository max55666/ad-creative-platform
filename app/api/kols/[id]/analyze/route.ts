import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fallbackKolAnalysis } from "@/lib/kol-fallbacks";
import { KolAnalysisInput, kolAnalysisPrompt } from "@/lib/kol-prompts";
import { runJsonPrompt } from "@/lib/openai";
import { getDemoUser } from "@/lib/projects";

type Params = {
  params: Promise<{ id: string }>;
};

function asString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const projectId = asString(body.projectId) || null;
  const profile = await prisma.kolProfile.findFirst({
    where: { id, userId: user.id },
    include: { videos: { orderBy: { createdAt: "desc" } } }
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

  const input: KolAnalysisInput = {
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
      : null
  };

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

  return NextResponse.json({ analysis, data, source: result.source, warning: result.warning });
}
