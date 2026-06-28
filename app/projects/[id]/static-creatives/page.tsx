import { notFound } from "next/navigation";
import { ProjectNav } from "@/components/project-nav";
import { ReferenceAssetManager } from "@/components/reference-asset-manager";
import { StaticCreativeClient } from "@/components/static-creative-client";
import { getProjectWithHistory } from "@/lib/projects";

export const dynamic = "force-dynamic";

export default async function StaticCreativesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await getProjectWithHistory(id);
  if (!project) notFound();

  return (
    <div>
      <ProjectNav projectId={project.id} />
      <div className="mb-5">
        <ReferenceAssetManager
          projectId={project.id}
          initialAssets={JSON.parse(JSON.stringify(project.assets || []))}
          initialRequiredObjects={[]}
        />
      </div>
      <StaticCreativeClient
        projectId={project.id}
        initialSuggestions={JSON.parse(JSON.stringify(project.staticCreatives))}
      />
    </div>
  );
}
