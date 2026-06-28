-- CreateTable
CREATE TABLE "Competitor" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "brandId" TEXT,
    "projectId" TEXT,
    "name" TEXT NOT NULL,
    "websiteUrl" TEXT,
    "productUrl" TEXT,
    "industry" TEXT,
    "targetMarket" TEXT,
    "description" TEXT,
    "priceRange" TEXT,
    "tags" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Competitor_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CompetitorAnalysis" (
    "id" TEXT NOT NULL,
    "competitorId" TEXT NOT NULL,
    "summary" JSONB NOT NULL,
    "positioning" JSONB NOT NULL,
    "productOffer" JSONB NOT NULL,
    "audience" JSONB NOT NULL,
    "messaging" JSONB NOT NULL,
    "landingPage" JSONB NOT NULL,
    "creativeAngles" JSONB NOT NULL,
    "opportunities" JSONB NOT NULL,
    "risks" JSONB NOT NULL,
    "rawOutput" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CompetitorAnalysis_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "Competitor_userId_idx" ON "Competitor"("userId");

-- CreateIndex
CREATE INDEX "Competitor_brandId_idx" ON "Competitor"("brandId");

-- CreateIndex
CREATE INDEX "Competitor_projectId_idx" ON "Competitor"("projectId");

-- CreateIndex
CREATE INDEX "Competitor_industry_idx" ON "Competitor"("industry");

-- CreateIndex
CREATE INDEX "Competitor_createdAt_idx" ON "Competitor"("createdAt");

-- CreateIndex
CREATE INDEX "CompetitorAnalysis_competitorId_idx" ON "CompetitorAnalysis"("competitorId");

-- CreateIndex
CREATE INDEX "CompetitorAnalysis_createdAt_idx" ON "CompetitorAnalysis"("createdAt");

-- AddForeignKey
ALTER TABLE "Competitor" ADD CONSTRAINT "Competitor_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Competitor" ADD CONSTRAINT "Competitor_brandId_fkey" FOREIGN KEY ("brandId") REFERENCES "Brand"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Competitor" ADD CONSTRAINT "Competitor_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CompetitorAnalysis" ADD CONSTRAINT "CompetitorAnalysis_competitorId_fkey" FOREIGN KEY ("competitorId") REFERENCES "Competitor"("id") ON DELETE CASCADE ON UPDATE CASCADE;
