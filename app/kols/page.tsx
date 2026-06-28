import { ArrowRight, Plus, UserRound } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { KolToolClient } from "@/components/kol-tool-client";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { formatDate, truncate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function KolsPage() {
  const user = await getDemoUser();
  const [projects, profiles] = await Promise.all([
    prisma.project.findMany({
      where: { userId: user.id },
      orderBy: { updatedAt: "desc" },
      select: { id: true, productName: true }
    }),
    prisma.kolProfile.findMany({
      where: { userId: user.id },
      orderBy: { updatedAt: "desc" },
      include: {
        project: true,
        videos: { orderBy: { createdAt: "desc" }, take: 2 },
        analyses: { orderBy: { createdAt: "desc" }, take: 1 },
        scripts: { orderBy: { createdAt: "desc" }, take: 2 },
        _count: { select: { videos: true, analyses: true, scripts: true } }
      }
    })
  ]);

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">KOL 分析與業配腳本工具</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            貼上 KOL 網址與過往業配影片，分析人設、粉絲輪廓、適合產品，再替指定產品產生以轉換為主的專屬腳本。
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/projects/new">
            <Plus className="h-4 w-4" />
            新增產品專案
          </Link>
        </Button>
      </section>

      <KolToolClient projects={projects} />

      <section className="grid gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">已建立的 KOL</h2>
            <p className="text-sm text-muted-foreground">點進去可以查看完整分析、重跑分析與產生產品腳本。</p>
          </div>
          <Badge>{profiles.length} 位</Badge>
        </div>

        {profiles.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {profiles.map((profile) => (
              <Link key={profile.id} href={`/kols/${profile.id}`} className="block">
                <Card className="h-full transition hover:border-primary/40 hover:shadow-panel">
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <CardTitle className="flex items-center gap-2">
                          <UserRound className="h-4 w-4" />
                          {profile.name}
                        </CardTitle>
                        <CardDescription>{profile.platform}</CardDescription>
                      </div>
                      <ArrowRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-3 text-sm">
                    <p className="leading-6 text-muted-foreground">{truncate(profile.description || latestOneLine(profile), 130) || "尚未提供描述。"}</p>
                    <div className="flex flex-wrap gap-2">
                      {profile.project ? <Badge>{profile.project.productName}</Badge> : null}
                      <Badge>{profile._count.videos} 支影片</Badge>
                      <Badge>{profile._count.scripts} 組腳本</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">更新 {formatDate(profile.updatedAt)}</p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>還沒有 KOL 紀錄</CardTitle>
              <CardDescription>先建立第一位 KOL，系統會保存分析結果與後續腳本紀錄。</CardDescription>
            </CardHeader>
          </Card>
        )}
      </section>
    </div>
  );
}

function latestOneLine(profile: { analyses: Array<{ rawOutput: unknown }> }) {
  const raw = profile.analyses[0]?.rawOutput as { kolSummary?: { oneLine?: string }; data?: { kolSummary?: { oneLine?: string } } } | undefined;
  return raw?.data?.kolSummary?.oneLine || raw?.kolSummary?.oneLine || "";
}
