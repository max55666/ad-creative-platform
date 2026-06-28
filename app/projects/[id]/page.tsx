import Link from "next/link";
import { notFound } from "next/navigation";
import { AnalysisReport } from "@/components/analysis-report";
import { ProjectOpsPanel } from "@/components/project-ops-panel";
import { ProjectNav } from "@/components/project-nav";
import { ReferenceAssetManager } from "@/components/reference-asset-manager";
import { RegenerateAnalysisButton } from "@/components/regenerate-analysis-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getProjectWithHistory } from "@/lib/projects";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function ProjectReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await getProjectWithHistory(id);
  if (!project) notFound();

  const latestAnalysis = project.analyses[0];

  return (
    <div className="grid gap-5">
      <ProjectNav projectId={project.id} />
      <ProjectOpsPanel
        jobs={JSON.parse(JSON.stringify(project.generationJobs || []))}
        usageLogs={JSON.parse(JSON.stringify(project.providerUsageLogs || []))}
        creatives={JSON.parse(JSON.stringify(project.creatives || []))}
      />
      <ReferenceAssetManager
        projectId={project.id}
        initialAssets={JSON.parse(JSON.stringify(project.assets || []))}
        initialRequiredObjects={collectRequiredObjects(project.videoScripts || [])}
      />

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-xl">{project.productName}</CardTitle>
              {project.targetMarket ? <Badge>{project.targetMarket}</Badge> : null}
              {project.price ? <Badge>{project.price}</Badge> : null}
            </div>
            <CardDescription className="mt-2">{project.productDescription || "尚未提供產品介紹"}</CardDescription>
          </div>
          <RegenerateAnalysisButton projectId={project.id} />
        </CardHeader>
        <CardContent className="grid gap-3 text-sm md:grid-cols-2">
          <p><span className="font-medium">商品頁：</span>{project.productUrl || "未提供"}</p>
          <p><span className="font-medium">使用場景：</span>{project.mainUseCase || "未提供"}</p>
          <p><span className="font-medium">規格：</span>{project.specs || "未提供"}</p>
          <p><span className="font-medium">競品：</span>{project.competitors || "未提供"}</p>
        </CardContent>
      </Card>

      {latestAnalysis ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">最新分析：{formatDate(latestAnalysis.createdAt)}</p>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline" size="sm"><Link href={`/projects/${project.id}/static-creatives`}>產生平面素材</Link></Button>
              <Button asChild variant="outline" size="sm"><Link href={`/projects/${project.id}/video-scripts`}>產生影片腳本</Link></Button>
              <Button asChild variant="outline" size="sm"><Link href={`/projects/${project.id}/viral-analysis`}>分析爆款影片</Link></Button>
            </div>
          </div>
          <AnalysisReport projectId={project.id} analysis={latestAnalysis} />
        </>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>尚未產生分析</CardTitle>
            <CardDescription>點擊重新分析後，系統會整理產品摘要、受眾、痛點、賣點與素材方向。</CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );
}

function collectRequiredObjects(scripts: any[]) {
  const map = new Map<string, any>();
  for (const script of scripts) {
    for (const object of toObjects(script.requiredObjects)) {
      const key = normalizeKey(object.referenceKey || object.key || object.name || object.label || "");
      if (!key) continue;
      map.set(key, {
        referenceKey: key,
        label: object.label || object.name || key,
        role: object.role || "reference",
        reason: object.reason || object.usage || "",
        scripts: [...(map.get(key)?.scripts || []), script.title]
      });
    }
  }
  return Array.from(map.values());
}

function toObjects(value: unknown): any[] {
  if (Array.isArray(value)) return value.map((item) => (typeof item === "string" ? { name: item } : item)).filter(Boolean);
  return [];
}

function normalizeKey(value: string) {
  return value.trim().toLowerCase().replace(/[\s/\\]+/g, "_").replace(/[^a-z0-9_\-\u4e00-\u9fa5]+/g, "").slice(0, 64);
}
