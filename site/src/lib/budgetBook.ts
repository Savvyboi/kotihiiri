// The "open book" view of a municipality's budget (PLAN.md §19.1), after the Harvard Ash Center's
// Open Book budget portal: the big picture first (is the budget balanced, where each euro comes
// from and goes), then income, running costs, investments and debt one by one, each line in plain
// language, compared with the year before and with other municipalities, and downloadable.
//
// The KTAS report has no breakdown by service or department, only by type of income and cost, so
// the groups below are built from its lines by key.
import { cities, type City } from './data';
import { budget, budgetItems, population, value, type BudgetLine, type BudgetYear, type Column } from './budget';

export interface Part { key: string; v: number; prev?: number; synthetic?: 'finIncome' | 'finCost' }
export interface Group { total: number; prevTotal?: number; parts: Part[] }

export const INCOME_KEYS = ['verotulot', 'valtionosuudet', 'myyntitulot', 'maksutulot', 'tuet-ja-avustukset', 'muut-toimintatulot'];
export const COST_KEYS = ['henkilostomenot', 'palvelujen-ostot', 'aineet-tarvikkeet-ja-tavarat', 'avustukset', 'muut-toimintamenot'];
export const INVEST_KEYS = [
  'rakennukset-opetus-ja-kulttuuritoimi', 'rakennukset-sosiaali-ja-terveystoimi', 'rakennukset-muut',
  'kiinteat-rakenteet-ja-laitteet', 'maa-ja-vesialueet', 'koneet-ja-kalusto', 'aineettomat-hyodykkeet',
  'muut-aineelliset-hyodykkeet', 'osakkeet-ja-osuudet',
];
const FIN = 'rahoitustulot-ja-menot';
const OWN_USE = ['valmistus-omaan-kayttoon', 'valmistevarastojen-muutos'];

const v = (y: BudgetYear, k: string, c: Column = 'budget') => value(y, k, c);

function group(y: BudgetYear, keys: string[], fin?: 'finIncome' | 'finCost'): Group | undefined {
  const parts: Part[] = [];
  for (const key of keys) {
    const b = v(y, key);
    if (b !== undefined && b > 0) parts.push({ key, v: b, prev: v(y, key, 'prev') });
  }
  const f = v(y, FIN);
  if (fin && f !== undefined) {
    const sign = fin === 'finIncome' ? 1 : -1;
    const p = v(y, FIN, 'prev');
    if (f * sign > 0) parts.push({ key: FIN, v: f * sign, prev: p !== undefined && p * sign > 0 ? p * sign : undefined, synthetic: fin });
  }
  if (!parts.length) return undefined;
  parts.sort((a, b) => b.v - a.v);
  const total = parts.reduce((s, p) => s + p.v, 0);
  const prevTotal = parts.every((p) => p.prev !== undefined) ? parts.reduce((s, p) => s + (p.prev ?? 0), 0) : undefined;
  return { total, prevTotal, parts };
}

/** All money coming in for running the municipality: operating income, taxes, transfers, net financial income. */
export const incomeGroup = (y: BudgetYear) => group(y, INCOME_KEYS, 'finIncome');
/** Running costs by type, with net financial costs (mostly interest) when they exceed financial income. */
export const costGroup = (y: BudgetYear) => group(y, COST_KEYS, 'finCost');
/** Gross investments by asset; buildings split into education, social and health, other. */
export function investGroup(y: BudgetYear): Group | undefined {
  // Some municipalities report buildings only as a total; then show the total.
  const split = INVEST_KEYS.slice(0, 3).some((k) => (v(y, k) ?? 0) > 0);
  return group(y, split ? INVEST_KEYS : ['rakennukset', ...INVEST_KEYS.slice(3)]);
}

/** Work and goods the municipality makes for its own investments: in the expenses, but not a running cost. */
export function ownUse(y: BudgetYear): number {
  return OWN_USE.reduce((s, k) => s + (v(y, k) ?? 0), 0);
}

export type Verdict = 'surplus' | 'covers' | 'short' | 'negative';
/**
 * The balance check. A municipality is in balance in the sense of the Local Government Act when
 * its annual margin (what is left of income after running costs) covers depreciation, so the
 * result for the year is not negative.
 */
