import { mkdir, writeFile } from "fs/promises";
import path from "path";
import { missingPackageMessage, optionalImport } from "@/lib/services/runtime-import";
import { getStorage } from "@/lib/storage";

export async function scrapeProductPage({
  url,
  projectId
}: {
  url: string;
  projectId: string;
}) {
  return scrapeAnyPage({
    url,
    storageKey: `scrapes/${projectId}`
  });
}

export async function scrapeAnyPage({
  url,
  storageKey
}: {
  url: string;
  storageKey: string;
}) {
  const playwrightModule = await optionalImport<any>("playwright");
  if (!playwrightModule?.chromium) {
    throw new Error(missingPackageMessage("playwright"));
  }

  const browser = await playwrightModule.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1365, height: 1800 } });

  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
    const title = await page.title();
    const data = await page.evaluate(() => {
      const text = document.body.innerText.replace(/\s+/g, " ").trim().slice(0, 12000);
      const images = Array.from(document.images)
        .map((img) => ({
          src: img.currentSrc || img.src,
          alt: img.alt,
          width: img.naturalWidth,
          height: img.naturalHeight
        }))
        .filter((img) => img.src && img.width >= 180 && img.height >= 180)
        .slice(0, 20);
      return { text, images };
    });

    const outputDir = getStorage().getLocalPath(storageKey);
    await mkdir(outputDir, { recursive: true });
    const screenshotName = `${Date.now()}-page.png`;
    const screenshotPath = path.join(outputDir, screenshotName);
    await page.screenshot({ path: screenshotPath, fullPage: true });

    const result = {
      url,
      title,
      text: data.text,
      images: data.images,
      screenshotUrl: getStorage().getPublicUrl(`${storageKey}/${screenshotName}`)
    };

    await writeFile(path.join(outputDir, `${Date.now()}-scrape.json`), JSON.stringify(result, null, 2), "utf8");
    return result;
  } finally {
    await browser.close();
  }
}
