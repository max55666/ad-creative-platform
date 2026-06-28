import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getProjectWithHistory } from "@/lib/projects";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const project = await getProjectWithHistory(id);

  if (!project) {
    return NextResponse.json({ message: "Project not found" }, { status: 404 });
  }

  return NextResponse.json({ project });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json();

  const project = await prisma.project.update({
    where: { id },
    data: {
      productName: body.productName?.trim(),
      productDescription: body.productDescription?.trim() || null,
      productUrl: body.productUrl?.trim() || null,
      targetMarket: body.targetMarket?.trim() || null,
      price: body.price?.trim() || null,
      specs: body.specs?.trim() || null,
      mainUseCase: body.mainUseCase?.trim() || null,
      competitors: body.competitors?.trim() || null
    }
  });

  return NextResponse.json({ project });
}

export async function DELETE(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  await prisma.project.delete({ where: { id } });

  return NextResponse.json({ ok: true });
}
