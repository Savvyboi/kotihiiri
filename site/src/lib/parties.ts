// Council groups (valtuustoryhmät) mapped to parties. Sources print groups differently:
// Helsinki's vote tables say "Kokoomuksen valtuustoryhmä", other lists use "Kok." or "KOK";
// Statistics Finland's candidate tables use KOK, LIIKE, LIBE and so on.
import type { Key } from '../i18n';

export type Party = 'vas' | 'sdp' | 'vihr' | 'rkp' | 'kesk' | 'lib' | 'kok' | 'kd' | 'liik' | 'ps' | 'other' | 'none';

/** Left-to-right order used for seat charts and group lists. */
export const PARTY_ORDER: Party[] = ['vas', 'sdp', 'vihr', 'rkp', 'kesk', 'lib', 'kok', 'kd', 'liik', 'ps', 'other', 'none'];

const RULES: [RegExp, Party][] = [
  [/^(ei valtuustoryhm|ingen grupp|sitoutumat)/i, 'none'],
  [/kokoomu|^kok\b|samlingspart/i, 'kok'],
  [/sosialidemokra|^sdp\b|socialdemokrat/i, 'sdp'],
  [/vihre|^vihr\b|gröna/i, 'vihr'],
  [/vasemmisto|^vas\b|vänsterförb/i, 'vas'],
  [/perussuomala|^ps\b|sannfinländ/i, 'ps'],
  [/ruotsalai|^rkp\b|svenska folkpart|^sfp\b/i, 'rkp'],
  [/keskusta|^kesk\b|centern/i, 'kesk'],
  [/kristillis|^kd\b|kristdemokrat/i, 'kd'],
  [/liike nyt|^liik(e)?\b|rörelse nu/i, 'liik'],
  [/liberaalipuolue|^lib(e)?\b|liberala partiet/i, 'lib'],
];

export function partyOf(group: string | undefined | null): Party | undefined {
  if (!group) return undefined;
  const g = group.trim();
  for (const [re, p] of RULES) if (re.test(g)) return p;
  return 'other';
}

export const PARTY_COLOURS: Record<Party, string> = {
  kok: '#006288',
  sdp: '#e11931',
  ps: '#f5c800',
  kesk: '#349a2b',
  vihr: '#61bf1a',
  vas: '#f00a64',
  rkp: '#f6c75a',
  kd: '#2b67c9',
  liik: '#b40078',
  lib: '#f28c00',
  other: '#8a8d99',
  none: '#b4b6c0',
};

/** Short labels for chips; the full name goes in the accessible text. */
export const PARTY_ABBR: Record<Party, string> = {
  kok: 'KOK', sdp: 'SDP', ps: 'PS', kesk: 'KESK', vihr: 'VIHR', vas: 'VAS',
  rkp: 'RKP', kd: 'KD', liik: 'LIIK', lib: 'LIB', other: '…', none: '–',
};

export const partyKey = (p: Party) => `party.${p}` as Key;

export function partyColour(group: string | undefined | null): string {
  const p = partyOf(group);
  return p ? PARTY_COLOURS[p] : 'var(--c-muted)';
}

/** True when dark text contrasts better than white on this colour (PS, RKP, Vihr., Kesk., Lib.). */
export function lightColour(hex: string): boolean {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  const l = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return (l + 0.05) / 0.0623 > 1.05 / (l + 0.05); // #1d1d1f against #fff
}
