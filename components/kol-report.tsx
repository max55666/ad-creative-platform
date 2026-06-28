import { CopyButton } from "@/components/copy-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ReactNode } from "react";

type KolAnalysisView = {
  persona: unknown;
  contentStyle: unknown;
  audienceProfile: unknown;
  brandFit: unknown;
  productFit: unknown;
  sponsoredVideoInsights: unknown;
  suitableProducts: unknown;
  riskAssessment: unknown;
  recommendations: unknown;
  rawOutput: unknown;
  createdAt: Date | string;
};

export function KolReport({ analysis }: { analysis?: KolAnalysisView | null }) {
  if (!analysis) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>尚未有 KOL 分析</CardTitle>
          <CardDescription>建立或重新分析後，這裡會顯示 KOL 人設、粉絲輪廓、適合產品與合作風險。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const raw = asRecord(analysis.rawOutput);
  const data = asRecord(raw.data);
  const summary = asRecord(data.kolSummary);
  const persona = asRecord(data.persona || analysis.persona);
  const contentStyle = asRecord(data.contentStyle || analysis.contentStyle);
  const audience = asRecord(data.audienceProfile || analysis.audienceProfile);
  const productFit = asRecord(data.productFit || analysis.productFit);
  const sponsored = asRecord(data.sponsoredVideoInsights || analysis.sponsoredVideoInsights);
  const brandFit = asRecord(data.brandFit || analysis.brandFit);
  const risk = asRecord(data.riskAssessment || analysis.riskAssessment);
  const recommendations = toArray(data.recommendations || analysis.recommendations);
  const fullText = JSON.stringify(data && Object.keys(data).length ? data : analysis, null, 2);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>KOL 分析報告</CardTitle>
            <CardDescription>包含人設定位、粉絲輪廓、業配適配度、風險與下一步建議。</CardDescription>
          </div>
          <CopyButton value={fullText} label="複製報告" />
        </CardHeader>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <InfoCard title="1. KOL 商業定位">
          <KeyValue label="一句話定位" value={summary.oneLine} />
          <KeyValue label="平台角色" value={summary.platformRole} />
          <KeyValue label="商業潛力" value={summary.commercialPotential} />
          <List title="推測依據" value={summary.assumptions} />
        </InfoCard>

        <InfoCard title="2. 人設與信任來源">
          <Pills value={persona.personaTags} />
          <KeyValue label="語氣" value={persona.voiceTone} />
          <KeyValue label="信任來源" value={persona.trustSource} />
          <KeyValue label="粉絲期待" value={persona.contentPromise} />
          <List title="合作風險" value={persona.redFlags} />
        </InfoCard>

        <InfoCard title="3. 內容風格">
          <List title="常見形式" value={contentStyle.formats} />
          <KeyValue label="畫面風格" value={contentStyle.visualStyle} />
          <KeyValue label="剪輯節奏" value={contentStyle.editingPace} />
          <List title="Hook 模式" value={contentStyle.hookPatterns} />
          <List title="CTA 模式" value={contentStyle.ctaPatterns} />
          <KeyValue label="置入方式" value={contentStyle.brandIntegrationStyle} />
        </InfoCard>

        <InfoCard title="4. 粉絲輪廓">
          <KeyValue label="主要粉絲" value={audience.primaryAudience} />
          <KeyValue label="次要粉絲" value={audience.secondaryAudience} />
          <KeyValue label="年齡層" value={audience.ageRange} />
          <KeyValue label="性別傾向" value={audience.genderSkew} />
          <KeyValue label="消費能力" value={audience.incomePower} />
          <List title="興趣" value={audience.interests} />
          <List title="購買觸發" value={audience.purchaseTriggers} />
          <List title="購買疑慮" value={audience.purchaseBarriers} />
        </InfoCard>

        <InfoCard title="5. 指定產品適配度">
          <div className="rounded-md border bg-muted/40 p-3">
            <p className="text-xs text-muted-foreground">適配分數</p>
            <p className="mt-1 text-3xl font-semibold">{String(productFit.score ?? "-")}</p>
          </div>
          <KeyValue label="轉換潛力" value={productFit.conversionPotential} />
          <KeyValue label="推薦合作形式" value={productFit.bestCollaborationFormat} />
          <KeyValue label="白名單投放" value={productFit.adWhitelistingPotential} />
          <List title="適合原因" value={productFit.fitReasons} />
          <List title="風險" value={productFit.risks} />
        </InfoCard>

        <InfoCard title="6. 業配影片洞察">
          <List title="觀察到的模式" value={sponsored.observedPatterns} />
          <List title="適合角度" value={sponsored.bestPerformingAngles} />
          <List title="弱點" value={sponsored.weaknesses} />
          <KeyValue label="業配揭露建議" value={sponsored.recommendedDisclosureStyle} />
        </InfoCard>

        <InfoCard title="7. 合作品牌適合度">
          <List title="適合品牌" value={brandFit.bestBrandTypes} />
          <List title="不建議品牌" value={brandFit.avoidBrandTypes} />
          <List title="合作形式" value={brandFit.collaborationFormats} />
        </InfoCard>

        <InfoCard title="8. 風險控管">
          <KeyValue label="品牌安全性" value={risk.brandSafety} />
          <KeyValue label="訊息落差" value={risk.messageMismatch} />
          <List title="素材風險" value={risk.creativeRisks} />
          <List title="降低風險做法" value={risk.mitigation} />
        </InfoCard>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>下一步建議</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          {recommendations.length ? (
            recommendations.map((item, index) => {
              const recommendation = asRecord(item);
              return (
                <div key={index} className="rounded-md border bg-white p-4">
                  <Badge>{String(recommendation.priority || "medium")}</Badge>
                  <p className="mt-3 text-sm font-medium">{String(recommendation.action || item)}</p>
                  {recommendation.reason ? <p className="mt-2 text-sm leading-6 text-muted-foreground">{String(recommendation.reason)}</p> : null}
                </div>
              );
            })
          ) : (
            <p className="text-sm text-muted-foreground">尚未產生建議。</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function InfoCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">{children}</CardContent>
    </Card>
  );
}

function KeyValue({ label, value }: { label: string; value: unknown }) {
  if (value == null || value === "") return null;
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm leading-6">{formatValue(value)}</p>
    </div>
  );
}

function List({ title, value }: { title: string; value: unknown }) {
  const items = toArray(value);
  if (!items.length) return null;
  return (
    <div>
      <p className="text-xs text-muted-foreground">{title}</p>
      <ul className="mt-2 grid gap-2 text-sm leading-6">
        {items.map((item, index) => (
          <li key={index} className="rounded-md bg-muted/50 px-3 py-2">
            {formatValue(item)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Pills({ value }: { value: unknown }) {
  const items = toArray(value);
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item, index) => (
        <Badge key={index}>
          {formatValue(item)}
        </Badge>
      ))}
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function toArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value == null || value === "") return [];
  return [value];
}

function formatValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  const record = asRecord(value);
  if (Object.keys(record).length) {
    return Object.entries(record)
      .map(([key, item]) => `${key}: ${formatValue(item)}`)
      .join(" / ");
  }
  return String(value);
}
