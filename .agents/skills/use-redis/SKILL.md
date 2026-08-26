---
name: use-redis
description: how to use Redis for caching and key-value storage
license: Apache 2.0
---

To use Redis in an endpoint, first use the tool `add-redis` to add the connection to your endpoint. This makes available:
- `ctx.REDIS` — the Redis client
- `ctx.REDIS_PREFIX` — the key prefix for namespacing keys

## Basic key-value operations

Use `ctx.REDIS` to get and set values. Prefix keys with `ctx.REDIS_PREFIX` to avoid collisions:

```python
def get_set_value(args, ctx=None):
    rd = ctx.REDIS
    prefix = ctx.REDIS_PREFIX

    key = f"{prefix}:mykey"
    rd.set(key, "hello")
    value = rd.get(key)
    return value.decode() if isinstance(value, bytes) else str(value)
```

## Executing any Redis command

Use `execute_command` to run arbitrary Redis commands:

```python
def ping_redis(args, ctx=None):
    rd = ctx.REDIS
    result = rd.execute_command("PING")
    return to_string(result)
```

## Handling Redis response types

Redis returns bytes, lists, or other types. Use a helper to convert them to strings:

```python
def to_string(response):
    if response is None:
        return "None"
    elif isinstance(response, bytes):
        return response.decode()
    elif isinstance(response, (list, tuple)):
        return "[" + ", ".join(to_string(item) for item in response) + "]"
    else:
        return str(response)
```

## Common operations

```python
rd = ctx.REDIS
prefix = ctx.REDIS_PREFIX

# set with expiration (seconds)
rd.setex(f"{prefix}:session", 3600, "data")

# increment a counter
rd.incr(f"{prefix}:visits")

# hash operations
rd.hset(f"{prefix}:user:1", mapping={"name": "Alice", "email": "alice@example.com"})
rd.hgetall(f"{prefix}:user:1")

# list operations
rd.lpush(f"{prefix}:queue", "task1")
rd.rpop(f"{prefix}:queue")

# check if key exists
rd.exists(f"{prefix}:mykey")

# delete a key
rd.delete(f"{prefix}:mykey")

# list all keys with prefix
rd.keys(f"{prefix}:*")
```
