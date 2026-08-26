import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search as SearchIcon,
  Loader2,
  ArrowLeft,
  Newspaper,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArticleCard } from "@/components/ArticleCard";
import { searchNews, sourceOp, type SearchArticle } from "@/lib/news";

const SEARCH_LIMIT = 30;

const Search = () => {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchArticle[]>([]);
  const [cached, setCached] = useState(false);
  const [submittedQ, setSubmittedQ] = useState("");

  // Add-source form
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");

  // Configuration-driven newspaper list (one fetch on mount, not continuous).
  const { data, isLoading: sourcesLoading } = useQuery({
    queryKey: ["search-sources"],
    queryFn: () => searchNews(""),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const sources = useMemo(() => data?.sources ?? [], [data]);
  const allEnabled = sources.length > 0 && sources.every((s) => s.enabled);
  const enabledCount = sources.filter((s) => s.enabled).length;

  const refreshSources = () =>
    queryClient.invalidateQueries({ queryKey: ["search-sources"] });

  const addMutation = useMutation({
    mutationFn: () => sourceOp("add", { name: newName.trim(), url: newUrl.trim() }),
    onSuccess: (res) => {
      if (res.ok) {
        toast.success("Source added");
        setNewName("");
        setNewUrl("");
        setShowAdd(false);
        refreshSources();
      } else {
        toast.error(res.error || "Could not add source");
      }
    },
    onError: (e: Error) => toast.error(e.message || "Could not add source"),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id?: string; enabled: boolean }) =>
      sourceOp("update", vars),
    onSuccess: (res) => {
      if (res.ok) refreshSources();
      else toast.error(res.error || "Could not update source");
    },
    onError: (e: Error) => toast.error(e.message || "Could not update source"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => sourceOp("delete", { id }),
    onSuccess: (res) => {
      if (res.ok) refreshSources();
      else toast.error(res.error || "Could not delete source");
    },
    onError: (e: Error) => toast.error(e.message || "Could not delete source"),
  });

  const searchMutation = useMutation({
    mutationFn: () => searchNews(q.trim(), undefined, SEARCH_LIMIT),
    onSuccess: (res) => {
      setResults(res.items);
      setCached(Boolean(res.cached));
      setSubmittedQ(res.q || q.trim());
    },
    onError: (e: Error) => toast.error(e.message || "Search failed"),
  });

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    searchMutation.mutate();
  };

  const onAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || !newUrl.trim()) return;
    addMutation.mutate();
  };

  const toggleAll = () =>
    updateMutation.mutate({ enabled: !allEnabled });

  const toggleOne = (id: string, enabled: boolean) =>
    updateMutation.mutate({ id, enabled: !enabled });

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-3xl px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Newspaper className="size-6 shrink-0 text-primary" />
              <h1 className="text-lg font-bold">News Search</h1>
            </div>
            <Button asChild variant="outline" size="sm">
              <Link to="/">
                <ArrowLeft className="size-4" />
                <span className="hidden sm:inline">Feed</span>
              </Link>
            </Button>
          </div>

          <form onSubmit={onSearch} className="mt-3">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="news-q"
                name="q"
                type="search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search across newspapers (e.g. OpenAI, Ukraine)…"
                aria-label="Search query"
                className="pl-8"
              />
            </div>
            <Button type="submit" className="mt-2 w-full" disabled={searchMutation.isPending || !q.trim()}>
              {searchMutation.isPending ? <Loader2 className="animate-spin" /> : <SearchIcon />}
              Search {enabledCount > 0 ? `(${enabledCount} source${enabledCount === 1 ? "" : "s"})` : ""}
            </Button>
          </form>

          {/* Newspaper selector + management */}
          <fieldset className="mt-3 rounded-md border border-border p-3">
            <div className="flex items-center justify-between">
              <legend className="px-1 text-xs font-medium text-muted-foreground">
                Sources
              </legend>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setShowAdd((v) => !v)}
              >
                <Plus className="size-4" />
                Add source
              </Button>
            </div>

            {showAdd && (
              <form onSubmit={onAdd} className="mt-2 space-y-2 rounded-md border border-border bg-muted/30 p-2">
                <Input
                  id="src-name"
                  name="name"
                  placeholder="Name (e.g. Reuters)"
                  aria-label="Source name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <Input
                  id="src-url"
                  name="url"
                  type="url"
                  placeholder="RSS URL (https://example.com/rss)"
                  aria-label="RSS URL"
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                />
                <Button type="submit" size="sm" disabled={addMutation.isPending || !newName.trim() || !newUrl.trim()}>
                  {addMutation.isPending ? <Loader2 className="animate-spin" /> : "Add"}
                </Button>
              </form>
            )}

            {sourcesLoading ? (
              <p className="px-2 py-1 text-sm text-muted-foreground">Loading sources…</p>
            ) : (
              <div className="mt-2 space-y-1">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={allEnabled}
                    onChange={toggleAll}
                    disabled={updateMutation.isPending}
                    className="size-4 accent-primary"
                  />
                  <span className="font-medium">All</span>
                  <span className="text-xs text-muted-foreground">({enabledCount}/{sources.length})</span>
                </label>
                <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                  {sources.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={s.enabled}
                        onChange={() => toggleOne(s.id, s.enabled)}
                        disabled={updateMutation.isPending}
                        className="size-4 accent-primary"
                      />
                      <span className={s.enabled ? "" : "text-muted-foreground line-through"}>
                        {s.name}
                      </span>
                      <button
                        type="button"
                        onClick={() => deleteMutation.mutate(s.id)}
                        disabled={deleteMutation.isPending}
                        aria-label={`Delete ${s.name}`}
                        className="ml-auto rounded-sm p-0.5 text-muted-foreground hover:text-destructive"
                      >
                        {deleteMutation.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </fieldset>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6">
        {searchMutation.isPending ? (
          <p className="py-12 text-center text-muted-foreground">Searching…</p>
        ) : submittedQ ? (
          <>
            <p className="mb-3 text-sm text-muted-foreground">
              {results.length} result{results.length === 1 ? "" : "s"} for
              “{submittedQ}”{cached ? " · cached" : ""}
            </p>
            {results.length === 0 ? (
              <div className="py-16 text-center">
                <Newspaper className="mx-auto size-10 text-muted-foreground" />
                <p className="mt-3 text-muted-foreground">No articles found.</p>
              </div>
            ) : (
              <div className="space-y-3">
                {results.map((a, i) => (
                  <ArticleCard
                    key={`${a.url}-${i}`}
                    title={a.title}
                    url={a.url}
                    source={a.source}
                    published={a.published}
                    summary={a.summary}
                  />
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="py-12 text-center text-muted-foreground">
            Enter a query to search across enabled newspapers.
          </p>
        )}
      </main>
    </div>
  );
};

export default Search;