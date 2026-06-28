import type { Prisma } from "@prisma/client";
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { normalizeCompetitorInput } from "@/lib/services/competitor-service";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const competitor = await prisma.competitor.findFirst({
    where: { id, userId: user.id },
    include: {
      brand: true,
      project: true,
      analyses: { orderBy: { createdAt: "desc" } }
    }
  });

  if (!competitor) {
    return NextResponse.json({ message: "找不到競品資料" }, { status: 404 });
  }

  return NextResponse.json({ competitor });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const existing = await prisma.competitor.findFirst({ where: { id, userId: user.id } });
  if (!existing) {
    return NextResponse.json({ message: "找不到競品資料" }, { status: 404 });
  }

  const body = await request.json().catch(() => ({}));
  const input = normalizeCompetitorInput({ ...existing, ...body });
  if (!input.name) {
    return NextResponse.json({ message: "競品名稱為必填" }, { status: 400 });
  }

  if (input.brandId) {
    const brand = await prisma.brand.findFirst({ where: { id: input.brandId, userId: user.id } });
    if (!brand) return NextResponse.json({ message: "找不到指定品牌" }, { status: 404 });
  }
  if (input.projectId) {
    const project = await prisma.project.findFirst({ where: { id: input.projectId, userId: user.id } });
    if (!project) return NextResponse.json({ message: "找不到指定產品專案" }, { status: 404 });
  }

  const competitor = await prisma.competitor.update({
    where: { id },
    data: {
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
    },
    include: {
      brand: true,
      project: true,
      analyses: { orderBy: { createdAt: "desc" } }
    }
  });

  return NextResponse.json({ competitor });
}

export async function DELETE(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const existing = await prisma.competitor.findFirst({ where: { id, userId: user.id } });
  if (!existing) {
    return NextResponse.json({ message: "找不到競品資料" }, { status: 404 });
  }

  await prisma.competitor.delete({ where: { id } });
  return NextResponse.json({ ok: true });
}
