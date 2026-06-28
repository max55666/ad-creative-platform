import Link from "next/link";
import { AlertCircle, ArrowRight, CheckCircle2, Copy, Lightbulb, Target, Users } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type AnalysisReportProps = {
  projectId: string;
  analysis: any;
};

export function AnalysisReport({ projectId, analysis }: AnalysisReportProps) {
  const summary = asObject(analysis.summary);
  const audience = asObject(analysis.audienceAnalysis);
  const painPoints = asObject(analysis.painPoints);
  const sellingPoints = asObject(analysis.sellingPoints);
  const adAngles = asArray(analysis.adAngles);
  const nextSteps = asArray(analysis.nextSteps);
  const rawOutput = asObject(analysis.rawOutput);
  const fullReport = {
    productSummary: summary,
    targetAudience: audience,
    painPoints,
    sellingPoints,
    adAngles,
    nextSteps
  };
  const source = rawOutput.source === "openai" ? "OpenAI 分析" : "本機草稿";
  const warning = typeof rawOutput.warning === "string" ? rawOutput.warning : null;
  const primaryAudience = asObject(audience.primary);
  const secondaryAudiences = asArray(audience.secondary);

  return (
    <div className="grid gap-5">
      <section className="rounded-lg border bg-white p-5 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Badge className={rawOutput.source === "openai" ? "border-primary/30 bg-primary/10 text-primary" : "border-amber-300 bg-amber-50 text-amber-800"}>
                {source}
              </Badge>
              {warning ? (
                <Badge className="border-amber-300 bg-amber-50 text-amber-800">
                  使用備援內容
                </Badge>
              ) : null}
            </div>
            <h2 className="text-2xl font-semibold tracking-normal">
              {text(summary.oneLine, "此產品適合用明確痛點、真實場景與可視化成果來溝通。")}
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {text(summary.positioning, "建議補齊產品資訊後，持續測試不同受眾、素材角度與短影音 Hook。")}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <CopyButton value={JSON.stringify(fullReport, null, 2)} label="複製完整報告" />
            <Button asChild>
              <Link href={`/projects/${projectId}/static-creatives`}>
                產生素材
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>

        {warning ? (
          <div className="mt-4 flex gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>AI 分析改用本機草稿。原因：{warning}</p>
          </div>
        ) : null}

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          <MiniFact label="產品類別" value={text(summary.category, "待確認")} />
          <MiniFact label="主要受眾" value={text(primaryAudience.name, "待確認")} />
          <MiniFact label="年齡層" value={text(primaryAudience.ageRange, "待確認")} />
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-4 w-4 text-primary" />
              目標受眾
            </CardTitle>
            <CardDescription>用於判斷素材語氣、平台、腳本情境與投放受眾標籤。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <AudienceBlock title="主要受眾" audience={primaryAudience} />
            {secondaryAudiences.length ? (
              <div className="grid gap-3">
                {secondaryAudiences.map((item, index) => (
                  <AudienceBlock key={index} title={`次要受眾 ${index + 1}`} audience={asObject(item)} compact />
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Target className="h-4 w-4 text-primary" />
              消費者痛點
            </CardTitle>
            <CardDescription>素材應先讓受眾感覺「這就是我的問題」，再帶出產品解法。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <ListBlock title="功能痛點" items={painPoints.functional} />
            <ListBlock title="情緒痛點" items={painPoints.emotional} />
            <ListBlock title="場景痛點" items={painPoints.scenario} />
            <ListBlock title="購買疑慮" items={painPoints.decisionBarriers} />
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-primary" />
            核心賣點
          </CardTitle>
          <CardDescription>將功能、情緒與場景賣點拆開，方便後續生成平面素材與影片腳本。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <ListBlock title="核心賣點" items={sellingPoints.core} emphasize />
          <ListBlock title="功能型賣點" items={sellingPoints.functional} />
          <ListBlock title="情緒型賣點" items={sellingPoints.emotional} />
          <ListBlock title="場景型賣點" items={sellingPoints.scenario} />
          <ListBlock title="競品差異" items={sellingPoints.competitorDifferences} />
          <ListBlock title="不適合主打" items={sellingPoints.avoidClaims} tone="warning" />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>素材角度矩陣</CardTitle>
          <CardDescription>可作為平面素材、短影音 Hook 與投放 A/B 測試的起點。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-auto rounded-md border bg-white">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead className="bg-muted text-left text-xs text-muted-foreground">
                <tr>
                  <th className="p-3">角度</th>
                  <th className="p-3">適合受眾</th>
                  <th className="p-3">溝通訊息</th>
                  <th className="p-3">風險</th>
                </tr>
              </thead>
              <tbody>
                {adAngles.length ? (
                  adAngles.map((item, index) => {
                    const angle = asObject(item);
                    return (
                      <tr key={index} className="border-t align-top">
                        <td className="p-3 font-medium">{text(angle.angle, `角度 ${index + 1}`)}</td>
                        <td className="p-3">{text(angle.audience, "未提供")}</td>
                        <td className="p-3 leading-6">{text(angle.message, "未提供")}</td>
                        <td className="p-3 text-muted-foreground">{text(angle.risk, "無")}</td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td className="p-4 text-muted-foreground" colSpan={4}>
                      尚未產生素材角度。
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <CardHeader>
            <CardTitle>下一步執行建議</CardTitle>
            <CardDescription>建議先完成這些素材與資料補強，再進入大量生成。</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="grid gap-3">
              {nextSteps.length ? (
                nextSteps.map((item, index) => (
                  <li key={index} className="flex gap-3 rounded-md border bg-white p-3 text-sm leading-6">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <span>{text(item, "")}</span>
                  </li>
                ))
              ) : (
                <li className="text-sm text-muted-foreground">尚未產生下一步建議。</li>
              )}
            </ol>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>原始資料</CardTitle>
            <CardDescription>供除錯或與其他工具串接使用。</CardDescription>
          </CardHeader>
          <CardContent>
            <details className="rounded-md border bg-muted/60 p-3">
              <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                <Copy className="h-4 w-4" />
                查看 JSON
              </summary>
              <pre className="mt-3 max-h-[280px] overflow-auto rounded-md bg-white p-3 text-xs leading-6">
                {JSON.stringify(fullReport, null, 2)}
              </pre>
            </details>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function MiniFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-muted/45 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-medium">{value}</p>
    </div>
  );
}

function AudienceBlock({
  title,
  audience,
  compact
}: {
  title: string;
  audience: Record<string, unknown>;
  compact?: boolean;
}) {
  return (
    <div className="rounded-md border bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{title}</Badge>
        <p className="font-medium">{text(audience.name, "待確認受眾")}</p>
      </div>
      <div className="mt-3 grid gap-2 text-sm text-muted-foreground sm:grid-cols-3">
        <p><span className="font-medium text-foreground">年齡：</span>{text(audience.ageRange, "未提供")}</p>
        <p><span className="font-medium text-foreground">性別：</span>{text(audience.genderSkew, "未提供")}</p>
        <p><span className="font-medium text-foreground">消費力：</span>{text(audience.incomePower, "未提供")}</p>
      </div>
      {!compact ? (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <ListBlock title="使用情境" items={audience.useCases} />
          <ListBlock title="購買動機" items={audience.purchaseMotivations} />
          <ListBlock title="購買疑慮" items={audience.purchaseBarriers} />
          <ListBlock title="興趣標籤" items={audience.interestTags} tag />
        </div>
      ) : null}
    </div>
  );
}

function ListBlock({
  title,
  items,
  emphasize,
  tag,
  tone
}: {
  title: string;
  items: unknown;
  emphasize?: boolean;
  tag?: boolean;
  tone?: "warning";
}) {
  const values = asArray(items).map((item) => text(item, "")).filter(Boolean);

  return (
    <div>
      <p className="mb-2 text-xs font-medium text-muted-foreground">{title}</p>
      {values.length ? (
        tag ? (
          <div className="flex flex-wrap gap-2">
            {values.map((value, index) => (
              <Badge key={`${value}-${index}`}>{value}</Badge>
            ))}
          </div>
        ) : (
          <ul className="grid gap-2">
            {values.map((value, index) => (
              <li
                key={`${value}-${index}`}
                className={
                  tone === "warning"
                    ? "rounded-md border border-amber-200 bg-amber-50 p-2 text-sm leading-6 text-amber-900"
                    : emphasize
                      ? "rounded-md border border-primary/20 bg-primary/5 p-2 text-sm font-medium leading-6"
                      : "rounded-md bg-muted/60 p-2 text-sm leading-6"
                }
              >
                {value}
              </li>
            ))}
          </ul>
        )
      ) : (
        <p className="rounded-md bg-muted/60 p-2 text-sm text-muted-foreground">未提供</p>
      )}
    </div>
  );
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : value == null ? [] : [value];
}

function text(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return fallback;
}
