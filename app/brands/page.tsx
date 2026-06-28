import { ArrowRight, Building2 } from "lucide-react";
import Link from "next/link";
import { BrandForm } from "@/components/brand-form";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";
import { formatDate, truncate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function BrandsPage() {
  const user = await getDemoUser();
  const brands = await prisma.brand.findMany({
    where: { userId: user.id },
    orderBy: { updatedAt: "desc" },
    include: {
      brains: { orderBy: { createdAt: "desc" }, take: 1 },
      _count: { select: { projects: true, brains: true } }
    }
  });

  return (
    <div className="grid gap-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-normal">Brand Brain 品牌中心</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
          建立品牌定位、語氣、視覺規則、受眾與素材檢查清單。後續 Campaign、素材生成、KOL 腳本都會共用這份品牌基準。
        </p>
      </section>

      <BrandForm />

      <section className="grid gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">已建立品牌</h2>
            <p className="text-sm text-muted-foreground">點進品牌可以查看最新 Brand Brain，並重新生成。</p>
          </div>
          <Badge>{brands.length} 個品牌</Badge>
        </div>

        {brands.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {brands.map((brand) => (
              <Link key={brand.id} href={`/brands/${brand.id}`} className="block">
                <Card className="h-full transition hover:border-primary/40 hover:shadow-panel">
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <CardTitle className="flex items-center gap-2">
                          <Building2 className="h-4 w-4" />
                          {brand.name}
                        </CardTitle>
                        <CardDescription>{brand.industry || "尚未設定品類"}</CardDescription>
                      </div>
                      <ArrowRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-3 text-sm">
                    <p className="leading-6 text-muted-foreground">{truncate(brand.description || latestOneLine(brand), 130) || "尚未提供品牌介紹。"}</p>
                    <div className="flex flex-wrap gap-2">
                      {brand.targetMarket ? <Badge>{brand.targetMarket}</Badge> : null}
                      <Badge>{brand._count.projects} 個產品</Badge>
                      <Badge>{brand._count.brains} 版品牌腦</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">更新 {formatDate(brand.updatedAt)}</p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>尚未建立品牌</CardTitle>
              <CardDescription>先建立第一個品牌，讓後續素材生成與 Campaign 策略有共同基準。</CardDescription>
            </CardHeader>
          </Card>
        )}
      </section>
    </div>
  );
}

function latestOneLine(brand: { brains: Array<{ rawOutput: unknown }> }) {
  const raw = brand.brains[0]?.rawOutput as { data?: { summary?: { oneLine?: string } }; summary?: { oneLine?: string } } | undefined;
  return raw?.data?.summary?.oneLine || raw?.summary?.oneLine || "";
}
