import { prisma } from "@/lib/db";
import { runJsonPrompt } from "@/lib/openai";
import { fallbackCrowdfundingCaseAnalysis, fallbackCrowdfundingPagePlan } from "@/lib/crowdfunding-fallbacks";
import { crowdfundingCaseAnalysisPrompt, crowdfundingPagePlanPrompt } from "@/lib/prompts/crowdfunding";
import { scrapeAnyPage } from "@/lib/services/web-scraper";

type AnalyzeCaseInput = {
  sourceUrl?: string;
  title?: string;
  notes?: string;
  platform?: string;
};

type GeneratePagePlanInput = {
  caseAnalysisId?: string;
  mode?: "from_product" | "benchmark_case" | "hybrid";
  objective?: string;
  tone?: string;
  targetPlatform?: "zeczec" | "generic";
};

export async function analyzeCrowdfundingCase(projectId: string, input: AnalyzeCaseInput) {
  const project = await loadProjectContext(projectId);
  if (!project) throw new Error("Project not found");

  const scrapedPage = input.sourceUrl ? await scrapeCasePage(input.sourceUrl, projectId) : null;
  const promptInput = {
    sourceUrl: input.sourceUrl || null,
    platform: input.platform || "zeczec",
    title: input.title || scrapedPage?.title || null,
    notes: input.notes || null,
    project: compactProject(project),
    latestAnalysis: project.analyses[0] || null,
    scrapedPage
  };

  const result = await runJsonPrompt({
    prompt: crowdfundingCaseAnalysisPrompt(promptInput),
    fallback: () => fallbackCrowdfundingCaseAnalysis(promptInput),
    temperature: 0.4
  });

  const data = result.data as any;
  return prisma.crowdfundingCaseAnalysis.create({
    data: {
      projectId,
      sourceUrl: input.sourceUrl || null,
      title: data.summary?.caseName || input.title || scrapedPage?.title || "嘖嘖募資案例",
      platform: input.platform || "zeczec",
      scrapedPage: scrapedPage || undefined,
      structure: data.structure || {},
      visualStrategy: data.visualStrategy || {},
      copywriting: data.copywriting || {},
      conversionInsights: data.conversionInsights || {},
      reusableTemplate: data.reusableTemplate || {},
      rawOutput: {
        ...data,
        source: result.source,
        warning: result.warning || null,
        usage: result.usage || null
      }
    }
  });
}

export async function generateCrowdfundingPagePlan(projectId: string, input: GeneratePagePlanInput) {
  const project = await loadProjectContext(projectId);
  if (!project) throw new Error("Project not found");

  const caseAnalysis = input.caseAnalysisId
    ? await prisma.crowdfundingCaseAnalysis.findFirst({ where: { id: input.caseAnalysisId, projectId } })
    : null;

  const mode = input.mode || (caseAnalysis ? "benchmark_case" : "from_product");
  const promptInput = {
    mode,
    targetPlatform: input.targetPlatform || "zeczec",
    objective: input.objective || "募資轉換",
    tone: input.tone || "台灣群眾募資語氣，清楚、可信、有畫面感",
    project: compactProject(project),
    latestAnalysis: project.analyses[0] || null,
    caseAnalysis: caseAnalysis ? compactCase(caseAnalysis) : null
  };

  const result = await runJsonPrompt({
    prompt: crowdfundingPagePlanPrompt(promptInput as any),
    fallback: () => fallbackCrowdfundingPagePlan(promptInput),
    temperature: 0.45
  });

  const data = result.data as any;
  return prisma.crowdfundingPagePlan.create({
    data: {
      projectId,
      caseAnalysisId: caseAnalysis?.id || null,
      mode,
      targetPlatform: input.targetPlatform || "zeczec",
      title: data.title || `${project.productName} 嘖嘖募資頁規劃`,
      hero: data.hero || {},
      pageSections: data.pageSections || [],
      imageBriefs: data.imageBriefs || [],
      copywriting: data.copywriting || {},
      rewardStrategy: data.rewardStrategy || {},
      faq: data.faq || [],
      conversionScore: data.conversionScore || {},
      rawOutput: {
        ...data,
        strategy: data.strategy || {},
        executionPlan: data.executionPlan || {},
        source: result.source,
        warning: result.warning || null,
        usage: result.usage || null
      }
    }
  });
}

async function loadProjectContext(projectId: string) {
  return prisma.project.findUnique({
    where: { id: projectId },
    include: {
      brand: { include: { brains: { orderBy: { createdAt: "desc" }, take: 1 } } },
      assets: { orderBy: { createdAt: "desc" } },
      analyses: { orderBy: { createdAt: "desc" }, take: 1 },
      staticCreatives: { orderBy: { createdAt: "desc" }, take: 5 },
      videoScripts: { orderBy: { createdAt: "desc" }, take: 5 }
    }
  });
}

async function scrapeCasePage(sourceUrl: string, projectId: string) {
  try {
    return await scrapeAnyPage({
      url: sourceUrl,
      storageKey: `crowdfunding/${projectId}`
    });
  } catch (error) {
    return {
      url: sourceUrl,
      title: "",
      text: "",
      images: [],
      screenshotUrl: "",
      error: error instanceof Error ? error.message : "Page scrape failed."
    };
  }
}

function compactProject(project: any) {
  return {
    id: project.id,
    productName: project.productName,
    productDescription: project.productDescription,
    productUrl: project.productUrl,
    targetMarket: project.targetMarket,
    price: project.price,
    specs: project.specs,
    mainUseCase: project.mainUseCase,
    competitors: project.competitors,
    brand: project.brand ? {
      name: project.brand.name,
      industry: project.brand.industry,
      targetMarket: project.brand.targetMarket,
      voiceTone: project.brand.voiceTone,
      visualStyle: project.brand.visualStyle,
      latestBrain: project.brand.brains?.[0] || null
    } : null,
    assets: (project.assets || []).map((asset: any) => ({
      type: asset.type,
      fileUrl: asset.fileUrl,
      content: asset.content,
      meta: asset.meta
    })),
    latestAnalysis: project.analyses?.[0] || null,
    recentStaticCreatives: project.staticCreatives || [],
    recentVideoScripts: project.videoScripts || []
  };
}

function compactCase(caseAnalysis: any) {
  return {
    id: caseAnalysis.id,
    title: caseAnalysis.title,
    sourceUrl: caseAnalysis.sourceUrl,
    platform: caseAnalysis.platform,
    structure: caseAnalysis.structure,
    visualStrategy: caseAnalysis.visualStrategy,
    copywriting: caseAnalysis.copywriting,
    conversionInsights: caseAnalysis.conversionInsights,
    reusableTemplate: caseAnalysis.reusableTemplate
  };
}
