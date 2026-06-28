import { NextRequest, NextResponse } from "next/server";
import { getSystemSettings, saveSystemSettings, settingsOptions } from "@/lib/settings";

export async function GET() {
  const settings = await getSystemSettings();
  return NextResponse.json({ settings, options: settingsOptions });
}

export async function PUT(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const settings = await saveSystemSettings(body.settings || body);
  return NextResponse.json({ settings, options: settingsOptions });
}
