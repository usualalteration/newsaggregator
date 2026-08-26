# News Aggregator

A minimal news aggregator: React frontend + OpenServerless Python actions +
Redis. Fetches RSS/Atom feeds, deduplicates, stores in Redis, and lists
articles through an HTTP action.

![](screenshot.png)

## Actions

- `news/fetch` — fetch enabled sources from `packages/news/fetch/sources.json`,
  normalize, deduplicate (Redis sorted set, SHA-256 of URL as id), store in
  Redis. Uses conditional HTTP GET (`If-Modified-Since` / `If-None-Match`) so
  unchanged feeds return `304` and are not re-downloaded. Per-feed failures are
  isolated (counted in `errors`, never abort the run). Returns
  `{"added", "existing", "errors"}`.
- `news/list` — read newest articles first. Params: `limit` (default 20, max
  50), `offset`, `source` (substring filter), `q` (title+summary search).

## Sources

Sources are configured in `packages/news/fetch/sources.json` (manually
editable, no database table):

```json
[
  {"id": "bbc", "name": "BBC", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "enabled": true}
]
```

Set `"enabled": false` to disable a source. Add a new object to add a source.
The watcher redeploys `news/fetch` automatically when the file is saved.

## Scheduled refresh

`news/fetch` is scheduled with the OpenServerless scheduler via a `cron`
annotation on the action (no custom scheduler, no workers, no extra
infrastructure). The action stays independently invokable for testing.

Enable/refresh the schedule (every 10 minutes) with:

```bash
ops -wsk action update news/fetch -a cron "*/10 * * * *"
```

Verify it is set:

```bash
ops -wsk action get news/fetch | grep cron
```

The annotation survives normal `ops ide devel` watcher redeploys (the
OpenWhisk `action update` flow preserves existing annotations). To change the
interval, re-run the command with a different cron expression. The scheduler
must be enabled on the cluster (`ops config enable --cron`); repeated runs do
not re-store duplicates thanks to `ZADD ... nx`, and unchanged feeds are
skipped via `304` to minimize external HTTP traffic.
