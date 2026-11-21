// Actual net costs by service (PLAN.md §19.2), from the State Treasury's KKTPP report:
// data/talous/palvelut/services.json names each service class code, data/talous/palvelut/{city}.json
// holds per year code → [costs, allocated costs, income, allocated income]. Codes are grouped into
// about fifteen services a resident recognises; totals ("… yhteensä") are left out of the sums,
// because their children are counted already.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Locale } from '../i18n';
import { DATA_DIR, cities } from './data';
import { population } from './budget';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

type Text = Record<Locale, string>;
export type Amounts = [number, number, number, number];
export interface ServiceYear { year: number; stage: string; approved: string; source_url: string; services: Record<string, Amounts> }
interface ServiceFile { city: string; years: ServiceYear[] }
interface Names { source: { name: string; url: string; licence: string }; services: Record<string, Text> }

function dir(): string | undefined {
  for (const d of [path.join(DATA_DIR, 'talous', 'palvelut'), path.join(ROOT, 'data', 'talous', 'palvelut')]) {
    if (fs.existsSync(path.join(d, 'services.json'))) return d;
  }
  return undefined;
}

const cache = new Map<string, unknown>();
function memo<T>(key: string, fn: () => T): T {
  if (!cache.has(key)) cache.set(key, fn());
  return cache.get(key) as T;
}

export function serviceNames(): Names | undefined {
  return memo('names', () => {
    const d = dir();
    return d ? (JSON.parse(fs.readFileSync(path.join(d, 'services.json'), 'utf8')) as Names) : undefined;
  });
}

export function serviceData(cityId: string): ServiceFile | undefined {
  return memo(`s:${cityId}`, () => {
    const d = dir();
    const p = d && path.join(d, `${cityId}.json`);
    if (!p || !fs.existsSync(p)) return undefined;
    const f = JSON.parse(fs.readFileSync(p, 'utf8')) as ServiceFile;
    return f.years.some((y) => Object.keys(y.services).length > 1) ? f : undefined;
  });
}

export const net = (a: Amounts) => a[0] + a[1] - a[2] - a[3];

/** A service class whose figures are the sum of others in the same report. */
function isTotal(code: string): boolean {
  if (code === 'ALL' || code === '1100' || code === '5350') return true;
  return /yhteensä/i.test(serviceNames()?.services[code]?.fi ?? '');
}

