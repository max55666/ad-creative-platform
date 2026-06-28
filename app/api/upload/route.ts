import { mkdir, writeFile } from "fs/promises";
import path from "path";
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { analyzeAndUpdateReferenceAsset, normalizeReferenceKey } from "@/lib/services/reference-asset-service";

const uploadRoot = path.join(process.cwd(), "public", "uploads");

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const file = formData.get("file");
  const projectId = formData.get("projectId");
  const role = stringField(formData.get("role"));
  const label = stringField(formData.get("label"));
  const referenceKey = normalizeReferenceKey(stringField(formData.get("referenceKey")) || label || "reference");
  const usage = stringField(formData.get("usage"));
  const viewAngle = stringField(formData.get("viewAngle"));
  const notes = stringField(formData.get("notes"));
  const shouldAnalyze = stringField(formData.get("analyze")) !== "false";

  if (!(file instanceof File)) {
    return NextResponse.json({ message: "請選擇要上傳的檔案" }, { status: 400 });
  }

  const maxMb = Number(process.env.MAX_UPLOAD_MB || 200);
  if (file.size > maxMb * 1024 * 1024) {
    return NextResponse.json({ message: `檔案超過上限 ${maxMb}MB` }, { status: 413 });
  }

  await mkdir(uploadRoot, { recursive: true });

  const extension = path.extname(file.name) || mimeToExtension(file.type);
  const safeBase = path
    .basename(file.name, extension)
    .replace(/[^a-zA-Z0-9-_]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  const fileName = `${Date.now()}-${crypto.randomUUID()}-${safeBase || "asset"}${extension}`;
  const filePath = path.join(uploadRoot, fileName);
  const buffer = Buffer.from(await file.arrayBuffer());

  await writeFile(filePath, buffer);

  const fileUrl = `/uploads/${fileName}`;
  const assetType = file.type.startsWith("video") ? "video" : "image";
  let asset = null;

  if (typeof projectId === "string" && projectId) {
    asset = await prisma.productAsset.create({
      data: {
        projectId,
        type: assetType,
        fileUrl,
        meta: {
          originalName: file.name,
          mimeType: file.type,
          size: file.size,
          role: role || (assetType === "image" ? "product" : "other"),
          label: label || (assetType === "image" ? "主商品" : file.name),
          referenceKey: referenceKey || (assetType === "image" ? "main_product" : undefined),
          usage: usage || "外觀參考",
          viewAngle: viewAngle || "",
          notes: notes || ""
        }
      }
    });

    if (assetType === "image" && shouldAnalyze) {
      asset = await analyzeAndUpdateReferenceAsset(asset.id);
    }
  }

  return NextResponse.json({
    fileUrl,
    asset,
    meta: {
      originalName: file.name,
      mimeType: file.type,
      size: file.size
    }
  });
}

function stringField(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value.trim() : "";
}

function mimeToExtension(mimeType: string) {
  if (mimeType === "image/png") return ".png";
  if (mimeType === "image/webp") return ".webp";
  if (mimeType === "image/gif") return ".gif";
  if (mimeType === "video/mp4") return ".mp4";
  if (mimeType === "video/webm") return ".webm";
  if (mimeType === "video/quicktime") return ".mov";
  return ".bin";
}
