// Per-city visual identity. Colours are drafts drawn from each city's character and
// public visual identity; check them against the official brand guidelines before launch.
// CSS custom properties for each city live in src/styles/themes.css under [data-city="…"].

export interface CityTheme {
  /** One-line character sketch shown on the city hero. */
  motto: string;
  /** Short note on where the palette comes from, shown on /tietoa/. */
  inspiration: string;
  /** Inline SVG motif (viewBox 0 0 120 60), drawn with currentColor. */
  motif: string;
}

export const THEMES: Record<string, CityTheme> = {
  helsinki: {
    motto: 'Meren kaupunki',
    inspiration: 'Helsingin sininen ja kultainen kruunu vaakunan aalloilta.',
    motif: `<path d="M0 44c10-8 20-8 30 0s20 8 30 0 20-8 30 0 20 8 30 0" fill="none" stroke="currentColor" stroke-width="4"/>
      <path d="M0 54c10-8 20-8 30 0s20 8 30 0 20-8 30 0 20 8 30 0" fill="none" stroke="currentColor" stroke-width="4" opacity=".55"/>
      <path d="M44 30l4-16 8 9 4-13 4 13 8-9 4 16z" fill="var(--c-accent)"/>`,
  },
  espoo: {
    motto: 'Metsän ja meren välissä',
    inspiration: 'Nuuksion kuusikoiden vihreä ja ilta-auringon kulta.',
    motif: `<path d="M18 52l12-36 12 36zM48 52l14-44 14 44zM80 52l11-30 11 30z" fill="currentColor"/>
      <rect x="0" y="52" width="120" height="4" fill="var(--c-accent)"/>`,
  },
  tampere: {
    motto: 'Koskien ja tiilipiippujen kaupunki',
    inspiration: 'Tehdasperinnön punatiili ja Tammerkosken tumma vesi.',
    motif: `<path d="M8 56V30l16-8v8l16-8v8l16-8v34z" fill="currentColor"/>
      <rect x="62" y="8" width="8" height="48" fill="currentColor"/>
      <rect x="78" y="18" width="7" height="38" fill="currentColor" opacity=".7"/>
      <path d="M90 50c8-4 14 4 22 0s8 4 8 4" fill="none" stroke="var(--c-accent)" stroke-width="4"/>`,
  },
  vantaa: {
    motto: 'Joen ja lentokentän kaupunki',
    inspiration: 'Vantaanjoen vihreänsininen ja lentoaseman valojen korallinpuna.',
    motif: `<path d="M0 50C30 36 40 58 70 44s40-6 50-14" fill="none" stroke="currentColor" stroke-width="6"/>
      <path d="M78 14l26-6-8 6 10 4-4 2-10-3-8 9-4 1 4-10z" fill="var(--c-accent)"/>`,
  },
  oulu: {
    motto: 'Pohjoinen tervan ja teknologian kaupunki',
    inspiration: 'Tervan tumma sini ja revontulten hehku.',
    motif: `<path d="M0 30C20 10 40 26 60 14s40 6 60-8" fill="none" stroke="var(--c-accent)" stroke-width="5" opacity=".9"/>
      <path d="M0 40C24 24 44 36 64 26s36 2 56-6" fill="none" stroke="currentColor" stroke-width="3" opacity=".5"/>
      <path d="M10 56h100M20 56v-8h80v8" fill="none" stroke="currentColor" stroke-width="4"/>`,
  },
  turku: {
    motto: 'Aurajoen vanhin kaupunki',
    inspiration: 'Vaakunan punainen ja kultainen A sekä tuomiokirkon torni.',
    motif: `<path d="M56 56V22l6-14 6 14v34z" fill="currentColor"/>
      <rect x="40" y="34" width="16" height="22" fill="currentColor" opacity=".8"/>
      <rect x="68" y="34" width="16" height="22" fill="currentColor" opacity=".8"/>
      <path d="M0 58c20-4 40 4 60 0s40-4 60 0" fill="none" stroke="var(--c-accent)" stroke-width="4"/>`,
  },
};

/** Party / council-group colours for vote breakdowns, keyed by common abbreviations. */
export const GROUP_COLOURS: Record<string, string> = {
  KOK: '#006288',
  SDP: '#e11931',
  PS: '#ffde55',
  KESK: '#349a2b',
  VIHR: '#61bf1a',
  VAS: '#f00a64',
  RKP: '#ffdd93',
  KD: '#2b67c9',
  LIIK: '#b40078',
};

export function groupColour(group: string | undefined): string {
  if (!group) return 'var(--c-muted)';
  const key = group.toUpperCase().split(/[\s.]/)[0];
  return GROUP_COLOURS[key] ?? 'var(--c-muted)';
}
