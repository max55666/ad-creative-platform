import type { Prisma } from "@prisma/client";
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { generateAndSaveCompetitorAnalysis, normalizeCompetitorInput } from "@/lib/services/competitor-service";

async function validateRelations({
  userId,
  brandId,
  projectId
}: {
  userId: string;
  brandId?: string | null;
  projectId?: string | null;
}) {
  if (brandId) {
    const brand = await prisma.brand.findFirst({ where: { id: brandId, userId } });
    if (!brand) return "找不到指定品牌";
  }
  if (projectId) {
    const project = await prisma.project.findFirst({ where: { id: projectId, userId } });
    if (!project) return "找不到指定產品專案";
  }
  return null;
}

export async function GET(request: NextRequest) {
  const user = await getDemoUser();
  const searchParams = request.nextUrl.searchParams;
  const q = searchParams.get("q")?.trim();
  const brandId = searchParams.get("brandId")?.trim();
  const projectId = searchParams.get("projectId")?.trim();

  const competitors = await prisma.competitor.findMany({
    where: {
      userId: user.id,
      ...(brandId ? { brandId } : {}),
      ...(projectId ? { projectId } : {}),
      ...(q
        ? {
            OR: [
              { name: { contains: q, mode: "insensitive" } },
              { description: { contains: q, mode: "insensitive" } },
              { industry: { contains: q, mode: "insensitive" } }
            ]
          }
        : {})
    },
    orderBy: { updatedAt: "desc" },
    include: {
      brand: true,
      project: true,
      analyses: { orderBy: { createdAt: "desc" }, take: 1 },
      _count: { select: { analyses: true } }
    }
  });

  return NextResponse.json({ competitors });
}

export async function POST(request: NextRequest) {
  const user = await getDemoUser();
  const body = await request.json().catch(() => ({}));
  const input = normalizeCompetitorInput(body);
  const shouldAnalyze = body.analyze !== false;

  if (!input.name) {
    return NextResponse.json({ message: "競品名稱為必填" }, { status: 400 });
  }

  const relationError = await validateRelations({ userId: user.id, brandId: input.brandId, projectId: input.projectId });
  if (relationError) {
    return NextResponse.json({ message: relationError }, { status: 404 });
  }

  const competitor = await prisma.competitor.create({
    data: {
      userId: user.id,
      brandId: input.brandId,
      projectId: input.projectId,
      name: input.name,
      websiteUrl: input.websiteUrl,
      productUrl: input.productUrl,
      industry: input.industry,
      targetMarket: input.targetMarket,
      description: input.description,
      priceRange: input.priceRange,
      tags: input.tags as Prisma.InputJsonValue
    }
  });

  if (!shouldAnalyze) {
    return NextResponse.json({ competitor }, { status: 201 });
  }

  const analysisResult = await generateAndSaveCompetitorAnalysis({ competitorId: competitor.id, userId: user.id });
  const fullCompetitor = await prisma.competitor.findUnique({
    where: { id: competitor.id },
    include: {
      brand: true,
      project: true,
      analyses: { orderBy: { createdAt: "desc" }, take: 1 },
      _count: { select: { analyses: true } }
    }
  });

  return NextResponse.json(
    {
      competitor: fullCompetitor,
      analysis: analysisResult.analysis,
      source: analysisResult.source,
      warning: analysisResult.warning
    },
    { status: 201 }
  );
}
