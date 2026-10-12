// City coats of arms and hero photos with their credits. Written by scripts/fetch_city_images.py;
// a city without an entry simply renders without images.

export interface ImageCredit {
  title: string; page_url: string; sha1: string; width: number; height: number;
  licence: string; licence_name: string; licence_url: string | null; author: string | null;
  files: string[]; description?: string | null;
}
export interface CityImages { arms?: ImageCredit; photo?: ImageCredit }

// A glob, so a checkout without the file still builds.
const files = import.meta.glob<Record<string, CityImages>>('../data/city-images.json', { eager: true, import: 'default' });
const all: Record<string, CityImages> = Object.values(files)[0] ?? {};

export function cityImages(city: string): CityImages {
  return all[city] ?? {};
}

/** "Author" as printed on Commons, trimmed for a one-line credit. */
export function shortAuthor(c: ImageCredit): string {
  const a = (c.author ?? '').replace(/\s*\(talk\)|\s*\[.*?\]/gi, '').trim();
  return a.length > 60 ? `${a.slice(0, 57)}…` : a || 'Wikimedia Commons';
}
