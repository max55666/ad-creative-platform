export type StoredFile = {
  url: string;
  key: string;
  path?: string;
};

export type StoragePutOptions = {
  directory: string;
  fileName: string;
  contentType?: string;
};

export type StorageProvider = {
  put(buffer: Buffer, options: StoragePutOptions): Promise<StoredFile>;
  getPublicUrl(key: string): string;
  getLocalPath(keyOrUrl: string): string;
  createWriteTarget(options: StoragePutOptions): Promise<StoredFile & { path: string }>;
};
