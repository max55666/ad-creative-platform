import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { analyzeAndUpdateReferenceAsset, normalizeReferenceKey, readAssetMeta } from "@/lib/services/reference-asset-service";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const [assets, scripts] = await Promise.all([
    prisma.productAsset.findMany({
      where: { projectId: id, type: "image" },
      orderBy: [{ createdAt: "desc" }]
    }),
    prisma.videoScript.findMany({
      where: { projectId: id },
      orderBy: { createdAt: "desc" },
      select: { id: true, title: true, requiredObjects: true, storyboard: true }
    })
  ]);

  return NextResponse.json({
    assets,
    requiredObjects: collectRequiredObjects(scripts)
  });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const assetId = String(body.assetId || "");
  const asset = await prisma.productAsset.findFirst({ where: { id: assetId, projectId: id, type: "image" } });
  if (!asset) return NextResponse.json({ message: "找不到參考圖片" }, { status: 404 });

  const currentMeta = readAssetMeta(asset);
  const label = String(body.label ?? currentMeta.label ?? "").trim();
  const referenceKey = normalizeReferenceKey(String(body.referenceKey ?? currentMeta.referenceKey ?? label ?? "reference"));
  const role = String(body.role ?? currentMeta.role ?? "reference");
  const usage = String(body.usage ?? currentMeta.usage ?? "外觀參考").trim();
  const viewAngle = String(body.viewAngle ?? currentMeta.viewAngle ?? "").trim();
  const notes = String(body.notes ?? currentMeta.notes ?? "").trim();

  const updated = await prisma.productAsset.update({
    where: { id: asset.id },
    data: {
      meta: {
        ...currentMeta,
        label,
        referenceKey,
        role,
        usage,
        viewAngle,
        notes
      }
    }
  });

  const analyzed = body.analyze === true ? await analyzeAndUpdateReferenceAsset(updated.id) : updated;
  return NextResponse.json({ asset: analyzed || updated });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const assetId = String(body.assetId || "");
  const asset = await prisma.productAsset.findFirst({ where: { id: assetId, projectId: id, type: "image" } });
  if (!asset) return NextResponse.json({ message: "找不到參考圖片" }, { status: 404 });
  const analyzed = await analyzeAndUpdateReferenceAsset(asset.id);
  return NextResponse.json({ asset: analyzed || asset });
}

export async function DELETE(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const assetId = String(body.assetId || "");
  const asset = await prisma.productAsset.findFirst({ where: { id: assetId, projectId: id, type: "image" } });
  if (!asset) return NextResponse.json({ message: "找不到參考圖片" }, { status: 404 });
  await prisma.productAsset.delete({ where: { id: asset.id } });
  return NextResponse.json({ ok: true });
}

function collectRequiredObjects(scripts: Array<{ id: string; title: string; requiredObjects: unknown; storyboard: unknown }>) {
  const map = new Map<string, any>();

  for (const script of scripts) {
    for (const object of toObjectList(script.requiredObjects)) {
      const key = normalizeReferenceKey(String(object.referenceKey || object.key || object.name || object.label || ""));
      if (!key) continue;
      mergeObject(map, key, {
        referenceKey: key,
        label: object.label || object.name || key,
        role: object.role || inferRole(key),
        reason: object.reason || object.usage || "",
        scripts: [script.title]
      });
    }

    if (Array.isArray(script.storyboard)) {
      for (const shot of script.storyboard) {
        if (!shot || typeof shot !== "object") continue;
        const record = shot as Record<string, unknown>;
        for (const object of toObjectList(record.sceneObjects)) {
          const key = normalizeReferenceKey(String(object.referenceKey || object.key || object.name || object.label || ""));
          if (!key) continue;
          mergeObject(map, key, {
            referenceKey: key,
            label: object.label || object.name || key,
            role: object.role || inferRole(key),
            reason: object.reason || record.purpose || "",
            scripts: [script.title]
          });
        }
      }
    }
  }

  if (!map.has("main_product")) {
    map.set("main_product", {
      referenceKey: "main_product",
      label: "主商品",
      role: "product",
      reason: "所有素材生成都會優先鎖定主商品外觀。",
      scripts: []
    });
  }

  return Array.from(map.values());
}

function mergeObject(map: Map<string, any>, key: string, value: any) {
  const current = map.get(key);
  if (!current) {
    map.set(key, value);
    return;
  }
  map.set(key, {
    ...current,
    ...value,
    reason: current.reason || value.reason,
    scripts: Array.from(new Set([...(current.scripts || []), ...(value.scripts || [])]))
  });
}

function toObjectList(value: unknown): any[] {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (typeof item === "string") return [{ name: item, referenceKey: item }];
      if (item && typeof item === "object") return [item];
      return [];
    });
  }
  if (typeof value === "string") return value.split(/[,，、\n]/).map((name) => ({ name, referenceKey: name.trim() })).filter((item) => item.name);
  return [];
}

function inferRole(key: string) {
  if (key.includes("product") || key.includes("商品")) return "product";
  if (key.includes("cat") || key.includes("貓")) return "animal";
  if (key.includes("woman") || key.includes("female") || key.includes("person") || key.includes("人")) return "person";
  return "reference";
}
