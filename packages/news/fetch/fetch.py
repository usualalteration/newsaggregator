"""Fetch RSS/Atom feeds, normalize, deduplicate and store in Redis.

Sources are configured in ``sources.json`` next to this module (a small,
manually-editable JSON file — no database table, no admin UI). Each entry:
  {"id": "bbc", "name": "BBC", "url": "https://...", "enabled": true}
Only entries with ``enabled: true`` are fetched. An optional ``sources``
request parameter (a JSON list of URLs) overrides the config for ad-hoc
fetches; those use the feed's own channel title as the article source.

Storage model:
  * sorted set ``{prefix}news:feed`` — member = article id (SHA-256 of
    the article URL), score = published epoch seconds. Used for both
    deduplication (ZADD ... nx returns 0 when the member already exists)
    and newest-first ordering (ZREVRANGE).
  * hash ``{prefix}news:data`` — field = article id, value = article JSON
    containing only the frontend fields (title, url, source, published,
    summary). The id is the field key and is not duplicated in the payload.
  * hash ``{prefix}news:feedmeta`` — field = source id, value = JSON
    {lm, etag} capturing the feed's Last-Modified / ETag for conditional
    HTTP requests, so unchanged feeds are not re-downloaded.

The index is capped at the latest 2000 articles; trimming removes both the
sorted-set members and the matching hash records so no orphan content remains.

Feeds are fetched sequentially with a short timeout; a single feed failure
is counted and skipped without aborting the whole action. Only the Python
standard library is used (urllib, xml.etree, html.parser, hashlib,
email.utils). Redis round-trips are minimized with pipelines.

Scheduling: the OpenServerless scheduler invokes this action periodically
when a ``cron`` annotation is set on the action (e.g. ``*/10 * * * *``) —
no custom scheduler, no long-running process, no workers. The action
remains independently invokable for testing. Deduplication via
``ZADD ... nx`` plus conditional HTTP GETs ensure the same article is not
re-processed and external HTTP traffic is minimized on repeated runs.
"""

import os
import json
import time
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

# Path to the manually-editable source configuration (sibling of this module).
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")

