// Municipality boundaries for the map (/kartta/), written by scripts/fetch_municipality_map.py from
// Statistics Finland's open data. A checkout without the file still builds; the map page then says
// the map is not available.

export interface MapShape { code: string; name_fi: string; name_sv?: string; id?: string; d: string;
  /** Inset only: where the name label goes. */
  label?: [number, number] }
export interface MunicipalityMap {
  source: string; source_url: string; licence: string; year: number; layers: string[]; unit_m: number;
  viewbox: [number, number, number, number]; municipalities: MapShape[];
  inset?: { viewbox: [number, number, number, number]; municipalities: MapShape[] };
}

const files = import.meta.glob<MunicipalityMap>('../data/municipality-map.json', { eager: true, import: 'default' });
export const MUNICIPALITY_MAP: MunicipalityMap | undefined = Object.values(files)[0];

/** Map name in the UI language: Swedish where Statistics Finland gives one, Finnish otherwise. */
export function shapeName(s: MapShape, locale: string): string {
  return locale === 'sv' && s.name_sv ? s.name_sv : s.name_fi;
}
