import { prisma } from "@/lib/db";
import { ProjectNav } from "@/components/project-nav";
import { ProductLoraClient } from "@/components/product-lora-client";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function ProductLoraModelsPage({ params }: Props) {
  const { id } = await params;
  const project = await prisma.project.findUnique({
    where: { id },
    include: {
      assets: { orderBy: { createdAt: "desc" } },
      productLoraModels: { orderBy: { createdAt: "desc" } }
    }
  });

  if (!project) {
    return <main className="mx-auto max-w-6xl px-6 py-8">Project not found.</main>;
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <ProjectNav projectId={project.id} />
      <ProductLoraClient
        projectId={project.id}
        projectName={project.productName}
        initialAssets={project.assets}
        initialModels={project.productLoraModels}
      />
    </main>
  );
}
