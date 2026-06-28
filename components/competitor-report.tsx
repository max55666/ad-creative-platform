import { CopyButton } from "@/components/copy-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ReactNode } from "react";

type CompetitorAnalysisView = {
  summary: unknown;
  positioning: unknown;
  productOffer: unknown;
  audience: unknown;
  messaging: unknown;
  landingPage: unknown;
  creativeAngles: unknown;
  opportunities: unknown;
  risks: unknown;
  rawOutput?: unknown;
  createdAt?: Date | string;
};

export function CompetitorReport({ analysis }: { analysis?: CompetitorAnalysisView | null }) {
  if (!analysis) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>尚未有競品分析</CardTitle>
          <CardDescription>按下重新分析後，系統會擷取競品頁面並產生可用於廣告策略的拆解。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const raw = asRecord(analysis.rawOutput);
  const data = asRecord(raw.data);
  const report = Object.keys(data).length
    ? data
    : {
        summary: analysis.summary,
        positioning: analysis.positioning,
        productOffer: analysis.productOffer,
        audience: analysis.audience,
        messaging: analysis.messaging,
        landingPage: analysis.landingPage,
        creativeAngles: analysis.creativeAngles,
        opportunities: analysis.opportunities,
        risks: analysis.risks
      };
  const reportText = JSON.stringify(report, null, 2);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>競品情報報告</CardTitle>
            <CardDescription>定位、受眾、訊息、頁面結構、素材角度與反打機會。</CardDescription>
          </div>
          <CopyButton value={reportText} label="複製完整報告" />
        </CardHeader>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <InfoCard title="1. 競品摘要">
          <KeyValue label="一句話" value={asRecord(report.summary).oneLine} />
          <KeyValue label="品類" value={asRecord(report.summary).category} />
          <KeyValue label="強度" value={asRecord(report.summary).strengthLevel} />
          <List title="判讀假設" value={asRecord(report.summary).assumptions} />
        </InfoCard>

        <InfoCard title="2. 市場定位">
          <KeyValue label="定位" value={asRecord(report.positioning).marketPosition} />
          <List title="主張" value={asRecord(report.positioning).mainClaims} />
          <List title="差異點" value={asRecord(report.positioning).differentiators} />
          <KeyValue label="語氣" value={asRecord(report.positioning).brandTone} />
          <KeyValue label="視覺風格" value={asRecord(report.positioning).visualStyle} />
        </InfoCard>

        <InfoCard title="3. 商品與 Offer">
          <List title="商品組合" value={asRecord(report.productOffer).products} />
          <KeyValue label="價格訊號" value={asRecord(report.productOffer).priceSignals} />
          <List title="信任證據" value={asRecord(report.productOffer).proofPoints} />
          <List title="購買阻力" value={asRecord(report.productOffer).frictions} />
        </InfoCard>

        <InfoCard title="4. 可能受眾">
          <KeyValue label="主要受眾" value={asRecord(report.audience).likelyAudience} />
          <KeyValue label="次要受眾" value={asRecord(report.audience).secondaryAudience} />
          <List title="購買動機" value={asRecord(report.audience).motivations} />
          <List title="購買疑慮" value={asRecord(report.audience).barriers} />
          <List title="興趣標籤" value={asRecord(report.audience).interestTags} />
        </InfoCard>

        <InfoCard title="5. 訊息與 Hook">
          <List title="Hook" value={asRecord(report.messaging).hooks} />
          <List title="CTA 模式" value={asRecord(report.messaging).ctaPatterns} />
          <List title="文案模式" value={asRecord(report.messaging).copyPatterns} />
          <List title="情緒觸發" value={asRecord(report.messaging).emotionalTriggers} />
        </InfoCard>

        <InfoCard title="6. Landing Page">
          <List title="頁面結構" value={asRecord(report.landingPage).structure} />
          <KeyValue label="首屏訊息" value={asRecord(report.landingPage).aboveTheFold} />
          <List title="信任元素" value={asRecord(report.landingPage).trustElements} />
          <List title="弱點" value={asRecord(report.landingPage).weaknesses} />
        </InfoCard>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>7. 可借鏡與反打角度</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          {toArray(report.creativeAngles).map((angle, index) => {
            const item = asRecord(angle);
            return (
              <div key={index} className="rounded-md border bg-white p-4">
                <p className="font-medium">{formatValue(item.angle) || `角度 ${index + 1}`}</p>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{formatValue(item.whyItWorks)}</p>
                <p className="mt-3 text-sm">Hook：{formatValue(item.exampleHook)}</p>
                <p className="mt-2 text-xs text-muted-foreground">風險：{formatValue(item.risk)}</p>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <InfoCard title="8. 我方機會">
          <List title="市場空白" value={asRecord(report.opportunities).whiteSpace} />
          <List title="反打訊息" value={asRecord(report.opportunities).counterMessages} />
          <List title="建議測試" value={asRecord(report.opportunities).testsToRun} />
        </InfoCard>

        <InfoCard title="9. 風險與不要複製">
          <List title="不要直接抄" value={asRecord(report.risks).doNotCopy} />
          <List title="法務與品牌風險" value={asRecord(report.risks).legalOrBrandRisks} />
          <List title="資料缺口" value={asRecord(report.risks).dataGaps} />
        </InfoCard>
      </div>
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
