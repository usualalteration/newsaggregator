"""Multi-source news search action (news/search).

Search order:
  1. existing Redis articles (news:feed / news:data) filtered by the query
  2. RSS/Atom feeds configured in sources.json, filtered by the query
  3. source-specific public search endpoints (``search_url`` with ``{q}``)

This action also manages the configured source list stored in Redis
(``{prefix}news:sources``): add (with RSS/Atom validation), list, enable/
disable, and delete. The file ``sources.json`` seeds the built-in sources
into Redis on first use; afterwards Redis is the source of truth so new
sources are picked up by news/fetch and news/search without code changes.

Results are normalized, deduplicated by canonical URL (+ normalized title
when useful), sorted newest-first, and cached briefly in Redis. Each source
is fetched with a short timeout; a failing source is skipped without failing
the whole search. Only enabled sources are queried, and work stops once
enough results are available. Only the Python standard library is used.
"""

import os
import json
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")

USER_AGENT = "trustable-news-search/1.0 (+https://trustable.ai)"
FETCH_TIMEOUT = 8          # short per-source HTTP timeout
MAX_PER_SOURCE = 15        # cap results parsed per source
CACHE_TTL = 120            # cache search results for 2 minutes
SUMMARY_MAX = 300
MAX_LIMIT = 100
VALIDATE_TIMEOUT = 8       # timeout when validating a new source's feed

SOURCES_KEY = "news:sources"

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class _Stripper(HTMLParser):
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
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return value


def _normalize(item, source_name, source_url):
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
    else:
        t = item.find("title")
        title = _text(t) if t is not None else ""
        l = item.find("link")
        url = _text(l) if l is not None else ""
        d = item.find("description")
        summary = _strip_html(_text(d)) if d is not None else ""
        p = item.find("pubDate")
        published = _to_iso(_text(p)) if p is not None else ""
    return {
        "title": title,
        "url": url,
        "source": source_name or source_url,
        "published": published,
        "summary": summary,
    }


def _parse_feed(xml_bytes, source_name, source_url, q, filter_by_q):
    """Parse RSS/Atom, normalize, and (optionally) filter by query.

    ``filter_by_q`` is True for plain RSS feeds (tier 2) and False for
    source-specific search endpoints whose results already match the query.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []
    tag = _local(root.tag)
    items = []
    if tag == "rss":
        channel = root.find("channel")
        if channel is not None:
            items = list(channel.findall("item"))
    elif tag == "feed":
        items = list(root.findall(f"{_ATOM_NS}entry")) or list(root.findall("entry"))
    ql = q.lower() if q else ""
    out = []
    for item in items[:MAX_PER_SOURCE]:
        art = _normalize(item, source_name, source_url)
        if not (art["title"] or art["url"]):
            continue
        if filter_by_q and ql:
            hay = f"{art['title']} {art['summary']}".lower()
            if ql not in hay:
                continue
        out.append(art)
    return out


def _fetch(url, timeout=FETCH_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _canonical_url(url):
    if not url:
        return ""
    try:
        u = urllib.parse.urlparse(url)
        host = (u.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = u.path.rstrip("/") or "/"
        return f"{host}{path}"
    except Exception:
        return url.strip().lower()


def _norm_title(t):
    return " ".join((t or "").lower().split())


# --- source management (Redis-backed) -----------------------------------

def _slug(name):
    s = "".join(c if c.isalnum() else "-" for c in (name or "").lower()).strip("-")
    return s or "source"


def _file_sources():
    """Built-in seed sources from sources.json."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    out = []
    if isinstance(data, list):
        for s in data:
            if not (isinstance(s, dict) and (s.get("url") or s.get("search_url"))):
                continue
            if not s.get("id"):
                s["id"] = _slug(s.get("name") or s.get("url") or "")
            out.append(s)
    return out


def _source_list(all_sources):
    return [
        {
            "id": s.get("id", ""),
            "name": s.get("name", "") or s.get("id", ""),
            "enabled": bool(s.get("enabled", True)),
            "url": s.get("url", "") or "",
        }
        for s in all_sources
    ]