# Inline fallback used only if sources.json is missing or unreadable, so the
# action never breaks. The JSON file is the intended source of truth.
FALLBACK_SOURCES = [
    {"id": "hackernews", "name": "Hacker News", "url": "https://news.ycombinator.com/rss", "enabled": True},
    {"id": "bbc", "name": "BBC", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "enabled": True},
    {"id": "theverge", "name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "enabled": True},
    {"id": "aljazeera", "name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "enabled": True},
]

USER_AGENT = "trustable-news-aggregator/1.0 (+https://trustable.ai)"
FETCH_TIMEOUT = 10          # seconds per feed HTTP request (short)
DEFAULT_MAX_PER_FEED = 20   # cap entries processed per feed
MAX_ARTICLES = 2000         # keep only the latest 2000 articles
SUMMARY_MAX = 500           # max chars of stripped summary kept

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class _Stripper(HTMLParser):
    """Minimal HTML-to-text converter for feed summaries."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip > 0:
            self._skip -= 1
        if tag in ("p", "div", "br", "li"):
            self.parts.append(" ")

    def handle_data(self, data):
        if self._skip == 0:
            self.parts.append(data)

    def text(self):
        return " ".join("".join(self.parts).split())


def _strip_html(value):
    if not value:
        return ""
    try:
        s = _Stripper()
        s.feed(value)
        return s.text()[:SUMMARY_MAX]
    except Exception:
        return " ".join(str(value).split())[:SUMMARY_MAX]


def _text(elem):
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _local(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def _to_iso(value):
    """Best-effort conversion of a feed date string to ISO 8601."""
    if not value:
        return ""
    cleaned = value.replace(" GMT", " +0000").strip()
    for cand in (cleaned, value):
        try:
            dt = parsedate_to_datetime(cand)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
        except Exception:
            pass
    try:  # Atom ISO 8601
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return value


def _epoch(iso, fallback):
    """Epoch seconds (float) for a sorted-set score."""
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    return fallback


def _fetch_url(url, if_modified_since="", if_none_match=""):
    """Fetch a feed, optionally with conditional headers.

    Returns (body, last_modified, etag). Raises urllib.error.HTTPError on
    non-2xx responses (including 304 Not Modified, which the caller treats
    as "unchanged, skip").
    """
    headers = {"User-Agent": USER_AGENT}
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        body = resp.read()
        last_modified = resp.headers.get("Last-Modified", "") or ""
        etag = resp.headers.get("ETag", "") or ""
        return body, last_modified, etag


def _normalize_item(item, source_title, source_url):
    """Normalize one RSS <item> or Atom <entry> -> {id,title,url,source,published,summary}."""
    is_atom = "Atom" in item.tag
    title = url = summary = published = ""

    if is_atom:
        t = item.find(f"{_ATOM_NS}title")
        title = _text(t) if t is not None else ""
        chosen = None
        for ln in item.findall(f"{_ATOM_NS}link"):
            if (ln.get("rel") or "alternate").lower() == "alternate":
                chosen = ln
                break
        if chosen is None:
            chosen = item.find(f"{_ATOM_NS}link")
        url = chosen.get("href") if chosen is not None else ""
        if not url:
            i = item.find(f"{_ATOM_NS}id")
            url = _text(i) if i is not None else ""
        s = item.find(f"{_ATOM_NS}summary")
        if s is None:
            s = item.find(f"{_ATOM_NS}content")
        summary = _strip_html(_text(s)) if s is not None else ""
        p = item.find(f"{_ATOM_NS}published")
        if p is None:
            p = item.find(f"{_ATOM_NS}updated")
        published = _to_iso(_text(p)) if p is not None else ""
    else:  # RSS 2.0
        t = item.find("title")
        title = _text(t) if t is not None else ""
        l = item.find("link")
        url = _text(l) if l is not None else ""
        d = item.find("description")
        summary = _strip_html(_text(d)) if d is not None else ""
        p = item.find("pubDate")
        published = _to_iso(_text(p)) if p is not None else ""

    # Deterministic id from the URL (SHA-256); fall back to title if no URL.
    ident_input = url or title
    article_id = hashlib.sha256(ident_input.encode("utf-8")).hexdigest() if ident_input else ""

    return {
        "id": article_id,
        "title": title,
        "url": url,
        "source": source_title or source_url,
        "published": published,
        "summary": summary,
    }


def _parse_feed(xml_bytes, source_url, max_per_feed, source_name=""):
    """Parse RSS 2.0 or Atom 1.0 and return up to max_per_feed articles.

    ``source_name`` (from the config) is used as the article source when
    present; otherwise the feed's channel title is used.
    """
    root = ET.fromstring(xml_bytes)
    tag = _local(root.tag)
    channel_title = ""
    items = []

    if tag == "rss":
        channel = root.find("channel")
        if channel is not None:
            t = channel.find("title")
            channel_title = _text(t) if t is not None else ""
            items = list(channel.findall("item"))
    elif tag == "feed":
        t = root.find(f"{_ATOM_NS}title")
        if t is None:
            t = root.find("title")
        channel_title = _text(t) if t is not None else ""
        items = list(root.findall(f"{_ATOM_NS}entry"))
        if not items:
            items = list(root.findall("entry"))
    else:
        return []

    source_title = source_name or channel_title or source_url

    out = []
    for item in items[:max_per_feed]:
        art = _normalize_item(item, source_title, source_url)
        if art["id"] and (art["title"] or art["url"]):
            out.append(art)
    return out


def _load_config_sources():
    """Load enabled sources from sources.json, falling back to inline defaults."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            sources = [s for s in data if isinstance(s, dict) and s.get("enabled", True) and s.get("url")]
            if sources:
                return sources
    except Exception:
        pass
    return [s for s in FALLBACK_SOURCES if s.get("enabled", True) and s.get("url")]


def _load_sources_redis(redis, prefix):
    """Load enabled, fetchable (url) sources from the Redis source store.

    Returns None when Redis is unavailable or the store is empty so the caller
    falls back to the file config (sources.json).
    """
    if redis is None:
        return None
    try:
        raw = redis.hgetall(prefix + "news:sources")
    except Exception:
        return None
    if not raw:
        return None
    out = []
    for val in raw.values():
        if isinstance(val, bytes):
            val = val.decode("utf-8", "replace")
        try:
            s = json.loads(val)
        except Exception:
            continue
        if isinstance(s, dict) and s.get("enabled", True) and s.get("url"):
            out.append(s)
    return out or None


def _resolve_sources(args, ctx=None):
    """Return the list of sources to fetch: ad-hoc ``sources`` param override,
    otherwise the Redis source store (if populated), otherwise sources.json.

    Each item is {"id": str, "name": str, "url": str}. Ad-hoc URLs get a
    derived id and an empty name (the feed's channel title is then used).
    """
    raw = args.get("sources")
    if raw:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [u.strip() for u in raw.split(",") if u.strip()]
        if isinstance(raw, list) and raw:
            out = []
            for u in raw:
                u = str(u).strip()
                if u:
                    out.append({"id": hashlib.sha1(u.encode("utf-8")).hexdigest()[:16], "name": "", "url": u})
            return out
    redis = getattr(ctx, "REDIS", None) if ctx else None
    prefix = getattr(ctx, "REDIS_PREFIX", "") or "" if ctx else ""
    base = _load_sources_redis(redis, prefix) or _load_config_sources()
    return [{"id": s.get("id", ""), "name": s.get("name", ""), "url": s.get("url", "")} for s in base if s.get("url")]


def _load_feed_meta(redis, meta_key):
    """Load {source_id: {lm, etag}} from the feedmeta hash (one HGETALL)."""
    out = {}
    try:
        raw = redis.hgetall(meta_key) or {}
    except Exception:
        return out
    for k, v in raw.items():
        if isinstance(k, bytes):
            k = k.decode("utf-8")
        if isinstance(v, bytes):
            v = v.decode("utf-8")
        try:
            out[k] = json.loads(v)
        except Exception:
            continue
    return out


def _payload(art):
    """JSON stored per article: only the fields used by the frontend.

    The article id is NOT stored here — it is the hash field / sorted-set
    member, so it is re-injected by news/list on read to avoid duplicate
    content.
    """
    return json.dumps(
        {
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source": art.get("source", ""),
            "published": art.get("published", ""),
            "summary": art.get("summary", ""),
        },
        ensure_ascii=False,
    )


def _int_arg(args, name, default):
    try:
        return int(args.get(name, default))
    except (TypeError, ValueError):
        return default


def main(args, ctx=None):
    if not ctx or not hasattr(ctx, "REDIS") or ctx.REDIS is None:
        return {"added": 0, "existing": 0, "errors": 1}
    redis = ctx.REDIS

    prefix = getattr(ctx, "REDIS_PREFIX", "") or ""
    zset_key = f"{prefix}news:feed"
    data_key = f"{prefix}news:data"
    meta_key = f"{prefix}news:feedmeta"

    sources = _resolve_sources(args, ctx)
    max_per_feed = max(1, _int_arg(args, "max_per_feed", DEFAULT_MAX_PER_FEED))
    now = time.time()

    added = 0
    existing = 0
    errors = 0

    # Stage 1: fetch + parse sources sequentially. Conditional HTTP GETs use
    # the stored Last-Modified / ETag so unchanged feeds return 304 and are
    # skipped (not re-downloaded, not an error). One feed failure is counted
    # and skipped; it never aborts the whole action.
    feed_meta = _load_feed_meta(redis, meta_key)
    updated_meta = {}
    candidates = []
    for src in sources:
        url = src.get("url")
        if not url:
            continue
        sid = src.get("id") or hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        m = feed_meta.get(sid, {}) or {}
        try:
            body, lm, etag = _fetch_url(url, m.get("lm", ""), m.get("etag", ""))
        except urllib.error.HTTPError as e:
            if e.code == 304:
                continue  # feed unchanged — skip without counting as error
            errors += 1
            continue
        except Exception:
            errors += 1
            continue
        candidates.extend(_parse_feed(body, url, max_per_feed, src.get("name", "")))
        if lm or etag:
            updated_meta[sid] = {"lm": lm, "etag": etag}

    # Persist any new/changed feed conditional-request metadata (one pipeline).
    if updated_meta:
        try:
            pipe = redis.pipeline()
            for sid, m in updated_meta.items():
                pipe.hset(meta_key, sid, json.dumps(m, ensure_ascii=False))
            pipe.execute()
        except Exception:
            pass

    if not candidates:
        return {"added": added, "existing": existing, "errors": errors}

    # Stage 2: one pipelined ZADD (nx=True) per candidate -> dedup + ordering.
    pipe = redis.pipeline()
    for art in candidates:
        score = _epoch(art["published"], now)
        pipe.zadd(zset_key, {art["id"]: score}, nx=True)
    zadd_results = pipe.execute()

    # Stage 3: one pipelined HSET for the newly added payloads only.
    new_ids = []
    pipe = redis.pipeline()
    for art, was_added in zip(candidates, zadd_results):
        if was_added:
            pipe.hset(data_key, art["id"], _payload(art))
            new_ids.append(art["id"])
    if new_ids:
        pipe.execute()

    for was_added in zadd_results:
        if was_added:
            added += 1
        else:
            existing += 1

    # Stage 4 (occasional): keep the sorted set bounded and drop orphan payloads.
    total = redis.zcard(zset_key)
    if total > MAX_ARTICLES:
        evict = total - MAX_ARTICLES
        evicted_ids = redis.zrange(zset_key, 0, evict - 1)  # oldest
        if evicted_ids:
            pipe = redis.pipeline()
            pipe.zremrangebyrank(zset_key, 0, evict - 1)
            pipe.hdel(data_key, *evicted_ids)
            pipe.execute()

    return {"added": added, "existing": existing, "errors": errors}