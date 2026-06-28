import { StorageProvider } from "@/lib/storage/types";

export function createS3StorageProvider(): StorageProvider {
  throw new Error("S3/R2 storage provider is reserved for production and not configured yet.");
}
