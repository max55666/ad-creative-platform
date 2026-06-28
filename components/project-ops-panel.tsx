import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function ProjectOpsPanel({
  jobs,
  usageLogs,
  creatives
}: {
  jobs: any[];
  usageLogs: any[];
  creatives: any[];
}) {
  const estimatedCost = usageLogs.reduce((sum, log) => sum + Number(log.estimatedCostUsd || 0), 0);
  const imageCount = usageLogs.reduce((sum, log) => sum + Number(log.imageCount || 0), 0);
  const audioSeconds = usageLogs.reduce((sum, log) => sum + Number(log.audioSeconds || 0), 0);

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>生成歷史紀錄</CardTitle>
          <CardDescription>最近 20 筆非同步任務</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          {jobs.slice(0, 6).map((job) => (
            <div key={job.id} className="flex items-center justify-between gap-3 rounded-md border p-2">
              <span className="truncate">{job.type}</span>
              <Badge>{job.status}</Badge>
            </div>
          ))}
          {!jobs.length ? <p className="text-muted-foreground">尚無任務紀錄</p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>生成成本</CardTitle>
          <CardDescription>Provider usage log 摘要</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          <p>預估成本：USD {estimatedCost.toFixed(4)}</p>
          <p>圖片張數：{imageCount}</p>
          <p>音訊秒數：{Math.round(audioSeconds)}</p>
          <div className="flex flex-wrap gap-2">
            {[...new Set(usageLogs.map((log) => log.provider))].map((provider) => (
              <Badge key={provider}>{provider}</Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>素材版本比較</CardTitle>
          <CardDescription>最新素材與版本數</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          {creatives.slice(0, 6).map((creative) => (
            <div key={creative.id} className="rounded-md border p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{creative.title}</span>
                <Badge>v{creative.versions?.[0]?.version || 0}</Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{creative.type}</p>
            </div>
          ))}
          {!creatives.length ? <p className="text-muted-foreground">尚無版本紀錄</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}
