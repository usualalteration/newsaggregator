"""Minimal Redis client (RESP2 over a TCP socket), standard library only.

This is a tiny, single-file replacement for the ``redis`` PyPI package used by
the generated action wrapper (``import redis``; ``redis.from_url(...)``). It
implements only the sync commands the news actions need:

  from_url(url, decode_responses=...) -> Redis
  Redis: pipeline(), hgetall(), hmget(), zcard(), zrange(), zrevrange()
  Pipeline: zadd(mapping, nx=...), hset(), hdel(), zremrangebyrank(), execute()

It is intentionally small and understandable; it is NOT a full Redis client.
"""

import socket
from urllib.parse import urlparse


class RedisError(Exception):
    pass


class ConnectionError(RedisError):
    pass


def from_url(url, decode_responses=False, **_):
    """Parse ``redis://[user[:pass]@]host:port[/db]`` and return a Redis."""
    u = urlparse(url)
    try:
        db = int(u.path.lstrip("/") or "0")
    except ValueError:
        db = 0
    return Redis(
        host=u.hostname or "localhost",
        port=u.port or 6379,
        username=u.username or "",
        password=u.password or "",
        db=db,
        decode_responses=decode_responses,
    )


def _to_bytes(arg):
    if isinstance(arg, bytes):
        return arg
    if isinstance(arg, bool):
        return b"1" if arg else b"0"
    return str(arg).encode("utf-8")


class Redis:
    def __init__(self, host="localhost", port=6379, username="",
                 password="", db=0, decode_responses=False, socket_timeout=10):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.db = db
        self.decode = decode_responses
        self.timeout = socket_timeout
        self._sock = None
        self._fp = None

    # -- connection ---------------------------------------------------------
    def _connect(self):
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as e:
            raise ConnectionError(str(e))
        sock.settimeout(self.timeout)
        self._sock = sock
        self._fp = sock.makefile("rb")
        if self.password:
            if self.username and self.username != "default":
                self._cmd_raw("AUTH", self.username, self.password)
            else:
                self._cmd_raw("AUTH", self.password)
        if self.db:
            self._cmd_raw("SELECT", str(self.db))

    def close(self):
        if self._fp is not None:
            try:
                self._fp.close()
            except Exception:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = self._fp = None

    # -- protocol -----------------------------------------------------------
    def _send(self, *args):
        self._connect()
        chunks = [b"*" + str(len(args)).encode() + b"\r\n"]
        for a in args:
            b = _to_bytes(a)
            chunks.append(b"$" + str(len(b)).encode() + b"\r\n")
            chunks.append(b + b"\r\n")
        self._sock.sendall(b"".join(chunks))

    def _read_line(self):
        line = self._fp.readline()
        if not line:
            raise ConnectionError("connection closed by server")
        return line[:-2] if line.endswith(b"\r\n") else line.rstrip(b"\r\n")

    def _read_reply(self):
        line = self._read_line()
        p = line[:1]
        if p == b"+":
            return self._maybe_decode(line[1:])
        if p == b"-":
            raise RedisError(self._maybe_decode(line[1:]))
        if p == b":":
            return int(line[1:])
        if p == b"$":
            n = int(line[1:])
            if n == -1:
                return None
            data = self._fp.read(n)
            self._fp.read(2)  # trailing \r\n
            return self._maybe_decode(data)
        if p == b"*":
            n = int(line[1:])
            if n == -1:
                return None
            return [self._read_reply() for _ in range(n)]
        raise RedisError("unexpected reply: " + repr(line))

    def _maybe_decode(self, data):
        if data is None:
            return None
        if self.decode and isinstance(data, bytes):
            return data.decode("utf-8", "replace")
        return data

    def _cmd_raw(self, *args):
        self._send(*args)
        return self._read_reply()

    def execute_command(self, *args):
        return self._cmd_raw(*args)

    # -- commands used by the app ------------------------------------------
    def hgetall(self, key):
        r = self._cmd_raw("HGETALL", key)
        if not r:
            return {}
        return {r[i]: r[i + 1] for i in range(0, len(r), 2)}

    def hmget(self, key, *fields):
        return self._cmd_raw("HMGET", key, *fields)

    def zcard(self, key):
        return self._cmd_raw("ZCARD", key)

    def zrange(self, key, start, end):
        return self._cmd_raw("ZRANGE", key, start, end)

    def zrevrange(self, key, start, end):
        return self._cmd_raw("ZREVRANGE", key, start, end)

    def pipeline(self):
        return Pipeline(self)


def _zadd_args(key, mapping, nx=False, xx=False, ch=False, incr=False):
    args = ["ZADD", key]
    if nx:
        args.append("NX")
    if xx:
        args.append("XX")
    if ch:
        args.append("CH")
    if incr:
        args.append("INCR")
    for member, score in mapping.items():
        args.append(score)
        args.append(member)
    return args


class Pipeline:
    """Queues commands and sends them in one batch on execute()."""

    def __init__(self, redis):
        self.redis = redis
        self._queue = []

    def _add(self, *args):
        self._queue.append(args)

    def zadd(self, key, mapping, nx=False, xx=False, ch=False, incr=False):
        self._add(*_zadd_args(key, mapping, nx=nx, xx=xx, ch=ch, incr=incr))

    def hset(self, key, field=None, value=None, mapping=None):
        if mapping:
            args = [key]
            for f, v in mapping.items():
                args.append(f)
                args.append(v)
            self._add("HSET", *args)
        else:
            self._add("HSET", key, field, value)

    def hdel(self, key, *fields):
        self._add("HDEL", key, *fields)

    def zremrangebyrank(self, key, start, end):
        self._add("ZREMRANGEBYRANK", key, start, end)

    def execute(self):
        if not self._queue:
            return []
        self.redis._connect()
        for args in self._queue:
            self.redis._send(*args)
        results = [self.redis._read_reply() for _ in self._queue]
        self._queue = []
        return results