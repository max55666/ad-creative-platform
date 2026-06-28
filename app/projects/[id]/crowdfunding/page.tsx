import { notFound } from "next/navigation";
import { CrowdfundingClient } from "@/components/crowdfunding-client";
import { ProjectNav } from "@/components/project-nav";
import { getProjectWithHistory } from "@/lib/projects";

export const dynamic = "force-dynamic";

export default async function CrowdfundingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await getProjectWithHistory(id);
  if (!project) notFound();

  return (
    <div className="grid gap-5">
      <ProjectNav projectId={project.id} />
      <CrowdfundingClient
        projectId={project.id}
        initialCases={JSON.parse(JSON.stringify(project.crowdfundingCaseAnalyses || []))}
        initialPlans={JSON.parse(JSON.stringify(project.crowdfundingPagePlans || []))}
      />
    </div>
  );
}
