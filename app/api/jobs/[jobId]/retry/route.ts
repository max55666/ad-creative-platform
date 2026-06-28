import { NextRequest, NextResponse } from "next/server";
import { retryGenerationJob } from "@/lib/jobs/queue";

type Params = {
  params: Promise<{ jobId: string }>;
};

export async function POST(_request: NextRequest, { params }: Params) {
  const { jobId } = await params;
  const job = await retryGenerationJob(jobId);
  return NextResponse.json({ jobId: job.id, job });
}