export interface ServiceGroup { id: string; name: Text; about: Text; ranges: [number, number][] }
export const GROUPS: ServiceGroup[] = [
  { id: 'early', ranges: [[3020, 3039]],
    name: { fi: 'Varhaiskasvatus', sv: 'Småbarnspedagogik', en: 'Early childhood education' },
    about: { fi: 'Päiväkodit, perhepäivähoito ja muu varhaiskasvatus.', sv: 'Daghem, familjedagvård och annan småbarnspedagogik.', en: 'Day-care centres, family day care and other early education.' } },
  { id: 'basic', ranges: [[3040, 3099]],
    name: { fi: 'Esi- ja perusopetus', sv: 'För- och grundläggande utbildning', en: 'Pre-primary and basic education' },
    about: { fi: 'Esiopetus, peruskoulut sekä aamu- ja iltapäivätoiminta.', sv: 'Förskoleundervisning, grundskolor och morgon- och eftermiddagsverksamhet.', en: 'Pre-primary education, comprehensive schools and before- and after-school care.' } },
  { id: 'upper', ranges: [[3100, 3199]],
    name: { fi: 'Lukio ja ammatillinen koulutus', sv: 'Gymnasium och yrkesutbildning', en: 'Upper secondary and vocational education' },
    about: { fi: 'Kunnan omat lukiot ja ammattioppilaitokset. Monessa kunnassa ne järjestää kuntayhtymä, jolloin kunta maksaa osuutensa muiden menojen kautta.', sv: 'Kommunens egna gymnasier och yrkesläroanstalter. I många kommuner ordnar en samkommun dem.', en: 'The municipality’s own upper secondary and vocational schools. Many municipalities run these through a joint authority instead.' } },
  { id: 'adult', ranges: [[3200, 3499]],
    name: { fi: 'Kansalaisopisto ja muu opetus', sv: 'Medborgarinstitut och annan undervisning', en: 'Adult education and other teaching' },
    about: { fi: 'Kansalaisopisto, taiteen perusopetus, kuraattorit ja psykologit sekä muu opetus.', sv: 'Medborgarinstitut, grundläggande konstundervisning, kuratorer och psykologer samt annan undervisning.', en: 'Community college, basic arts education, school counsellors and psychologists, and other teaching.' } },
  { id: 'library', ranges: [[3500, 3549]],
    name: { fi: 'Kirjastot', sv: 'Bibliotek', en: 'Libraries' },
    about: { fi: 'Kirjastopalvelut.', sv: 'Bibliotekstjänster.', en: 'Library services.' } },
  { id: 'sports', ranges: [[3550, 3699]],
    name: { fi: 'Liikunta ja nuoriso', sv: 'Idrott och ungdom', en: 'Sports and youth' },
    about: { fi: 'Liikuntapaikat ja -palvelut, ulkoilu ja nuorisotyö.', sv: 'Idrottsplatser och -tjänster, friluftsliv och ungdomsarbete.', en: 'Sports facilities and services, outdoor recreation and youth work.' } },
  { id: 'culture', ranges: [[3700, 3999]],
    name: { fi: 'Kulttuuri', sv: 'Kultur', en: 'Culture' },
    about: { fi: 'Museot, teatteri, musiikki ja muu kulttuuritoiminta.', sv: 'Museer, teater, musik och annan kulturverksamhet.', en: 'Museums, theatre, music and other cultural activities.' } },
  { id: 'streets', ranges: [[4600, 4799], [6300, 6399]],
    name: { fi: 'Kadut, puistot ja joukkoliikenne', sv: 'Gator, parker och kollektivtrafik', en: 'Streets, parks and public transport' },
    about: { fi: 'Katujen ja yleisten alueiden ylläpito, pysäköinti, puistot ja joukkoliikenne.', sv: 'Underhåll av gator och allmänna områden, parkering, parker och kollektivtrafik.', en: 'Upkeep of streets and public areas, parking, parks and public transport.' } },
  { id: 'planning', ranges: [[4100, 4399]],
    name: { fi: 'Kaavoitus, rakennusvalvonta ja asuminen', sv: 'Planläggning, byggnadstillsyn och boende', en: 'Planning, building control and housing' },
    about: { fi: 'Asema- ja yleiskaavoitus, paikkatieto, rakennusvalvonta ja asumisen palvelut.', sv: 'Detalj- och generalplanering, geodata, byggnadstillsyn och boendetjänster.', en: 'Detailed and general planning, spatial data, building control and housing services.' } },
  { id: 'environment', ranges: [[4400, 4599], [2700, 2799], [6900, 6999]],
    name: { fi: 'Ympäristö ja ympäristöterveys', sv: 'Miljö och miljöhälsa', en: 'Environment and environmental health' },
    about: { fi: 'Ympäristönsuojelu, elintarvikevalvonta, eläinlääkärit ja löytöeläimet.', sv: 'Miljöskydd, livsmedelstillsyn, veterinärer och hittedjur.', en: 'Environmental protection, food safety, vets and lost animals.' } },
  { id: 'employment', ranges: [[5550, 5699], [7100, 7199]],
    name: { fi: 'Työllisyys, kotoutuminen ja elinkeinot', sv: 'Sysselsättning, integration och näringsliv', en: 'Employment, integration and business' },
    about: { fi: 'Työllisyyspalvelut (vuodesta 2025 kuntien vastuulla), kotoutuminen, elinkeinojen edistäminen ja aluekehitys.', sv: 'Sysselsättningstjänster (kommunernas ansvar från 2025), integration, näringsfrämjande och regionutveckling.', en: 'Employment services (run by municipalities since 2025), integration, business promotion and regional development.' } },
  { id: 'premises', ranges: [[5350, 5399]],
    name: { fi: 'Tilat ja maaomaisuus', sv: 'Lokaler och markegendom', en: 'Premises and land' },
    about: { fi: 'Kunnan rakennusten vuokraus muille palveluille ja ulkopuolisille sekä maaomaisuus. Usein voitollinen, koska palvelut maksavat tiloistaan sisäistä vuokraa ja maata myydään.', sv: 'Uthyrning av kommunens byggnader och markegendom. Ofta med överskott, eftersom tjänsterna betalar intern hyra och mark säljs.', en: 'Renting the municipality’s buildings to its services and others, and land. Often in surplus, because services pay internal rent and land is sold.' } },
  { id: 'admin', ranges: [[1100, 1199], [5500, 5549]],
    name: { fi: 'Hallinto ja tukipalvelut', sv: 'Förvaltning och stödtjänster', en: 'Administration and support services' },
    about: { fi: 'Yleishallinto, vaalit, talous-, henkilöstö- ja ICT-palvelut.', sv: 'Allmän förvaltning, val, ekonomi-, personal- och IT-tjänster.', en: 'General administration, elections, finance, HR and IT services.' } },
  { id: 'utilities', ranges: [[6100, 6299], [6600, 6699]],
    name: { fi: 'Vesi, jäte, energia ja metsät', sv: 'Vatten, avfall, energi och skog', en: 'Water, waste, energy and forests' },
    about: { fi: 'Vesihuolto, jätehuolto, energia sekä kunnan maa- ja metsätalous.', sv: 'Vatten, avfall, energi samt kommunens jord- och skogsbruk.', en: 'Water and sewerage, waste, energy, and the municipality’s farming and forestry.' } },
  { id: 'health', ranges: [[2000, 2699], [2800, 2999], [4800, 4899], [7200, 7299]],
    name: { fi: 'Sosiaali-, terveys- ja pelastuspalvelut', sv: 'Social-, hälso- och räddningstjänster', en: 'Social, health and rescue services' },
    about: { fi: 'Vuoteen 2022 kunnan suurin menoerä. Vuodesta 2023 ne kuuluvat hyvinvointialueille; jäljellä on lähinnä vanhojen vuosien jälkiä.', sv: 'Kommunens största utgift fram till 2022. Sedan 2023 sköts de av välfärdsområdena.', en: 'The biggest cost until 2022. Since 2023 they belong to the wellbeing services counties; what remains is mostly settling earlier years.' } },
];
export const OTHER: Text = { fi: 'Muut palvelut', sv: 'Övriga tjänster', en: 'Other services' };

