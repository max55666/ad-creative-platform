import { SettingsClient } from "@/components/settings-client";
import { getSystemSettings, settingsOptions } from "@/lib/settings";

export default async function SettingsPage() {
  const settings = await getSystemSettings();
  return <SettingsClient initialSettings={settings} options={settingsOptions} />;
}
