"use client";

import { Clapperboard, Film, ImageIcon, Loader2, Sparkles, Upload, Volume2, Wand2 } from "lucide-react";
import { ChangeEvent, useState } from "react";
import type { ReactNode } from "react";
import { CopyButton } from "@/components/copy-button";
import { FieldNote } from "@/components/field-note";
import { JobProgress } from "@/components/job-progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ClientJob, pollJob } from "@/lib/client-jobs";
import type { SystemSettings } from "@/lib/settings";

const platforms = ["TikTok", "Reels", "Shorts", "Facebook"];
const durations = ["15秒", "30秒", "60秒"];
const styles = ["痛點", "搞笑", "開箱", "情境劇", "專家推薦", "素人分享"];
const voiceLanguages = [
  { label: "中文", value: "zh" },
  { label: "日文", value: "ja" },
  { label: "英文", value: "en" }
];
const voiceGenders = [
  { label: "女聲", value: "female" },
  { label: "男聲", value: "male" }
];
const subtitleStyles = [
  { label: "標準字幕", value: "default" },
  { label: "粗體大字卡", value: "bold" },
  { label: "乾淨簡約", value: "clean" },
  { label: "底部黑底", value: "bottom-heavy" }
];
const videoRatios = ["9:16", "4:5", "1:1"];
const renderModes = [
  { label: "AI 動態影片", value: "ai-motion" },
  { label: "靜態圖合成影片", value: "static" }
];
const motionStyles = [
  { label: "細膩微動", value: "subtle" },
  { label: "產品展示", value: "product-demo" },
  { label: "情境動作", value: "scene-action" },
  { label: "戲劇張力", value: "dramatic" }
];

