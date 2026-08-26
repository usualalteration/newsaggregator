import { memo } from "react";
import { ExternalLink } from "lucide-react";

export interface ArticleCardProps {
  title: string;
  url: string;
  source: string;
  published: string;
  summary: string;
}

// Feed titles are often verbose ("Name – subtitle …"); show just the name.
function shortSource(source: string): string {
  if (!source) return "";
  return (source.split(/\s+[–-]\s+/)[0] || source).trim();
}

function formatPublished(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const ArticleCard = memo(({ title, url, source, published, summary }: ArticleCardProps) => {
  const src = shortSource(source);
  return (
    <article className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold leading-snug">
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-primary hover:underline"
            >
              {title || "(untitled)"}
            </a>
          ) : (
            title || "(untitled)"
          )}
        </h2>
        {url && <ExternalLink className="mt-1 size-4 shrink-0 text-muted-foreground" />}
      </div>
      {(src || published) && (
        <p className="mt-1 text-xs font-medium text-muted-foreground">
          {src}
          {src && published ? " · " : ""}
          {published ? formatPublished(published) : ""}
        </p>
      )}
      {summary && (
        <p className="mt-2 text-sm text-muted-foreground line-clamp-3">{summary}</p>
      )}
    </article>
  );
});
ArticleCard.displayName = "ArticleCard";

export { ArticleCard };