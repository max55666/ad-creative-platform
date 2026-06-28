"use client";

import { AlertCircle, CheckCircle2, Loader2, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ClientJob, pollJob } from "@/lib/client-jobs";

export function JobProgress({
  job,
  onRetry
}: {
  job?: ClientJob | null;
  onRetry?: (job: ClientJob) => void;
}) {
  if (!job) return null;

  const failed = job.status === "failed";
  const completed = job.status === "completed";
  const active = job.status === "queued" || job.status === "processing";

  return (
    <div className="grid gap-2 rounded-md border bg-white p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 font-medium">
          {active ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {completed ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : null}
          {failed ? <AlertCircle className="h-4 w-4 text-red-600" /> : null}
          任務 {statusLabel(job.status)}
        </span>
        <span className="text-xs text-muted-foreground">{job.progress || 0}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={failed ? "h-full bg-red-500" : "h-full bg-primary transition-all"}
          style={{ width: `${Math.min(Math.max(job.progress || 0, 4), 100)}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">{stageLabel(job)}</p>
      {job.errorMessage ? <p className="whitespace-pre-wrap text-xs text-red-700">{job.errorMessage}</p> : null}
      {failed && onRetry ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={async () => {
            const response = await fetch(`/api/jobs/${job.id}/retry`, { method: "POST" });
            const data = await response.json();
            if (data.job) {
              onRetry(data.job);
              void pollJob(data.job.id, onRetry);
            }
          }}
        >
          <RotateCw className="h-4 w-4" />
          重試
        </Button>
      ) : null}
    </div>
  );
}

function statusLabel(status: string) {
  if (status === "queued") return "排隊中";
  if (status === "processing") return "處理中";
  if (status === "completed") return "完成";
  if (status === "failed") return "失敗";
  return status;
}

function stageLabel(job: ClientJob) {
  if (job.status === "completed") return "已完成，可以查看結果。";
  if (job.status === "failed") return "任務失敗，請查看錯誤原因後重試。";
  if (job.status === "queued") return "等待後端開始處理。";

  if (job.type === "storyboard_images") {
    if (job.progress < 20) return "準備分鏡提示詞。";
    if (job.progress < 90) return "正在產生分鏡圖，已鎖定的手動上傳圖會被保留。";
    return "正在儲存分鏡圖紀錄。";
  }

  if (job.type === "voiceover") {
    if (job.progress < 40) return "準備口白文字與聲線。";
    return "正在呼叫 ElevenLabs 產生配音。";
  }

  if (job.type === "render_video") {
    if (job.progress < 20) return "檢查分鏡圖，必要時自動補圖。";
    if (job.progress < 70) return "檢查或產生配音。";
    if (job.progress < 91) return "正在用分鏡圖產生動態片段，Kling / 外部 AI 這段通常最久。";
    return "正在用 FFmpeg 合成影片、字幕與配音。";
  }

  return "任務處理中。";
}
