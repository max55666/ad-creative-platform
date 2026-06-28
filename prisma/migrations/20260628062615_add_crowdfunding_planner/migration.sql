-- CreateTable
CREATE TABLE "CrowdfundingCaseAnalysis" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "sourceUrl" TEXT,
    "title" TEXT,
    "platform" TEXT NOT NULL DEFAULT 'zeczec',
    "scrapedPage" JSONB,
    "structure" JSONB NOT NULL,
    "visualStrategy" JSONB NOT NULL,
    "copywriting" JSONB NOT NULL,
    "conversionInsights" JSONB NOT NULL,
    "reusableTemplate" JSONB NOT NULL,
    "rawOutput" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CrowdfundingCaseAnalysis_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CrowdfundingPagePlan" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "caseAnalysisId" TEXT,
    "mode" TEXT NOT NULL DEFAULT 'from_product',
    "targetPlatform" TEXT NOT NULL DEFAULT 'zeczec',
    "title" TEXT NOT NULL,
    "hero" JSONB NOT NULL,
    "pageSections" JSONB NOT NULL,
    "imageBriefs" JSONB NOT NULL,
    "copywriting" JSONB NOT NULL,
    "rewardStrategy" JSONB,
    "faq" JSONB,
    "conversionScore" JSONB,
    "rawOutput" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CrowdfundingPagePlan_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "CrowdfundingCaseAnalysis_projectId_idx" ON "CrowdfundingCaseAnalysis"("projectId");

-- CreateIndex
CREATE INDEX "CrowdfundingCaseAnalysis_platform_idx" ON "CrowdfundingCaseAnalysis"("platform");

-- CreateIndex
CREATE INDEX "CrowdfundingCaseAnalysis_createdAt_idx" ON "CrowdfundingCaseAnalysis"("createdAt");

-- CreateIndex
CREATE INDEX "CrowdfundingPagePlan_projectId_idx" ON "CrowdfundingPagePlan"("projectId");

-- CreateIndex
CREATE INDEX "CrowdfundingPagePlan_caseAnalysisId_idx" ON "CrowdfundingPagePlan"("caseAnalysisId");

-- CreateIndex
CREATE INDEX "CrowdfundingPagePlan_targetPlatform_idx" ON "CrowdfundingPagePlan"("targetPlatform");

-- CreateIndex
CREATE INDEX "CrowdfundingPagePlan_createdAt_idx" ON "CrowdfundingPagePlan"("createdAt");

-- AddForeignKey
ALTER TABLE "CrowdfundingCaseAnalysis" ADD CONSTRAINT "CrowdfundingCaseAnalysis_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CrowdfundingPagePlan" ADD CONSTRAINT "CrowdfundingPagePlan_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CrowdfundingPagePlan" ADD CONSTRAINT "CrowdfundingPagePlan_caseAnalysisId_fkey" FOREIGN KEY ("caseAnalysisId") REFERENCES "CrowdfundingCaseAnalysis"("id") ON DELETE SET NULL ON UPDATE CASCADE;
