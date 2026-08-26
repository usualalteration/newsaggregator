"""List stored news articles from Redis.

  * hash ``{prefix}news:data`` — field = article id, value = article JSON
    (frontend fields only; the id is the field key and is re-injected here).
  * hash ``{prefix}news:feedmeta`` — feed conditional-GET metadata (owned by
    news/fetch, not read here).

The article id is not stored in the payload; it is re-injected from the
sorted-set member / hash field on read so the API shape is unchanged.

Parameters:
  limit   - page size (default 20, max 50)
  offset  - zero-based page offset (default 0)
  source  - case-insensitive substring filter on the article source
  q       - case-insensitive substring search over title + summary

Response: {"items": [...], "count": N, "offset": O, "limit": L}

Redis access is kept to at most two calls and never uses SCAN:
  * no filter  -> ZREVRANGE(window) + HMGET(window)
  * filtered   -> ZREVRANGE(0, -1) + HMGET(all), filter in Python
The sorted set is globally capped by news/fetch, so the filtered path is
bounded and cheap.
"""

import json


def _int_arg(args, name, default):
    try:
        return int(args.get(name, default))
    except (TypeError, ValueError):
        return default


def _str_arg(args, name):
    value = args.get(name)
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def _decode(item):
    if item is None:
        return None
    if isinstance(item, bytes):
        item = item.decode("utf-8")
    try:
        return json.loads(item)
    except Exception:
        return None


def _items_with_ids(redis, data_key, ids):
    """Fetch payloads for ``ids`` (one HMGET) and re-inject the id field."""
    items = []
    if not ids:
        return items
    payloads = redis.hmget(data_key, *ids)
    for sid, raw in zip(ids, payloads):
        art = _decode(raw)
        if art is None:
            continue
        art["id"] = sid
        items.append(art)
    return items


def main(args, ctx=None):
    if not ctx or not hasattr(ctx, "REDIS") or ctx.REDIS is None:
        return {"items": [], "count": 0, "offset": 0, "limit": 20}

    redis = ctx.REDIS
    prefix = getattr(ctx, "REDIS_PREFIX", "") or ""
    zset_key = f"{prefix}news:feed"
    data_key = f"{prefix}news:data"

    limit = max(1, min(_int_arg(args, "limit", 20), 50))
    offset = max(0, _int_arg(args, "offset", 0))
    source_filter = _str_arg(args, "source").lower()
    query = _str_arg(args, "q").lower()
    filtered = bool(source_filter or query)

    if not filtered:
        # Exact window only: two Redis calls, no scan.
        ids = redis.zrevrange(zset_key, offset, offset + limit - 1)
        items = _items_with_ids(redis, data_key, ids)
        return {"items": items, "count": len(items), "offset": offset, "limit": limit}

    # Filtered path: pull all ids newest-first (indexed range, not SCAN) and
    # their payloads in one HMGET, then filter in memory and slice the page.
    all_ids = redis.zrevrange(zset_key, 0, -1)
    matched = []
    for art in _items_with_ids(redis, data_key, all_ids):
        if source_filter and source_filter not in str(art.get("source", "")).lower():
            continue
        if query:
            hay = f"{art.get('title', '')} {art.get('summary', '')}".lower()
            if query not in hay:
                continue
        matched.append(art)

    page = matched[offset:offset + limit]
    return {"items": page, "count": len(page), "offset": offset, "limit": limit}