export function VideoScriptClient({
  projectId,
  initialScripts,
  initialSettings
}: {
  projectId: string;
  initialScripts: any[];
  initialSettings?: SystemSettings;
}) {
  const [scripts, setScripts] = useState<any[]>(initialScripts);
  const [platform, setPlatform] = useState("TikTok");
  const [duration, setDuration] = useState("30秒");
  const [style, setStyle] = useState("痛點");
  const [loading, setLoading] = useState(false);
  const [imageLoading, setImageLoading] = useState<Record<string, boolean>>({});
  const [voiceLoading, setVoiceLoading] = useState<Record<string, boolean>>({});
  const [renderLoading, setRenderLoading] = useState<Record<string, boolean>>({});
  const [uploadLoading, setUploadLoading] = useState<Record<string, boolean>>({});
  const [jobs, setJobs] = useState<Record<string, ClientJob>>({});
  const [voiceLanguage, setVoiceLanguage] = useState<string>(initialSettings?.providers.voiceover.defaultLanguage || "zh");
  const [voiceGender, setVoiceGender] = useState<string>(initialSettings?.providers.voiceover.defaultGender || "female");
  const [subtitleStyle, setSubtitleStyle] = useState<string>(initialSettings?.output.subtitleStyle || "default");
  const [videoAspectRatio, setVideoAspectRatio] = useState<string>(initialSettings?.output.defaultAspectRatio || "9:16");
  const [renderMode, setRenderMode] = useState<string>(initialSettings?.providers.video.defaultMode || "ai-motion");
  const [motionStyle, setMotionStyle] = useState<string>(initialSettings?.providers.video.motionStyle || "subtle");
  const [message, setMessage] = useState("");

  async function generate() {
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/video-scripts`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ platform, duration, style })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "產生腳本失敗");
      const nextScripts = data.scripts || [];
      setScripts([...nextScripts, ...scripts]);
      setMessage(`已產生 ${nextScripts.length} 組腳本，系統會自動開始產生前 5 組分鏡圖。`);
      for (const script of nextScripts.slice(0, 5)) {
        if (script.id) void generateStoryboardImages(script.id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "產生腳本失敗");
    } finally {
      setLoading(false);
    }
  }

  async function generateStoryboardImages(scriptId: string) {
    setImageLoading((current) => ({ ...current, [scriptId]: true }));
    try {
      const response = await fetch(`/api/projects/${projectId}/video-scripts/${scriptId}/storyboard-images`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ maxFrames: initialSettings?.workflow.maxStoryboardFrames || 5 })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "產生分鏡圖失敗");
      if (data.jobId) {
        setJobs((current) => ({ ...current, [`storyboard:${scriptId}`]: data.job }));
        const job = await pollJob(data.jobId, (job) =>
          setJobs((current) => ({ ...current, [`storyboard:${scriptId}`]: job }))
        );
        if (job?.outputPayload?.script) {
          setScripts((current) => current.map((item) => (item.id === scriptId ? job.outputPayload.script : item)));
        }
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "產生分鏡圖失敗");
    } finally {
      setImageLoading((current) => ({ ...current, [scriptId]: false }));
    }
  }

  async function generateVoiceover(scriptId: string) {
    setVoiceLoading((current) => ({ ...current, [scriptId]: true }));
    try {
      const response = await fetch(`/api/projects/${projectId}/video-scripts/${scriptId}/voiceover`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ language: voiceLanguage, gender: voiceGender })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "產生配音失敗");
      if (data.jobId) {
        setJobs((current) => ({ ...current, [`voice:${scriptId}`]: data.job }));
        const job = await pollJob(data.jobId, (job) =>
          setJobs((current) => ({ ...current, [`voice:${scriptId}`]: job }))
        );
        if (job?.outputPayload?.voiceover) {
          setScripts((current) =>
            current.map((item) => (item.id === scriptId ? { ...item, latestVoiceover: job.outputPayload.voiceover } : item))
          );
        }
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "產生配音失敗");
    } finally {
      setVoiceLoading((current) => ({ ...current, [scriptId]: false }));
    }
  }

  async function renderVideo(scriptId: string) {
    setRenderLoading((current) => ({ ...current, [scriptId]: true }));
    try {
      const response = await fetch(`/api/projects/${projectId}/video-scripts/${scriptId}/render`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          secondsPerImage: 3,
          subtitleStyle,
          aspectRatio: videoAspectRatio,
          autoGenerateAssets: true,
        maxFrames: initialSettings?.workflow.maxStoryboardFrames || 5,
          language: voiceLanguage,
          gender: voiceGender,
          motionStyle,
          renderMode,
          clipDurationSec: renderMode === "ai-motion" ? (initialSettings?.providers.video.clipDurationSec || 5) : undefined
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "產生影片失敗");
      if (data.jobId) {
        setJobs((current) => ({ ...current, [`render:${scriptId}`]: data.job }));
        const job = await pollJob(data.jobId, (job) =>
          setJobs((current) => ({ ...current, [`render:${scriptId}`]: job }))
        );
        if (job?.outputPayload?.render) {
          setScripts((current) =>
            current.map((item) => (item.id === scriptId ? { ...item, latestRender: job.outputPayload.render } : item))
          );
        }
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "產生影片失敗");
    } finally {
      setRenderLoading((current) => ({ ...current, [scriptId]: false }));
    }
  }

  async function uploadStoryboardImage(scriptId: string, index: number, file?: File) {
    if (!file) return;
    const key = `${scriptId}:${index}`;
    setUploadLoading((current) => ({ ...current, [key]: true }));
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("projectId", projectId);
      const uploadResponse = await fetch("/api/upload", { method: "POST", body: formData });
      const uploadData = await uploadResponse.json();
      if (!uploadResponse.ok) throw new Error(uploadData.message || "上傳分鏡圖失敗");

      const patchResponse = await fetch(`/api/projects/${projectId}/video-scripts/${scriptId}/storyboard-frames`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          index,
          imageUrl: uploadData.fileUrl,
          imageSource: "manual_upload",
          imageLocked: initialSettings?.workflow.keepUploadedStoryboardLocked ?? true
        })
      });
      const patchData = await patchResponse.json();
      if (!patchResponse.ok) throw new Error(patchData.message || "更新分鏡圖失敗");
      if (patchData.script) {
        setScripts((current) => current.map((item) => (item.id === scriptId ? patchData.script : item)));
      }
      setMessage("已上傳並鎖定這格分鏡圖，後續產生影片會優先使用你上傳的圖。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上傳分鏡圖失敗");
    } finally {
      setUploadLoading((current) => ({ ...current, [key]: false }));
    }
  }

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>影片腳本生產工作台</CardTitle>
          <CardDescription>
            產生腳本、分鏡圖、即夢提示詞、配音與完整影片。你也可以手動上傳分鏡圖，再交給系統合成影片。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end">
          <Picker label="平台" value={platform} onChange={setPlatform} options={platforms} note={<FieldNote impact="high">影響 Hook、節奏、字卡密度與 CTA 寫法。</FieldNote>} />
          <Picker label="影片長度" value={duration} onChange={setDuration} options={durations} note={<FieldNote impact="high">影響分鏡數量、口白長度與賣點取捨。</FieldNote>} />
          <Picker label="腳本風格" value={style} onChange={setStyle} options={styles} note={<FieldNote impact="high">影響劇情結構、語氣、拍攝方式與痛點切入。</FieldNote>} />
          <Button onClick={generate} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            產生 5 組腳本
          </Button>
        </CardContent>
        <CardContent className="grid gap-3 border-t pt-4 md:grid-cols-3 lg:grid-cols-6">
          <Picker label="配音語言" value={voiceLanguage} onChange={setVoiceLanguage} options={voiceLanguages} note={<FieldNote impact="medium">影響配音音檔語言，不會改寫已生成腳本文字。</FieldNote>} />
          <Picker label="配音聲線" value={voiceGender} onChange={setVoiceGender} options={voiceGenders} note={<FieldNote impact="medium">影響配音感受，不影響 AI 對產品的判讀。</FieldNote>} />
          <Picker label="字幕樣式" value={subtitleStyle} onChange={setSubtitleStyle} options={subtitleStyles} note={<FieldNote impact="none">只影響合成影片字幕外觀。</FieldNote>} />
          <Picker label="影片比例" value={videoAspectRatio} onChange={setVideoAspectRatio} options={videoRatios} note={<FieldNote impact="medium">影響分鏡構圖與影片安全區。</FieldNote>} />
          <Picker label="生成模式" value={renderMode} onChange={setRenderMode} options={renderModes} note={<FieldNote impact="high">決定是否呼叫 AI 動態影片模型，或只做圖片合成。</FieldNote>} />
          <Picker label="動態風格" value={motionStyle} onChange={setMotionStyle} options={motionStyles} note={<FieldNote impact="medium">影響動態影片運鏡與動作幅度。</FieldNote>} />
        </CardContent>
        {message ? <CardContent className="border-t pt-4 text-sm text-muted-foreground">{message}</CardContent> : null}
      </Card>

      <div className="grid gap-4">
        {scripts.map((script) => {
          const storyboard = Array.isArray(script.storyboard) ? script.storyboard : [];
          return (
            <Card key={script.id || `${script.title}-${script.hook}`}>
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>{script.title}</CardTitle>
                  <div className="flex flex-wrap gap-2">
                    <Badge>{script.platform}</Badge>
                    <Badge>{script.duration}</Badge>
                    {script.style ? <Badge>{script.style}</Badge> : null}
                  </div>
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <JobProgress
                    job={jobs[`storyboard:${script.id}`]}
                    onRetry={(job) => setJobs((current) => ({ ...current, [`storyboard:${script.id}`]: job }))}
                  />
                  <JobProgress
                    job={jobs[`voice:${script.id}`]}
                    onRetry={(job) => setJobs((current) => ({ ...current, [`voice:${script.id}`]: job }))}
                  />
                  <JobProgress
                    job={jobs[`render:${script.id}`]}
                    onRetry={(job) => setJobs((current) => ({ ...current, [`render:${script.id}`]: job }))}
                  />
                </div>
                <CardDescription>Hook：{script.hook}</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-5">
                <StoryboardPreview
                  script={script}
                  storyboard={storyboard}
                  uploadLoading={uploadLoading}
                  onUpload={uploadStoryboardImage}
                />

                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => generateStoryboardImages(script.id)}
                    disabled={!script.id || imageLoading[script.id]}
                  >
                    {imageLoading[script.id] ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                    {script.imageStatus === "ready" ? "重新生成未鎖定分鏡圖" : "產生分鏡圖"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => generateVoiceover(script.id)}
                    disabled={!script.id || voiceLoading[script.id]}
                  >
                    {voiceLoading[script.id] ? <Loader2 className="h-4 w-4 animate-spin" /> : <Volume2 className="h-4 w-4" />}
                    產生配音
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => renderVideo(script.id)}
                    disabled={!script.id || renderLoading[script.id]}
                  >
                    {renderLoading[script.id] ? <Loader2 className="h-4 w-4 animate-spin" /> : <Film className="h-4 w-4" />}
                    {renderMode === "ai-motion" ? "一鍵生成動態影片" : "合成靜態影片"}
                  </Button>
                  <CopyButton value={buildExternalPromptPack(script)} label="複製即夢提示詞包" />
                  <CopyButton value={JSON.stringify(script, null, 2)} label="複製完整腳本 JSON" />
                </div>

                {script.latestVoiceover?.audioUrl ? (
                  <audio className="w-full" controls src={script.latestVoiceover.audioUrl} />
                ) : null}
                {script.latestRender?.videoUrl ? (
                  <video className="w-full max-w-sm rounded-md border bg-black" controls src={script.latestRender.videoUrl} />
                ) : null}

                <div className="grid gap-3 rounded-md border bg-white p-4 text-sm md:grid-cols-2">
                  <p><span className="font-medium">拍攝道具：</span>{Array.isArray(script.props) ? script.props.join("、") : "未提供"}</p>
                  <p><span className="font-medium">BGM：</span>{script.bgmSuggestion || "未提供"}</p>
                  <p><span className="font-medium">語調：</span>{script.tone || "未提供"}</p>
                  <p><span className="font-medium">CTA：</span>{script.cta || "未提供"}</p>
                  <p className="md:col-span-2"><span className="font-medium">適合受眾：</span>{script.targetAudience || "未提供"}</p>
                </div>

                <StoryboardTable storyboard={storyboard} />
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function StoryboardPreview({
  script,
  storyboard,
  uploadLoading,
  onUpload
}: {
  script: any;
  storyboard: any[];
  uploadLoading: Record<string, boolean>;
  onUpload: (scriptId: string, index: number, file?: File) => void;
}) {
  return (
    <div className="rounded-lg border bg-slate-950 p-3">
      <div className="mb-3 flex items-center justify-between text-xs text-white/70">
        <span className="flex items-center gap-2">
          <Clapperboard className="h-4 w-4" />
          分鏡圖與即夢提示詞
        </span>
        <span>{script.platform || "短影音"}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
        {storyboard.slice(0, 5).map((shot, index) => (
          <StoryboardFrame
            key={`${shot.time}-${index}`}
            scriptId={script.id}
            shot={shot}
            index={index}
            uploading={Boolean(uploadLoading[`${script.id}:${index}`])}
            onUpload={onUpload}
          />
        ))}
      </div>
    </div>
  );
}

function StoryboardFrame({
  scriptId,
  shot,
  index,
  uploading,
  onUpload
}: {
  scriptId: string;
  shot: any;
  index: number;
  uploading: boolean;
  onUpload: (scriptId: string, index: number, file?: File) => void;
}) {
  const palette = [
    "from-slate-100 via-emerald-100 to-orange-100",
    "from-zinc-100 via-sky-100 to-emerald-100",
    "from-stone-100 via-white to-amber-100",
    "from-slate-100 via-rose-100 to-orange-100",
    "from-neutral-100 via-emerald-50 to-slate-200"
  ][index % 5];

  return (
    <div className="rounded-md bg-white/10 p-2">
      <div className={`relative aspect-[9/16] overflow-hidden rounded-md bg-gradient-to-br ${palette} text-slate-950`}>
        {shot.imageUrl ? (
          <img src={shot.imageUrl} alt={`分鏡 ${index + 1}`} className="absolute inset-0 h-full w-full object-cover" />
        ) : null}
        {shot.imageUrl ? <div className="absolute inset-0 bg-gradient-to-t from-slate-950/80 via-transparent to-slate-950/20" /> : null}
        <div className="absolute left-2 top-2 rounded bg-slate-950 px-2 py-1 text-[10px] font-semibold text-white">
          {shot.time || `第 ${index + 1} 格`}
        </div>
        {shot.imageSource ? (
          <div className="absolute right-2 top-2 rounded bg-white/90 px-2 py-1 text-[10px] font-medium text-slate-900">
            {shot.imageSource === "manual_upload" ? "手動上傳" : "AI 生成"}
          </div>
        ) : null}
        {!shot.imageUrl ? (
          <>
            <div className="absolute inset-x-4 top-16 h-24 rounded-md bg-white/65 shadow-panel">
              <div className="mx-auto mt-5 h-12 w-12 rounded-full bg-primary/25" />
              <div className="mx-auto mt-3 h-2 w-20 rounded bg-slate-300" />
            </div>
            <div className="absolute left-3 right-3 top-[46%] rounded-md bg-white/85 p-2 shadow-panel">
              <p className="line-clamp-3 text-xs font-semibold leading-5">{shot.scene || shot.visual || "尚未產生分鏡圖"}</p>
            </div>
          </>
        ) : null}
        <div className="absolute bottom-12 left-3 right-3 rounded-md bg-slate-950/90 p-2 text-center text-xs font-semibold leading-5 text-white">
          {shot.caption || "字卡"}
        </div>
        <div className="absolute bottom-3 left-3 right-3 text-center text-[10px] text-white/80">
          {shot.purpose || "段落目的"}
        </div>
      </div>
      <p className="mt-2 line-clamp-2 text-xs leading-5 text-white/80">{shot.voiceover || shot.visual || "口白與畫面說明"}</p>
      <label className="mt-2 flex cursor-pointer items-center justify-center gap-2 rounded-md border border-white/20 px-2 py-2 text-xs text-white hover:bg-white/10">
        {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
        上傳替換這格
        <input
          type="file"
          accept="image/*"
          className="hidden"
          disabled={uploading}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            onUpload(scriptId, index, file);
          }}
        />
      </label>
      <div className="mt-2 grid gap-2">
        <CopyButton value={shot.imagePrompt || ""} label="複製生圖提示詞" />
        <CopyButton value={shot.jimengPrompt || shot.motionPrompt || ""} label="複製即夢提示詞" />
      </div>
    </div>
  );
}

function StoryboardTable({ storyboard }: { storyboard: any[] }) {
  return (
    <div>
      <p className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <ImageIcon className="h-4 w-4" />
        專業分鏡細節
      </p>
      <div className="overflow-auto rounded-md border">
        <table className="w-full min-w-[1100px] border-collapse bg-white text-sm">
          <thead className="bg-muted text-left text-xs text-muted-foreground">
            <tr>
              <th className="p-3">時間</th>
              <th className="p-3">目的</th>
              <th className="p-3">畫面</th>
              <th className="p-3">構圖 / 運鏡</th>
              <th className="p-3">情緒 / 場景</th>
              <th className="p-3">產品露出</th>
              <th className="p-3">字卡</th>
              <th className="p-3">口白</th>
            </tr>
          </thead>
          <tbody>
            {storyboard.map((shot: any, index: number) => (
              <tr key={`${shot.time}-${index}`} className="border-t align-top">
                <td className="p-3 text-xs font-medium">{shot.time}</td>
                <td className="p-3">{shot.purpose}</td>
                <td className="p-3">
                  <p>{shot.scene}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{shot.subject || shot.visual}</p>
                </td>
                <td className="p-3">
                  <p>{shot.composition}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{shot.cameraMovement}</p>
                </td>
                <td className="p-3">
                  <p>{shot.emotion}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{shot.setting}</p>
                </td>
                <td className="p-3">{shot.productPlacement}</td>
                <td className="p-3">{shot.caption}</td>
                <td className="p-3">{shot.voiceover}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function buildExternalPromptPack(script: any) {
  const storyboard = Array.isArray(script.storyboard) ? script.storyboard : [];
  return [
    `影片主題：${script.title}`,
    `平台：${script.platform}`,
    `長度：${script.duration}`,
    `風格：${script.style || "未指定"}`,
    `Hook：${script.hook}`,
    "",
    "即夢 AI 圖生影片提示詞：",
    ...storyboard.map((shot: any, index: number) => [
      "",
      `第 ${index + 1} 段｜${shot.time || ""}`,
      shot.jimengPrompt || shot.motionPrompt || shot.visual || ""
    ].join("\n")),
    "",
    "負面提示詞：",
    storyboard[0]?.negativePrompt || "不要亂碼文字、不要額外 Logo、不要浮水印、不要產品外觀變形、不要手指變形"
  ].join("\n");
}

function Picker({
  label,
  value,
  options,
  onChange,
  note
}: {
  label: string;
  value: string;
  options: Array<string | { label: string; value: string }>;
  onChange: (value: string) => void;
  note?: ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      <Select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => {
          const item = typeof option === "string" ? { label: option, value: option } : option;
          return (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          );
        })}
      </Select>
      {note}
    </div>
  );
}
