-- CreateTable
CREATE TABLE "generation_jobs" (
    "id" TEXT NOT NULL,
    "projectId" TEXT,
    "userId" TEXT,
    "type" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'queued',
    "progress" INTEGER NOT NULL DEFAULT 0,
    "inputPayload" JSONB NOT NULL,
    "outputPayload" JSONB,
    "errorMessage" TEXT,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "startedAt" TIMESTAMP(3),
    "completedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "generation_jobs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Creative" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "userId" TEXT,
    "type" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT,
    "sourceRefId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Creative_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CreativeVersion" (
    "id" TEXT NOT NULL,
    "creativeId" TEXT NOT NULL,
    "version" INTEGER NOT NULL,
    "kind" TEXT NOT NULL,
    "prompt" TEXT,
    "model" TEXT,
    "provider" TEXT,
    "generationParams" JSONB,
    "content" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CreativeVersion_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CreativeAsset" (
    "id" TEXT NOT NULL,
    "creativeId" TEXT NOT NULL,
    "versionId" TEXT,
    "type" TEXT NOT NULL,
    "url" TEXT NOT NULL,
    "storageKey" TEXT,
    "mimeType" TEXT,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CreativeAsset_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProviderUsageLog" (
    "id" TEXT NOT NULL,
    "provider" TEXT NOT NULL,
    "model" TEXT,
    "projectId" TEXT,
    "userId" TEXT,
    "jobId" TEXT,
    "inputTokens" INTEGER,
    "outputTokens" INTEGER,
    "imageCount" INTEGER,
    "audioSeconds" DOUBLE PRECISION,
    "videoSeconds" DOUBLE PRECISION,
    "estimatedCostUsd" DOUBLE PRECISION,
    "status" TEXT NOT NULL,
    "errorMessage" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ProviderUsageLog_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ViralVideo" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "sourceUrl" TEXT NOT NULL,
    "durationSec" DOUBLE PRECISION,
    "transcript" JSONB,
    "hookType" TEXT,
    "firstThreeSec" TEXT,
    "paceSummary" TEXT,
    "captionStrategy" TEXT,
    "productExposure" JSONB,
    "painPointArc" JSONB,
    "cta" JSONB,
    "analysisId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ViralVideo_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ViralFrame" (
    "id" TEXT NOT NULL,
    "viralVideoId" TEXT NOT NULL,
    "frameUrl" TEXT NOT NULL,
    "timestampSec" DOUBLE PRECISION,
    "captionText" TEXT,
    "visualNotes" TEXT,
    "productVisible" BOOLEAN NOT NULL DEFAULT false,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ViralFrame_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ViralSegment" (
    "id" TEXT NOT NULL,
    "viralVideoId" TEXT NOT NULL,
    "startSec" DOUBLE PRECISION,
    "endSec" DOUBLE PRECISION,
    "role" TEXT,
    "hookType" TEXT,
    "visual" TEXT,
    "caption" TEXT,
    "voiceover" TEXT,
    "pace" TEXT,
    "emotion" TEXT,
    "productExposure" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ViralSegment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ViralPattern" (
    "id" TEXT NOT NULL,
    "viralVideoId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "evidence" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ViralPattern_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ViralTemplate" (
    "id" TEXT NOT NULL,
    "viralVideoId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "template" JSONB NOT NULL,
    "rewrittenScripts" JSONB,
    "bestFitProducts" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ViralTemplate_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "generation_jobs_projectId_idx" ON "generation_jobs"("projectId");

-- CreateIndex
CREATE INDEX "generation_jobs_status_idx" ON "generation_jobs"("status");

-- CreateIndex
CREATE INDEX "generation_jobs_type_idx" ON "generation_jobs"("type");

-- CreateIndex
CREATE INDEX "generation_jobs_createdAt_idx" ON "generation_jobs"("createdAt");

-- CreateIndex
CREATE INDEX "Creative_projectId_idx" ON "Creative"("projectId");

-- CreateIndex
CREATE INDEX "Creative_type_idx" ON "Creative"("type");

-- CreateIndex
CREATE INDEX "Creative_sourceRefId_idx" ON "Creative"("sourceRefId");

-- CreateIndex
CREATE INDEX "CreativeVersion_creativeId_idx" ON "CreativeVersion"("creativeId");

-- CreateIndex
CREATE INDEX "CreativeVersion_kind_idx" ON "CreativeVersion"("kind");

-- CreateIndex
CREATE UNIQUE INDEX "CreativeVersion_creativeId_version_key" ON "CreativeVersion"("creativeId", "version");

-- CreateIndex
CREATE INDEX "CreativeAsset_creativeId_idx" ON "CreativeAsset"("creativeId");

-- CreateIndex
CREATE INDEX "CreativeAsset_versionId_idx" ON "CreativeAsset"("versionId");

-- CreateIndex
CREATE INDEX "CreativeAsset_type_idx" ON "CreativeAsset"("type");

-- CreateIndex
CREATE INDEX "ProviderUsageLog_provider_idx" ON "ProviderUsageLog"("provider");

-- CreateIndex
CREATE INDEX "ProviderUsageLog_projectId_idx" ON "ProviderUsageLog"("projectId");

-- CreateIndex
CREATE INDEX "ProviderUsageLog_userId_idx" ON "ProviderUsageLog"("userId");

-- CreateIndex
CREATE INDEX "ProviderUsageLog_jobId_idx" ON "ProviderUsageLog"("jobId");

-- CreateIndex
CREATE INDEX "ProviderUsageLog_createdAt_idx" ON "ProviderUsageLog"("createdAt");

-- CreateIndex
CREATE INDEX "ViralVideo_projectId_idx" ON "ViralVideo"("projectId");

-- CreateIndex
CREATE INDEX "ViralVideo_analysisId_idx" ON "ViralVideo"("analysisId");

-- CreateIndex
CREATE INDEX "ViralVideo_createdAt_idx" ON "ViralVideo"("createdAt");

-- CreateIndex
CREATE INDEX "ViralFrame_viralVideoId_idx" ON "ViralFrame"("viralVideoId");

-- CreateIndex
CREATE INDEX "ViralFrame_timestampSec_idx" ON "ViralFrame"("timestampSec");

-- CreateIndex
CREATE INDEX "ViralSegment_viralVideoId_idx" ON "ViralSegment"("viralVideoId");

-- CreateIndex
CREATE INDEX "ViralSegment_startSec_idx" ON "ViralSegment"("startSec");

-- CreateIndex
CREATE INDEX "ViralPattern_viralVideoId_idx" ON "ViralPattern"("viralVideoId");

-- CreateIndex
CREATE INDEX "ViralPattern_type_idx" ON "ViralPattern"("type");

-- CreateIndex
CREATE INDEX "ViralTemplate_viralVideoId_idx" ON "ViralTemplate"("viralVideoId");

-- AddForeignKey
ALTER TABLE "generation_jobs" ADD CONSTRAINT "generation_jobs_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Creative" ADD CONSTRAINT "Creative_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CreativeVersion" ADD CONSTRAINT "CreativeVersion_creativeId_fkey" FOREIGN KEY ("creativeId") REFERENCES "Creative"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CreativeAsset" ADD CONSTRAINT "CreativeAsset_creativeId_fkey" FOREIGN KEY ("creativeId") REFERENCES "Creative"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CreativeAsset" ADD CONSTRAINT "CreativeAsset_versionId_fkey" FOREIGN KEY ("versionId") REFERENCES "CreativeVersion"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProviderUsageLog" ADD CONSTRAINT "ProviderUsageLog_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProviderUsageLog" ADD CONSTRAINT "ProviderUsageLog_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ViralVideo" ADD CONSTRAINT "ViralVideo_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ViralFrame" ADD CONSTRAINT "ViralFrame_viralVideoId_fkey" FOREIGN KEY ("viralVideoId") REFERENCES "ViralVideo"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ViralSegment" ADD CONSTRAINT "ViralSegment_viralVideoId_fkey" FOREIGN KEY ("viralVideoId") REFERENCES "ViralVideo"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ViralPattern" ADD CONSTRAINT "ViralPattern_viralVideoId_fkey" FOREIGN KEY ("viralVideoId") REFERENCES "ViralVideo"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ViralTemplate" ADD CONSTRAINT "ViralTemplate_viralVideoId_fkey" FOREIGN KEY ("viralVideoId") REFERENCES "ViralVideo"("id") ON DELETE CASCADE ON UPDATE CASCADE;
