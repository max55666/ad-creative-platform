-- CreateTable
CREATE TABLE "KolProfile" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "projectId" TEXT,
    "name" TEXT NOT NULL,
    "platform" TEXT NOT NULL,
    "profileUrl" TEXT NOT NULL,
    "description" TEXT,
    "followerCount" TEXT,
    "avgViews" TEXT,
    "avgEngagement" TEXT,
    "tags" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "KolProfile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "KolVideo" (
    "id" TEXT NOT NULL,
    "kolProfileId" TEXT NOT NULL,
    "videoUrl" TEXT,
    "fileUrl" TEXT,
    "title" TEXT,
    "sponsoredBrand" TEXT,
    "sponsoredProduct" TEXT,
    "transcript" JSONB,
    "notes" TEXT,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "KolVideo_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "KolAnalysis" (
    "id" TEXT NOT NULL,
    "kolProfileId" TEXT NOT NULL,
    "userId" TEXT,
    "projectId" TEXT,
    "persona" JSONB NOT NULL,
    "contentStyle" JSONB NOT NULL,
    "audienceProfile" JSONB NOT NULL,
    "brandFit" JSONB NOT NULL,
    "productFit" JSONB NOT NULL,
    "sponsoredVideoInsights" JSONB NOT NULL,
    "suitableProducts" JSONB NOT NULL,
    "riskAssessment" JSONB NOT NULL,
    "recommendations" JSONB NOT NULL,
    "rawOutput" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "KolAnalysis_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "KolScript" (
    "id" TEXT NOT NULL,
    "kolProfileId" TEXT NOT NULL,
    "userId" TEXT,
    "projectId" TEXT,
    "title" TEXT NOT NULL,
    "platform" TEXT NOT NULL,
    "objective" TEXT NOT NULL,
    "duration" TEXT NOT NULL,
    "hook" TEXT NOT NULL,
    "storyline" JSONB NOT NULL,
    "captions" JSONB NOT NULL,
    "voiceover" JSONB NOT NULL,
    "shotList" JSONB NOT NULL,
    "cta" TEXT NOT NULL,
    "adUsageNotes" JSONB,
    "rawOutput" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "KolScript_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "KolProfile_userId_idx" ON "KolProfile"("userId");

-- CreateIndex
CREATE INDEX "KolProfile_projectId_idx" ON "KolProfile"("projectId");

-- CreateIndex
CREATE INDEX "KolProfile_platform_idx" ON "KolProfile"("platform");

-- CreateIndex
CREATE INDEX "KolProfile_createdAt_idx" ON "KolProfile"("createdAt");

-- CreateIndex
CREATE INDEX "KolVideo_kolProfileId_idx" ON "KolVideo"("kolProfileId");

-- CreateIndex
CREATE INDEX "KolVideo_createdAt_idx" ON "KolVideo"("createdAt");

-- CreateIndex
CREATE INDEX "KolAnalysis_kolProfileId_idx" ON "KolAnalysis"("kolProfileId");

-- CreateIndex
CREATE INDEX "KolAnalysis_userId_idx" ON "KolAnalysis"("userId");

-- CreateIndex
CREATE INDEX "KolAnalysis_projectId_idx" ON "KolAnalysis"("projectId");

-- CreateIndex
CREATE INDEX "KolAnalysis_createdAt_idx" ON "KolAnalysis"("createdAt");

-- CreateIndex
CREATE INDEX "KolScript_kolProfileId_idx" ON "KolScript"("kolProfileId");

-- CreateIndex
CREATE INDEX "KolScript_userId_idx" ON "KolScript"("userId");

-- CreateIndex
CREATE INDEX "KolScript_projectId_idx" ON "KolScript"("projectId");

-- CreateIndex
CREATE INDEX "KolScript_createdAt_idx" ON "KolScript"("createdAt");

-- AddForeignKey
ALTER TABLE "KolProfile" ADD CONSTRAINT "KolProfile_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolProfile" ADD CONSTRAINT "KolProfile_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolVideo" ADD CONSTRAINT "KolVideo_kolProfileId_fkey" FOREIGN KEY ("kolProfileId") REFERENCES "KolProfile"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolAnalysis" ADD CONSTRAINT "KolAnalysis_kolProfileId_fkey" FOREIGN KEY ("kolProfileId") REFERENCES "KolProfile"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolAnalysis" ADD CONSTRAINT "KolAnalysis_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolAnalysis" ADD CONSTRAINT "KolAnalysis_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolScript" ADD CONSTRAINT "KolScript_kolProfileId_fkey" FOREIGN KEY ("kolProfileId") REFERENCES "KolProfile"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolScript" ADD CONSTRAINT "KolScript_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KolScript" ADD CONSTRAINT "KolScript_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE SET NULL ON UPDATE CASCADE;
