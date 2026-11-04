"""Backtest: if you had copied the watchlist traders' recent buys under the tracker's rules
(30-70c entry, skip if live price >3c above their entry), would you have made or lost money?
Result is written to backtest.md. Run via the 'backtest' workflow."""
import json, os, sys, time
from collections import defaultdict
from pathlib import Path
import requests

API = "https://data-api.polymarket.com/v2"
DAYS = int(os.environ.get("DAYS", "30"))
MIN_USD = float(os.environ.get("MIN_USD", "50"))
MIN_PRICE = float(os.environ.get("MIN_PRICE", "0.30"))
MAX_PRICE = float(os.environ.get("MAX_PRICE", "0.70"))
MAX_SLIP = float(os.environ.get("MAX_SLIP", "0.03"))
DELAYS = [int(x) for x in os.environ.get("DELAYS", "5,20").split(",")]  # minutes between their buy and yours
MAX_TRADES_PER_TRADER = int(os.environ.get("MAX_TRADES", "40"))
STAKE = 100.0  # hypothetical dollars per copied trade


def get(path, **params):
    for attempt in range(4):
        r = requests.get(f"{API}{path}", params=params, timeout=30)
        if r.status_code in (429, 503):
            time.sleep(float(r.headers.get("Retry-After", 2 * (attempt + 1))))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def price_at(token, ts):
    try:
        pts = get("/prices-history", token_id=token, as_of=int(ts))["data"]
        return float(pts[-1]["price"]) if pts else None
    except Exception:
        return None


def recent_buys(wallet):
    start = int(time.time()) - DAYS * 86400
    out, cursor = [], None
    for _ in range(4):
        p = {"user": wallet, "type": "TRADE", "side": "BUY", "start": start, "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        d = get("/activity", **p)
        out += d["data"]
        cursor = d["pagination"].get("next_cursor")
        if not cursor:
            break
    return out


def resolutions(tokens):
    res = {}
    tokens = list(tokens)
    for i in range(0, len(tokens), 50):
        for row in get("/tokens", token_id=",".join(tokens[i:i + 50]))["data"]:
            res[row["token_id"]] = row
    return res


def main():
    wl = json.loads(Path("watchlist.json").read_text())
    now = time.time()
    trades = []  # (trader, delay, entry_price, token, ts, stake_pnl placeholder)
    skipped = defaultdict(int)
    per_trader_buys = {}
    for t in wl:
        try:
            buys = recent_buys(t["wallet"])
        except Exception as e:
            print("fail", t["name"], e, file=sys.stderr)
            continue
        buys = [b for b in buys if b["usdc_size"] >= MIN_USD]
        in_range = [b for b in buys if MIN_PRICE <= b["price"] <= MAX_PRICE]
        skipped["outside 30-70c"] += len(buys) - len(in_range)
        in_range.sort(key=lambda b: b["timestamp"], reverse=True)
        per_trader_buys[t["name"]] = len(in_range)
        for b in in_range[:MAX_TRADES_PER_TRADER]:
            for d in DELAYS:
                ts = b["timestamp"] + d * 60
                if ts > now - 300:
                    skipped[f"too recent ({d}m)"] += 1
                    continue
                entry = price_at(b["token_id"], ts)
                time.sleep(0.1)
                if entry is None or entry <= 0.01:
                    skipped[f"no price data ({d}m)"] += 1
                    continue
                if entry - b["price"] > MAX_SLIP:
                    skipped[f"price moved >{MAX_SLIP*100:.0f}c ({d}m)"] += 1
                    continue
                trades.append({"trader": t["name"], "delay": d, "their": b["price"], "entry": entry,
                               "token": b["token_id"], "title": b.get("title", "")})
    res = resolutions({x["token"] for x in trades}) if trades else {}
    lines = [f"# Backtest: last {DAYS} days, ${STAKE:.0f} per copied buy", "",
             f"Rules: their buy >= ${MIN_USD:.0f}, entry {MIN_PRICE:.2f}-{MAX_PRICE:.2f}, "
             f"skip if your price is >{MAX_SLIP*100:.0f}c above theirs. Positions held to resolution (sells ignored).", ""]
    summary = []
    for d in DELAYS:
        rs = [x for x in trades if x["delay"] == d]
        won = lost = 0
        pnl = 0.0
        open_pnl = 0.0
        open_n = 0
        for x in rs:
            r = res.get(x["token"])
            if r and r.get("resolved") and r.get("final_price") is not None:
                gain = STAKE * (float(r["final_price"]) / x["entry"] - 1)
                pnl += gain
                won += gain > 0
                lost += gain <= 0
            else:
                cur = price_at(x["token"], now)
                if cur is not None:
                    open_pnl += STAKE * (cur / x["entry"] - 1)
                    open_n += 1
        n = won + lost
        roi = pnl / (STAKE * n) if n else 0
        lines += [f"## You buy {d} min after them", f"- Copied buys: {len(rs)} ({n} resolved, {open_n} still open)",
                  f"- Resolved: {won} won / {lost} lost" + (f" ({won/n:.0%} win rate)" if n else ""),
                  f"- Resolved P&L: ${pnl:,.0f} on ${STAKE*n:,.0f} staked ({roi:+.1%})",
                  f"- Open positions marked to market: ${open_pnl:,.0f}", ""]
        summary.append(f"{d}min: {n} resolved, P&L ${pnl:,.0f} ({roi:+.1%}), open ${open_pnl:,.0f}")
    lines += ["## Skipped"] + [f"- {k}: {v}" for k, v in sorted(skipped.items())]
    lines += ["", "## Per-trader qualifying buys (in 30-70c range)"] + [f"- {k}: {v}" for k, v in per_trader_buys.items()]
    lines += ["", "Caveats: resolved trades are biased toward short-dated markets; open trades are not final; "
              "sample is small; past results do not predict future results."]
    Path("backtest.md").write_text("\n".join(lines))
    print("\n".join(lines))
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        requests.post("https://ntfy.sh", json={"topic": topic, "title": "Backtest done",
                      "message": "\n".join(summary) or "no trades qualified"}, timeout=20)


if __name__ == "__main__":
    main()
