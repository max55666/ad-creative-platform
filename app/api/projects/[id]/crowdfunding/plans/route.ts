import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { generateCrowdfundingPagePlan } from "@/lib/services/crowdfunding-service";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const plans = await prisma.crowdfundingPagePlan.findMany({
    where: { projectId: id },
    orderBy: { createdAt: "desc" },
    include: {
      caseAnalysis: {
        select: { id: true, title: true, sourceUrl: true, platform: true }
      }
    }
  });
  return NextResponse.json({ plans });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));

  try {
    const plan = await generateCrowdfundingPagePlan(id, {
      caseAnalysisId: body.caseAnalysisId ? String(body.caseAnalysisId) : undefined,
      mode: body.mode || undefined,
      objective: body.objective ? String(body.objective) : undefined,
      tone: body.tone ? String(body.tone) : undefined,
      targetPlatform: body.targetPlatform || "zeczec"
    });
    return NextResponse.json({ plan });
  } catch (error) {
    return NextResponse.json(
      { message: error instanceof Error ? error.message : "募資頁規劃生成失敗" },
      { status: 500 }
    );
  }
}
