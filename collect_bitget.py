"""Collect PUBLIC Bitget observations. This does not produce trading logs."""
import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(path, **parameters):
    url = "https://api.bitget.com" + path
    if parameters:
        url += "?" + urllib.parse.urlencode(parameters)
    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.load(response)
    if data.get("code") != "00000":
        raise RuntimeError("Bitget API rejected request: " + str(data.get("code")))
    return {"url": url, "observed_at": time.time(), "response": data}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", nargs="+", default=["RAAPLUSDT", "RNVDAUSDT", "RMSFTUSDT"])
    p.add_argument("--output", default="evidence/bitget-observations.json")
    args = p.parse_args()
    rows = []
    for symbol in args.symbols:
        for endpoint in ("instruments", "tickers"):
            try:
                rows.append(fetch("/api/v3/market/" + endpoint, category="SPOT", symbol=symbol))
            except Exception as exc:
                rows.append({"symbol": symbol, "endpoint": endpoint, "error": type(exc).__name__})
    output = {"notice": "READ-ONLY MARKET OBSERVATIONS; NOT PAPER TRADING OR PERFORMANCE EVIDENCE", "rows": rows}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2))
    print(json.dumps({"output": str(target), "successful_requests": sum("response" in r for r in rows), "total_requests": len(rows)}))


if __name__ == "__main__":
    main()
