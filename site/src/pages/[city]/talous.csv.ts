// One municipality's budgets as CSV (/{city}/talous.csv, PLAN.md §19.1): every year, line and
// column, in long format.
import type { APIRoute } from 'astro';
import { cities, type City } from '../../lib/data';
import { budget } from '../../lib/budget';
import { budgetCsv } from '../../lib/budgetBook';

export function getStaticPaths() {
  return cities().filter((c) => budget(c.id)).map((c) => ({ params: { city: c.id }, props: { city: c } }));
}

export const GET: APIRoute = ({ props }) =>
  new Response(budgetCsv([(props as { city: City }).city]), { headers: { 'Content-Type': 'text/csv; charset=utf-8' } });
