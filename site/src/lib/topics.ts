// Topics for browsing decisions by subject (/aiheet/). An item gets every topic whose pattern
// matches its title, in Finnish or Swedish; titles are short and formulaic ("Asemakaavan muutos …",
// "Valtuustoaloite …"), so plain word stems are enough and the result is the same on every build.
// Patterns avoid \b, which in JavaScript does not treat ä and ö as letters.
import { bodies, bodyName, cities, itemUrl, meetingFiles } from './data';

export interface Topic { id: string; re: RegExp }

export const TOPICS: Topic[] = [
  { id: 'talous', re: /talousarvi|talouden seuran|talousraport|taloustilan|tilinpäätö|budjet|veroprosent|kiinteistöver|tuloverop|lainan|lainoj|takau|tilintarkast|taloussuunnitelm|osavuosikatsa|budget|bokslut|skattesats|borgen/i },
  { id: 'kaavoitus', re: /kaava|tonttijako|maankäyt|rakennusjärjestys|detaljplan|generalplan|delgeneralplan|tomtindelning|markanvändning/i },
  { id: 'maa-ja-kiinteistot', re: /kiinteistö(?!ver)|tontin|tontt|maa-alue|maanvuokr|maankäyttösopim|vuokrasopim|kauppakirj|esisopim|myynti|ostaminen|fastighet|tomt|arrende|markområde/i },
  { id: 'rakentaminen', re: /hankesuunnitelm|tarveselvity|peruskorjau|uudisrakennu|rakentamin|urakk|perusparannu|byggnad|byggande|grundrenover/i },
  { id: 'liikenne', re: /liikente|liikenne|katusuunnitelm|kadun|katujen|joukkoliikent|pysäköin|pyörä|raitiotie|kevyen liikenteen|väyläsuunnitelm|trafik|gatuplan|kollektivtrafik|parkering/i },
  { id: 'kasvatus-ja-opetus', re: /koulu|opetus|varhaiskasvatu|päiväko|lukio|perusopetu|oppilas|esiopetu|skola|utbildning|småbarnspedagog|daghem|gymnasi/i },
  { id: 'kulttuuri-ja-vapaa-aika', re: /kulttuur|liikun|kirjasto|museo|nuoriso|urheilu|vapaa-aika|uimahall|teatter|kultur|idrott|bibliotek|ungdom/i },
  { id: 'hyvinvointi', re: /hyvinvoin|terveys|terveyden|ikäänty|vanhus|vammais|mielenterv|päihde|sosiaali|lastensuojel|välfärd|hälsa|äldre|funktionsned/i },
  { id: 'ymparisto', re: /(?<!kaupunki)ympäristö(?!lauta|- ja rakennuslauta|toimiala|palvelu)|ilmasto|luonnonsuojel|jätehuol|jätteen|jätet(?!ään|ty|yt)|vesihuol|hulevesi|energia|metsä|puisto|miljö|klimat|naturskydd|avfall|vattentjänst/i },
  { id: 'elinvoima', re: /elinvoim|elinkeino|työllisyy|yrittäj|yritys|matkailu|kehittämisyhtiö|kotoutum|näringsliv|sysselsättning|företag|turism|integration/i },
  { id: 'asuminen', re: /asunto|asumi|asukasvalinta|bostad|boende/i },
  { id: 'omistajaohjaus', re: /yhtiö|konserni|omistajaohjau|kuntayhtym|osakkeiden|osakas|bolag|koncern|ägarstyrning|samkommun/i },
  { id: 'henkilosto', re: /henkilöst|viran |virka|viranhaltija|palkka|palkkau|työsopim|rekrytoi|johtosääntö|personal|tjänst|lönesättning/i },
  { id: 'hallinto', re: /valinta|valitseminen|valitsem|eron |eroa |ero luottamus|vapautu|jäsenen|varajäsen|edustaj|hallintosääntö|kokousaika|kokousaikataulu|nimeäminen|luottamushenkilö|tilintarkastaj|val av|befrielse|förvaltningsstadga|ledamot|ersättare/i },
  { id: 'avustukset', re: /avustu|bidrag|understöd/i },
  { id: 'aloitteet', re: /aloite|aloitteet|aloitteiden|motion|initiativ/i },
  { id: 'oikaisuvaatimukset', re: /oikaisuvaatim|valitus(?:\s|$|ta|ten)|valitukse|valituslup|hallinto-oikeu|korkeimman hallinto|rättelseyrkande|besvär|förvaltningsdomstol/i },
  { id: 'turvallisuus', re: /valmius|pelastu|turvallisuu|varautumi|beredskap|räddning|säkerhet/i },
  { id: 'digitalisaatio', re: /digitali|tietojärjestelm|tietohallin|ict-|tekoäly|digital|informationssystem/i },
  { id: 'ilmoitusasiat', re: /ilmoitusasi|tiedoksi|tiedoksianto|viranhaltijapäätö|viranhaltijoiden päätö|otto-oikeu|ottomenettel|päätösten seuraamin|anmälningsärend|delegeringsbeslut|för kännedom/i },
];

export const topicIds = TOPICS.map((t) => t.id);

/** Meeting formalities, never a topic even when a word matches ("Pöytäkirjan tarkastajien valinta"). */
const FORMALITY = /pöytäkirjan tarkast|laillisuu|päätösvaltaisuu|työjärjestyksen hyväksy|protokolljustera|laglighet och beslutför/i;

export function itemTopics(title: string): string[] {
  if (FORMALITY.test(title)) return [];
  return TOPICS.filter((t) => t.re.test(title)).map((t) => t.id);
}

/** One item as a row of a topic page, short keys because a topic's file can hold thousands. */
export interface TopicRow {
  d: string; // meeting date
  c: string; // municipality id
  b: string; // body name
  k: string; // body kind
  s: 'agenda' | 'decisions' | 'minutes'; // stage of the meeting
  t: string; // item title
  u: string; // item page path (Finnish)
  v: number; // votes in the item
}

let cache: Map<string, TopicRow[]> | undefined;

/** Items per topic across every enabled municipality, newest first, in a byte-stable order. */
export function topicRows(): Map<string, TopicRow[]> {
  if (cache) return cache;
  const out = new Map<string, TopicRow[]>(topicIds.map((id) => [id, []]));
  const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
  for (const c of cities().filter((x) => x.enabled)) {
    const kinds = new Map(bodies(c.id).map((b) => [b.id, b.kind]));
    for (const { meeting, items } of meetingFiles(c.id)) {
      for (const item of items) {
        const topics = itemTopics(item.title);
        if (!topics.length) continue;
        const row: TopicRow = {
          d: meeting.date, c: c.id, b: bodyName(meeting.body_id), k: kinds.get(meeting.body_id) ?? 'other',
          s: meeting.stage, t: clip(item.title, 200), u: itemUrl(item), v: item.votes.length,
        };
        for (const id of topics) out.get(id)!.push(row);
      }
    }
  }
  for (const rows of out.values()) {
    rows.sort((a, b) => b.d.localeCompare(a.d) || a.c.localeCompare(b.c) || a.u.localeCompare(b.u, 'fi', { numeric: true }));
  }
  cache = out;
  return out;
}
