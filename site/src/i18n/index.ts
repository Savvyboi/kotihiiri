import { fi, type Dict, type Key } from './fi';
import { DEFAULT_LOCALE, LOCALES } from './locales.js';

export type Locale = 'fi';
export { DEFAULT_LOCALE, LOCALES };

const DICTS: Record<Locale, Dict> = { fi };

/** Translate `key` for `locale`, filling `{name}` placeholders from `vars`. */
export function t(key: Key, vars: Record<string, string | number> = {}, locale: Locale = DEFAULT_LOCALE as Locale): string {
  const template = DICTS[locale][key] ?? DICTS.fi[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
}

/** Locale-aware path under the configured base. Finnish has no prefix. */
export function localePath(path: string, locale: Locale = DEFAULT_LOCALE as Locale): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const prefix = locale === DEFAULT_LOCALE ? '' : `/${locale}`;
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${base}${prefix}${clean}`;
}

export function formatDate(iso: string, locale: Locale = DEFAULT_LOCALE as Locale): string {
  const [y, m, d] = iso.split('-').map(Number);
  return t('common.date', { d, m, y }, locale);
}

export function formatNumber(n: number, locale: Locale = DEFAULT_LOCALE as Locale): string {
  return new Intl.NumberFormat(locale).format(n);
}
