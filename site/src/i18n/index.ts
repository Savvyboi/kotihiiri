import { fi, type Dict, type Key } from './fi';
import { sv } from './sv';
import { en } from './en';
import { DEFAULT_LOCALE, LOCALES } from './locales.js';

export type Locale = 'fi' | 'sv' | 'en';
export type { Key };
export { DEFAULT_LOCALE, LOCALES };

export const DICTS: Record<Locale, Dict> = { fi, sv, en };
const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function isLocale(x: unknown): x is Locale {
  return typeof x === 'string' && (LOCALES as string[]).includes(x);
}

/** Translate `key` for `locale`, filling `{name}` placeholders from `vars`. */
export function t(key: Key, vars: Record<string, string | number> = {}, locale: Locale = DEFAULT_LOCALE as Locale): string {
  const template = DICTS[locale][key] ?? DICTS.fi[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
}

const base = () => import.meta.env.BASE_URL.replace(/\/$/, '');

/** Locale-aware page path under the configured base. Finnish has no prefix. */
export function localePath(path: string, locale: Locale = DEFAULT_LOCALE as Locale): string {
  const prefix = locale === DEFAULT_LOCALE ? '' : `/${locale}`;
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${base()}${prefix}${clean}`;
}

/** Path of a static file under the configured base (never locale-prefixed). */
export function assetPath(path: string): string {
  return `${base()}${path.startsWith('/') ? path : `/${path}`}`;
}

/**
 * Item pages are built once, at their Finnish path, to stay inside the GitHub Pages size budget
 * (PLAN.md §13). Other locales link to them with ?lang=, and a small script translates the
 * interface text on the page (see SharedI18n.astro).
 */
export function sharedPath(path: string, locale: Locale = DEFAULT_LOCALE as Locale): string {
  return localePath(path) + (locale === DEFAULT_LOCALE ? '' : `?lang=${locale}`);
}

/** The locale a URL belongs to, and the path without base and locale prefix. */
export function splitLocale(pathname: string): { locale: Locale; rest: string } {
  const b = base();
  const p = b && pathname.startsWith(b) ? pathname.slice(b.length) : pathname;
  const m = p.match(/^\/(sv|en)(\/.*|$)/);
  return m ? { locale: m[1] as Locale, rest: m[2] || '/' } : { locale: 'fi', rest: p || '/' };
}

export function formatDate(iso: string, locale: Locale = DEFAULT_LOCALE as Locale): string {
  const [y, m, d] = iso.split('-').map(Number);
  return t('common.date', { d, m, y, mon: EN_MONTHS[m - 1] }, locale);
}

const INTL: Record<Locale, string> = { fi: 'fi-FI', sv: 'sv-FI', en: 'en-GB' };
export function formatNumber(n: number, locale: Locale = DEFAULT_LOCALE as Locale): string {
  return new Intl.NumberFormat(INTL[locale]).format(n);
}

/** `lang` route parameter for each locale: undefined (root) for Finnish. */
export function localeParams(): { lang: string | undefined; locale: Locale }[] {
  return (LOCALES as Locale[]).map((l) => ({ lang: l === DEFAULT_LOCALE ? undefined : l, locale: l }));
}

/** Multiply static paths by locale. */
export function localized<P extends Record<string, string>, T extends object>(
  paths: { params: P; props: T }[],
): { params: P & { lang: string | undefined }; props: T & { locale: Locale } }[] {
  return localeParams().flatMap(({ lang, locale }) =>
    paths.map((p) => ({ params: { ...p.params, lang }, props: { ...p.props, locale } })));
}

/** Bound helpers for one locale, for use in pages and components. */
export function useI18n(locale: Locale) {
  return {
    locale,
    t: (key: Key, vars: Record<string, string | number> = {}) => t(key, vars, locale),
    path: (p: string) => localePath(p, locale),
    shared: (p: string) => sharedPath(p, locale),
    date: (iso: string) => formatDate(iso, locale),
    num: (n: number) => formatNumber(n, locale),
  };
}

/** Locale of the page being rendered, from its URL. */
export function pageLocale(url: URL): Locale {
  return splitLocale(url.pathname).locale;
}