export function balance(y: BudgetYear) {
  const margin = v(y, 'vuosikate');
  const depreciation = v(y, 'poistot-ja-arvonalentumiset');
  const result = v(y, 'tilikauden-tulos');
  const surplus = v(y, 'tilikauden-ylijaama-alijaama');
  const investNet = (v(y, 'investointimenot-yhteensa-brutto') ?? 0)
    - (v(y, 'rahoitusosuudet-investointimenoihin') ?? 0) - (v(y, 'investointihyodykkeiden-luovutustulot-brutto') ?? 0);
  const cashflow = v(y, 'toiminnan-ja-investointien-rahavirta');
  let verdict: Verdict | undefined;
  if (margin !== undefined) {
    if (margin < 0) verdict = 'negative';
    else if (depreciation !== undefined) verdict = margin >= depreciation ? ((result ?? 0) > 0 ? 'surplus' : 'covers') : 'short';
  }
  return { margin, depreciation, result, surplus, investNet, cashflow, verdict };
}

/** Change from the previous year's amended budget, in per cent, when both are positive. */
export function change(now: number | undefined, prev: number | undefined): number | undefined {
  if (now === undefined || prev === undefined || prev <= 0 || now < 0) return undefined;
  return ((now - prev) / prev) * 100;
}

const medianCache = new Map<string, { median: number; n: number; sorted: number[] }>();
/**
 * Per-resident figure of a budget line (or a synthetic part) across every municipality with a
 * budget for `year`: the median and the sorted list, for "where does this municipality stand".
 */
export function peers(year: number, key: string, synthetic?: Part['synthetic']) {
  const id = `${year}:${key}:${synthetic ?? ''}`;
  if (!medianCache.has(id)) {
    const vals: number[] = [];
    for (const c of cities()) {
      const y = budget(c.id)?.years.find((x) => x.year === year);
      const pop = population(c);
      if (!y || !pop) continue;
      let x = v(y, key);
      if (x !== undefined && synthetic) x = synthetic === 'finIncome' ? Math.max(x, 0) : Math.max(-x, 0);
      if (x !== undefined) vals.push(x / pop);
    }
    vals.sort((a, b) => a - b);
    const n = vals.length;
    const median = n ? (n % 2 ? vals[(n - 1) / 2] : (vals[n / 2 - 1] + vals[n / 2]) / 2) : 0;
    medianCache.set(id, { median, n, sorted: vals });
  }
  return medianCache.get(id)!;
}

/** Rank of a per-resident figure among the peers, largest first: 1 = the most per resident. */
export function rank(year: number, key: string, perResident: number, synthetic?: Part['synthetic']): { rank: number; n: number } | undefined {
  const { sorted, n } = peers(year, key, synthetic);
  if (n < 5) return undefined;
  return { rank: sorted.filter((x) => x > perResident + 1e-9).length + 1, n };
}

/** One budget line by key. */
export function line(key: string): BudgetLine | undefined {
  return budgetItems()?.lines.find((l) => l.key === key);
}

/** The main figures over the years, for the trend charts: past budgets, then the latest plan years. */
export interface TrendPoint { year: number; v: number; plan: boolean }
export function trend(years: BudgetYear[], key: string): TrendPoint[] {
  const pts: TrendPoint[] = [];
  const sorted = [...years].sort((a, b) => a.year - b.year);
  for (const y of sorted) {
    const x = v(y, key);
    if (x !== undefined) pts.push({ year: y.year, v: x, plan: false });
  }
  const last = sorted[sorted.length - 1];
  if (last) {
    for (const [c, off] of [['plan1', 1], ['plan2', 2]] as const) {
      const x = v(last, key, c);
      if (x !== undefined) pts.push({ year: last.year + off, v: x, plan: true });
    }
  }
  return pts;
}

// CSV export: every year, line and column of a municipality's budgets, in long format.
// Labels in Swedish and English are in data/talous/items.json; the CSV keeps Finnish to stay small.
const CSV_HEAD = ['municipality', 'year', 'stage', 'line', 'label_fi', 'column', 'column_year', 'value'];
const COL_OFFSET: Record<Column, number> = { prev: -1, budget: 0, plan1: 1, plan2: 2 };
const csvCell = (x: unknown) => {
  const s = x === undefined || x === null ? '' : String(x);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function budgetCsvRows(c: City): string[] {
  const data = budget(c.id);
  const lines = budgetItems()?.lines ?? [];
  if (!data) return [];
  const rows: string[] = [];
  for (const y of data.years) {
    for (const l of lines) {
      for (const col of ['prev', 'budget', 'plan1', 'plan2'] as Column[]) {
        const x = v(y, l.key, col);
        if (x === undefined) continue;
        rows.push([c.id, y.year, y.stage, l.key, l.fi, col, y.year + COL_OFFSET[col], x]
          .map(csvCell).join(','));
      }
    }
  }
  return rows;
}

export function budgetCsv(list: City[]): string {
  return '﻿' + [CSV_HEAD.join(','), ...list.flatMap(budgetCsvRows)].join('\r\n') + '\r\n';
}
