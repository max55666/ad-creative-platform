import { prisma } from "@/lib/db";

const DEMO_USER_EMAIL = "demo@internal.local";

export async function getDemoUser() {
  return prisma.user.upsert({
    where: { email: DEMO_USER_EMAIL },
    update: {},
    create: {
      name: "Internal Team",
      email: DEMO_USER_EMAIL
    }
  });
}

export async function getProjectWithHistory(id: string) {
  return prisma.project.findUnique({
    where: { id },
    include: {
      assets: { orderBy: { createdAt: "desc" } },
      analyses: { orderBy: { createdAt: "desc" } },
      staticCreatives: { orderBy: { createdAt: "desc" } },
      videoScripts: { orderBy: { createdAt: "desc" } },
      viralAnalyses: { orderBy: { createdAt: "desc" } },
      crowdfundingCaseAnalyses: { orderBy: { createdAt: "desc" } },
      crowdfundingPagePlans: { orderBy: { createdAt: "desc" } },
      generationJobs: { orderBy: { createdAt: "desc" }, take: 20 },
      providerUsageLogs: { orderBy: { createdAt: "desc" }, take: 50 },
      creatives: {
        orderBy: { updatedAt: "desc" },
        include: {
          versions: { orderBy: { version: "desc" }, include: { assets: true } },
          assets: { orderBy: { createdAt: "desc" } }
        }
      }
    }
  });
}
