import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { generateAndSaveCompetitorAnalysis } from "@/lib/services/competitor-service";

type Params = {
  params: Promise<{ id: string }>;
};

export async function POST(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const competitor = await prisma.competitor.findFirst({ where: { id, userId: user.id } });

  if (!competitor) {
    return NextResponse.json({ message: "找不到競品資料" }, { status: 404 });
  }

  const result = await generateAndSaveCompetitorAnalysis({ competitorId: id, userId: user.id });
  return NextResponse.json(result);
}
