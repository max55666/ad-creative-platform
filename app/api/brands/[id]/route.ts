import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { normalizeBrandInput } from "@/lib/services/brand-service";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const brand = await prisma.brand.findFirst({
    where: { id, userId: user.id },
    include: {
      projects: { orderBy: { updatedAt: "desc" }, take: 10 },
      brains: { orderBy: { createdAt: "desc" } }
    }
  });

  if (!brand) {
    return NextResponse.json({ message: "Brand not found" }, { status: 404 });
  }

  return NextResponse.json({ brand });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const existing = await prisma.brand.findFirst({ where: { id, userId: user.id } });
  if (!existing) {
    return NextResponse.json({ message: "Brand not found" }, { status: 404 });
  }

  const body = await request.json().catch(() => ({}));
  const input = normalizeBrandInput({ ...existing, ...body });
  if (!input.name) {
    return NextResponse.json({ message: "品牌名稱為必填。" }, { status: 400 });
  }

  const brand = await prisma.brand.update({
    where: { id },
    data: input,
    include: {
      projects: { orderBy: { updatedAt: "desc" }, take: 10 },
      brains: { orderBy: { createdAt: "desc" } }
    }
  });

  return NextResponse.json({ brand });
}

export async function DELETE(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const existing = await prisma.brand.findFirst({ where: { id, userId: user.id } });
  if (!existing) {
    return NextResponse.json({ message: "Brand not found" }, { status: 404 });
  }

  await prisma.brand.delete({ where: { id } });
  return NextResponse.json({ ok: true });
}
