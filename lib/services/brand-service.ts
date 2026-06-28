import { Prisma } from "@prisma/client";
import { runBrandBrainAgent } from "@/lib/agents/brand-brain-agent";
import { prisma } from "@/lib/db";
import type { BrandBrainInput } from "@/lib/prompts/brand-brain";

export type BrandFormInput = {
  name?: unknown;
  websiteUrl?: unknown;
  industry?: unknown;
  targetMarket?: unknown;
  description?: unknown;
  voiceTone?: unknown;
  visualStyle?: unknown;
};

function asString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export function normalizeBrandInput(input: BrandFormInput) {
  return {
    name: asString(input.name),
    websiteUrl: asString(input.websiteUrl) || null,
    industry: asString(input.industry) || null,
    targetMarket: asString(input.targetMarket) || null,
    description: asString(input.description) || null,
    voiceTone: asString(input.voiceTone) || null,
    visualStyle: asString(input.visualStyle) || null
  };
}

export async function buildBrandBrainInput(brandId: string): Promise<BrandBrainInput | null> {
  const brand = await prisma.brand.findUnique({
    where: { id: brandId },
    include: {
      projects: {
        orderBy: { updatedAt: "desc" },
        take: 8,
        select: {
          productName: true,
          productDescription: true,
          targetMarket: true,
          price: true,
          mainUseCase: true
        }
      }
    }
  });

  if (!brand) return null;

  return {
    name: brand.name,
    websiteUrl: brand.websiteUrl,
    industry: brand.industry,
    targetMarket: brand.targetMarket,
    description: brand.description,
    voiceTone: brand.voiceTone,
    visualStyle: brand.visualStyle,
    products: brand.projects
  };
}

export async function generateAndSaveBrandBrain({
  brandId,
  userId
}: {
  brandId: string;
  userId?: string;
}) {
  const input = await buildBrandBrainInput(brandId);
  if (!input) throw new Error("Brand not found.");

  const result = await runBrandBrainAgent(input);
  const data = result.data;

  const brain = await prisma.brandBrain.create({
    data: {
      brandId,
      summary: data.summary as Prisma.InputJsonValue,
      positioning: data.positioning as Prisma.InputJsonValue,
      voice: data.voice as Prisma.InputJsonValue,
      visualIdentity: data.visualIdentity as Prisma.InputJsonValue,
      audience: data.audience as Prisma.InputJsonValue,
      messaging: data.messaging as Prisma.InputJsonValue,
      guardrails: data.guardrails as Prisma.InputJsonValue,
      rawOutput: {
        source: result.source,
        warning: result.warning,
        nextSteps: data.nextSteps || [],
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

  return { brain, data, source: result.source, warning: result.warning };
}
