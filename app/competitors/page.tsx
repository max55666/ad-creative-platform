import { ArrowRight, Search } from "lucide-react";
import Link from "next/link";
import { CompetitorForm } from "@/components/competitor-form";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { formatDate, truncate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function CompetitorsPage() {
  const user = await getDemoUser();
  const [competitors, brands, projects] = await Promise.all([
    prisma.competitor.findMany({
      where: { userId: user.id },
      orderBy: { updatedAt: "desc" },
      include: {
        brand: true,
        project: true,
        analyses: { orderBy: { createdAt: "desc" }, take: 1 },
        _count: { select: { analyses: true } }
      }
    }),
    prisma.brand.findMany({
      where: { userId: user.id },
      orderBy: { updatedAt: "desc" },
      select: { id: true, name: true }
    }),
    prisma.project.findMany({
      where: { userId: user.id },
      orderBy: { updatedAt: "desc" },
      select: { id: true, productName: true }
    })
  ]);

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">競品情報中心</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            建立競品檔案、擷取商品頁與官網資訊，讓 AI 拆解定位、受眾、文案模式、頁面結構與可反打的廣告角度。
          </p>
        </div>
        <Badge>{competitors.length} 筆競品</Badge>
      </section>

      <CompetitorForm brands={brands} projects={projects} />

      <section className="grid gap-4">
        <div>
          <h2 className="text-lg font-semibold">競品分析紀錄</h2>
          <p className="text-sm text-muted-foreground">點進競品可查看完整報告，或重新擷取頁面進行分析。</p>
        </div>

        {competitors.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {competitors.map((competitor) => {
              const latest = competitor.analyses[0];
              const summary = readOneLine(latest?.summary) || competitor.description || "尚未產生摘要";
              return (
                <Link key={competitor.id} href={`/competitors/${competitor.id}`} className="block">
                  <Card className="h-full transition hover:border-primary/40 hover:shadow-panel">
                    <CardHeader>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <CardTitle className="flex items-center gap-2">
                            <Search className="h-4 w-4" />
                            {competitor.name}
                          </CardTitle>
                          <CardDescription>{competitor.industry || "未設定產業"}</CardDescription>
                        </div>
                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                      </div>
                    </CardHeader>
                    <CardContent className="grid gap-3 text-sm">
                      <p className="leading-6 text-muted-foreground">{truncate(summary, 130)}</p>
                      <div className="flex flex-wrap gap-2">
                        {competitor.brand ? <Badge>{competitor.brand.name}</Badge> : null}
                        {competitor.project ? <Badge>{competitor.project.productName}</Badge> : null}
                        {competitor.targetMarket ? <Badge>{competitor.targetMarket}</Badge> : null}
                        <Badge>{competitor._count.analyses} 次分析</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">更新 {formatDate(competitor.updatedAt)}</p>
                    </CardContent>
                  </Card>
                </Link>
              );
            })}
          </div>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>尚未建立競品</CardTitle>
              <CardDescription>先新增一個競品 URL，系統就能開始累積你的競品情報資料庫。</CardDescription>
            </CardHeader>
          </Card>
        )}
      </section>
    </div>
  );
}

function readOneLine(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  return typeof record.oneLine === "string" ? record.oneLine : "";
}
