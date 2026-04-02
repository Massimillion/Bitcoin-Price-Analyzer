#!/usr/bin/env python3
"""BitEdge API proxy — fetches crypto data server-side to avoid CORS/ad-blocker issues."""
import json
import time
import urllib.request
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Simple in-memory cache to avoid hammering upstream APIs
_cache = {}
CACHE_TTL = 12  # seconds


def cached_fetch(url, ttl=CACHE_TTL):
    now = time.time()
    if url in _cache and now - _cache[url]["t"] < ttl:
        return _cache[url]["data"]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BitEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            _cache[url] = {"data": data, "t": now}
            return data
    except Exception as e:
        print(f"Fetch error for {url}: {e}")
        # Return stale cache if available
        if url in _cache:
            return _cache[url]["data"]
        return None


@app.get("/api/candles")
def get_candles(limit: int = 60):
    """Fetch 1-minute BTC candles from CryptoCompare."""
    url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym=BTC&tsym=USD&limit={limit}"
    data = cached_fetch(url)
    if data and data.get("Data") and data["Data"].get("Data"):
        return {"candles": data["Data"]["Data"], "source": "CryptoCompare"}
    # Fallback: CoinGecko OHLC
    url2 = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days=1"
    data2 = cached_fetch(url2, ttl=30)
    if data2 and isinstance(data2, list) and len(data2) > 0:
        candles = [
            {"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volumefrom": 1}
            for c in data2
        ]
        return {"candles": candles, "source": "CoinGecko"}
    return {"candles": [], "source": "none", "error": "All upstream sources failed"}


@app.get("/api/signals")
def get_signals():
    """Fetch Fear & Greed + Funding Rate."""
    result = {}
    # Fear & Greed
    fng = cached_fetch("https://api.alternative.me/fng/?limit=1", ttl=60)
    if fng and fng.get("data") and fng["data"][0]:
        result["fearGreed"] = int(fng["data"][0]["value"])
        result["fearGreedLabel"] = fng["data"][0]["value_classification"]
    # Funding Rate from CoinGecko derivatives
    deriv = cached_fetch("https://api.coingecko.com/api/v3/derivatives?per_page=10", ttl=60)
    if deriv and isinstance(deriv, list):
        btc = next((d for d in deriv if d.get("symbol", "").upper().find("BTCUSDT") >= 0 and d.get("market") == "Binance (Futures)"), None)
        if btc:
            result["fundingRate"] = float(btc.get("funding_rate", 0))
            result["openInterest"] = float(btc.get("open_interest", 0))
            result["spread"] = float(btc.get("spread", 0))
    return result


@app.get("/api/health")
def health():
    return {"status": "ok", "time": int(time.time())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
