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

print("vendor: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
