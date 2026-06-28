import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fallbackProductAnalysis } from "@/lib/fallbacks";
import { runJsonPrompt } from "@/lib/openai";
import { productAnalysisPrompt, type ProductPromptInput } from "@/lib/prompts";
import { extractUrlContext } from "@/lib/url-extractor";

type Params = {
  params: Promise<{ id: string }>;
};

export async function POST(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const project = await prisma.project.findUnique({
    where: { id },
    include: {
      assets: true,
      brand: {
        include: {
          brains: { orderBy: { createdAt: "desc" }, take: 1 }
        }
      }
    }
  });

  if (!project) {
    return NextResponse.json({ message: "Project not found" }, { status: 404 });
  }

  const urlContext = await extractUrlContext(project.productUrl);
  const input: ProductPromptInput = {
    productName: project.productName,
    productDescription: project.productDescription,
    productUrl: project.productUrl,
    targetMarket: project.targetMarket,
    price: project.price,
    specs: project.specs,
    mainUseCase: project.mainUseCase,
    competitors: project.competitors,
    brandContext: project.brand
      ? {
          name: project.brand.name,
          industry: project.brand.industry,
          targetMarket: project.brand.targetMarket,
          description: project.brand.description,
          latestBrandBrain: project.brand.brains[0]?.rawOutput || project.brand.brains[0] || null
        }
      : null,
    urlContext: urlContext ? JSON.stringify(urlContext) : null,
    assets: project.assets.map((asset: any) => ({
      type: asset.type,
      fileUrl: asset.fileUrl,
      content: asset.content
    }))
  };

  const result = await runJsonPrompt({
    prompt: productAnalysisPrompt(input),
    fallback: () => fallbackProductAnalysis(input)
  });

  const data = result.data as ReturnType<typeof fallbackProductAnalysis>;

  const analysis = await prisma.productAnalysis.create({
    data: {
      projectId: project.id,
      summary: data.productSummary,
      audienceAnalysis: data.targetAudience,
      painPoints: data.painPoints,
      sellingPoints: data.sellingPoints,
      adAngles: data.adAngles,
      nextSteps: data.nextSteps,
      rawOutput: {
        source: result.source,
        warning: result.warning,
        data
      }
    }
  });

  return NextResponse.json({ analysis, data, source: result.source, warning: result.warning });
}
