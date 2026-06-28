import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { analyzeCrowdfundingCase } from "@/lib/services/crowdfunding-service";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const cases = await prisma.crowdfundingCaseAnalysis.findMany({
    where: { projectId: id },
    orderBy: { createdAt: "desc" }
  });
  return NextResponse.json({ cases });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const sourceUrl = String(body.sourceUrl || "").trim();
  const title = String(body.title || "").trim();
  const notes = String(body.notes || "").trim();

  if (!sourceUrl && !notes) {
    return NextResponse.json({ message: "請輸入嘖嘖案例網址，或至少提供案例說明。" }, { status: 400 });
  }

  try {
    const analysis = await analyzeCrowdfundingCase(id, {
      sourceUrl: sourceUrl || undefined,
      title: title || undefined,
      notes: notes || undefined,
      platform: "zeczec"
    });
    return NextResponse.json({ analysis });
  } catch (error) {
    return NextResponse.json(
      { message: error instanceof Error ? error.message : "案例拆解失敗" },
      { status: 500 }
    );
  }
}
