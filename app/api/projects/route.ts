import { NextRequest, NextResponse } from "next/server";
import type { Prisma } from "@prisma/client";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";

export async function GET() {
  const user = await getDemoUser();
  const projects = await prisma.project.findMany({
    where: { userId: user.id },
    orderBy: { updatedAt: "desc" },
    include: {
      _count: {
        select: {
          analyses: true,
          staticCreatives: true,
          videoScripts: true,
          viralAnalyses: true,
          assets: true
        }
      },
      analyses: {
        orderBy: { createdAt: "desc" },
        take: 1
      }
    }
  });

  return NextResponse.json({ projects });
}

export async function POST(request: NextRequest) {
  const user = await getDemoUser();
  const body = await request.json();
  const brandId = body.brandId?.trim() || null;

  if (!body.productName?.trim()) {
    return NextResponse.json({ message: "productName is required" }, { status: 400 });
  }

  if (brandId) {
    const brand = await prisma.brand.findFirst({ where: { id: brandId, userId: user.id } });
    if (!brand) {
      return NextResponse.json({ message: "Brand not found" }, { status: 404 });
    }
  }

  const project = await prisma.project.create({
    data: {
      userId: user.id,
      brandId,
      productName: body.productName.trim(),
      productDescription: body.productDescription?.trim() || null,
      productUrl: body.productUrl?.trim() || null,
      targetMarket: body.targetMarket?.trim() || null,
      price: body.price?.trim() || null,
      specs: body.specs?.trim() || null,
      mainUseCase: body.mainUseCase?.trim() || null,
      competitors: body.competitors?.trim() || null
    }
  });

  const assetData: Prisma.ProductAssetCreateManyInput[] = [];

  if (project.productUrl) {
    assetData.push({
      projectId: project.id,
      type: "url",
      content: project.productUrl
    });
  }

  if (project.productDescription) {
    assetData.push({
      projectId: project.id,
      type: "text",
      content: project.productDescription
    });
  }

  if (assetData.length) {
    await prisma.productAsset.createMany({ data: assetData });
  }

  return NextResponse.json({ project }, { status: 201 });
}
