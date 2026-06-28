import Link from "next/link";
import { ArrowRight, Film, Plus, Settings, Sparkles, UserRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { formatDate, truncate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  try {
    const user = await getDemoUser();
    const [projects, staticRecords, viralRecords, kolProfiles] = await Promise.all([
      prisma.project.findMany({
        where: { userId: user.id },
        orderBy: { updatedAt: "desc" },
        take: 12,
        include: {
          _count: {
            select: {
              analyses: true,
              staticCreatives: true,
              videoScripts: true,
              viralAnalyses: true
            }
          },
          analyses: { orderBy: { createdAt: "desc" }, take: 1 }
        }
      }),
      prisma.staticCreativeSuggestion.findMany({
        orderBy: { createdAt: "desc" },
        take: 6,
        include: { project: true }
      }),
      prisma.viralVideoAnalysis.findMany({
        orderBy: { createdAt: "desc" },
        take: 6,
        include: { project: true }
      }),
      prisma.kolProfile.findMany({
        where: { userId: user.id },
        orderBy: { updatedAt: "desc" },
        take: 6,
        include: { analyses: { orderBy: { createdAt: "desc" }, take: 1 }, _count: { select: { scripts: true, videos: true } } }
      })
    ]);

    return (
      <div className="grid gap-6">
        <section className="grid gap-4 md:grid-cols-[1.3fr_0.7fr]">
          <div>
            <h1 className="text-2xl font-semibold tracking-normal">Dashboard</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              管理產品分析專案、素材生成歷史、爆款影片拆解與 KOL 業配腳本。所有生成結果會保存，方便團隊回看與複製。
            </p>
          </div>
          <div className="flex flex-wrap items-start justify-start gap-2 md:justify-end">
            <Button asChild>
              <Link href="/projects/new">
                <Plus className="h-4 w-4" />
                新增產品分析
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/kols">
                <UserRound className="h-4 w-4" />
                KOL 工具
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/settings">
                <Settings className="h-4 w-4" />
                系統設定
              </Link>
            </Button>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-5">
          <Metric label="專案數" value={projects.length} />
          <Metric label="平面素材" value={projects.reduce((sum, item) => sum + item._count.staticCreatives, 0)} />
          <Metric label="影片腳本" value={projects.reduce((sum, item) => sum + item._count.videoScripts, 0)} />
          <Metric label="爆款拆解" value={projects.reduce((sum, item) => sum + item._count.viralAnalyses, 0)} />
          <Metric label="KOL" value={kolProfiles.length} />
        </section>

        <section className="grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
          <Card>
            <CardHeader>
              <CardTitle>過去專案</CardTitle>
              <CardDescription>點進專案後可查看報告、生成平面素材、短影音腳本與爆款拆解。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              {projects.length ? (
                projects.map((project) => (
                  <Link
                    key={project.id}
                    href={`/projects/${project.id}`}
                    className="grid gap-3 rounded-lg border bg-white p-4 transition hover:border-primary/40 hover:shadow-panel md:grid-cols-[1fr_auto]"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="font-semibold">{project.productName}</h2>
                        {project.targetMarket ? <Badge>{project.targetMarket}</Badge> : null}
                      </div>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        {truncate(project.productDescription || "尚未提供產品介紹", 160)}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                        <span>分析 {project._count.analyses}</span>
                        <span>平面 {project._count.staticCreatives}</span>
                        <span>腳本 {project._count.videoScripts}</span>
                        <span>爆款 {project._count.viralAnalyses}</span>
                        <span>更新 {formatDate(project.updatedAt)}</span>
                      </div>
                    </div>
                    <span className="flex items-center gap-2 text-sm font-medium text-primary">
                      開啟
                      <ArrowRight className="h-4 w-4" />
                    </span>
                  </Link>
                ))
              ) : (
                <EmptyState text="尚未建立產品專案，先新增一個產品分析。" />
              )}
            </CardContent>
          </Card>

          <div className="grid gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <UserRound className="h-4 w-4" />
                  最近 KOL 分析
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                {kolProfiles.length ? (
                  kolProfiles.map((profile) => (
                    <Link key={profile.id} href={`/kols/${profile.id}`} className="rounded-md border bg-white p-3 text-sm hover:border-primary/40">
                      <p className="font-medium">{profile.name}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {profile.platform} / 影片 {profile._count.videos} / 腳本 {profile._count.scripts}
                      </p>
                    </Link>
                  ))
                ) : (
                  <EmptyState text="尚未建立 KOL 分析。" />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4" />
                  素材分析紀錄
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                {staticRecords.length ? (
                  staticRecords.map((record) => (
                    <Link key={record.id} href={`/projects/${record.projectId}/static-creatives`} className="rounded-md border bg-white p-3 text-sm hover:border-primary/40">
                      <p className="font-medium">{record.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{record.project.productName} / {formatDate(record.createdAt)}</p>
                    </Link>
                  ))
                ) : (
                  <EmptyState text="尚未有平面素材紀錄。" />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Film className="h-4 w-4" />
                  爆款影片分析紀錄
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                {viralRecords.length ? (
                  viralRecords.map((record) => (
                    <Link key={record.id} href={`/projects/${record.projectId}/viral-analysis`} className="rounded-md border bg-white p-3 text-sm hover:border-primary/40">
                      <p className="font-medium">{record.project.productName}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{record.videoUrl} / {formatDate(record.createdAt)}</p>
                    </Link>
                  ))
                ) : (
                  <EmptyState text="尚未有爆款影片分析紀錄。" />
                )}
              </CardContent>
            </Card>
          </div>
        </section>
      </div>
    );
  } catch (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>資料庫尚未啟動</CardTitle>
          <CardDescription>Dashboard 需要 PostgreSQL。請確認 Docker Postgres 已啟動，並執行 Prisma migration。</CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="rounded-md bg-muted p-4 text-sm">docker compose up -d{"\n"}pnpm prisma:migrate</pre>
          <p className="mt-3 text-sm text-muted-foreground">{error instanceof Error ? error.message : "Database unavailable"}</p>
        </CardContent>
      </Card>
    );
  }
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-2 text-2xl font-semibold">{value}</p>
      </CardContent>
    </Card>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">{text}</p>;
}
