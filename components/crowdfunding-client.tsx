"use client";

import { FileSearch, Loader2, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { FieldNote } from "@/components/field-note";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

export function CrowdfundingClient({
  projectId,
  initialCases,
  initialPlans
}: {
  projectId: string;
  initialCases: any[];
  initialPlans: any[];
}) {
  const [cases, setCases] = useState<any[]>(initialCases || []);
  const [plans, setPlans] = useState<any[]>(initialPlans || []);
  const [sourceUrl, setSourceUrl] = useState("");
  const [caseTitle, setCaseTitle] = useState("");
  const [caseNotes, setCaseNotes] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState(cases[0]?.id || "");
  const [mode, setMode] = useState(cases[0]?.id ? "benchmark_case" : "from_product");
  const [objective, setObjective] = useState("募資轉換");
  const [tone, setTone] = useState("台灣嘖嘖募資語氣，清楚、可信、有畫面感");
  const [loadingCase, setLoadingCase] = useState(false);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [message, setMessage] = useState("");

  const selectedCase = useMemo(() => cases.find((item) => item.id === selectedCaseId), [cases, selectedCaseId]);

  async function analyzeCase() {
    setLoadingCase(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/crowdfunding/cases`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sourceUrl, title: caseTitle, notes: caseNotes })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "案例拆解失敗");
      setCases((current) => [data.analysis, ...current]);
      setSelectedCaseId(data.analysis.id);
      setMode("benchmark_case");
      setMessage("案例拆解完成，可以套用到我方產品。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "案例拆解失敗");
    } finally {
      setLoadingCase(false);
    }
  }

  async function generatePlan() {
    setLoadingPlan(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/crowdfunding/plans`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          caseAnalysisId: mode === "from_product" ? "" : selectedCaseId,
          mode,
          objective,
          tone,
          targetPlatform: "zeczec"
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "募資頁規劃生成失敗");
      setPlans((current) => [data.plan, ...current]);
      setMessage("募資頁規劃已生成。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "募資頁規劃生成失敗");
    } finally {
      setLoadingPlan(false);
    }
  }

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>嘖嘖募資頁規劃</CardTitle>
          <CardDescription>
            拆解嘖嘖案例，或直接根據目前產品產生募資頁架構、頁面圖需求、文案與轉換評分。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {message ? <p className="rounded-md border bg-muted/50 px-3 py-2 text-sm">{message}</p> : null}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="grid gap-3 rounded-lg border bg-white p-4">
              <div>
                <h3 className="font-medium">1. 拆解嘖嘖案例</h3>
                <p className="mt-1 text-sm text-muted-foreground">貼上成功案例網址，AI 會拆頁面結構、圖片策略、文案公式與可複製模板。</p>
              </div>
              <Field label="嘖嘖案例網址" note={<FieldNote impact="high">若 Playwright 擷取成功，會影響 AI 對頁面段落、圖片與文案的判讀。</FieldNote>}>
                <Input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://www.zeczec.com/projects/..." />
              </Field>
              <Field label="案例名稱" note={<FieldNote impact="medium">方便之後辨識案例，不會大幅影響 AI 判讀。</FieldNote>}>
                <Input value={caseTitle} onChange={(event) => setCaseTitle(event.target.value)} placeholder="例如：某某智慧產品募資頁" />
              </Field>
              <Field label="你觀察到的重點" note={<FieldNote impact="high">會影響 AI 拆解方向，例如你想學它的首屏、方案、圖片風格或痛點鋪陳。</FieldNote>}>
                <Textarea value={caseNotes} onChange={(event) => setCaseNotes(event.target.value)} placeholder="例如：我想學它的首屏情境圖、痛點段落與方案呈現方式" />
              </Field>
              <Button type="button" onClick={analyzeCase} disabled={loadingCase || (!sourceUrl.trim() && !caseNotes.trim())}>
                {loadingCase ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
                拆解案例
              </Button>
            </div>

            <div className="grid gap-3 rounded-lg border bg-white p-4">
              <div>
                <h3 className="font-medium">2. 生成我方募資頁</h3>
                <p className="mt-1 text-sm text-muted-foreground">可直接從產品生成，也可對標案例產生相似說服架構。</p>
              </div>
              <Field label="生成模式" note={<FieldNote impact="high">會決定是否套用案例的頁面節奏與模板。</FieldNote>}>
                <Select value={mode} onChange={(event) => setMode(event.target.value)}>
                  <option value="from_product">從產品直接生成</option>
                  <option value="benchmark_case">套用單一案例</option>
                  <option value="hybrid">混合產品與案例邏輯</option>
                </Select>
              </Field>
              <Field label="對標案例" note={<FieldNote impact="high">選擇後會保留案例說服邏輯，但改寫為我方產品。</FieldNote>}>
                <Select value={selectedCaseId} onChange={(event) => setSelectedCaseId(event.target.value)} disabled={!cases.length || mode === "from_product"}>
                  <option value="">不指定</option>
                  {cases.map((item) => <option key={item.id} value={item.id}>{item.title || item.sourceUrl || item.id}</option>)}
                </Select>
              </Field>
              <Field label="活動目標" note={<FieldNote impact="high">會影響 CTA、頁面段落與方案策略。</FieldNote>}>
                <Input value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="募資轉換 / 新品上市 / 高單價說服" />
              </Field>
              <Field label="頁面語氣" note={<FieldNote impact="medium">會影響文案風格與設計描述。</FieldNote>}>
                <Input value={tone} onChange={(event) => setTone(event.target.value)} />
              </Field>
              <Button type="button" onClick={generatePlan} disabled={loadingPlan || (mode !== "from_product" && !selectedCaseId)}>
                {loadingPlan ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                生成募資頁規劃
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {selectedCase ? <CaseAnalysisCard item={selectedCase} /> : null}

      <div className="grid gap-4">
        {plans.map((plan) => <PagePlanCard key={plan.id} plan={plan} />)}
        {!plans.length ? (
          <Card>
            <CardHeader>
              <CardTitle>尚未產生募資頁規劃</CardTitle>
              <CardDescription>先按「生成募資頁規劃」，系統會建立完整段落、圖片需求與文案。</CardDescription>
            </CardHeader>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

function CaseAnalysisCard({ item }: { item: any }) {
  const raw = item.rawOutput || {};
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>案例拆解：{item.title || raw.summary?.caseName || "未命名案例"}</CardTitle>
            <CardDescription>{item.sourceUrl || "手動輸入案例"}</CardDescription>
          </div>
          <CopyButton value={JSON.stringify(raw || item, null, 2)} label="複製案例拆解" />
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-3">
        <MiniBlock title="頁面節奏" value={item.structure?.pageRhythm || raw.structure?.pageRhythm} />
        <MiniList title="可複製段落" values={item.reusableTemplate?.pageBlueprint || raw.reusableTemplate?.pageBlueprint} />
        <MiniList title="不要照抄" values={item.reusableTemplate?.doNotCopy || raw.reusableTemplate?.doNotCopy} />
      </CardContent>
    </Card>
  );
}

function PagePlanCard({ plan }: { plan: any }) {
  const raw = plan.rawOutput || {};
  const strategy = raw.strategy || {};
  const score = plan.conversionScore || raw.conversionScore || {};
  const sections = Array.isArray(plan.pageSections) ? plan.pageSections : [];
  const imageBriefs = Array.isArray(plan.imageBriefs) ? plan.imageBriefs : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>{plan.title}</CardTitle>
              <Badge>{plan.targetPlatform || "zeczec"}</Badge>
              <Badge className="bg-white">AI 預測，僅供參考</Badge>
            </div>
            <CardDescription className="mt-2">{strategy.bigIdea || strategy.coreMessage || "募資頁架構與素材規劃"}</CardDescription>
          </div>
          <CopyButton value={JSON.stringify(raw || plan, null, 2)} label="複製完整企劃" />
        </div>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-3 lg:grid-cols-3">
          <MiniBlock title="首屏標題" value={plan.hero?.headline} />
          <MiniBlock title="核心訊息" value={strategy.coreMessage} />
          <MiniBlock title="轉換分數" value={score.totalScore ? `${score.totalScore} / 100` : "尚未評分"} />
        </div>

        <section className="grid gap-3">
          <h3 className="font-medium">頁面段落架構</h3>
          <div className="grid gap-3">
            {sections.map((section: any, index: number) => (
              <div key={`${section.sectionName}-${index}`} className="rounded-lg border bg-white p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{section.order || index + 1}</Badge>
                  <p className="font-medium">{section.sectionName}</p>
                </div>
                <p className="mt-2 text-sm font-medium">{section.headline}</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">{section.body}</p>
                <div className="mt-3 grid gap-2 text-sm md:grid-cols-2">
                  <MiniBlock title="段落目的" value={section.purpose} />
                  <MiniBlock title="圖片需求" value={section.visualBrief} />
                </div>
                {section.imagePrompt ? (
                  <div className="mt-3">
                    <CopyButton value={section.imagePrompt} label="複製圖片 Prompt" />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <section className="grid gap-3">
          <h3 className="font-medium">頁面圖需求</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {imageBriefs.map((brief: any, index: number) => (
              <div key={`${brief.assetName}-${index}`} className="rounded-lg border bg-white p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium">{brief.assetName}</p>
                  <Badge>{brief.priority || "medium"}</Badge>
                  <Badge className="bg-white">{brief.ratio || "long-page"}</Badge>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{brief.purpose}</p>
                <p className="mt-2 text-sm leading-6">{brief.composition}</p>
                {brief.mainCopy ? <p className="mt-2 rounded-md bg-muted/60 p-2 text-sm">字卡：{brief.mainCopy}</p> : null}
                {brief.prompt ? <div className="mt-3"><CopyButton value={brief.prompt} label="複製生圖 Prompt" /></div> : null}
              </div>
            ))}
          </div>
        </section>

        <section className="grid gap-3">
          <h3 className="font-medium">修改建議</h3>
          <MiniList title="優點" values={score.strengths} />
          <MiniList title="缺點" values={score.weaknesses} />
          <MiniList title="建議" values={score.suggestions} />
        </section>
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

function MiniBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <p className="mt-1 text-sm leading-6">{formatValue(value)}</p>
    </div>
  );
}

function MiniList({ title, values }: { title: string; values: unknown }) {
  const list = Array.isArray(values) ? values.map(String) : values ? [String(values)] : [];
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      {list.length ? (
        <ul className="mt-2 grid gap-1 text-sm leading-6">
          {list.map((item, index) => <li key={`${item}-${index}`}>- {item}</li>)}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">尚未提供</p>
      )}
    </div>
  );
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "尚未提供";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}
