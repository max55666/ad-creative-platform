import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

type Params = {
  params: Promise<{ jobId: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { jobId } = await params;
  const job = await prisma.generationJob.findUnique({ where: { id: jobId } });

  if (!job) {
    return NextResponse.json({ message: "Job not found" }, { status: 404 });
  }

  return NextResponse.json({ job });
}
