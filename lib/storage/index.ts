import { localStorageProvider } from "@/lib/storage/local";
import { createS3StorageProvider } from "@/lib/storage/s3";

export function getStorage() {
  const provider = process.env.STORAGE_PROVIDER || "local";
  if (provider === "s3" || provider === "r2") return createS3StorageProvider();
  return localStorageProvider;
}
