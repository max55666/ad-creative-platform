"use client";

import { BrainCircuit, CheckCircle2, Copy, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { FieldNote } from "@/components/field-note";
import { JobProgress } from "@/components/job-progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ClientJob, pollJob } from "@/lib/client-jobs";

export function ProductLoraClient({
  projectId,
  projectName,
  initialAssets,
  initialModels
}: {
  projectId: string;
  projectName: string;
  initialAssets: any[];
  initialModels: any[];
}) {
  const imageAssets = useMemo(() => initialAssets.filter((asset) => asset.type === "image" && asset.fileUrl), [initialAssets]);
  const [models, setModels] = useState<any[]>(initialModels);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>(imageAssets.slice(0, 30).map((asset) => asset.id));
  const [triggerWord, setTriggerWord] = useState(normalizeTriggerWord(projectName));
  const [steps, setSteps] = useState(1000);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [job, setJob] = useState<ClientJob | null>(null);
  const [message, setMessage] = useState("");

  async function startTraining() {
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/lora-models`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: `${projectName} LoRA`,
          triggerWord,
          steps,
          createMasks: true,
          assetIds: selectedAssetIds
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "建立 LoRA 訓練任務失敗。");
      setModels((current) => [data.model, ...current]);
      setJob(data.job);
      const completed = await pollJob(data.jobId, setJob);
      const model = completed.outputPayload?.model;
      if (model) setModels((current) => current.map((item) => (item.id === model.id ? model : item)));
      setMessage("訓練任務已送到 fal.ai。接下來請按「同步狀態」檢查是否完成。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "建立 LoRA 訓練任務失敗。");
    } finally {
      setLoading(false);
    }
  }

  async function syncModel(modelId: string) {
    setSyncing((current) => ({ ...current, [modelId]: true }));
    try {
      const response = await fetch(`/api/projects/${projectId}/lora-models/${modelId}/sync`, { method: "POST" });
      const data = await response.json();
      if (data.model) {
        setModels((current) => current.map((item) => (item.id === modelId ? data.model : item)));
      }
      if (!response.ok) setMessage(data.message || "同步 fal 訓練狀態失敗。");
    } finally {
      setSyncing((current) => ({ ...current, [modelId]: false }));
    }
  }

  function toggleAsset(assetId: string) {
    setSelectedAssetIds((current) =>
      current.includes(assetId) ? current.filter((id) => id !== assetId) : [...current, assetId]
    );
  }

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <BrainCircuit className="h-5 w-5" />
                產品模型訓練中心
              </CardTitle>
              <CardDescription>
                使用 fal.ai FLUX LoRA 訓練產品模型，讓後續廣告圖更認得你的商品外觀。
              </CardDescription>
            </div>
            <Badge>fal.ai / FLUX LoRA</Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="grid gap-4 md:grid-cols-[1fr_180px]">
            <label className="grid gap-2 text-sm font-medium">
              Trigger word
              <input
                className="h-10 rounded-md border border-input px-3 text-sm"
                value={triggerWord}
                onChange={(event) => setTriggerWord(normalizeTriggerWord(event.target.value))}
                placeholder="ubpet_c41_litterbox"
              />
              <FieldNote impact="high">會影響 AI 判讀。之後生圖 prompt 必須包含這個詞，模型才會叫出這個產品。</FieldNote>
            </label>
            <label className="grid gap-2 text-sm font-medium">
              Training steps
              <input
                className="h-10 rounded-md border border-input px-3 text-sm"
                type="number"
                min={400}
                max={2500}
                step={100}
                value={steps}
                onChange={(event) => setSteps(Number(event.target.value || 1000))}
              />
              <FieldNote impact="medium">會影響訓練時間與成本。先用 1000 測試即可。</FieldNote>
            </label>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">訓練圖片</p>
                <p className="text-xs text-muted-foreground">至少 4 張，建議 15-30 張。角度越完整，產品越不容易跑掉。</p>
              </div>
              <Badge>{selectedAssetIds.length} 張已選</Badge>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {imageAssets.map((asset) => {
                const selected = selectedAssetIds.includes(asset.id);
                return (
                  <button
                    key={asset.id}
                    type="button"
                    onClick={() => toggleAsset(asset.id)}
                    className={`rounded-md border bg-white p-2 text-left transition ${selected ? "border-primary ring-2 ring-primary/20" : "hover:border-primary/40"}`}
                  >
                    <div className="relative aspect-square overflow-hidden rounded bg-muted">
                      <img src={asset.fileUrl} alt={asset.meta?.label || "training asset"} className="h-full w-full object-cover" />
                      {selected ? (
                        <span className="absolute right-2 top-2 rounded-full bg-primary p-1 text-white">
                          <CheckCircle2 className="h-4 w-4" />
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-2 truncate text-xs font-medium">{asset.meta?.label || asset.meta?.originalName || "產品圖"}</p>
                    <p className="truncate text-xs text-muted-foreground">{asset.meta?.viewAngle || asset.meta?.usage || "未標註角度"}</p>
                  </button>
                );
              })}
            </div>
          </div>

          {message ? <p className="rounded-md border bg-amber-50 p-3 text-sm text-amber-800">{message}</p> : null}
          <div className="flex flex-wrap gap-2">
            <Button onClick={startTraining} disabled={loading || selectedAssetIds.length < 4 || !triggerWord}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              開始 fal LoRA 訓練
            </Button>
          </div>
          <JobProgress job={job} onRetry={setJob} />
        </CardContent>
      </Card>

      <div className="grid gap-4">
        {models.map((model) => (
          <Card key={model.id}>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>{model.name}</CardTitle>
                  <CardDescription>
                    Trigger word：<span className="font-mono">{model.triggerWord}</span>
                  </CardDescription>
                </div>
                <Badge>{statusLabel(model.status)}</Badge>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              <div className="grid gap-3 md:grid-cols-3">
                <Info label="訓練圖片" value={`${model.trainingImageCount || 0} 張`} />
                <Info label="fal request id" value={model.requestId || "尚未提交"} mono />
                <Info label="Endpoint" value={model.endpoint || "fal-ai/flux-lora-fast-training"} mono />
              </div>
              {model.samplePrompt ? (
                <div className="rounded-md border bg-muted/50 p-3">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">建議測試 prompt</p>
                  <p className="font-mono text-xs">{model.samplePrompt}</p>
                </div>
              ) : null}
              {model.diffusersLoraUrl ? (
                <div className="grid gap-2 rounded-md border bg-emerald-50 p-3 text-emerald-900">
                  <p className="font-medium">LoRA 已完成</p>
                  <p className="break-all text-xs">{model.diffusersLoraUrl}</p>
                  <div className="flex flex-wrap gap-2">
                    <CopyButton value={model.diffusersLoraUrl} label="複製 LoRA URL" />
                    <CopyButton value={model.triggerWord} label="複製 trigger word" />
                  </div>
                </div>
              ) : null}
              {model.errorMessage ? <p className="whitespace-pre-wrap rounded-md border bg-red-50 p-3 text-xs text-red-700">{model.errorMessage}</p> : null}
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => syncModel(model.id)} disabled={!model.requestId || syncing[model.id]}>
                  {syncing[model.id] ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  同步狀態
                </Button>
                {model.diffusersLoraUrl ? (
                  <Button type="button" variant="outline" size="sm" asChild>
                    <a href={model.diffusersLoraUrl} target="_blank" rel="noreferrer">
                      <Copy className="h-4 w-4" />
                      開啟 LoRA 檔
                    </a>
                  </Button>
                ) : null}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-md border bg-white p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={mono ? "mt-1 break-all font-mono text-xs" : "mt-1 font-medium"}>{value}</p>
    </div>
  );
}

function normalizeTriggerWord(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
}

function statusLabel(status: string) {
  if (status === "queued") return "等待提交";
  if (status === "training") return "訓練中";
  if (status === "ready") return "可使用";
  if (status === "failed") return "失敗";
  if (status === "completed") return "完成";
  return status || "draft";
}
