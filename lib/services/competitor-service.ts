import type { Prisma } from "@prisma/client";
import { runCompetitorIntelligenceAgent } from "@/lib/agents/competitor-intelligence-agent";
import { prisma } from "@/lib/db";
import type { CompetitorInput } from "@/lib/prompts/competitor-intelligence";
import { scrapeAnyPage } from "@/lib/services/web-scraper";

export type CompetitorFormInput = {
  name?: unknown;
  websiteUrl?: unknown;
  productUrl?: unknown;
  industry?: unknown;
  targetMarket?: unknown;
  description?: unknown;
  priceRange?: unknown;
  tags?: unknown;
  brandId?: unknown;
  projectId?: unknown;
};

function asString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export function normalizeCompetitorInput(input: CompetitorFormInput) {
  return {
    name: asString(input.name),
    websiteUrl: asString(input.websiteUrl) || null,
    productUrl: asString(input.productUrl) || null,
    industry: asString(input.industry) || null,
    targetMarket: asString(input.targetMarket) || null,
    description: asString(input.description) || null,
    priceRange: asString(input.priceRange) || null,
    brandId: asString(input.brandId) || null,
    projectId: asString(input.projectId) || null,
    tags: normalizeTags(input.tags)
  };
}

export function normalizeTags(value: unknown) {
  if (Array.isArray(value)) return value.map(asString).filter(Boolean);
  return asString(value)
    .split(/[,\n，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export async function buildCompetitorInput(competitorId: string): Promise<CompetitorInput | null> {
  const competitor = await prisma.competitor.findUnique({
    where: { id: competitorId },
    include: {
      brand: {
        include: { brains: { orderBy: { createdAt: "desc" }, take: 1 } }
      },
      project: {
        include: { analyses: { orderBy: { createdAt: "desc" }, take: 1 } }
      }
    }
  });

  if (!competitor) return null;

  const sourceUrl = competitor.productUrl || competitor.websiteUrl;
  const scrapedPage = sourceUrl ? await scrapeCompetitorPage(sourceUrl, competitor.id) : null;

  return {
    name: competitor.name,
    websiteUrl: competitor.websiteUrl,
    productUrl: competitor.productUrl,
    industry: competitor.industry,
    targetMarket: competitor.targetMarket,
    description: competitor.description,
    priceRange: competitor.priceRange,
    tags: Array.isArray(competitor.tags) ? (competitor.tags as string[]) : [],
    brandContext: competitor.brand
      ? {
          name: competitor.brand.name,
          industry: competitor.brand.industry,
          targetMarket: competitor.brand.targetMarket,
          latestBrandBrain: competitor.brand.brains[0]?.rawOutput || competitor.brand.brains[0] || null
        }
      : null,
    projectContext: competitor.project
      ? {
          productName: competitor.project.productName,
          productDescription: competitor.project.productDescription,
          targetMarket: competitor.project.targetMarket,
          price: competitor.project.price,
          latestAnalysis: competitor.project.analyses[0]?.rawOutput || competitor.project.analyses[0] || null
        }
      : null,
    scrapedPage
  };
}

async function scrapeCompetitorPage(url: string, competitorId: string) {
  try {
    return await scrapeAnyPage({
      url,
      storageKey: `competitors/${competitorId}`
    });
  } catch (error) {
    return {
      url,
      error: error instanceof Error ? error.message : "Page scrape failed."
    };
  }
}

export async function generateAndSaveCompetitorAnalysis({
  competitorId,
  userId
}: {
  competitorId: string;
  userId?: string;
}) {
  const input = await buildCompetitorInput(competitorId);
  if (!input) throw new Error("Competitor not found.");

  const result = await runCompetitorIntelligenceAgent(input);
  const data = result.data;

  const analysis = await prisma.competitorAnalysis.create({
    data: {
      competitorId,
      summary: data.summary as Prisma.InputJsonValue,
      positioning: data.positioning as Prisma.InputJsonValue,
      productOffer: data.productOffer as Prisma.InputJsonValue,
      audience: data.audience as Prisma.InputJsonValue,
      messaging: data.messaging as Prisma.InputJsonValue,
      landingPage: data.landingPage as Prisma.InputJsonValue,
      creativeAngles: data.creativeAngles as Prisma.InputJsonValue,
      opportunities: data.opportunities as Prisma.InputJsonValue,
      risks: data.risks as Prisma.InputJsonValue,
      rawOutput: {
        source: result.source,
        warning: result.warning,
        nextSteps: data.nextSteps || [],
        scrapedPage: input.scrapedPage || null,
        data
      } as Prisma.InputJsonValue
    }
  });

  await prisma.providerUsageLog.create({
    data: {
      provider: result.usage?.provider || "openai",
      model: result.usage?.model,
      userId: userId || null,
      inputTokens: result.usage?.inputTokens,
      outputTokens: result.usage?.outputTokens,
      status: result.source === "openai" ? "completed" : "fallback",
      errorMessage: result.warning
    }
  });

  return { analysis, data, source: result.source, warning: result.warning };
}
