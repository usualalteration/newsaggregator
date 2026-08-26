// Minimal client for the news aggregator OpenServerless actions.
// The generated wrapper nests the module result under a "body" key, so we
// unwrap it here before returning data to callers.

export interface Article {
  id: string;
  title: string;
  url: string;
  source: string;
  published: string;
  summary: string;
}

export interface NewsListResponse {
  items: Article[];
  count: number;
  offset: number;
  limit: number;
}

export interface NewsFetchResponse {
  added: number;
  existing: number;
  errors: number;
}

export interface SearchSource {
  id: string;
  name: string;
  enabled: boolean;
  url: string;
}

export interface SearchArticle {
  title: string;
  url: string;
  source: string;
  published: string;
  summary: string;
}

export interface NewsSearchResponse {
  items: SearchArticle[];
  sources: SearchSource[];
  count: number;
  q: string;
  cached: boolean;
}

function unwrap<T>(raw: unknown): T {
  if (raw && typeof raw === "object" && "body" in raw) {
    return (raw as { body: T }).body;
  }
  return raw as T;
}

async function parse<T>(res: Response): Promise<T> {
  const raw = await res.json();
  const data = unwrap<T>(raw);
  if (!res.ok) {
    const msg = (data as { error?: string })?.error || `Request failed: ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

export async function listNews(
  limit = 20,
  offset = 0,
  q?: string,
  source?: string,
): Promise<NewsListResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (q) params.set("q", q);
  if (source) params.set("source", source);
  const res = await fetch(`/api/my/news/list?${params.toString()}`);
  return parse<NewsListResponse>(res);
}

export async function fetchNews(sources?: string[]): Promise<NewsFetchResponse> {
  const res = await fetch(`/api/my/news/fetch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sources && sources.length ? { sources } : {}),
  });
  return parse<NewsFetchResponse>(res);
}

export async function searchNews(
  q: string,
  sources?: string[],
  limit = 30,
): Promise<NewsSearchResponse> {
  const res = await fetch(`/api/my/news/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      q,
      sources: sources && sources.length ? sources : undefined,
      limit,
    }),
  });
  return parse<NewsSearchResponse>(res);
}

export interface SourceOpResponse {
  ok: boolean;
  error?: string;
  sources: SearchSource[];
}

// Manage configured news sources (add / update / delete) via news/search.
export async function sourceOp(
  op: "add" | "update" | "delete",
  data: Record<string, unknown> = {},
): Promise<SourceOpResponse> {
  const res = await fetch(`/api/my/news/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op, ...data }),
  });
  return parse<SourceOpResponse>(res);
}