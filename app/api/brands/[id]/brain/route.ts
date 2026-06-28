import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { generateAndSaveBrandBrain } from "@/lib/services/brand-service";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const brand = await prisma.brand.findFirst({ where: { id, userId: user.id } });
  if (!brand) {
    return NextResponse.json({ message: "Brand not found" }, { status: 404 });
  }

  const brains = await prisma.brandBrain.findMany({
    where: { brandId: id },
    orderBy: { createdAt: "desc" }
  });

  return NextResponse.json({ brains });
}

export async function POST(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const brand = await prisma.brand.findFirst({ where: { id, userId: user.id } });
  if (!brand) {
    return NextResponse.json({ message: "Brand not found" }, { status: 404 });
  }

  const result = await generateAndSaveBrandBrain({ brandId: id, userId: user.id });
  return NextResponse.json(result);
}
