import { prisma } from "@/lib/db";
import { runJobHandler } from "@/lib/jobs/handlers";
import { JobType } from "@/lib/jobs/types";

export async function enqueueGenerationJob({
  type,
  projectId,
  userId,
  inputPayload
}: {
  type: JobType | string;
  projectId?: string | null;
  userId?: string | null;
  inputPayload: unknown;
}) {
  const job = await prisma.generationJob.create({
    data: {
      type,
      projectId: projectId || null,
      userId: userId || null,
      inputPayload: inputPayload as any,
      status: "queued",
      progress: 0
    }
  });

  if (process.env.JOB_AUTO_START !== "false") {
    setTimeout(() => {
      processGenerationJob(job.id).catch((error) => {
        console.error(`Job ${job.id} failed outside handler`, error);
      });
    }, 0);
  }

  return job;
}

export async function processGenerationJob(jobId: string) {
  const job = await prisma.generationJob.findUnique({ where: { id: jobId } });
  if (!job) throw new Error("Job not found");
  if (job.status === "completed") return job;
  if (job.status === "processing") return job;

  await prisma.generationJob.update({
    where: { id: jobId },
    data: {
      status: "processing",
      startedAt: new Date(),
      attempts: { increment: 1 },
      errorMessage: null,
      progress: Math.max(job.progress, 5)
    }
  });

  try {
    const output = await runJobHandler({
      jobId,
      projectId: job.projectId,
      userId: job.userId,
      input: job.inputPayload,
      progress: async (progress) => {
        await prisma.generationJob.update({
          where: { id: jobId },
          data: { progress: Math.min(Math.max(Math.round(progress), 0), 99) }
        });
      }
    });

    return prisma.generationJob.update({
      where: { id: jobId },
      data: {
        status: "completed",
        progress: 100,
        outputPayload: output as any,
        completedAt: new Date()
      }
    });
  } catch (error) {
    return prisma.generationJob.update({
      where: { id: jobId },
      data: {
        status: "failed",
        errorMessage: formatJobError(error),
        completedAt: new Date()
      }
    });
  }
}

export async function retryGenerationJob(jobId: string) {
  await prisma.generationJob.update({
    where: { id: jobId },
    data: {
      status: "queued",
      progress: 0,
      errorMessage: null,
      outputPayload: undefined,
      startedAt: null,
      completedAt: null
    }
  });

  return processGenerationJob(jobId);
}

export async function cancelGenerationJob(jobId: string) {
  return prisma.generationJob.update({
    where: { id: jobId },
    data: {
      status: "failed",
      errorMessage: "Canceled by user",
      completedAt: new Date()
    }
  });
}

function formatJobError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || "Job failed");
  if (message.includes("Rate limit") || message.includes("429") || message.includes("圖片生成額度")) {
    return [
      "圖片生成額度暫時用完，請稍後按「重試」。",
      "原因：OpenAI gpt-image-1 有每分鐘圖片數限制，分鏡圖一次會生成多張，短時間連續生成時容易被限制。",
      message
    ].join("\n");
  }
  return message;
}
