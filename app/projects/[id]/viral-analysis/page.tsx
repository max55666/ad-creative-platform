import { notFound } from "next/navigation";
import { ProjectNav } from "@/components/project-nav";
import { ViralAnalysisClient } from "@/components/viral-analysis-client";
import { getProjectWithHistory } from "@/lib/projects";

export const dynamic = "force-dynamic";

export default async function ViralAnalysisPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await getProjectWithHistory(id);
  if (!project) notFound();

  const videoAsset = project.assets.find((asset: any) => asset.type === "video");

  return (
    <div>
      <ProjectNav projectId={project.id} />
      <ViralAnalysisClient
        projectId={project.id}
        initialAnalyses={JSON.parse(JSON.stringify(project.viralAnalyses))}
        initialVideoUrl={videoAsset?.fileUrl || null}
      />
    </div>
  );
}