def _sources_get_all(redis, prefix):
    """All sources from Redis; seed from the file on first use (empty hash)."""
    if redis is None:
        return _file_sources()
    key = prefix + SOURCES_KEY
    try:
        raw = redis.hgetall(key)
    except Exception:
        return _file_sources()
    if not raw:
        seeded = _file_sources()
        if seeded:
            try:
                for s in seeded:
                    redis.execute_command("HSET", key, s.get("id", ""),
                                          json.dumps(s, ensure_ascii=False))
                raw = redis.hgetall(key)
            except Exception:
                return seeded
    out = []
    for val in (raw or {}).values():
        if isinstance(val, bytes):
            val = val.decode("utf-8", "replace")
        try:
            s = json.loads(val)
            if isinstance(s, dict):
                out.append(s)
        except Exception:
            continue
    return out or _file_sources()


def _sources_put(redis, prefix, source):
    redis.execute_command("HSET", prefix + SOURCES_KEY, source["id"],
                          json.dumps(source, ensure_ascii=False))


def _sources_del(redis, prefix, sid):
    redis.execute_command("HDEL", prefix + SOURCES_KEY, sid)


def _select(all_sources, ids):
    if not ids:
        return all_sources
    idset = set(ids)
    sel = [s for s in all_sources if s.get("id") in idset]
    return sel or all_sources


def _request_data(args):
    data = dict(args) if isinstance(args, dict) else {}
    body = data.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = {}
    if isinstance(body, dict):
        for k, v in body.items():
            if k not in ("body", "__ow_method", "__ow_headers", "__ow_path"):
                data.setdefault(k, v)
    return data


def _source_op(op, data, redis, prefix, all_sources):
    """Handle add / update / delete on the Redis source store."""
    listing = _source_list(all_sources)

    if op == "add":
        name = str(data.get("name") or "").strip()
        url = str(data.get("url") or "").strip()
        if not name or not url:
            return {"ok": False, "error": "name and url are required", "sources": listing}
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {"ok": False, "error": "invalid URL", "sources": listing}
        cu = _canonical_url(url)
        for s in all_sources:
            if cu and _canonical_url(s.get("url") or s.get("search_url") or "") == cu:
                return {"ok": False, "error": "a source with this URL already exists",
                        "sources": listing}
        # validate it is a real RSS/Atom feed
        try:
            body = _fetch(url, timeout=VALIDATE_TIMEOUT)
            sample = _parse_feed(body, name, url, "", False)
        except Exception:
            return {"ok": False, "error": "could not fetch the URL", "sources": listing}
        if not sample:
            return {"ok": False, "error": "not a valid RSS/Atom feed", "sources": listing}
        sid = _slug(name)
        existing = {s.get("id") for s in all_sources}
        base, i = sid, 1
        while sid in existing:
            sid = f"{base}-{i}"
            i += 1
        source = {"id": sid, "name": name, "url": url, "enabled": True}
        try:
            _sources_put(redis, prefix, source)
        except Exception as e:
            return {"ok": False, "error": f"could not save: {e}", "sources": listing}
        return {"ok": True, "sources": _source_list(_sources_get_all(redis, prefix))}

    if op == "update":
        sid = str(data.get("id") or "").strip()
        if data.get("enabled") is None:
            return {"ok": False, "error": "enabled is required", "sources": listing}
        enabled = bool(data.get("enabled"))
        try:
            if sid:
                target = next((s for s in all_sources if s.get("id") == sid), None)
                if target is None:
                    return {"ok": False, "error": "source not found", "sources": listing}
                target["enabled"] = enabled
                _sources_put(redis, prefix, target)
            else:
                for s in all_sources:
                    s["enabled"] = enabled
                    _sources_put(redis, prefix, s)
        except Exception as e:
            return {"ok": False, "error": str(e), "sources": listing}
        return {"ok": True, "sources": _source_list(_sources_get_all(redis, prefix))}

    if op == "delete":
        sid = str(data.get("id") or "").strip()
        if not sid:
            return {"ok": False, "error": "id is required", "sources": listing}
        try:
            _sources_del(redis, prefix, sid)
        except Exception as e:
            return {"ok": False, "error": str(e), "sources": listing}
        return {"ok": True, "sources": _source_list(_sources_get_all(redis, prefix))}

    return {"ok": False, "error": "unknown op", "sources": listing}


