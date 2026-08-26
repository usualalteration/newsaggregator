import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Newspaper,
  Plus,
  Loader2,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { searchNews, sourceOp } from "@/lib/news";

// The Search page is the source-management home: add / enable / disable /
// delete configured newspapers. Searching happens on the feed page (and via
// news/search); the source list here is configuration-driven (from Redis).

const Sources = () => {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["search-sources"],
    queryFn: () => searchNews(""),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const sources = useMemo(() => data?.sources ?? [], [data]);
  const allEnabled = sources.length > 0 && sources.every((s) => s.enabled);
  const enabledCount = sources.filter((s) => s.enabled).length;

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["search-sources"] });

  const addMutation = useMutation({
    mutationFn: () => sourceOp("add", { name: newName.trim(), url: newUrl.trim() }),
    onSuccess: (res) => {
      if (res.ok) {
        toast.success("Source added");
        setNewName("");
        setNewUrl("");
        setShowAdd(false);
        refresh();
      } else {
        toast.error(res.error || "Could not add source");
      }
    },
    onError: (e: Error) => toast.error(e.message || "Could not add source"),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id?: string; enabled: boolean }) => sourceOp("update", vars),
    onSuccess: (res) => {
      if (res.ok) refresh();
      else toast.error(res.error || "Could not update source");
    },
    onError: (e: Error) => toast.error(e.message || "Could not update source"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => sourceOp("delete", { id }),
    onSuccess: (res) => {
      if (res.ok) refresh();
      else toast.error(res.error || "Could not delete source");
    },
    onError: (e: Error) => toast.error(e.message || "Could not delete source"),
  });

  const onAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || !newUrl.trim()) return;
    addMutation.mutate();
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-3xl px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Newspaper className="size-6 shrink-0 text-primary" />
              <h1 className="text-lg font-bold">News Sources</h1>
            </div>
            <Button asChild variant="outline" size="sm">
              <Link to="/">
                <ArrowLeft className="size-4" />
                <span className="hidden sm:inline">Feed</span>
              </Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6">
        <div className="mb-4 flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {sources.length} source{sources.length === 1 ? "" : "s"} · {enabledCount} enabled
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setShowAdd((v) => !v)}
          >
            <Plus className="size-4" />
            Add source
          </Button>
        </div>

        {showAdd && (
          <form
            onSubmit={onAdd}
            className="mb-4 space-y-2 rounded-md border border-border bg-muted/30 p-3"
          >
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
            <Button
              type="submit"
              size="sm"
              disabled={addMutation.isPending || !newName.trim() || !newUrl.trim()}
            >
              {addMutation.isPending ? <Loader2 className="animate-spin" /> : "Add"}
            </Button>
          </form>
        )}

        {isLoading ? (
          <p className="py-8 text-center text-muted-foreground">Loading sources…</p>
        ) : (
          <div className="space-y-2">
            <label className="flex items-center gap-2 rounded-md border border-border bg-card p-3 text-sm">
              <input
                type="checkbox"
                checked={allEnabled}
                onChange={() => updateMutation.mutate({ enabled: !allEnabled })}
                disabled={updateMutation.isPending}
                className="size-4 accent-primary"
              />
              <span className="font-medium">All</span>
              <span className="text-xs text-muted-foreground">({enabledCount}/{sources.length})</span>
            </label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {sources.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center gap-2 rounded-md border border-border bg-card p-3 text-sm"
                >
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    onChange={() => updateMutation.mutate({ id: s.id, enabled: !s.enabled })}
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
                    {deleteMutation.isPending ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="size-3.5" />
                    )}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default Sources;