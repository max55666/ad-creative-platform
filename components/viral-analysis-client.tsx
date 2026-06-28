"use client";

import { Loader2, UploadCloud, Wand2 } from "lucide-react";
import { FormEvent, useState } from "react";
import { JobProgress } from "@/components/job-progress";
import { JsonPanel } from "@/components/json-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ClientJob, pollJob } from "@/lib/client-jobs";

export function ViralAnalysisClient({
  projectId,
  initialAnalyses,
  initialVideoUrl
}: {
  projectId: string;
  initialAnalyses: any[];
  initialVideoUrl?: string | null;
}) {
  const [analyses, setAnalyses] = useState<any[]>(initialAnalyses);
  const [videoUrl, setVideoUrl] = useState(initialVideoUrl || "");
  const [file, setFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<ClientJob | null>(null);
  const latest = analyses[0];

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);

    let nextVideoUrl = videoUrl;
    if (file) {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("projectId", projectId);
      const uploadResponse = await fetch("/api/upload", { method: "POST", body: formData });
      const upload = await uploadResponse.json();
      nextVideoUrl = upload.fileUrl;
      setVideoUrl(nextVideoUrl);
    }

    const response = await fetch(`/api/projects/${projectId}/viral-analysis`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ videoUrl: nextVideoUrl, transcript, notes })
    });
    const data = await response.json();
    if (data.jobId) {
      setJob(data.job);
      const completed = await pollJob(data.jobId, setJob);
      if (completed?.outputPayload?.analysis) {
        setAnalyses([completed.outputPayload.analysis, ...analyses]);
      }
    } else if (data.analysis) {
      setAnalyses([data.analysis, ...analyses]);
    }
    setLoading(false);
  }

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>爆款素材分析頁</CardTitle>
          <CardDescription>上傳影片或使用既有影片資產，拆解腳本、字卡、口白、節奏、音樂、爆點與可複製模板。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="grid gap-2">
                <Label className="flex items-center gap-2">
                  <UploadCloud className="h-4 w-4" />
                  上傳爆款素材影片
                </Label>
                <Input type="file" accept="video/*" onChange={(event) => setFile(event.target.files?.[0] || null)} />
              </div>
              <div className="grid gap-2">
                <Label>影片 URL</Label>
                <Input value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="/uploads/demo.mp4 或 https://..." />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="grid gap-2">
                <Label>口白逐字稿，選填</Label>
                <Textarea value={transcript} onChange={(event) => setTranscript(event.target.value)} placeholder="若已有字幕或逐字稿，貼上可提升分析精準度。" />
              </div>
              <div className="grid gap-2">
                <Label>補充觀察，選填</Label>
                <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="例：影片長度 31 秒、前 3 秒是痛點畫面、留言很多人問價格..." />
              </div>
            </div>
            <Button disabled={loading || (!file && !videoUrl)}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
              分析爆款影片
            </Button>
            <JobProgress job={job} onRetry={setJob} />
          </form>
        </CardContent>
      </Card>

      {latest ? (
        <div className="grid gap-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
              <div>
                <CardTitle>最新爆款拆解</CardTitle>
                <CardDescription>{latest.videoUrl}</CardDescription>
              </div>
              <Badge>已保存</Badge>
            </CardHeader>
          </Card>
          <div className="report-grid">
            <JsonPanel title="影片逐段拆解" data={latest.segmentBreakdown} />
            <JsonPanel title="腳本結構分析" data={latest.structureAnalysis} />
            <JsonPanel title="字卡分析" data={latest.captionAnalysis} />
            <JsonPanel title="口白分析" data={latest.voiceAnalysis} />
            <JsonPanel title="音樂與節奏分析" data={latest.musicAnalysis} />
            <JsonPanel title="情緒與痛點分析" data={latest.emotionAnalysis} />
            <JsonPanel title="爆點推測" data={latest.viralReason} />
            <JsonPanel title="可複製腳本模板" data={latest.reusableTemplate} />
            <JsonPanel title="改寫成我方產品版本" data={latest.rewrittenScripts} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
