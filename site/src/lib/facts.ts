// Municipal key figures (Kuntien avainluvut) from Statistics Finland. Written by `kunta facts`
// (kunta/facts.py); a municipality without an entry renders without the section.
import type { Locale } from '../i18n';

export interface Figure { code: string; label: Record<string, string>; decimals: number; order: number }
export interface FactsFile {
  source: {
    publisher: string; table: string; title: Record<string, string>; updated: string | null;
    api_url: string; page_url: Record<string, string>; licence: string;
  };
  figures: Figure[];
  country: Record<string, number | null>;
  municipalities: Record<string, { area_code: string; values: Record<string, number | null> }>;
}

// A glob, so a checkout without the file still builds.
const files = import.meta.glob<FactsFile>('../data/municipality-facts.json', { eager: true, import: 'default' });
const file: FactsFile | undefined = Object.values(files)[0];

export interface FactRow { code: string; name: string; unit: string; year: string; value: number; country: number | null; decimals: number }

/** "Väkiluku, 2025" → name, unit "", year; "Ruotsinkielisten osuus väestöstä, %, 2025" → unit "%". */
export function splitLabel(label: string): { name: string; unit: string; year: string } {
  const parts = label.split(/,\s+/);
  const year = /^\d{4}$/.test(parts.at(-1) ?? '') ? parts.pop()! : '';
  const unit = parts.length > 1 ? parts.pop()! : '';
  return { name: parts.join(', '), unit, year };
}

export function municipalityFacts(city: string, locale: Locale): FactRow[] {
  const m = file?.municipalities[city];
  if (!file || !m) return [];
  return [...file.figures]
    .sort((a, b) => a.order - b.order)
    .flatMap((f) => {
      const value = m.values[f.code];
      if (value == null) return [];
      const { name, unit, year } = splitLabel(f.label[locale] ?? f.label.fi);
      return [{ code: f.code, name, unit, year, value, country: file.country[f.code] ?? null, decimals: f.decimals }];
    });
}

export function factsSource(): FactsFile['source'] | undefined {
  return file?.source;
}
