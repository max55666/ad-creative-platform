import { ProductAnalysisForm } from "@/components/product-analysis-form";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";

export const dynamic = "force-dynamic";

export default async function NewProjectPage() {
  const user = await getDemoUser();
  const brands = await prisma.brand.findMany({
    where: { userId: user.id },
    orderBy: { updatedAt: "desc" },
    select: { id: true, name: true }
  });

  return (
    <div className="mx-auto max-w-4xl">
      <ProductAnalysisForm brands={brands} />
    </div>
  );
}
