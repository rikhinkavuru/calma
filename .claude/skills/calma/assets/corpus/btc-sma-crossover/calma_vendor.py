"""calma.vendor - turn a live-data repo into a hermetically-verifiable one by RECORDING its HTTP
fetches once (with network) and REPLAYING them offline (network-off, under isolation). This is the
generic form of what was done by hand for the BTC fixture: vendor the data to a snapshot so the
recompute runs with no network. Patches both urllib and requests, keyed by URL.

Recipe:
  1. RECORD (once, with network):  python3 -c "import calma_vendor as v; v.install_record('<cache>')" + run the repo
     - or use the in-process API: install_record(cache_dir) then run the fetch.
  2. REPLAY (offline, under Calma isolation): install_replay(cache_dir); a cache MISS raises (proving no
     network reliance) so the run is provably hermetic.
"""
import hashlib
import json
import os
import urllib.request

_CACHE = None
_MODE = None  # 'record' | 'replay'
_ORIG_URLOPEN = urllib.request.urlopen  # captured before any patch (avoids recursion in record)


def _key(method, url, body=b""):
    h = hashlib.sha256()
    h.update((method + " " + url).encode())
    if body:
        h.update(b"\x00")
        h.update(body if isinstance(body, bytes) else str(body).encode())
    return h.getvalue().hex()[:32] if hasattr(h, "getvalue") else h.hexdigest()[:32]


def _path(method, url, body=b""):
    return os.path.join(_CACHE, _key(method, url, body) + ".bin")


def _index_add(method, url):
    idx = os.path.join(_CACHE, "index.json")
    cur = json.load(open(idx)) if os.path.exists(idx) else {}
    cur[_key(method, url)] = {"method": method, "url": url}
    json.dump(cur, open(idx, "w"), indent=2)


# ---- a minimal requests.Response stand-in ----
class _Resp:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if not (200 <= self.status_code < 400):
            raise RuntimeError("HTTP %d" % self.status_code)


def _with_params(url, params):
    """Fold a requests-style params dict into the URL so the querystring is part of the cache key AND
    the recorded fetch (otherwise GET .../candles?...  collapses to .../candles and every page aliases
    to one cache entry). No-op when params is falsy."""
    if not params:
        return url
    import urllib.parse
    qs = urllib.parse.urlencode(params, doseq=True)
    sep = "&" if ("?" in url) else "?"
    return url + sep + qs


def _fetch(method, url, body=b"", headers=None, timeout=30):
    # headers ARE forwarded on record: many public APIs (Coinbase, etc.) 403 without a User-Agent.
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers or {})
    return _ORIG_URLOPEN(req, timeout=timeout).read()


def _serve(method, url, body=b"", headers=None):
    p = _path(method, url, body)
    if _MODE == "replay":
        if not os.path.exists(p):
            raise RuntimeError("calma_vendor: cache MISS for %s %s (offline replay; no network)" % (method, url))
        return open(p, "rb").read()
    # record (headers used only to fetch; the key stays method+url+body so replay needs no headers)
    data = _fetch(method, url, body, headers)
    open(p, "wb").write(data)
    _index_add(method, url)
    return data


def _patch():
    # urllib
    def urlopen(req, *a, **k):
        if isinstance(req, str):
            method, url, body, headers = "GET", req, b"", None
        else:
            method, url, body, headers = (req.get_method(), req.full_url, req.data or b"", dict(req.header_items()))
        data = _serve(method, url, body, headers)
        import io
        r = io.BytesIO(data)
        r.read  # file-like
        r.status = 200
        return r
    urllib.request.urlopen = urlopen

    # requests + ccxt (if installed). Real repos fetch via requests.Session (ccxt wraps one), not just
    # the module-level helpers, so BOTH are patched; params/headers are honored.
    try:
        import json as json_lib
        import requests

        def _body(data, json):
            if data is not None:
                return data if isinstance(data, (bytes, str)) else json_lib.dumps(data)
            return json_lib.dumps(json) if json is not None else b""

        def _get(url, params=None, headers=None, **k):
            return _Resp(_serve("GET", _with_params(url, params), b"", headers))

        def _post(url, data=None, json=None, params=None, headers=None, **k):
            return _Resp(_serve("POST", _with_params(url, params), _body(data, json), headers))

        def _request(self, method, url, params=None, data=None, json=None, headers=None, **k):
            m = str(method).upper()
            body = _body(data, json) if m != "GET" else b""
            return _Resp(_serve(m, _with_params(url, params), body, headers))

        requests.get = _get
        requests.post = _post
        requests.sessions.Session.request = _request   # covers requests.Session() and ccxt
    except ImportError:
        pass


def install_record(cache_dir):
    global _CACHE, _MODE
    _CACHE = os.path.realpath(cache_dir)
    os.makedirs(_CACHE, exist_ok=True)
    _MODE = "record"
    _patch()


def install_replay(cache_dir):
    global _CACHE, _MODE
    _CACHE = os.path.realpath(cache_dir)
    _MODE = "replay"
    _patch()
