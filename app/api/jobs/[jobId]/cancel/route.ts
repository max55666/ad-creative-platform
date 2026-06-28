import { NextRequest, NextResponse } from "next/server";
import { cancelGenerationJob } from "@/lib/jobs/queue";

type Params = {
  params: Promise<{ jobId: string }>;
};

export async function POST(_request: NextRequest, { params }: Params) {
  const { jobId } = await params;
  const job = await cancelGenerationJob(jobId);
  return NextResponse.json({ jobId: job.id, job });
}
