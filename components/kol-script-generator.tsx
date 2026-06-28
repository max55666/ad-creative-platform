"use client";

import { Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, ReactNode, useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { FieldNote } from "@/components/field-note";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

type ProjectOption = {
  id: string;
  productName: string;
};

type KolScriptView = {
  id?: string;
  title: string;
  platform: string;
  objective: string;
  duration: string;
  hook: string;
  storyline: unknown;
  captions: unknown;
  voiceover: unknown;
  shotList: unknown;
  cta: string;
  adUsageNotes?: unknown;
};

export function KolScriptGenerator({
  profileId,
  projects,
  defaultProjectId
}: {
  profileId: string;
  projects: ProjectOption[];
  defaultProjectId?: string | null;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [scripts, setScripts] = useState<KolScriptView[]>([]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const formData = new FormData(event.currentTarget);
    const payload = {
      projectId: String(formData.get("projectId") || ""),
      platformTarget: String(formData.get("platformTarget") || ""),
      duration: String(formData.get("duration") || ""),
      style: String(formData.get("style") || ""),
      objective: String(formData.get("objective") || "")
    };

    try {
      const response = await fetch(`/api/kols/${profileId}/scripts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "生成 KOL 腳本失敗。");
      setScripts(data.scripts || []);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成 KOL 腳本失敗。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>依指定產品產生 KOL 專屬腳本</CardTitle>
        <CardDescription>把 KOL 人設、粉絲輪廓與產品賣點結合，產生可拍攝且可投放的轉換腳本。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <form className="grid gap-4 lg:grid-cols-[1fr_1fr_1fr_1fr_auto]" onSubmit={handleSubmit}>
          <Field label="產品" note={<FieldNote impact="high">會決定腳本主打賣點、痛點、CTA 與產品露出方式。</FieldNote>}>
            <Select name="projectId" defaultValue={defaultProjectId || projects[0]?.id || ""} required>
              <option value="">選擇產品</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.productName}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="平台" note={<FieldNote impact="high">會影響腳本節奏、字卡密度、開頭 Hook 與 CTA 寫法。</FieldNote>}>
            <Select name="platformTarget" defaultValue="TikTok / Reels">
              <option value="TikTok / Reels">TikTok / Reels</option>
              <option value="Shorts">YouTube Shorts</option>
              <option value="Facebook">Facebook</option>
              <option value="Instagram">Instagram</option>
            </Select>
          </Field>
          <Field label="長度" note={<FieldNote impact="high">會影響分鏡數量、口白長度、賣點數量與 CTA 時機。</FieldNote>}>
            <Select name="duration" defaultValue="30秒">
              <option value="15秒">15秒</option>
              <option value="30秒">30秒</option>
              <option value="60秒">60秒</option>
            </Select>
          </Field>
          <Field label="風格" note={<FieldNote impact="high">會影響 KOL 語氣、劇情結構、Hook 類型與拍攝方式。</FieldNote>}>
            <Select name="style" defaultValue="真實分享">
              <option value="真實分享">真實分享</option>
              <option value="痛點解法">痛點解法</option>
              <option value="開箱實測">開箱實測</option>
              <option value="避坑清單">避坑清單</option>
              <option value="Before / After">Before / After</option>
            </Select>
          </Field>
          <div className="grid content-end">
            <input type="hidden" name="objective" value="導購轉換" />
            <Button type="submit" disabled={loading || projects.length === 0}>
              <Wand2 className="h-4 w-4" />
              {loading ? "生成中..." : "生成腳本"}
            </Button>
          </div>
        </form>

        {projects.length === 0 ? <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">請先建立產品分析專案，才能產生指定產品腳本。</p> : null}
        {error ? <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}

        {scripts.length ? (
          <div className="grid gap-4">
            <p className="text-sm font-medium">本次生成結果</p>
            {scripts.map((script, index) => (
              <KolScriptCard key={script.id || index} script={script} />
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function KolScriptCard({ script }: { script: KolScriptView }) {
  const text = JSON.stringify(script, null, 2);
  return (
    <Card className="shadow-none">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>{script.title}</CardTitle>
          <CardDescription>
            {script.platform} / {script.duration} / {script.objective}
          </CardDescription>
        </div>
        <CopyButton value={text} label="複製腳本" />
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="rounded-md border bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">Hook</p>
          <p className="mt-1 text-sm font-medium">{script.hook}</p>
        </div>
        <MiniTimeline title="分鏡 / 劇情" value={script.storyline} />
        <MiniTimeline title="拍攝鏡頭" value={script.shotList} />
        <MiniTimeline title="字卡" value={script.captions} />
        <MiniTimeline title="口白" value={script.voiceover} />
        <div>
          <p className="text-xs text-muted-foreground">CTA</p>
          <p className="mt-1 text-sm leading-6">{script.cta}</p>
        </div>
      </CardContent>
    </Card>
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

function MiniTimeline({ title, value }: { title: string; value: unknown }) {
  const items = Array.isArray(value) ? value : [];
  if (!items.length) return null;
  return (
    <div>
      <p className="text-xs text-muted-foreground">{title}</p>
      <div className="mt-2 grid gap-2">
        {items.map((item, index) => {
          const record = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
          return (
            <div key={index} className="rounded-md border bg-white p-3 text-sm leading-6">
              {record.time || record.shot ? <p className="font-medium">{String(record.time || record.shot)}</p> : null}
              <p>{formatRecord(record, item)}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatRecord(record: Record<string, unknown>, fallback: unknown) {
  const entries = Object.entries(record).filter(([key]) => key !== "time" && key !== "shot");
  if (!entries.length) return String(fallback || "");
  return entries.map(([key, value]) => `${key}: ${formatValue(value)}`).join(" / ");
}

function formatValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
