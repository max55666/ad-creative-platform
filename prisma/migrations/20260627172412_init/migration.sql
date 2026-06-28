-- CreateEnum
CREATE TYPE "AssetType" AS ENUM ('image', 'video', 'url', 'text');

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Project" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "productName" TEXT NOT NULL,
    "productDescription" TEXT,
    "productUrl" TEXT,
    "targetMarket" TEXT,
    "price" TEXT,
    "specs" TEXT,
    "mainUseCase" TEXT,
    "competitors" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Project_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProductAsset" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "type" "AssetType" NOT NULL,
    "fileUrl" TEXT,
    "content" TEXT,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ProductAsset_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProductAnalysis" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "summary" JSONB NOT NULL,
    "audienceAnalysis" JSONB NOT NULL,
    "painPoints" JSONB NOT NULL,
    "sellingPoints" JSONB NOT NULL,
    "adAngles" JSONB NOT NULL,
    "nextSteps" JSONB,
    "rawOutput" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ProductAnalysis_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StaticCreativeSuggestion" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "headline" TEXT NOT NULL,
    "subHeadline" TEXT,
    "visualDirection" TEXT NOT NULL,
    "copywriting" JSONB NOT NULL,
    "cta" TEXT NOT NULL,
    "platform" TEXT NOT NULL,
    "targetAudience" TEXT NOT NULL,
    "communication" TEXT,
    "source" TEXT NOT NULL DEFAULT 'ai',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "StaticCreativeSuggestion_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "VideoScript" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "platform" TEXT NOT NULL,
    "duration" TEXT NOT NULL,
    "style" TEXT,
    "hook" TEXT NOT NULL,
    "storyboard" JSONB NOT NULL,
    "voiceover" JSONB NOT NULL,
    "captions" JSONB NOT NULL,
    "bgmSuggestion" TEXT NOT NULL,
    "tone" TEXT,
    "props" JSONB,
    "cta" TEXT NOT NULL,
    "targetAudience" TEXT,
    "source" TEXT NOT NULL DEFAULT 'ai',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "VideoScript_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ViralVideoAnalysis" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "videoUrl" TEXT NOT NULL,
    "transcript" JSONB,
    "segmentBreakdown" JSONB NOT NULL,
    "structureAnalysis" JSONB NOT NULL,
    "captionAnalysis" JSONB NOT NULL,
    "voiceAnalysis" JSONB NOT NULL,
    "musicAnalysis" JSONB NOT NULL,
    "emotionAnalysis" JSONB NOT NULL,
    "viralReason" JSONB NOT NULL,
    "reusableTemplate" JSONB NOT NULL,
    "rewrittenScripts" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ViralVideoAnalysis_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE INDEX "Project_userId_idx" ON "Project"("userId");

-- CreateIndex
CREATE INDEX "Project_createdAt_idx" ON "Project"("createdAt");

-- CreateIndex
CREATE INDEX "ProductAsset_projectId_idx" ON "ProductAsset"("projectId");

-- CreateIndex
CREATE INDEX "ProductAsset_type_idx" ON "ProductAsset"("type");

-- CreateIndex
CREATE INDEX "ProductAnalysis_projectId_idx" ON "ProductAnalysis"("projectId");

-- CreateIndex
CREATE INDEX "ProductAnalysis_createdAt_idx" ON "ProductAnalysis"("createdAt");

-- CreateIndex
CREATE INDEX "StaticCreativeSuggestion_projectId_idx" ON "StaticCreativeSuggestion"("projectId");

-- CreateIndex
CREATE INDEX "StaticCreativeSuggestion_createdAt_idx" ON "StaticCreativeSuggestion"("createdAt");

-- CreateIndex
CREATE INDEX "VideoScript_projectId_idx" ON "VideoScript"("projectId");

-- CreateIndex
CREATE INDEX "VideoScript_createdAt_idx" ON "VideoScript"("createdAt");

-- CreateIndex
CREATE INDEX "ViralVideoAnalysis_projectId_idx" ON "ViralVideoAnalysis"("projectId");

-- CreateIndex
CREATE INDEX "ViralVideoAnalysis_createdAt_idx" ON "ViralVideoAnalysis"("createdAt");

-- AddForeignKey
ALTER TABLE "Project" ADD CONSTRAINT "Project_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProductAsset" ADD CONSTRAINT "ProductAsset_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProductAnalysis" ADD CONSTRAINT "ProductAnalysis_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaticCreativeSuggestion" ADD CONSTRAINT "StaticCreativeSuggestion_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "VideoScript" ADD CONSTRAINT "VideoScript_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ViralVideoAnalysis" ADD CONSTRAINT "ViralVideoAnalysis_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;
