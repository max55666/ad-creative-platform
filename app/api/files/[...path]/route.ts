import { readFile } from "fs/promises";
import path from "path";
import { NextRequest, NextResponse } from "next/server";
import { getStorage } from "@/lib/storage";

type Params = {
  params: Promise<{ path: string[] }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { path: parts } = await params;
  const safeParts = (parts || []).filter((part) => part && part !== ".." && !part.includes("\\"));
  if (!safeParts.length) return NextResponse.json({ message: "File path is required" }, { status: 400 });

  const key = safeParts.join("/");
  try {
    const filePath = getStorage().getLocalPath(key);
    const file = await readFile(filePath);
    return new NextResponse(file, {
      headers: {
        "content-type": mimeTypeFromPath(filePath),
        "cache-control": "private, max-age=31536000, immutable"
      }
    });
  } catch {
    return NextResponse.json({ message: "File not found" }, { status: 404 });
  }
}

function mimeTypeFromPath(filePath: string) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  if (ext === ".mp4") return "video/mp4";
  if (ext === ".webm") return "video/webm";
  if (ext === ".mov") return "video/quicktime";
  if (ext === ".mp3") return "audio/mpeg";
  if (ext === ".wav") return "audio/wav";
  return "application/octet-stream";
}
