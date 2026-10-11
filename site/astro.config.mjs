// @ts-check
import { defineConfig } from 'astro/config';
import { LOCALES, DEFAULT_LOCALE } from './src/i18n/locales.js';

// GitHub Pages project sites live under /<repo>/; set BASE_PATH in CI.
export default defineConfig({
  site: process.env.SITE_URL || 'https://example.org',
  base: process.env.BASE_PATH || '/',
  output: 'static',
  trailingSlash: 'always',
  i18n: {
    defaultLocale: DEFAULT_LOCALE,
    locales: LOCALES,
    // Finnish lives at the root; Swedish/English will get /sv/ and /en/ prefixes.
    routing: { prefixDefaultLocale: false },
  },
});
