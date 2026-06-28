import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fallbackStaticCreatives } from "@/lib/fallbacks";
import { runJsonPrompt } from "@/lib/openai";
import { staticCreativePrompt } from "@/lib/prompts";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const suggestions = await prisma.staticCreativeSuggestion.findMany({
    where: { projectId: id },
    orderBy: { createdAt: "desc" }
  });

  return NextResponse.json({ suggestions });
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

  const context = {
    project,
    latestAnalysis: project.analyses[0] || null,
    referenceRules: [
      "Generated ad images must preserve uploaded product/reference images.",
      "The main product is referenceKey main_product. Do not replace it with a generic substitute.",
      "If reference assets have visualDescription in meta/content, use them as strict visual locks."
    ],
    regenerateTitle: body.regenerateTitle || null
  };

  const result = await runJsonPrompt({
    prompt: staticCreativePrompt(context),
    fallback: () => fallbackStaticCreatives(project)
  });

  const fallbackSuggestions = fallbackStaticCreatives(project).suggestions;
  const aiSuggestions = Array.isArray((result.data as any).suggestions)
    ? (result.data as any).suggestions
    : [];
  const suggestions = [...aiSuggestions, ...fallbackSuggestions].slice(0, Math.max(5, aiSuggestions.length));

  const created = await prisma.$transaction(
    suggestions.slice(0, 8).map((item: any) =>
      prisma.staticCreativeSuggestion.create({
        data: {
          projectId: id,
          title: item.title,
          headline: item.headline,
          subHeadline: item.subHeadline || null,
          visualDirection: item.visualDirection,
          copywriting: item.copywriting,
          cta: item.cta,
          platform: item.platform,
          targetAudience: item.targetAudience,
          communication: item.communication || null,
          imageStatus: "pending",
          source: result.source
        }
      })
    )
  );

  return NextResponse.json({ suggestions: created, source: result.source, warning: result.warning });
}