function groupOf(code: string): string {
  const n = Number(code);
  return GROUPS.find((g) => g.ranges.some(([lo, hi]) => n >= lo && n <= hi))?.id ?? 'other';
}

export interface GroupRow { id: string; net: number; costs: number; income: number; services: { code: string; net: number; costs: number; income: number }[] }
/** One year's services grouped, largest net cost first; "other" last. */
export function grouped(y: ServiceYear): { rows: GroupRow[]; total: number | undefined } {
  const rows = new Map<string, GroupRow>();
  for (const [code, a] of Object.entries(y.services)) {
    if (isTotal(code)) continue;
    const id = groupOf(code);
    const r = rows.get(id) ?? { id, net: 0, costs: 0, income: 0, services: [] };
    r.net += net(a); r.costs += a[0] + a[1]; r.income += a[2] + a[3];
    r.services.push({ code, net: net(a), costs: a[0] + a[1], income: a[2] + a[3] });
    rows.set(id, r);
  }
  for (const r of rows.values()) r.services.sort((a, b) => b.net - a.net);
  const list = [...rows.values()].filter((r) => Math.abs(r.net) >= 2e5 || r.costs >= 2e5) // leftovers of a few thousand euros are noise
    .sort((a, b) => (a.id === 'other' ? 1 : b.id === 'other' ? -1 : b.net - a.net));
  const all = y.services.ALL;
  return { rows: list, total: all ? net(all) : undefined };
}

export function groupName(id: string, locale: Locale): string {
  return (GROUPS.find((g) => g.id === id)?.name ?? OTHER)[locale];
}
export function groupAbout(id: string, locale: Locale): string | undefined {
  return GROUPS.find((g) => g.id === id)?.about[locale];
}
export function serviceName(code: string, locale: Locale): string {
  const n = serviceNames()?.services[code];
  return n ? n[locale] || n.fi : code;
}

/** Net cost per resident of a group in every municipality with data for `year`, sorted ascending. */
export function groupPeers(year: number, id: string): number[] {
  return memo(`p:${year}:${id}`, () => {
    const out: number[] = [];
    for (const c of cities()) {
      const y = serviceData(c.id)?.years.find((x) => x.year === year);
      const pop = population(c);
      if (!y || !pop) continue;
      const r = grouped(y).rows.find((x) => x.id === id);
      out.push((r?.net ?? 0) / pop);
    }
    return out.sort((a, b) => a - b);
  });
}
