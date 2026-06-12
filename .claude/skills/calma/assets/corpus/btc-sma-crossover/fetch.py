"""Fetch BTC-USD hourly OHLC from Coinbase. Used by BOTH the one-time recorder and the offline
replay - identical URLs, so record (network) and replay (cache) hit the same keys. The window is
anchored to a FIXED end epoch (not "now") so the recorded cache is reproducible forever.
"""
import json
import urllib.request

PRODUCT = "BTC-USD"
GRAN = 3600                       # 1-hour candles (the upstream strategy is H1)
ANCHOR_END = 1735603200          # 2024-12-31T00:00:00Z, fixed
SPAN = 300 * GRAN                # Coinbase returns <=300 candles/request
PAGES = 15                       # ~187 days of hourly bars (enough for 50/100 SMA + trades)


def _url(start, end):
    return ("https://api.exchange.coinbase.com/products/%s/candles?granularity=%d&start=%d&end=%d"
            % (PRODUCT, GRAN, start, end))


def fetch_ohlc():
    """Return {'close':[...], 'high':[...], 'low':[...]} oldest->newest, de-duped by timestamp."""
    rows = {}
    for p in range(PAGES):
        end = ANCHOR_END - p * SPAN
        start = end - SPAN
        req = urllib.request.Request(_url(start, end), headers={"User-Agent": "calma-vendor/1"})
        for c in json.loads(urllib.request.urlopen(req, timeout=30).read()):
            rows[int(c[0])] = c          # [time, low, high, open, close, volume]
    ordered = [rows[t] for t in sorted(rows)]
    return {"close": [float(c[4]) for c in ordered],
            "high": [float(c[2]) for c in ordered],
            "low": [float(c[1]) for c in ordered]}
