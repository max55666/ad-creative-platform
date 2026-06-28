"use client";

import { ImageIcon, Loader2, RefreshCw, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { FieldNote } from "@/components/field-note";
import { JobProgress } from "@/components/job-progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ClientJob, pollJob } from "@/lib/client-jobs";

export function StaticCreativeClient({
  projectId,
  initialSuggestions
}: {
  projectId: string;
  initialSuggestions: any[];
}) {
  const [suggestions, setSuggestions] = useState<any[]>(initialSuggestions);
  const [loading, setLoading] = useState(false);
  const [imageLoading, setImageLoading] = useState<Record<string, boolean>>({});
  const [jobs, setJobs] = useState<Record<string, ClientJob>>({});
  const [aspectRatio, setAspectRatio] = useState("4:5");

  async function generate(regenerateTitle?: string) {
    setLoading(true);
    const response = await fetch(`/api/projects/${projectId}/static-creatives`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ regenerateTitle })
    });
    const data = await response.json();
    const nextSuggestions = data.suggestions || [];
    setSuggestions([...nextSuggestions, ...suggestions]);
    setLoading(false);
    for (const item of nextSuggestions.slice(0, 5)) {
      if (item.id) void generateImage(item.id, aspectRatio);
    }
  }

  async function generateImage(creativeId: string, selectedAspectRatio = aspectRatio) {
    setImageLoading((current) => ({ ...current, [creativeId]: true }));
    const response = await fetch(`/api/projects/${projectId}/static-creatives/${creativeId}/image`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ aspectRatio: selectedAspectRatio })
    });
    const data = await response.json();
    if (data.jobId) {
      setJobs((current) => ({ ...current, [creativeId]: data.job }));
      const job = await pollJob(data.jobId, (job) =>
        setJobs((current) => ({ ...current, [creativeId]: job }))
      );
      const output = job?.outputPayload;
      if (output?.creative) {
        setSuggestions((current) =>
          current.map((item) => (item.id === creativeId ? output.creative : item))
        );
      }
    } else if (data.creative) {
      setSuggestions((current) =>
        current.map((item) => (item.id === creativeId ? data.creative : item))
      );
    }
    setImageLoading((current) => ({ ...current, [creativeId]: false }));
  }

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle>平面素材製作方向</CardTitle>
            <CardDescription>每組素材包含 AI 生成預覽圖、主標、副標、字卡、CTA、平台與受眾，方便美術直接抓方向。</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="grid gap-1">
              <select
                className="h-10 rounded-md border border-input bg-white px-3 text-sm"
                value={aspectRatio}
                onChange={(event) => setAspectRatio(event.target.value)}
                aria-label="廣告圖版型"
              >
                <option value="1:1">1:1</option>
                <option value="4:5">4:5</option>
                <option value="9:16">9:16</option>
              </select>
              <FieldNote impact="medium">影響 AI 圖片構圖與版面比例，不影響產品分析文字。</FieldNote>
            </div>
            <Button onClick={() => generate()} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              產生 5 組素材
            </Button>
          </div>
        </CardHeader>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        {suggestions.map((item) => {
          const copy = JSON.stringify(item, null, 2);
          const copywriting = normalizeCopywriting(item.copywriting);
          return (
            <Card key={item.id || `${item.title}-${item.headline}`} className="overflow-hidden">
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>{item.title}</CardTitle>
                  <Badge>{item.platform}</Badge>
                </div>
                <CardDescription>{item.communication}</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
                <CreativeMockup item={item} cardText={copywriting.cardText} />

                <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
                  <div className="grid gap-3">
                    <InfoBlock label="主標題" value={item.headline} strong />
                    {item.subHeadline ? <InfoBlock label="副標題" value={item.subHeadline} /> : null}
                    <div className="rounded-md border bg-white p-3 text-sm">
                      <p><span className="font-medium">CTA：</span>{item.cta}</p>
                      <p className="mt-2"><span className="font-medium">受眾：</span>{item.targetAudience}</p>
                    </div>
                  </div>

                  <div className="grid gap-3">
                    <div>
                      <p className="mb-2 text-xs font-medium text-muted-foreground">圖片構圖建議</p>
                      <p className="rounded-md bg-muted/70 p-3 text-sm leading-6">{item.visualDirection}</p>
                    </div>
                    <div>
                      <p className="mb-2 text-xs font-medium text-muted-foreground">字卡內容</p>
                      <div className="flex flex-wrap gap-2">
                        {copywriting.cardText.length ? (
                          copywriting.cardText.map((text, index) => (
                            <Badge key={`${text}-${index}`} className="bg-white">
                              {text}
                            </Badge>
                          ))
                        ) : (
                          <Badge className="bg-white">尚未提供字卡</Badge>
                        )}
                      </div>
                    </div>
                    {copywriting.body ? <InfoBlock label="廣告內文" value={copywriting.body} /> : null}
                    {copywriting.proof ? <InfoBlock label="佐證資訊" value={copywriting.proof} /> : null}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <CopyButton value={copy} label="複製素材" />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => generateImage(item.id, aspectRatio)}
                    disabled={!item.id || imageLoading[item.id]}
                  >
                    {imageLoading[item.id] ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                    {item.previewImageUrl ? "重新生成真圖" : "生成真圖"}
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => generate(item.title)} disabled={loading}>
                    <RefreshCw className="h-4 w-4" />
                    重新生成此方向
                  </Button>
                </div>
                <JobProgress
                  job={jobs[item.id]}
                  onRetry={(job) => setJobs((current) => ({ ...current, [item.id]: job }))}
                />
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function CreativeMockup({ item, cardText }: { item: any; cardText: string[] }) {
  const kind = getCreativeKind(`${item.title || ""} ${item.headline || ""}`);
  const headline = String(item.headline || "主標題");
  const subHeadline = String(item.subHeadline || item.communication || "副標題或利益點");
  const firstCard = cardText[0] || headline;
  const secondCard = cardText[1] || subHeadline;

  return (
    <div className="rounded-lg border bg-slate-950 p-3">
      <div className="mb-2 flex items-center justify-between text-xs text-white/70">
        <span className="flex items-center gap-2">
          <ImageIcon className="h-4 w-4" />
          4:5 AI 生成預覽圖
        </span>
        <span>{item.platform || "Meta / TikTok"}</span>
      </div>
      <div className="relative aspect-[4/5] overflow-hidden rounded-md bg-[#f8fafc] text-slate-950">
        {item.previewImageUrl ? (
          <img src={item.previewImageUrl} alt={`${item.title} generated preview`} className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <div className="absolute inset-0 bg-[linear-gradient(135deg,#f8fafc_0%,#d8eee9_42%,#fdebd7_100%)]" />
        )}
        {item.previewImageUrl ? <div className="absolute inset-0 bg-gradient-to-t from-slate-950/75 via-transparent to-slate-950/10" /> : null}

        {item.previewImageUrl ? (
          <div className="absolute inset-0 p-5">
            <div className="max-w-[78%]">
              <p className="rounded-md bg-white/90 px-3 py-2 text-xs font-semibold text-slate-950 shadow-panel">{item.title || "素材方向"}</p>
              <h3 className="mt-4 text-3xl font-semibold leading-tight tracking-normal text-white drop-shadow">{headline}</h3>
              <p className="mt-3 text-sm leading-6 text-white/90 drop-shadow">{subHeadline}</p>
            </div>
            <div className="absolute bottom-5 left-5 right-5 grid gap-2">
              <div className="rounded-md bg-white/92 px-3 py-2 text-sm font-medium text-slate-950 shadow-panel">{firstCard}</div>
              <div className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white">{item.cta || "立即了解"}</div>
            </div>
          </div>
        ) : kind === "compare" ? (
          <div className="absolute inset-0 grid grid-cols-2">
            <div className="border-r border-slate-900/15 bg-slate-200/75 p-4">
              <p className="text-xs font-semibold uppercase text-slate-500">Before</p>
              <div className="mt-8 h-28 rounded-md bg-slate-400/40" />
              <p className="mt-4 text-sm font-semibold">{firstCard}</p>
            </div>
            <div className="bg-emerald-50/85 p-4">
              <p className="text-xs font-semibold uppercase text-emerald-700">After</p>
              <div className="mt-8 h-28 rounded-md bg-emerald-500/25 shadow-inner" />
              <p className="mt-4 text-sm font-semibold">{secondCard}</p>
            </div>
          </div>
        ) : kind === "testimonial" ? (
          <div className="absolute inset-0 p-5">
            <div className="h-24 rounded-md bg-white/70 shadow-panel" />
            <div className="mt-6 rounded-md bg-white p-4 shadow-panel">
              <p className="text-lg font-semibold leading-7">“{headline}”</p>
              <p className="mt-3 text-sm leading-6 text-slate-600">{subHeadline}</p>
            </div>
            <div className="absolute bottom-5 left-5 right-5 rounded-md bg-slate-950 px-4 py-3 text-sm font-semibold text-white">
              {item.cta || "立即了解"}
            </div>
          </div>
        ) : (
          <div className="absolute inset-0 p-5">
            <div className="absolute right-5 top-5 h-40 w-32 rounded-md bg-white/65 shadow-panel">
              <div className="mx-auto mt-5 h-24 w-16 rounded-full bg-emerald-500/30" />
              <div className="mx-auto mt-3 h-3 w-20 rounded bg-slate-300" />
            </div>
            <div className="max-w-[68%]">
              <p className="rounded-md bg-slate-950 px-3 py-2 text-xs font-semibold text-white">{item.title || "素材方向"}</p>
              <h3 className="mt-5 text-3xl font-semibold leading-tight tracking-normal">{headline}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-700">{subHeadline}</p>
            </div>
            <div className="absolute bottom-5 left-5 right-5 grid gap-2">
              <div className="rounded-md bg-white/90 px-3 py-2 text-sm font-medium shadow-panel">{firstCard}</div>
              <div className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white">{item.cta || "立即了解"}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function InfoBlock({ label, value, strong }: { label: string; value: unknown; strong?: boolean }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <p className={strong ? "text-base font-semibold leading-7" : "text-sm leading-6"}>{String(value || "未提供")}</p>
    </div>
  );
}

function normalizeCopywriting(value: any): { cardText: string[]; body: string; proof: string } {
  if (!value || typeof value !== "object") {
    return { cardText: [], body: "", proof: "" };
  }

  return {
    cardText: Array.isArray(value.cardText) ? value.cardText.map(String) : [],
    body: typeof value.body === "string" ? value.body : "",
    proof: typeof value.proof === "string" ? value.proof : ""
  };
}

function getCreativeKind(value: string) {
  if (/Before|After|對比|前後/i.test(value)) return "compare";
  if (/評價|見證|心得|口碑/i.test(value)) return "testimonial";
  return "standard";
}
