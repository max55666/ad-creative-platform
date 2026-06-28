-- CreateTable
CREATE TABLE "GeneratedImage" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "creativeId" TEXT,
    "videoScriptId" TEXT,
    "type" TEXT NOT NULL,
    "aspectRatio" TEXT,
    "prompt" TEXT NOT NULL,
    "imageUrl" TEXT NOT NULL,
    "provider" TEXT NOT NULL DEFAULT 'openai',
    "model" TEXT,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "GeneratedImage_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "VoiceoverAsset" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "videoScriptId" TEXT,
    "language" TEXT NOT NULL,
    "gender" TEXT NOT NULL,
    "voiceId" TEXT,
    "provider" TEXT NOT NULL DEFAULT 'elevenlabs',
    "text" TEXT NOT NULL,
    "audioUrl" TEXT NOT NULL,
    "durationSec" DOUBLE PRECISION,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "VoiceoverAsset_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProcessedMedia" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "sourceUrl" TEXT,
    "type" TEXT NOT NULL,
    "fileUrl" TEXT NOT NULL,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ProcessedMedia_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "VideoRender" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "videoScriptId" TEXT,
    "provider" TEXT NOT NULL DEFAULT 'ffmpeg',
    "status" TEXT NOT NULL DEFAULT 'pending',
    "videoUrl" TEXT,
    "input" JSONB,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "VideoRender_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "GeneratedImage_projectId_idx" ON "GeneratedImage"("projectId");

-- CreateIndex
CREATE INDEX "GeneratedImage_creativeId_idx" ON "GeneratedImage"("creativeId");

-- CreateIndex
CREATE INDEX "GeneratedImage_videoScriptId_idx" ON "GeneratedImage"("videoScriptId");

-- CreateIndex
CREATE INDEX "VoiceoverAsset_projectId_idx" ON "VoiceoverAsset"("projectId");

-- CreateIndex
CREATE INDEX "VoiceoverAsset_videoScriptId_idx" ON "VoiceoverAsset"("videoScriptId");

-- CreateIndex
CREATE INDEX "ProcessedMedia_projectId_idx" ON "ProcessedMedia"("projectId");

-- CreateIndex
CREATE INDEX "ProcessedMedia_type_idx" ON "ProcessedMedia"("type");

-- CreateIndex
CREATE INDEX "VideoRender_projectId_idx" ON "VideoRender"("projectId");

-- CreateIndex
CREATE INDEX "VideoRender_videoScriptId_idx" ON "VideoRender"("videoScriptId");

-- AddForeignKey
ALTER TABLE "GeneratedImage" ADD CONSTRAINT "GeneratedImage_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "VoiceoverAsset" ADD CONSTRAINT "VoiceoverAsset_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProcessedMedia" ADD CONSTRAINT "ProcessedMedia_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "VideoRender" ADD CONSTRAINT "VideoRender_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;
