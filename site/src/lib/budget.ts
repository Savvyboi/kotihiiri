// Municipal budgets from the State Treasury (PLAN.md §19): data/talous/items.json lists the budget
// lines, data/talous/{city}.json holds each year's approved budget and plan. Read from DATA_DIR,
// else from the repository's data/ (the demo tree has no budgets).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DATA_DIR, type City } from './data';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

export type Column = 'prev' | 'budget' | 'plan1' | 'plan2';
export const COLUMNS: Column[] = ['prev', 'budget', 'plan1', 'plan2'];
export interface BudgetLine { key: string; order: number; level: number; fi: string; sv: string; en: string }
export interface BudgetYear {
  year: number; stage: string; approved: string; source_url: string;
  values: Record<string, Partial<Record<Column, number>>>; notes?: Record<string, string>;
}
export interface BudgetFile { city: string; business_id: string; years: BudgetYear[] }
interface Items { source: { name: string; url: string; licence: string }; lines: BudgetLine[] }

function dir(): string | undefined {
  for (const d of [path.join(DATA_DIR, 'talous'), path.join(ROOT, 'data', 'talous')]) {
    if (fs.existsSync(path.join(d, 'items.json'))) return d;
  }
  return undefined;
}

const cache = new Map<string, unknown>();
function memo<T>(key: string, fn: () => T): T {
  if (!cache.has(key)) cache.set(key, fn());
  return cache.get(key) as T;
}

export function budgetItems(): Items | undefined {
  return memo('items', () => {
    const d = dir();
    return d ? (JSON.parse(fs.readFileSync(path.join(d, 'items.json'), 'utf8')) as Items) : undefined;
  });
}

export function budget(cityId: string): BudgetFile | undefined {
  return memo(`b:${cityId}`, () => {
    const d = dir();
    const p = d && path.join(d, `${cityId}.json`);
    if (!p || !fs.existsSync(p)) return undefined;
    const f = JSON.parse(fs.readFileSync(p, 'utf8')) as BudgetFile;
    return f.years.length ? f : undefined;
  });
}

/** The report prints its subtotals in capitals (VUOSIKATE); show them in sentence case, bold. */
export function isTotal(line: BudgetLine): boolean {
  return line.fi === line.fi.toUpperCase();
}

export function lineLabel(line: BudgetLine, locale: string): string {
  const s = locale === 'sv' ? line.sv : locale === 'en' ? line.en : line.fi;
  return s === s.toUpperCase() ? s.charAt(0) + s.slice(1).toLowerCase() : s;
}

/** Lines that are a rate or a count, not euros: shown as they are, never per resident. */
export function isAmount(line: BudgetLine): boolean {
  return !/prosentti|henkilötyövuo/i.test(line.fi);
}

/** The value of a line in the budget column of a year. */
export function value(y: BudgetYear | undefined, key: string, col: Column = 'budget'): number | undefined {
  return y?.values[key]?.[col];
}

/** Years with a budget in any municipality, newest first. */
export function budgetYears(ids: string[]): number[] {
  const s = new Set<number>();
  for (const id of ids) for (const y of budget(id)?.years ?? []) s.add(y.year);
  return [...s].sort((a, b) => b - a);
}

/** Main figures for cards, trends and the national table: a budget line found by its Finnish label. */
export interface Measure { id: string; label: string; amount: boolean; match: RegExp }
export const SUMMARY: Measure[] = [
  { id: 'expenses', label: 'budget.m.expenses', amount: true, match: /^toimintamenot$/i },
  { id: 'tax', label: 'budget.m.tax', amount: true, match: /^verotulot$/i },
  { id: 'transfers', label: 'budget.m.transfers', amount: true, match: /^valtionosuudet$/i },
  { id: 'margin', label: 'budget.m.margin', amount: true, match: /^vuosikate$/i },
  { id: 'investments', label: 'budget.m.investments', amount: true, match: /^investointimenot yhteensä/i },
  { id: 'loans', label: 'budget.m.loans', amount: true, match: /^lainakanta/i },
  { id: 'result', label: 'budget.m.result', amount: true, match: /^tilikauden tulos$/i },
];

function measureKey(m: Measure): string | undefined {
  return memo(`m:${m.id}`, () => budgetItems()?.lines.find((l) => m.match.test(l.fi))?.key);
}

export function summaryValue(y: BudgetYear | undefined, m: Measure): number | undefined {
  const k = measureKey(m);
  return k ? value(y, k) : undefined;
}

// Population for per-resident figures: Statistics Finland's key figures when that file is in the
// checkout (src/data/municipality-facts.json, `kunta facts`), else the registry's population.
interface Facts { figures: { code: string; label: Record<string, string> }[]; municipalities: Record<string, { values: Record<string, number | null> }> }
const factFiles = import.meta.glob<Facts>('../data/municipality-facts.json', { eager: true, import: 'default' });
const facts: Facts | undefined = Object.values(factFiles)[0];
const popCode = facts?.figures.find((f) => /^väkiluku\b/i.test(f.label.fi ?? ''))?.code;

export function population(c: City): number | undefined {
  const v = popCode ? facts?.municipalities[c.id]?.values[popCode] : undefined;
  return v ?? c.population ?? undefined;
}
