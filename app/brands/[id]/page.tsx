import { ArrowLeft, Building2, ExternalLink } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { BrandBrainReport } from "@/components/brand-brain-report";
import { CopyButton } from "@/components/copy-button";
import { RegenerateBrandBrainButton } from "@/components/regenerate-brand-brain-button";
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

export default async function BrandDetailPage({ params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const brand = await prisma.brand.findFirst({
    where: { id, userId: user.id },
    include: {
      projects: { orderBy: { updatedAt: "desc" }, take: 12 },
      brains: { orderBy: { createdAt: "desc" } }
    }
  });

  if (!brand) notFound();

  const latestBrain = brand.brains[0] || null;

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="outline" size="sm">
          <Link href="/brands">
            <ArrowLeft className="h-4 w-4" />
            返回品牌中心
          </Link>
        </Button>
        <div className="flex flex-wrap gap-2">
          {brand.websiteUrl ? (
            <Button asChild variant="outline" size="sm">
              <a href={brand.websiteUrl} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" />
                開啟官網
              </a>
            </Button>
          ) : null}
          <RegenerateBrandBrainButton brandId={brand.id} />
        </div>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-xl">
                <Building2 className="h-5 w-5" />
                {brand.name}
              </CardTitle>
              <CardDescription className="mt-2">建立 {formatDate(brand.createdAt)} / 更新 {formatDate(brand.updatedAt)}</CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              {brand.industry ? <Badge>{brand.industry}</Badge> : null}
              {brand.targetMarket ? <Badge>{brand.targetMarket}</Badge> : null}
              <Badge>{brand.projects.length} 個產品</Badge>
              <Badge>{brand.brains.length} 版品牌腦</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4">
          {brand.description ? <p className="text-sm leading-6 text-muted-foreground">{brand.description}</p> : null}
          <div className="grid gap-3 md:grid-cols-2">
            <MiniBlock label="品牌語氣" value={brand.voiceTone || "尚未設定"} />
            <MiniBlock label="視覺風格" value={brand.visualStyle || "尚未設定"} />
          </div>
          <CopyButton value={JSON.stringify(brand, null, 2)} label="複製品牌資料" />
        </CardContent>
      </Card>

      <BrandBrainReport brain={latestBrain} />

      <Card>
        <CardHeader>
          <CardTitle>綁定產品</CardTitle>
          <CardDescription>後續產品專案可綁定品牌，讓素材與 Campaign 共用 Brand Brain。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          {brand.projects.length ? (
            brand.projects.map((project) => (
              <Link key={project.id} href={`/projects/${project.id}`} className="rounded-md border bg-white p-4 text-sm hover:border-primary/40">
                <p className="font-medium">{project.productName}</p>
                <p className="mt-2 leading-6 text-muted-foreground">{project.productDescription || "尚未提供產品介紹"}</p>
              </Link>
            ))
          ) : (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">尚未有產品綁定這個品牌。</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MiniBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-muted/30 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-2 text-sm leading-6">{value}</p>
    </div>
  );
}
