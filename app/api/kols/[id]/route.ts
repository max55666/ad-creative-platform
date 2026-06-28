import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getDemoUser } from "@/lib/projects";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: Request, { params }: Params) {
  const { id } = await params;
  const user = await getDemoUser();
  const profile = await prisma.kolProfile.findFirst({
    where: { id, userId: user.id },
    include: {
      project: true,
      videos: { orderBy: { createdAt: "desc" } },
      analyses: { orderBy: { createdAt: "desc" } },
      scripts: { orderBy: { createdAt: "desc" }, include: { project: true } }
    }
  });

  if (!profile) {
    return NextResponse.json({ message: "KOL profile not found" }, { status: 404 });
  }

  return NextResponse.json({ profile });
}