def main(args, ctx=None):
    data = _request_data(args)
    redis_ok = bool(ctx and hasattr(ctx, "REDIS") and ctx.REDIS is not None)
    prefix = getattr(ctx, "REDIS_PREFIX", "") or "" if redis_ok else ""

    all_sources = _sources_get_all(ctx.REDIS if redis_ok else None, prefix)
    source_list = _source_list(all_sources)

    op = str(data.get("op") or "").strip().lower()
    if op in ("add", "update", "delete"):
        if not redis_ok:
            return {"ok": False, "error": "Redis non configurato", "sources": source_list}
        return _source_op(op, data, ctx.REDIS, prefix, all_sources)

    q = str(data.get("q") or "").strip()
    src_ids = data.get("sources")
    if isinstance(src_ids, str):
        try:
            src_ids = json.loads(src_ids)
        except Exception:
            src_ids = [s.strip() for s in src_ids.split(",") if s.strip()]
    if not isinstance(src_ids, list):
        src_ids = []
    src_ids = [str(s) for s in src_ids if str(s).strip()]
    try:
        limit = int(data.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, MAX_LIMIT))

    if not q:
        return {"items": [], "sources": source_list, "count": 0, "q": "", "cached": False}

    enabled_sources = [s for s in all_sources if s.get("enabled", True)]
    selected = _select(enabled_sources, src_ids)
    cache_key_seed = q.lower() + "|" + "|".join(sorted(s.get("id", "") for s in selected))
    cache_key = f"news:search:{hashlib.sha1(cache_key_seed.encode('utf-8')).hexdigest()}"

    # --- cache hit -------------------------------------------------------
    if redis_ok:
        try:
            cached = ctx.REDIS.execute_command("GET", prefix + cache_key)
            if cached:
                try:
                    payload = json.loads(cached)
                    payload["sources"] = source_list
                    payload["cached"] = True
                    return payload
                except Exception:
                    pass
        except Exception:
            pass

    items = []
    seen_urls = set()
    seen_titles = set()

    def _add(art):
        cu = _canonical_url(art.get("url"))
        nt = _norm_title(art.get("title"))
        if cu and cu in seen_urls:
            return False
        if nt and nt in seen_titles:
            return False
        if cu:
            seen_urls.add(cu)
        if nt:
            seen_titles.add(nt)
        items.append({
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source": art.get("source", ""),
            "published": art.get("published", ""),
            "summary": art.get("summary", ""),
        })
        return True

    # --- tier 1: existing Redis articles --------------------------------
    if redis_ok:
        try:
            ids = ctx.REDIS.zrevrange(prefix + "news:feed", 0, 199)
            if ids:
                sel_names = {s.get("name") for s in selected}
                payloads = ctx.REDIS.hmget(prefix + "news:data", *ids)
                for raw in payloads:
                    if raw is None:
                        continue
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "replace")
                    try:
                        art = json.loads(raw)
                    except Exception:
                        continue
                    if sel_names and art.get("source") not in sel_names:
                        continue
                    hay = f"{art.get('title', '')} {art.get('summary', '')}".lower()
                    if q.lower() not in hay:
                        continue
                    _add(art)
                    if len(items) >= limit:
                        break
        except Exception:
            pass

    # --- tiers 2 & 3: configured feeds / search endpoints ---------------
    if len(items) < limit:
        for s in selected:
            if len(items) >= limit:
                break
            search_url = s.get("search_url")
            feed_url = s.get("url")
            name = s.get("name", "") or s.get("id", "")
            if search_url:
                url = search_url.replace("{q}", urllib.parse.quote(q))
                filter_by_q = False
            elif feed_url:
                url = feed_url
                filter_by_q = True
            else:
                continue
            try:
                body = _fetch(url)
            except Exception:
                continue  # failing source is skipped
            for art in _parse_feed(body, name, url, q, filter_by_q):
                if len(items) >= limit:
                    break
                _add(art)

    # --- sort newest first, cap, cache ---------------------------------
    items.sort(key=lambda a: a.get("published") or "", reverse=True)
    items = items[:limit]

    result = {"items": items, "sources": source_list, "count": len(items), "q": q, "cached": False}

    if redis_ok:
        try:
            ctx.REDIS.execute_command("SET", prefix + cache_key, json.dumps(result, ensure_ascii=False), "EX", CACHE_TTL)
        except Exception:
            pass

    return result