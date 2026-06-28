"use client";

import { Save, Settings, SlidersHorizontal, Sparkles, ToggleLeft, Video } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldNote } from "@/components/field-note";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { SystemSettings } from "@/lib/settings";

type SettingsOptions = Record<string, readonly string[]>;

export function SettingsClient({
  initialSettings,
  options
}: {
  initialSettings: SystemSettings;
  options: SettingsOptions;
}) {
  const [settings, setSettings] = useState<SystemSettings>(initialSettings);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  function update(path: string, value: unknown) {
    setSettings((current) => {
      const next: any = structuredClone(current);
      const keys = path.split(".");
      let target = next;
      for (const key of keys.slice(0, -1)) target = target[key];
      target[keys[keys.length - 1]] = value;
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setMessage("");
    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ settings })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "儲存設定失敗。");
      setSettings(data.settings);
      setMessage("設定已儲存。新的設定會套用到後續生成任務。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "儲存設定失敗。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">系統設定</h1>
          <p className="mt-1 text-sm text-muted-foreground">調整模型、配音、影片生成、字幕與工作流程。設定只會影響之後的新任務。</p>
        </div>
        <Button onClick={save} disabled={saving}>
          <Save className="h-4 w-4" />
          {saving ? "儲存中..." : "儲存設定"}
        </Button>
      </div>
      {message ? <div className="rounded-md border bg-white px-4 py-3 text-sm text-muted-foreground">{message}</div> : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Sparkles className="h-5 w-5" />AI 模型設定</CardTitle>
          <CardDescription>這些設定會改變 AI 生成品質、風格穩定度、圖片品質、語音與轉文字行為。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label="文字模型供應商" note={<FieldNote impact="none">目前固定使用 OpenAI，只影響系統路由，不直接改變輸入內容。</FieldNote>}>
            <Select value={settings.providers.text.provider} onChange={(event) => update("providers.text.provider", event.target.value)}>
              <option value="openai">OpenAI</option>
            </Select>
          </Field>
          <Field label="文字模型" note={<FieldNote impact="high">會直接影響產品分析、腳本、KOL 分析與 Brand Brain 的理解品質。</FieldNote>}>
            <ComboInput value={settings.providers.text.model} options={options.textModels || []} onChange={(value) => update("providers.text.model", value)} />
          </Field>
          <Field label="圖片模型" note={<FieldNote impact="high">會影響平面素材圖、分鏡圖的畫面品質與提示詞遵循程度。</FieldNote>}>
            <ComboInput value={settings.providers.image.model} options={options.imageModels || []} onChange={(value) => update("providers.image.model", value)} />
          </Field>
          <Field label="圖片品質" note={<FieldNote impact="medium">主要影響圖片清晰度、生成時間與成本，不會改變文案判讀。</FieldNote>}>
            <Select value={settings.providers.image.quality} onChange={(event) => update("providers.image.quality", event.target.value)}>
              <option value="medium">medium</option>
              <option value="low">low</option>
              <option value="high">high</option>
              <option value="auto">auto</option>
            </Select>
          </Field>
          <Field label="語音轉文字模型" note={<FieldNote impact="medium">會影響爆款影片分析的逐字稿品質，進而影響 Hook、口白與節奏判讀。</FieldNote>}>
            <ComboInput value={settings.providers.transcription.model} options={options.transcriptionModels || []} onChange={(value) => update("providers.transcription.model", value)} />
          </Field>
          <Field label="配音供應商" note={<FieldNote impact="none">影響配音服務來源，不影響 AI 腳本內容。</FieldNote>}>
            <Select value={settings.providers.voiceover.provider} onChange={(event) => update("providers.voiceover.provider", event.target.value)}>
              <option value="elevenlabs">ElevenLabs</option>
            </Select>
          </Field>
          <Field label="ElevenLabs 模型" note={<FieldNote impact="medium">影響配音音質與語言表現，不改變文字腳本。</FieldNote>}>
            <ComboInput value={settings.providers.voiceover.model} options={options.voiceModels || []} onChange={(value) => update("providers.voiceover.model", value)} />
          </Field>
          <Field label="預設聲線" note={<FieldNote impact="medium">影響生成配音的聲音性別，可能影響素材感受，但不改變腳本文字。</FieldNote>}>
            <Select value={settings.providers.voiceover.defaultGender} onChange={(event) => update("providers.voiceover.defaultGender", event.target.value)}>
              <option value="female">女聲</option>
              <option value="male">男聲</option>
            </Select>
          </Field>
          <Field label="女聲 Voice ID" note={<FieldNote impact="medium">影響女聲配音聲音，不影響 AI 對產品或腳本的判讀。</FieldNote>}>
            <Input value={settings.providers.voiceover.femaleVoiceId} onChange={(event) => update("providers.voiceover.femaleVoiceId", event.target.value)} />
          </Field>
          <Field label="男聲 Voice ID" note={<FieldNote impact="medium">影響男聲配音聲音，不影響 AI 對產品或腳本的判讀。</FieldNote>}>
            <Input value={settings.providers.voiceover.maleVoiceId} onChange={(event) => update("providers.voiceover.maleVoiceId", event.target.value)} />
          </Field>
          <Field label="預設配音語言" note={<FieldNote impact="medium">影響配音語言；若腳本文案也要換語言，需在生成腳本時指定。</FieldNote>}>
            <Select value={settings.providers.voiceover.defaultLanguage} onChange={(event) => update("providers.voiceover.defaultLanguage", event.target.value)}>
              <option value="zh">中文</option>
              <option value="ja">日文</option>
              <option value="en">英文</option>
            </Select>
          </Field>
          <Field label="文字發散度 temperature" note={<FieldNote impact="high">數字越高越有變化，越低越穩定。部分模型不支援自訂值，系統會自動改用預設。</FieldNote>}>
            <Input
              type="number"
              step="0.1"
              min="0"
              max="2"
              value={settings.providers.text.temperature}
              onChange={(event) => update("providers.text.temperature", Number(event.target.value))}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Video className="h-5 w-5" />影片生成設定</CardTitle>
          <CardDescription>這些設定影響影片生成方式、等待時間與動態效果。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label="影片供應商" note={<FieldNote impact="high">會決定是否能生成真的動態影片，以及使用哪家影片模型。</FieldNote>}>
            <Select value={settings.providers.video.provider} onChange={(event) => update("providers.video.provider", event.target.value)}>
              {(options.videoProviders || []).map((item) => <option key={item} value={item}>{videoProviderLabel(item)}</option>)}
            </Select>
          </Field>
          <Field label="影片模型" note={<FieldNote impact="high">會影響動態品質、生成能力、成本與支援比例。</FieldNote>}>
            <ComboInput value={settings.providers.video.model} options={options.videoModels || []} onChange={(value) => update("providers.video.model", value)} />
          </Field>
          <Field label="預設生成模式" note={<FieldNote impact="high">AI 動態影片會呼叫影片模型；靜態模式只用圖片、配音與字幕合成。</FieldNote>}>
            <Select value={settings.providers.video.defaultMode} onChange={(event) => update("providers.video.defaultMode", event.target.value)}>
              <option value="ai-motion">AI 動態影片</option>
              <option value="static">靜態圖片合成</option>
            </Select>
          </Field>
          <Field label="預設動態風格" note={<FieldNote impact="medium">會影響 image-to-video 的動作幅度與畫面運動方向。</FieldNote>}>
            <Select value={settings.providers.video.motionStyle} onChange={(event) => update("providers.video.motionStyle", event.target.value)}>
              <option value="subtle">輕微動態</option>
              <option value="product-demo">產品展示</option>
              <option value="scene-action">情境動作</option>
              <option value="dramatic">戲劇化</option>
            </Select>
          </Field>
          <Field label="單段動態秒數" note={<FieldNote impact="medium">影響每張分鏡生成影片的長度，會影響總影片節奏與成本。</FieldNote>}>
            <Input type="number" min="3" max="10" value={settings.providers.video.clipDurationSec} onChange={(event) => update("providers.video.clipDurationSec", Number(event.target.value))} />
          </Field>
          <Field label="Kling mode" note={<FieldNote impact="medium">Kling 專用參數，影響生成模式；填錯可能導致影片任務失敗。</FieldNote>}>
            <Input value={settings.providers.video.klingMode} onChange={(event) => update("providers.video.klingMode", event.target.value)} />
          </Field>
          <Field label="Kling cfg scale" note={<FieldNote impact="medium">影響 Kling 對提示詞的遵循程度；太高或太低都可能讓畫面不穩。</FieldNote>}>
            <Input type="number" step="0.1" value={settings.providers.video.klingCfgScale} onChange={(event) => update("providers.video.klingCfgScale", Number(event.target.value))} />
          </Field>
          <Field label="輪詢間隔 ms" note={<FieldNote impact="none">只影響系統多久查一次任務狀態，不影響 AI 生成內容。</FieldNote>}>
            <Input type="number" value={settings.providers.video.pollIntervalMs} onChange={(event) => update("providers.video.pollIntervalMs", Number(event.target.value))} />
          </Field>
          <Field label="等待逾時 ms" note={<FieldNote impact="none">只影響任務等待多久宣告失敗，不影響 AI 生成內容。</FieldNote>}>
            <Input type="number" value={settings.providers.video.timeoutMs} onChange={(event) => update("providers.video.timeoutMs", Number(event.target.value))} />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><ToggleLeft className="h-5 w-5" />工作流程開關</CardTitle>
          <CardDescription>這些開關控制系統是否自動進行下一步，通常不改變 AI 對產品的理解。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          <CheckField label="自動生成分鏡圖" note="部分影響：會讓流程自動產生分鏡圖，但不改變腳本內容。" checked={settings.workflow.autoGenerateStoryboard} onChange={(value) => update("workflow.autoGenerateStoryboard", value)} />
          <CheckField label="自動生成配音" note="不影響 AI 判讀：只影響是否自動產生 voiceover 音檔。" checked={settings.workflow.autoGenerateVoiceover} onChange={(value) => update("workflow.autoGenerateVoiceover", value)} />
          <CheckField label="手動上傳分鏡優先保留" note="部分影響：會讓影片合成優先使用你上傳的分鏡圖。" checked={settings.workflow.keepUploadedStoryboardLocked} onChange={(value) => update("workflow.keepUploadedStoryboardLocked", value)} />
          <CheckField label="允許外部影片上傳" note="不影響 AI 判讀：只控制是否允許上傳外部素材。" checked={settings.workflow.allowExternalVideoUpload} onChange={(value) => update("workflow.allowExternalVideoUpload", value)} />
          <CheckField label="生成即夢提示詞" note="部分影響：會額外輸出給外部 AI 平台看的提示詞。" checked={settings.workflow.generateJimengPrompts} onChange={(value) => update("workflow.generateJimengPrompts", value)} />
          <CheckField label="顯示成本估算" note="不影響 AI 判讀：只控制 UI 是否顯示成本資訊。" checked={settings.workflow.showCostEstimate} onChange={(value) => update("workflow.showCostEstimate", value)} />
          <Field label="預設分鏡張數" note={<FieldNote impact="medium">會影響影片腳本拆成幾個畫面，也會影響分鏡圖與影片生成成本。</FieldNote>}>
            <Input type="number" min="1" max="8" value={settings.workflow.maxStoryboardFrames} onChange={(event) => update("workflow.maxStoryboardFrames", Number(event.target.value))} />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><SlidersHorizontal className="h-5 w-5" />輸出格式與外部平台</CardTitle>
          <CardDescription>這些欄位多半影響輸出格式，不一定改變 AI 對產品本身的判讀。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label="預設影片比例" note={<FieldNote impact="medium">影響分鏡構圖、字幕安全區與合成影片比例。</FieldNote>}>
            <Select value={settings.output.defaultAspectRatio} onChange={(event) => update("output.defaultAspectRatio", event.target.value)}>
              {(options.aspectRatios || []).map((item) => <option key={item} value={item}>{item}</option>)}
            </Select>
          </Field>
          <Field label="預設字幕樣式" note={<FieldNote impact="none">只影響影片合成時字幕外觀，不影響 AI 腳本內容。</FieldNote>}>
            <Select value={settings.output.subtitleStyle} onChange={(event) => update("output.subtitleStyle", event.target.value)}>
              {(options.subtitleStyles || []).map((item) => <option key={item} value={item}>{subtitleStyleLabel(item)}</option>)}
            </Select>
          </Field>
          <Field label="靜態圖片停留秒數" note={<FieldNote impact="none">只影響 FFmpeg 靜態合成影片節奏，不影響 AI 文案判讀。</FieldNote>}>
            <Input type="number" min="1" max="10" value={settings.output.secondsPerImage} onChange={(event) => update("output.secondsPerImage", Number(event.target.value))} />
          </Field>
          <Field label="即夢提示詞語言" note={<FieldNote impact="medium">影響外部平台提示詞語言，不影響本系統的產品分析內容。</FieldNote>}>
            <Select value={settings.externalPlatforms.jimeng.defaultPromptLanguage} onChange={(event) => update("externalPlatforms.jimeng.defaultPromptLanguage", event.target.value)}>
              <option value="both">中文 + 英文</option>
              <option value="zh">中文</option>
              <option value="en">英文</option>
            </Select>
          </Field>
          <PlatformCard label="即夢 AI" enabled={settings.externalPlatforms.jimeng.enabled} notes={settings.externalPlatforms.jimeng.notes} onEnabled={(value) => update("externalPlatforms.jimeng.enabled", value)} onNotes={(value) => update("externalPlatforms.jimeng.notes", value)} />
          <PlatformCard label="Kling" enabled={settings.externalPlatforms.kling.enabled} notes={settings.externalPlatforms.kling.notes} onEnabled={(value) => update("externalPlatforms.kling.enabled", value)} onNotes={(value) => update("externalPlatforms.kling.notes", value)} />
          <PlatformCard label="Runway" enabled={settings.externalPlatforms.runway.enabled} notes={settings.externalPlatforms.runway.notes} onEnabled={(value) => update("externalPlatforms.runway.enabled", value)} onNotes={(value) => update("externalPlatforms.runway.notes", value)} />
          <PlatformCard label="Google Veo" enabled={settings.externalPlatforms.veo.enabled} notes={settings.externalPlatforms.veo.notes} onEnabled={(value) => update("externalPlatforms.veo.enabled", value)} onNotes={(value) => update("externalPlatforms.veo.notes", value)} />
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, note, children }: { label: string; note?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      {children}
      {note}
    </div>
  );
}

function ComboInput({
  value,
  options,
  onChange
}: {
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <Input value={value} onChange={(event) => onChange(event.target.value)} />
      <Select value={options.includes(value) ? value : ""} onChange={(event) => event.target.value && onChange(event.target.value)}>
        <option value="">選擇常用模型</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </Select>
    </div>
  );
}

function CheckField({
  label,
  note,
  checked,
  onChange
}: {
  label: string;
  note: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="grid gap-2 rounded-md border bg-white px-3 py-3 text-sm">
      <span className="flex items-center justify-between gap-3">
        <span>{label}</span>
        <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      </span>
      <span className="text-xs leading-5 text-muted-foreground">{note}</span>
    </label>
  );
}

function PlatformCard({
  label,
  enabled,
  notes,
  onEnabled,
  onNotes
}: {
  label: string;
  enabled: boolean;
  notes: string;
  onEnabled: (value: boolean) => void;
  onNotes: (value: string) => void;
}) {
  return (
    <div className="grid gap-3 rounded-md border bg-white p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{label}</span>
        <Badge>{enabled ? "啟用" : "停用"}</Badge>
      </div>
      <CheckField label="允許使用" note="不影響 AI 判讀：只控制是否顯示或允許使用這個外部平台。" checked={enabled} onChange={onEnabled} />
      <Field label="平台備註" note={<FieldNote impact="none">只給團隊查看，不會送進生成 Prompt。</FieldNote>}>
        <Textarea value={notes} onChange={(event) => onNotes(event.target.value)} />
      </Field>
    </div>
  );
}

function videoProviderLabel(value: string) {
  const labels: Record<string, string> = {
    kling: "Kling API",
    jimeng_manual: "即夢 AI 手動流程",
    runway: "Runway API 預留",
    veo: "Google Veo API 預留",
    heygen: "HeyGen API 預留",
    fal: "Fal API 預留"
  };
  return labels[value] || value;
}

function subtitleStyleLabel(value: string) {
  const labels: Record<string, string> = {
    default: "預設字幕",
    bold: "粗體醒目",
    clean: "乾淨簡潔",
    "bottom-heavy": "底部重點字幕"
  };
  return labels[value] || value;
}
