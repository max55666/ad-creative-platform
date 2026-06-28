export type UrlContext = {
  url: string;
  title?: string;
  description?: string;
  images: string[];
  textSample: string;
  error?: string;
};

export async function extractUrlContext(url?: string | null): Promise<UrlContext | null> {
  if (!url) return null;

  try {
    const response = await fetch(url, {
      headers: {
        "user-agent": "Mozilla/5.0 AdCreativeIntelligenceBot/0.1"
      },
      next: { revalidate: 0 }
    });

    if (!response.ok) {
      return {
        url,
        images: [],
        textSample: "",
        error: `Fetch failed with status ${response.status}`
      };
    }

    const html = await response.text();
    const title = matchMeta(html, /<title[^>]*>([\s\S]*?)<\/title>/i);
    const description =
      matchMeta(html, /<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["'][^>]*>/i) ||
      matchMeta(html, /<meta[^>]+property=["']og:description["'][^>]+content=["']([^"']+)["'][^>]*>/i);
    const images = Array.from(html.matchAll(/<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["'][^>]*>/gi))
      .map((match) => match[1])
      .slice(0, 8);
    const textSample = html
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 5000);

    return { url, title, description, images, textSample };
  } catch (error) {
    return {
      url,
      images: [],
      textSample: "",
      error: error instanceof Error ? error.message : "Unable to fetch URL"
    };
  }
}

function matchMeta(html: string, pattern: RegExp) {
  const match = html.match(pattern);
  return match?.[1]?.replace(/\s+/g, " ").trim();
}
