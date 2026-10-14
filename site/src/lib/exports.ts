// The downloads listed on /data/ (PLAN.md §13). The kunta CLI writes them; the Pages workflow
// copies the Parquet files, all.zip and manifest.json into public/data/files/ before the build.
import fs from 'node:fs';
import path from 'node:path';

export interface TableInfo { rows: number; columns: string[]; csv_bytes: number; parquet_bytes: number }
export interface Manifest { tables: Record<string, TableInfo>; zip_bytes: number }

// The build runs in site/ (npm run build); the bundled module's own URL is not a stable anchor.
const FILES = path.resolve(process.cwd(), 'public/data/files');

/** The export manifest, or null when no exports were copied in (demo and CI builds). */
export function exportManifest(): Manifest | null {
  const p = path.join(FILES, 'manifest.json');
  return fs.existsSync(p) ? (JSON.parse(fs.readFileSync(p, 'utf8')) as Manifest) : null;
}

/** "1,2 MB" / "38 kB" in the reader's locale. */
export function fileSize(bytes: number, nf: Intl.NumberFormat): string {
  if (bytes >= 1e6) return `${nf.format(Math.round(bytes / 1e5) / 10)} MB`;
  return `${nf.format(Math.max(1, Math.round(bytes / 1e3)))} kB`;
}
