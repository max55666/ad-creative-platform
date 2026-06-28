import { mkdir } from "fs/promises";
import path from "path";
import { missingPackageMessage, optionalImport } from "@/lib/services/runtime-import";
import { getStorage } from "@/lib/storage";

export async function processImage({
  inputPath,
  projectId,
  width,
  height,
  format = "webp",
  quality = 86,
  logoPath
}: {
  inputPath: string;
  projectId: string;
  width?: number;
  height?: number;
  format?: "png" | "jpeg" | "webp";
  quality?: number;
  logoPath?: string;
}) {
  const sharpModule = await optionalImport<any>("sharp");
  const sharp = sharpModule?.default || sharpModule;
  if (!sharp) throw new Error(missingPackageMessage("sharp"));

  const outputDir = getStorage().getLocalPath(`processed/${projectId}`);
  await mkdir(outputDir, { recursive: true });
  const outputName = `${Date.now()}-processed.${format}`;
  const outputPath = path.join(outputDir, outputName);

  let pipeline = sharp(inputPath).rotate();
  if (width || height) {
    pipeline = pipeline.resize(width, height, { fit: "cover", position: "center" });
  }

  if (logoPath) {
    pipeline = pipeline.composite([{ input: logoPath, gravity: "southeast" }]);
  }

  await pipeline.toFormat(format, { quality }).toFile(outputPath);

  return {
    filePath: outputPath,
    fileUrl: getStorage().getPublicUrl(`processed/${projectId}/${outputName}`),
    meta: { width, height, format, quality, logoPath }
  };
}
