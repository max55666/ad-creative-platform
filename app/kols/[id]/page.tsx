import { ArrowLeft, ExternalLink, Film, Link2, UserRound } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CopyButton } from "@/components/copy-button";
import { KolReport } from "@/components/kol-report";
import { KolScriptCard, KolScriptGenerator } from "@/components/kol-script-generator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

type Params = {
  params: Promise<{ id: string }>;
};

export default async function KolDetailPage({ params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const [profile, projects] = await Promise.all([
    prisma.kolProfile.findFirst({
      where: { id, userId: user.id },
      include: {
        project: true,
        videos: { orderBy: { createdAt: "desc" } },
        analyses: { orderBy: { createdAt: "desc" } },
        scripts: { orderBy: { createdAt: "desc" }, include: { project: true } }
      }
    }),
    prisma.project.findMany({
      where: { userId: user.id },
      orderBy: { updatedAt: "desc" },
      select: { id: true, productName: true }
    })
  ]);

  if (!profile) notFound();

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="outline" size="sm">
          <Link href="/kols">
            <ArrowLeft className="h-4 w-4" />
            返回 KOL 列表
          </Link>
        </Button>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <a href={profile.profileUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="h-4 w-4" />
              開啟 KOL 網址
            </a>
          </Button>
          <CopyButton value={profile.profileUrl} label="複製網址" />
        </div>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-xl">
                <UserRound className="h-5 w-5" />
                {profile.name}
              </CardTitle>
              <CardDescription className="mt-2">
                {profile.platform} / 建立 {formatDate(profile.createdAt)}
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge>{profile.followerCount || "未填粉絲數"}</Badge>
              {profile.avgViews ? <Badge>平均觀看 {profile.avgViews}</Badge> : null}
              {profile.avgEngagement ? <Badge>互動 {profile.avgEngagement}</Badge> : null}
              {profile.project ? <Badge>{profile.project.productName}</Badge> : null}
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4">
          {profile.description ? <p className="text-sm leading-6 text-muted-foreground">{profile.description}</p> : null}
          <div className="grid gap-3 md:grid-cols-3">
            <MiniStat label="分析紀錄" value={profile.analyses.length} />
            <MiniStat label="業配影片樣本" value={profile.videos.length} />
            <MiniStat label="已產生腳本" value={profile.scripts.length} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Film className="h-4 w-4" />
            過往業配影片樣本
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          {profile.videos.length ? (
            profile.videos.map((video) => (
              <div key={video.id} className="rounded-md border bg-white p-4 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{video.title || "未命名影片"}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {[video.sponsoredBrand, video.sponsoredProduct].filter(Boolean).join(" / ") || "尚未標記合作品牌"}
                    </p>
                  </div>
                  {video.videoUrl ? (
                    <a href={video.videoUrl} target="_blank" rel="noreferrer" className="text-primary">
                      <Link2 className="h-4 w-4" />
                    </a>
                  ) : null}
                </div>
                {video.notes ? <p className="mt-3 leading-6 text-muted-foreground">{video.notes}</p> : null}
              </div>
            ))
          ) : (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">尚未新增過往業配影片。</p>
          )}
        </CardContent>
      </Card>

      <KolReport analysis={profile.analyses[0] || null} />

      <KolScriptGenerator profileId={profile.id} projects={projects} defaultProjectId={profile.projectId} />

      <Card>
        <CardHeader>
          <CardTitle>腳本歷史紀錄</CardTitle>
          <CardDescription>每次生成都會保存，方便比較不同產品、風格與 Hook。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {profile.scripts.length ? (
            profile.scripts.map((script) => (
              <KolScriptCard
                key={script.id}
                script={{
                  title: script.title,
                  platform: script.platform,
                  objective: script.objective,
                  duration: script.duration,
                  hook: script.hook,
                  storyline: script.storyline,
                  captions: script.captions,
                  voiceover: script.voiceover,
                  shotList: script.shotList,
                  cta: script.cta,
                  adUsageNotes: script.adUsageNotes
                }}
              />
            ))
          ) : (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">尚未產生 KOL 專屬腳本。</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-muted/30 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}
