export async function optionalImport<T = any>(packageName: string): Promise<T | null> {
  try {
    const importer = new Function("name", "return import(name)") as (name: string) => Promise<T>;
    return await importer(packageName);
  } catch {
    return null;
  }
}

export function missingPackageMessage(packageName: string) {
  return `Missing optional package "${packageName}". Install it with: pnpm add ${packageName}`;
}
