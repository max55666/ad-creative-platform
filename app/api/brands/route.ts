import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { generateAndSaveBrandBrain, normalizeBrandInput } from "@/lib/services/brand-service";

export async function GET() {
  const user = await getDemoUser();
  const brands = await prisma.brand.findMany({
    where: { userId: user.id },
    orderBy: { updatedAt: "desc" },
    include: {
      brains: { orderBy: { createdAt: "desc" }, take: 1 },
      _count: { select: { projects: true, brains: true } }
    }
  });

  return NextResponse.json({ brands });
}

export async function POST(request: NextRequest) {
  const user = await getDemoUser();
  const body = await request.json().catch(() => ({}));
  const input = normalizeBrandInput(body);
  const shouldGenerateBrain = body.generateBrain !== false;

  if (!input.name) {
    return NextResponse.json({ message: "品牌名稱為必填。" }, { status: 400 });
  }

  const brand = await prisma.brand.create({
    data: {
      userId: user.id,
      ...input
    }
  });

  if (!shouldGenerateBrain) {
    return NextResponse.json({ brand }, { status: 201 });
  }

  const brainResult = await generateAndSaveBrandBrain({ brandId: brand.id, userId: user.id });
  const fullBrand = await prisma.brand.findUnique({
    where: { id: brand.id },
    include: {
      brains: { orderBy: { createdAt: "desc" }, take: 1 },
      _count: { select: { projects: true, brains: true } }
    }
  });

  return NextResponse.json({ brand: fullBrand, brain: brainResult.brain, source: brainResult.source, warning: brainResult.warning }, { status: 201 });
}
