import { mkdir } from "fs/promises";
import path from "path";
import { StorageProvider, StoragePutOptions, StoredFile } from "@/lib/storage/types";

const PUBLIC_UPLOAD_ROOT = path.join(process.cwd(), "public", "uploads");

function normalizeKey(value: string) {
  return value.replace(/\\/g, "/").replace(/^\/+/, "");
}

function keyFromUrl(keyOrUrl: string) {
  const clean = keyOrUrl.split("?")[0];
  if (clean.startsWith("/uploads/")) return clean.replace("/uploads/", "");
  return normalizeKey(clean);
}

export const localStorageProvider: StorageProvider = {
  async put(buffer: Buffer, options: StoragePutOptions): Promise<StoredFile> {
    const target = await this.createWriteTarget(options);
    const { writeFile } = await import("fs/promises");
    await writeFile(target.path, buffer);
    return target;
  },

  getPublicUrl(key: string) {
    return `/uploads/${normalizeKey(key)}`;
  },

  getLocalPath(keyOrUrl: string) {
    return path.join(PUBLIC_UPLOAD_ROOT, keyFromUrl(keyOrUrl));
  },

  async createWriteTarget(options: StoragePutOptions) {
    const directory = normalizeKey(options.directory);
    const key = normalizeKey(path.posix.join(directory, options.fileName));
    const outputDir = path.join(PUBLIC_UPLOAD_ROOT, directory);
    await mkdir(outputDir, { recursive: true });
    return {
      key,
      url: this.getPublicUrl(key),
      path: path.join(outputDir, options.fileName)
    };
  }
};
