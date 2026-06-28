import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const assets = await prisma.productAsset.findMany({
    where: { projectId: id },
    orderBy: { createdAt: "desc" }
  });

  return NextResponse.json({ assets });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json();

  const asset = await prisma.productAsset.create({
    data: {
      projectId: id,
      type: body.type,
      fileUrl: body.fileUrl || null,
      content: body.content || null,
      meta: body.meta || null
    }
  });

  return NextResponse.json({ asset }, { status: 201 });
}
