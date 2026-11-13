"""Shared helpers: percentiles and client-side new-connection counting."""
import json

def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)

CONN = {"n": 0}

def install_connection_counters():
    """Count new TCP connections opened by httpx (httpcore), openai-python (httpcore2) and aiohttp."""
    def wrap(cls, name):
        orig = cls.__dict__[name]
        async def counted(self, *args, **kwargs):
            CONN["n"] += 1
            return await orig(self, *args, **kwargs)
        setattr(cls, name, counted)
    import httpcore
    wrap(httpcore._async.connection.AsyncHTTPConnection, "_connect")
    try:
        import httpcore2
        wrap(httpcore2._async.connection.AsyncHTTPConnection, "_connect")
    except ImportError:
        pass
    try:
        import aiohttp
        wrap(aiohttp.TCPConnector, "_create_connection")
    except ImportError:
        pass

def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)
