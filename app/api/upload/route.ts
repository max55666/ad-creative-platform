import path from "path";
import sharp from "sharp";
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getStorage } from "@/lib/storage";
import { analyzeAndUpdateReferenceAsset, normalizeReferenceKey } from "@/lib/services/reference-asset-service";

export const runtime = "nodejs";

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
    return NextResponse.json({ message: "請上傳有效的圖片或影片檔案。" }, { status: 400 });
  }

  const maxMb = positiveInt(process.env.MAX_UPLOAD_MB, 200);
  if (file.size > maxMb * 1024 * 1024) {
    return NextResponse.json({ message: `檔案大小不可超過 ${maxMb}MB。` }, { status: 413 });
  }

  const rawBuffer = Buffer.from(await file.arrayBuffer());
  const assetType = file.type.startsWith("video") ? "video" : "image";
  const normalized = await normalizeUploadFile(file, rawBuffer, assetType);
  const safeBase = path
    .basename(file.name, path.extname(file.name) || normalized.extension)
    .replace(/[^a-zA-Z0-9-_]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  const fileName = `${Date.now()}-${crypto.randomUUID()}-${safeBase || "asset"}${normalized.extension}`;

  const stored = await getStorage().put(normalized.buffer, {
    directory: "",
    fileName,
    contentType: normalized.contentType
  });
  const fileUrl = stored.url;
  let asset = null;

  if (typeof projectId === "string" && projectId) {
    asset = await prisma.productAsset.create({
      data: {
        projectId,
        type: assetType as any,
        fileUrl,
        meta: {
          originalName: file.name,
          mimeType: file.type,
          size: file.size,
          storedMimeType: normalized.contentType,
          storedSize: normalized.buffer.length,
          optimized: normalized.optimized,
          storageKey: stored.key,
          role: role || (assetType === "image" ? "product" : "other"),
          label: label || (assetType === "image" ? "主商品" : file.name),
          referenceKey: referenceKey || (assetType === "image" ? "main_product" : undefined),
          usage: usage || "素材生成參考",
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
      size: file.size,
      storedMimeType: normalized.contentType,
      storedSize: normalized.buffer.length,
      optimized: normalized.optimized
    }
  });
}

function stringField(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value.trim() : "";
}

function mimeToExtension(mimeType: string) {
  if (mimeType === "image/png") return ".png";
  if (mimeType === "image/jpeg") return ".jpg";
  if (mimeType === "image/webp") return ".webp";
  if (mimeType === "image/gif") return ".gif";
  if (mimeType === "video/mp4") return ".mp4";
  if (mimeType === "video/webm") return ".webm";
  if (mimeType === "video/quicktime") return ".mov";
  return ".bin";
}

async function normalizeUploadFile(file: File, buffer: Buffer, assetType: string) {
  const fallback = {
    buffer,
    contentType: file.type || undefined,
    extension: path.extname(file.name) || mimeToExtension(file.type),
    optimized: false
  };

  if (assetType !== "image") return fallback;

  const supportedInput = ["image/jpeg", "image/png", "image/webp", "image/gif"].includes(file.type);
  if (!supportedInput) return fallback;

  try {
    const maxWidth = positiveInt(process.env.UPLOAD_IMAGE_MAX_WIDTH, 1800);
    const quality = positiveInt(process.env.UPLOAD_IMAGE_QUALITY, 82);
    const optimizedBuffer = await sharp(buffer, { animated: false })
      .rotate()
      .resize({ width: maxWidth, height: maxWidth, fit: "inside", withoutEnlargement: true })
      .jpeg({ quality, mozjpeg: true })
      .toBuffer();

    return {
      buffer: optimizedBuffer,
      contentType: "image/jpeg",
      extension: ".jpg",
      optimized: optimizedBuffer.length < buffer.length
    };
  } catch {
    return fallback;
  }
}

function positiveInt(value: string | undefined, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}
