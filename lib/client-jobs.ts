export type ClientJob = {
  id: string;
  type: string;
  status: "queued" | "processing" | "completed" | "failed" | string;
  progress: number;
  outputPayload?: any;
  errorMessage?: string | null;
};

export async function pollJob(
  jobId: string,
  onUpdate?: (job: ClientJob) => void,
  intervalMs = 1200
) {
  while (true) {
    const response = await fetch(`/api/jobs/${jobId}`);
    const data = await response.json();
    const job = data.job as ClientJob;
    if (job) onUpdate?.(job);
    if (!job || job.status === "completed" || job.status === "failed") return job;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
