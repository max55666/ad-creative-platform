import { ArrowLeft, ExternalLink, Search } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CompetitorReport } from "@/components/competitor-report";
import { RegenerateCompetitorAnalysisButton } from "@/components/regenerate-competitor-analysis-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { formatDate } from "@/lib/utils";

type Params = {
  params: Promise<{ id: string }>;
};

export const dynamic = "force-dynamic";

export default async function CompetitorDetailPage({ params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const competitor = await prisma.competitor.findFirst({
    where: { id, userId: user.id },
    include: {
      brand: true,
      project: true,
      analyses: { orderBy: { createdAt: "desc" } }
    }
  });

  if (!competitor) notFound();

  const latest = competitor.analyses[0];

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <Button asChild variant="ghost" size="sm" className="-ml-3 mb-2">
            <Link href="/competitors">
              <ArrowLeft className="h-4 w-4" />
              回競品情報中心
            </Link>
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-normal">{competitor.name}</h1>
            {competitor.industry ? <Badge>{competitor.industry}</Badge> : null}
            {competitor.targetMarket ? <Badge>{competitor.targetMarket}</Badge> : null}
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {competitor.description || "競品資料會結合手動補充、商品頁擷取、品牌與產品上下文進行分析。"}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {competitor.websiteUrl ? (
            <Button asChild variant="outline">
              <Link href={competitor.websiteUrl} target="_blank">
                <ExternalLink className="h-4 w-4" />
                官網
              </Link>
            </Button>
          ) : null}
          {competitor.productUrl ? (
            <Button asChild variant="outline">
              <Link href={competitor.productUrl} target="_blank">
                <ExternalLink className="h-4 w-4" />
                商品頁
              </Link>
            </Button>
          ) : null}
          <RegenerateCompetitorAnalysisButton competitorId={competitor.id} />
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <Metric label="分析次數" value={competitor.analyses.length.toString()} />
        <Metric label="對應品牌" value={competitor.brand?.name || "未指定"} />
        <Metric label="對應產品" value={competitor.project?.productName || "未指定"} />
        <Metric label="最新分析" value={latest ? formatDate(latest.createdAt) : "尚未分析"} />
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            資料來源
          </CardTitle>
          <CardDescription>這些欄位會影響 AI 判讀；資訊越完整，競品拆解越能貼近實際市場。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm md:grid-cols-2">
          <Info label="官網" value={competitor.websiteUrl} />
          <Info label="商品頁" value={competitor.productUrl} />
          <Info label="價格帶" value={competitor.priceRange} />
          <Info label="標籤" value={Array.isArray(competitor.tags) ? competitor.tags.join(", ") : ""} />
        </CardContent>
      </Card>

      <CompetitorReport analysis={latest} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-2 text-lg font-semibold">{value}</p>
      </CardContent>
    </Card>
  );
}

function Info({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-md border bg-white px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 break-words">{value || "未提供"}</p>
    </div>
  );
}
