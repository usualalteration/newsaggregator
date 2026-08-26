import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { RefreshCw, Newspaper, Search, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArticleCard } from "@/components/ArticleCard";
import { listNews, fetchNews } from "@/lib/news";
import { useDebounce } from "@/hooks/use-debounce";

const PAGE_SIZE = 20; // fetch 20 initially, more only on request
const SOURCE_BATCH = 50; // one-time fetch to populate the source filter

// Feed titles are often verbose ("Name – subtitle …"); show just the name.
function shortSource(source: string): string {
  if (!source) return "";
  const head = source.split(/\s+[–-]\s+/)[0];
  return (head || source).trim();
}

const News = () => {
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [selectedSource, setSelectedSource] = useState("");
  const query = useDebounce(searchInput, 300).trim();

  // Append-style pagination: load 20 initially, fetch more only on request.
  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    isFetching,
  } = useInfiniteQuery({
    queryKey: ["news", query, selectedSource],
    queryFn: ({ pageParam }) =>
      listNews(PAGE_SIZE, pageParam, query || undefined, selectedSource || undefined),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.count === PAGE_SIZE ? last.offset + last.count : undefined,
    refetchOnWindowFocus: false,
  });

  // One-time fetch to populate the source filter dropdown (not continuous).
  const { data: sourcesData } = useQuery({
    queryKey: ["news-sources"],
    queryFn: () => listNews(SOURCE_BATCH, 0),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const sources = useMemo(() => {
    const set = new Set<string>();
    for (const a of sourcesData?.items ?? []) {
      const name = shortSource(a.source);
      if (name) set.add(name);
    }
    return Array.from(set).sort();
  }, [sourcesData]);

  const articles = useMemo(
    () => data?.pages.flatMap((p) => p.items) ?? [],
    [data],
  );

  const fetchMutation = useMutation({
    mutationFn: () => fetchNews(),
    onSuccess: (res) => {
      toast.success(
        `Added ${res.added} new · ${res.existing} already stored` +
          (res.errors ? ` · ${res.errors} error(s)` : ""),
      );
      queryClient.invalidateQueries({ queryKey: ["news"] });
      queryClient.invalidateQueries({ queryKey: ["news-sources"] });
    },
    onError: (err: Error) => toast.error(err.message || "Fetch failed"),
  });

  const hasFilters = Boolean(query || selectedSource);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-3xl px-4 py-3">
          {/* Title + refresh */}
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Newspaper className="size-6 shrink-0 text-primary" />
              <h1 className="text-lg font-bold">News Aggregator</h1>
            </div>
            <div className="flex items-center gap-2">
              <Button asChild variant="outline" size="sm">
                <Link to="/search">Multi-source search</Link>
              </Button>
              <Button
                size="sm"
                onClick={() => fetchMutation.mutate()}
                disabled={fetchMutation.isPending}
              >
                <RefreshCw className={fetchMutation.isPending ? "animate-spin" : ""} />
                <span className="hidden sm:inline">
                  {fetchMutation.isPending ? "Fetching…" : "Refresh"}
                </span>
              </Button>
            </div>
          </div>

          {/* Search + source filter (stacks on mobile) */}
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="news-search"
                name="q"
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search title or summary…"
                aria-label="Search articles"
                className="pl-8 pr-8"
              />
              {searchInput && (
                <button
                  type="button"
                  onClick={() => setSearchInput("")}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm text-muted-foreground hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              )}
            </div>
            <div className="flex items-center gap-1.5">
              <label
                htmlFor="news-source"
                className="shrink-0 text-xs font-medium text-muted-foreground"
              >
                Source
              </label>
              <select
                id="news-source"
                name="source"
                value={selectedSource}
                onChange={(e) => setSelectedSource(e.target.value)}
                aria-label="Filter by source"
                className="h-10 min-w-32 flex-1 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:flex-none"
              >
                <option value="">All</option>
                {sources.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6">
        {isLoading ? (
          <p className="py-12 text-center text-muted-foreground">
            Loading articles…
          </p>
        ) : error ? (
          <p className="py-12 text-center text-destructive">
            {error.message || "Failed to load news."}
          </p>
        ) : articles.length === 0 ? (
          <div className="py-16 text-center">
            <Newspaper className="mx-auto size-10 text-muted-foreground" />
            <p className="mt-3 text-muted-foreground">
              {hasFilters ? "No articles match your filters." : "No articles yet."}
            </p>
            {!hasFilters && (
              <Button
                className="mt-4"
                onClick={() => fetchMutation.mutate()}
                disabled={fetchMutation.isPending}
              >
                <RefreshCw className={fetchMutation.isPending ? "animate-spin" : ""} />
                Fetch news feeds
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {articles.map((a) => (
              <ArticleCard
                key={a.id}
                title={a.title}
                url={a.url}
                source={a.source}
                published={a.published}
                summary={a.summary}
              />
            ))}
            {hasNextPage && (
              <div className="flex justify-center pt-2">
                <Button
                  variant="outline"
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                >
                  {isFetchingNextPage ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    "Load more"
                  )}
                </Button>
              </div>
            )}
            {!hasNextPage && isFetching && !isLoading && (
              <p className="py-2 text-center text-xs text-muted-foreground">
                Updating…
              </p>
            )}
          </div>
        )}
      </main>
    </div>
  );
};

export default News;