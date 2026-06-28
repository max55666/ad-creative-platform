CREATE TABLE "ProductLoraModel" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "userId" TEXT,
    "name" TEXT NOT NULL,
    "triggerWord" TEXT NOT NULL,
    "provider" TEXT NOT NULL DEFAULT 'fal',
    "endpoint" TEXT NOT NULL DEFAULT 'fal-ai/flux-lora-fast-training',
    "status" TEXT NOT NULL DEFAULT 'draft',
    "trainingImageCount" INTEGER NOT NULL DEFAULT 0,
    "assetIds" JSONB,
    "input" JSONB,
    "output" JSONB,
    "requestId" TEXT,
    "dataArchiveUrl" TEXT,
    "diffusersLoraUrl" TEXT,
    "configFileUrl" TEXT,
    "debugPreprocessedUrl" TEXT,
    "samplePrompt" TEXT,
    "errorMessage" TEXT,
    "completedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ProductLoraModel_pkey" PRIMARY KEY ("id")
);

CREATE INDEX "ProductLoraModel_projectId_idx" ON "ProductLoraModel"("projectId");
CREATE INDEX "ProductLoraModel_provider_idx" ON "ProductLoraModel"("provider");
CREATE INDEX "ProductLoraModel_status_idx" ON "ProductLoraModel"("status");
CREATE INDEX "ProductLoraModel_createdAt_idx" ON "ProductLoraModel"("createdAt");

ALTER TABLE "ProductLoraModel" ADD CONSTRAINT "ProductLoraModel_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;
