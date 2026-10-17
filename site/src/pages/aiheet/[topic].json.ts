// One topic's items in every enabled municipality, for its topic page (/aiheet/{topic}/).
import type { APIRoute } from 'astro';
import { topicIds, topicRows } from '../../lib/topics';

export function getStaticPaths() {
  return topicIds.map((topic) => ({ params: { topic } }));
}

export const GET: APIRoute = ({ params }) =>
  new Response(JSON.stringify(topicRows().get(params.topic as string) ?? []), { headers: { 'Content-Type': 'application/json' } });
