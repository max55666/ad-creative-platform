import { CopyButton } from "@/components/copy-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ReactNode } from "react";

type BrandBrainView = {
  summary: unknown;
  positioning: unknown;
  voice: unknown;
  visualIdentity: unknown;
  audience: unknown;
  messaging: unknown;
  guardrails: unknown;
  rawOutput?: unknown;
  createdAt?: Date | string;
};

export function BrandBrainReport({ brain }: { brain?: BrandBrainView | null }) {
  if (!brain) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>尚未建立 Brand Brain</CardTitle>
          <CardDescription>按下重新生成後，系統會整理品牌定位、語氣、視覺規則、受眾與素材檢查清單。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const raw = asRecord(brain.rawOutput);
  const data = asRecord(raw.data);
  const summary = asRecord(data.summary || brain.summary);
  const positioning = asRecord(data.positioning || brain.positioning);
  const voice = asRecord(data.voice || brain.voice);
  const visualIdentity = asRecord(data.visualIdentity || brain.visualIdentity);
  const audience = asRecord(data.audience || brain.audience);
  const messaging = asRecord(data.messaging || brain.messaging);
  const guardrails = asRecord(data.guardrails || brain.guardrails);
  const reportText = JSON.stringify(Object.keys(data).length ? data : brain, null, 2);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Brand Brain</CardTitle>
            <CardDescription>後續素材、Campaign、KOL 腳本會共用這份品牌基準。</CardDescription>
          </div>
          <CopyButton value={reportText} label="複製品牌腦" />
        </CardHeader>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <InfoCard title="品牌摘要">
          <KeyValue label="一句話定位" value={summary.oneLine} />
          <KeyValue label="品牌類別" value={summary.category} />
          <KeyValue label="品牌承諾" value={summary.brandPromise} />
          <KeyValue label="商業角色" value={summary.commercialRole} />
          <List title="推測依據" value={summary.assumptions} />
        </InfoCard>

        <InfoCard title="市場定位">
          <KeyValue label="定位" value={positioning.marketPosition} />
          <KeyValue label="價值主張" value={positioning.valueProposition} />
          <KeyValue label="競品語境" value={positioning.competitorFrame} />
          <List title="差異化" value={positioning.differentiators} />
        </InfoCard>

        <InfoCard title="品牌語氣">
          <List title="個性標籤" value={voice.personality} />
          <KeyValue label="語氣" value={voice.tone} />
          <List title="文案規則" value={voice.copyRules} />
          <List title="適合用字" value={voice.preferredWords} />
          <List title="避免用字" value={voice.avoidWords} />
        </InfoCard>

        <InfoCard title="視覺規則">
          <List title="視覺標籤" value={visualIdentity.styleKeywords} />
          <KeyValue label="色彩方向" value={visualIdentity.colorDirection} />
          <List title="構圖規則" value={visualIdentity.compositionRules} />
          <List title="應該拍什麼" value={visualIdentity.imageDos} />
          <List title="避免什麼畫面" value={visualIdentity.imageDonts} />
        </InfoCard>

        <InfoCard title="受眾">
          <KeyValue label="主要受眾" value={audience.primary} />
          <KeyValue label="次要受眾" value={audience.secondary} />
          <List title="購買動機" value={audience.motivations} />
          <List title="購買疑慮" value={audience.barriers} />
          <List title="興趣標籤" value={audience.interestTags} />
        </InfoCard>

        <InfoCard title="訊息與平台規則">
          <KeyValue label="核心訊息" value={messaging.coreMessage} />
          <List title="輔助訊息" value={messaging.supportingMessages} />
          <List title="證據點" value={messaging.proofPoints} />
          <KeyValue label="平台改寫" value={messaging.platformAdaptation} />
        </InfoCard>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>素材檢查清單與風險</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <List title="宣稱限制" value={guardrails.claimLimits} />
          <List title="品牌安全" value={guardrails.brandSafety} />
          <List title="素材風險" value={guardrails.creativeRisks} />
          <List title="檢查清單" value={guardrails.reviewChecklist} />
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
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  const record = asRecord(value);
  if (Object.keys(record).length) {
    return Object.entries(record)
      .map(([key, item]) => `${key}: ${formatValue(item)}`)
      .join(" / ");
  }
  return String(value);
}
