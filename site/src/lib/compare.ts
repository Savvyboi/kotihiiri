// Every statistic we hold on the municipalities, one row per municipality (/vertailu/): Statistics
// Finland's key figures, the State Treasury budget per resident, and our own counts of meetings,
// votes, councillors and kuntalaisaloitteet. Missing values are null and sort last.
import type { Locale } from '../i18n';
import { cities, cityName, cityStats, type City } from './data';
import { SUMMARY, budget, budgetItems, budgetYears, population, value } from './budget';
import { councillorRows } from './councillors';
import { initiativeFile } from './initiatives';

const factFiles = import.meta.glob<{
  figures: { code: string; label: Record<string, string>; decimals: number; order: number }[];
  country: Record<string, number | null>;
  municipalities: Record<string, { values: Record<string, number | null> }>;
}>('../data/municipality-facts.json', { eager: true, import: 'default' });
const facts = Object.values(factFiles)[0];

export type Group = 'people' | 'work' | 'budget' | 'decisions';
export const GROUPS: Group[] = ['people', 'work', 'budget', 'decisions'];

export interface Column {
  key: string; group: Group;
  /** Header text and the small line under it (unit, year), already translated where the source is. */
  label: string; sub: string;
  /** i18n key for labels we translate ourselves; the page resolves it. */
  labelKey?: string; subKey?: string; subVars?: Record<string, string | number>;
  decimals: number; percent: boolean;
  /** Shown before the reader picks columns. */
  initial: boolean;
}

export interface Row { city: City; name: string; values: Record<string, number | null> }

// The columns a first-time reader sees: size, age, language, jobs, the tax rate and spending,
// and how much of the municipality's decision-making this site follows.
const INITIAL = new Set(['M411', 'M476', 'M478', 'M404', 'M486', 'M162', 'b:tax', 'b:expenses', 'b:loans', 'meetings', 'votes', 'initiatives']);

/** Statistics Finland's figures in their own order: population and housing first, then education and work. */
const WORK_FROM = 'M488';

/** "Väkiluku, 2025" → name, unit "", year; "Ruotsinkielisiä, %, 2025" → unit "%". */
function split(label: string) {
  const parts = label.split(/,\s+/);
  const year = /^\d{4}$/.test(parts.at(-1) ?? '') ? parts.pop()! : '';
  const unit = parts.length > 1 ? parts.pop()! : '';
  return { name: parts.join(', '), unit, year };
}

export function budgetYear(): number | undefined {
  return budgetYears(cities().map((c) => c.id))[0];
}

export function compareColumns(locale: Locale): Column[] {
  const cols: Column[] = [];
  if (facts) {
    const figs = [...facts.figures].sort((a, b) => a.order - b.order);
    const workOrder = figs.find((f) => f.code === WORK_FROM)?.order ?? Infinity;
    for (const f of figs) {
      const { name, unit, year } = split(f.label[locale] ?? f.label.fi);
      cols.push({
        key: f.code, group: f.order >= workOrder ? 'work' : 'people', label: name,
        sub: [unit === '%' ? '%' : unit, year].filter(Boolean).join(', '),
        decimals: f.decimals, percent: unit === '%', initial: INITIAL.has(f.code),
      });
    }
  }
  const year = budgetYear();
  if (year) {
    for (const m of SUMMARY) {
      cols.push({ key: `b:${m.id}`, group: 'budget', label: '', labelKey: m.label, sub: '', subKey: 'cmp.sub.perResident', subVars: { year },
        decimals: 0, percent: false, initial: INITIAL.has(`b:${m.id}`) });
    }
    for (const m of SUMMARY) {
      cols.push({ key: `b:${m.id}:total`, group: 'budget', label: '', labelKey: m.label, sub: '', subKey: 'cmp.sub.millions', subVars: { year },
        decimals: 1, percent: false, initial: false });
    }
    cols.push({ key: 'b:tax-rate', group: 'budget', label: '', labelKey: 'cmp.col.taxRate', sub: '', subKey: 'cmp.sub.pctYear', subVars: { year },
      decimals: 2, percent: true, initial: INITIAL.has('b:tax-rate') });
    cols.push({ key: 'b:staff', group: 'budget', label: '', labelKey: 'cmp.col.staff', sub: '', subKey: 'cmp.sub.per1000', subVars: { year },
      decimals: 1, percent: false, initial: INITIAL.has('b:staff') });
  }
  const ours: [string, string, string][] = [
    ['meetings', 'cmp.col.meetings', 'cmp.sub.stored'],
    ['items', 'cmp.col.items', 'cmp.sub.stored'],
    ['votes', 'cmp.col.votes', 'cmp.sub.stored'],
    ['councillors', 'cmp.col.councillors', 'cmp.sub.term'],
    ['initiatives', 'cmp.col.initiatives', 'cmp.sub.kuntalaisaloite'],
    ['initiativesPer', 'cmp.col.initiativesPer', 'cmp.sub.per10000'],
    ['supporters', 'cmp.col.supporters', 'cmp.sub.kuntalaisaloite'],
  ];
  for (const [key, labelKey, subKey] of ours) {
    cols.push({ key, group: 'decisions', label: '', labelKey, sub: '', subKey, decimals: key === 'initiativesPer' ? 1 : 0, percent: false, initial: INITIAL.has(key) });
  }
  return cols;
}

const lineKey = (re: RegExp) => budgetItems()?.lines.find((l) => re.test(l.fi))?.key;

export function compareRows(locale: Locale): Row[] {
  const year = budgetYear();
  const summaryKeys = SUMMARY.map((m) => [m.id, lineKey(m.match)] as const);
  const taxKey = lineKey(/^tuloveroprosentti$/i);
  const staffKey = lineKey(/^henkilötyövuodet$/i);
  const councillors = new Map<string, number>();
  for (const r of councillorRows()) councillors.set(r.c, (councillors.get(r.c) ?? 0) + 1);

  return cities().map((c) => {
    const values: Record<string, number | null> = {};
    for (const [code, v] of Object.entries(facts?.municipalities[c.id]?.values ?? {})) values[code] = v;
    const pop = population(c);
    const y = year ? budget(c.id)?.years.find((x) => x.year === year) : undefined;
    const per = (n: number | undefined, k = 1) => (n === undefined || !pop ? null : (n * k) / pop);
    for (const [id, key] of summaryKeys) {
      const v = key ? value(y, key) : undefined;
      values[`b:${id}`] = per(v);
      values[`b:${id}:total`] = v === undefined ? null : v / 1e6;
    }
    // Only the budget column: 55 municipalities leave it empty and fill the plan years only.
    values['b:tax-rate'] = taxKey ? value(y, taxKey) ?? null : null;
    values['b:staff'] = staffKey ? per(value(y, staffKey), 1000) : null;

    // Our own counts exist only where we read the minutes; elsewhere they are unknown, not zero.
    const s = cityStats(c.id);
    const followed = s.meetings > 0;
    values.meetings = followed ? s.meetings : null;
    values.items = followed ? s.items : null;
    values.votes = followed ? s.votes : null;
    values.councillors = councillors.get(c.id) ?? null;
    const inits = initiativeFile(c.id)?.initiatives;
    values.initiatives = inits ? inits.length : null;
    values.initiativesPer = inits && pop ? (inits.length * 10000) / pop : null;
    values.supporters = inits ? inits.reduce((n, x) => n + (x.participants ?? 0), 0) : null;
    return { city: c, name: cityName(c, locale), values };
  });
}

/** The whole country's value where Statistics Finland gives one. */
export function countryValues(): Record<string, number | null> {
  return facts?.country ?? {};
}
