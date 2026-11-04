"""Daily job: score leaderboard traders and keep only ones worth copying -> watchlist.json"""
import json, math, os, statistics, sys
from collections import defaultdict
from pathlib import Path
import requests

API = "https://data-api.polymarket.com"
PICK = int(os.environ.get("TOP_N", "10"))
MIN_ROI = float(os.environ.get("MIN_ROI", "0.05"))          # monthly pnl / volume
MIN_WIN = float(os.environ.get("MIN_WIN", "0.55"))          # win rate on closed positions
MIN_CLOSED = int(os.environ.get("MIN_CLOSED", "30"))        # sample size
MAX_PER_DAY = float(os.environ.get("MAX_TRADES_PER_DAY", "100"))  # bot / market maker filter
MAX_HEDGE = float(os.environ.get("MAX_HEDGE", "0.25"))      # share of markets bought on both sides
MIN_MEDIAN_USD = float(os.environ.get("MIN_MEDIAN_USD", "20"))


def board(period):
    out = {}
    for offset in (0, 50):
        r = requests.get(f"{API}/v1/leaderboard", params={
            "timePeriod": period, "orderBy": "PNL", "limit": 50, "offset": offset}, timeout=20)
        r.raise_for_status()
        for t in r.json():
            out[t["proxyWallet"].lower()] = t
    return out


def evaluate(wallet, month):
    pnl, vol = float(month.get("pnl") or 0), float(month.get("vol") or 0)
    roi = pnl / vol if vol else 0
    if roi < MIN_ROI:
        return None, f"roi {roi:.1%}"
    acts = requests.get(f"{API}/activity", params={
        "user": wallet, "type": "TRADE", "limit": 100,
        "sortBy": "TIMESTAMP", "sortDirection": "DESC"}, timeout=20).json()
    if len(acts) < 10:
        return None, "too few trades"
    span = max((acts[0]["timestamp"] - acts[-1]["timestamp"]) / 86400, 0.04)
    if len(acts) / span > MAX_PER_DAY:
        return None, "bot-like frequency"
    sides = defaultdict(set)
    for a in acts:
        sides[a["conditionId"]].add(a.get("outcomeIndex"))
    hedge = sum(len(s) > 1 for s in sides.values()) / len(sides)
    if hedge > MAX_HEDGE:
        return None, f"hedger/MM ({hedge:.0%})"
    med = statistics.median(float(a.get("usdcSize") or 0) for a in acts)
    if med < MIN_MEDIAN_USD:
        return None, "tiny trades"
    closed = requests.get(f"{API}/closed-positions", params={"user": wallet, "limit": 50}, timeout=20).json()
    if len(closed) < MIN_CLOSED:
        return None, "small sample"
    win = sum(float(p.get("realizedPnl") or 0) > 0 for p in closed) / len(closed)
    if win < MIN_WIN:
        return None, f"win rate {win:.0%}"
    score = roi * win * math.log10(max(pnl, 10))
    return {"wallet": wallet, "name": month.get("userName") or wallet[:8],
            "score": round(score, 4), "roi": round(roi, 3), "win": round(win, 3), "pnl": round(pnl)}, "ok"


def main():
    month, alltime = board("MONTH"), board("ALL")
    candidates = [w for w in month if w in alltime]  # must be profitable short AND long term
    print(f"{len(candidates)} candidates")
    good = []
    for w in candidates:
        try:
            res, why = evaluate(w, month[w])
        except Exception as e:
            print("error", w[:8], e, file=sys.stderr)
            continue
        print(w[:8], why)
        if res:
            good.append(res)
    good.sort(key=lambda x: -x["score"])
    picks = good[:PICK]
    if not picks:
        print("nothing qualified; keeping old watchlist")
        return
    path = Path("watchlist.json")
    old = {t["wallet"] for t in json.loads(path.read_text())} if path.exists() else set()
    path.write_text(json.dumps(picks, indent=1))
    added = [t for t in picks if t["wallet"] not in old]
    topic = os.environ.get("NTFY_TOPIC")
    if topic and added:
        msg = "\n".join(f"{t['name']}: ROI {t['roi']:.0%}, win {t['win']:.0%}" for t in added)
        requests.post("https://ntfy.sh", json={"topic": topic, "title": "New traders on your watchlist",
                                               "message": msg}, timeout=20)


if __name__ == "__main__":
    main()
