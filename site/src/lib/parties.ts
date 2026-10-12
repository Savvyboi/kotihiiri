// Council groups (valtuustoryhmät) mapped to parties. Sources print groups differently:
// Helsinki's vote tables say "Kokoomuksen valtuustoryhmä", other lists use "Kok." or "KOK".
import type { Key } from '../i18n';

export type Party = 'vas' | 'sdp' | 'vihr' | 'rkp' | 'kesk' | 'kok' | 'kd' | 'liik' | 'ps' | 'other' | 'none';

/** Left-to-right order used for seat charts and group lists. */
export const PARTY_ORDER: Party[] = ['vas', 'sdp', 'vihr', 'rkp', 'kesk', 'kok', 'kd', 'liik', 'ps', 'other', 'none'];

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
  [/liike nyt|^liik\b|rörelse nu/i, 'liik'],
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
  other: '#8a8d99',
  none: '#b4b6c0',
};

/** Short labels for chips; the full name goes in the accessible text. */
export const PARTY_ABBR: Record<Party, string> = {
  kok: 'KOK', sdp: 'SDP', ps: 'PS', kesk: 'KESK', vihr: 'VIHR', vas: 'VAS',
  rkp: 'RKP', kd: 'KD', liik: 'LIIK', other: '…', none: '–',
};

export const partyKey = (p: Party) => `party.${p}` as Key;

export function partyColour(group: string | undefined | null): string {
  const p = partyOf(group);
  return p ? PARTY_COLOURS[p] : 'var(--c-muted)';
}
