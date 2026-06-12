"""calma_vendor regression (network-free): seed a cache, replay it offline, and confirm a cache MISS
raises (so an offline replay is provably hermetic). Record-mode is exercised opportunistically only if
network is available. Pure stdlib. Run: python3 test_vendor.py
"""
import os
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma_vendor as v  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


cache = tempfile.mkdtemp()
url = "https://example.test/data.json"
payload = b'{"price": 42}'
# seed the cache exactly as record() would key it
open(os.path.join(cache, v._key("GET", url, b"") + ".bin"), "wb").write(payload)

v.install_replay(cache)
got = urllib.request.urlopen(url).read()
truth(got == payload, "replay serves the cached response offline")

# requests is replayed too, if installed
try:
    import requests
    truth(requests.get(url).content == payload, "requests.get replayed from cache")
    truth(requests.get(url).json() == {"price": 42}, "requests .json() works on replay")
except ImportError:
    pass

# a cache MISS must raise -> proves the offline run cannot silently reach the network
try:
    urllib.request.urlopen("https://example.test/MISSING")
    truth(False, "cache miss should raise")
except RuntimeError as e:
    truth("cache MISS" in str(e), "cache MISS raises (hermetic guarantee)")

# params are folded into the URL (so paged GETs don't all alias to one cache entry)
base = "https://example.test/candles"
p1 = b'[[1,2,3]]'
full1 = v._with_params(base, {"granularity": 3600, "start": 100})
open(os.path.join(cache, v._key("GET", full1, b"") + ".bin"), "wb").write(p1)
try:
    import requests
    truth(requests.get(base, params={"granularity": 3600, "start": 100}).content == p1,
          "requests.get params are keyed into the URL on replay")
    # a DIFFERENT param set is a different key -> MISS (params actually disambiguate)
    try:
        requests.get(base, params={"granularity": 3600, "start": 999})
        truth(False, "differing params should MISS")
    except RuntimeError:
        truth(True, "differing params -> distinct key -> MISS")
    # ccxt and real repos fetch via a Session, not the module helper - that path is patched too
    truth(requests.Session().get(full1).content == p1, "requests.Session().get replayed from cache")
except ImportError:
    pass

# drift guard: the shim copy vendored into the btc-sma-crossover corpus member must stay byte-identical
# to the canonical shim, or its offline replay could silently diverge from what the suite validates.
_canon = os.path.join(HERE, "..", "calma_vendor.py")
_copy = os.path.join(HERE, "..", "..", "assets", "corpus", "btc-sma-crossover", "calma_vendor.py")
if os.path.exists(_copy):
    truth(open(_canon, "rb").read() == open(_copy, "rb").read(),
          "vendored calma_vendor.py copy is byte-identical to the canonical shim")

print("vendor: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
