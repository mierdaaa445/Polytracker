"""Daily job: score leaderboard traders, keep only ones worth copying -> watchlist.json
Uses Polymarket Data API v2 (v1 routes return 410 Gone)."""
import json, math, os, statistics, sys, time
from collections import defaultdict
from pathlib import Path
import requests

API = "https://data-api.polymarket.com/v2"
PICK = int(os.environ.get("TOP_N", "10"))
CANDIDATES = int(os.environ.get("CANDIDATES", "80"))          # top monthly PnL traders to examine
MIN_ROI = float(os.environ.get("MIN_ROI", "0.03"))            # 30d PnL / 30d USDC volume
MIN_WIN = float(os.environ.get("MIN_WIN", "0.55"))            # win rate on recent closed positions
MIN_CLOSED = int(os.environ.get("MIN_CLOSED", "30"))          # sample size
MAX_PER_DAY = float(os.environ.get("MAX_TRADES_PER_DAY", "100"))  # bot / market-maker filter
MAX_HEDGE = float(os.environ.get("MAX_HEDGE", "0.25"))        # share of markets bought on both sides
MIN_MEDIAN_USD = float(os.environ.get("MIN_MEDIAN_USD", "20"))


def get(path, **params):
    for attempt in range(4):
        r = requests.get(f"{API}{path}", params=params, timeout=30)
        if r.status_code in (429, 503):
            time.sleep(float(r.headers.get("Retry-After", 2 * (attempt + 1))))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def board(period, limit):
    return get("/leaderboard", time_period=period, sort_by="PNL", limit=limit)["data"]


def evaluate(row):
    wallet = row["user_id"].lower()
    # 30-day ROI: pnl over the window vs USDC actually traded in it
    vol = get("/user-volume", user=wallet, start=int(time.time()) - 30 * 86400)["data"]["volume_usdc"]
    roi = row["pnl"] / vol if vol else 0
    if roi < MIN_ROI:
        return None, f"roi {roi:.1%}"
    acts = get("/activity", user=wallet, type="TRADE", limit=100, sort_direction="DESC")["data"]
    if len(acts) < 10:
        return None, "too few trades"
    span = max((acts[0]["timestamp"] - acts[-1]["timestamp"]) / 86400, 0.04)
    if len(acts) / span > MAX_PER_DAY:
        return None, "bot-like frequency"
    sides = defaultdict(set)
    for a in acts:
        if a["side"] == "BUY":
            sides[a["condition_id"]].add(a["outcome_index"])
    hedge = sum(len(s) > 1 for s in sides.values()) / max(len(sides), 1)
    if hedge > MAX_HEDGE:
        return None, f"hedger/MM ({hedge:.0%})"
    med = statistics.median(a["usdc_size"] for a in acts)
    if med < MIN_MEDIAN_USD:
        return None, "tiny trades"
    closed = get("/positions", user=wallet, status="CLOSED", sort_by="TIMESTAMP",
                 sort_direction="DESC", limit=200)["data"]
    if len(closed) < MIN_CLOSED:
        return None, "small sample"
    win = sum(p["realized_pnl"] > 0 for p in closed) / len(closed)
    if win < MIN_WIN:
        return None, f"win rate {win:.0%}"
    score = roi * win * math.log10(max(row["pnl"], 10))
    return {"wallet": wallet, "name": row.get("user_name") or wallet[:8],
            "score": round(score, 4), "roi": round(roi, 3), "win": round(win, 3),
            "pnl": round(row["pnl"])}, "ok"


def main():
    month = board("month", CANDIDATES)
    alltime = {r["user_id"].lower(): r["pnl"] for r in board("all", 1000)}
    print(f"{len(month)} monthly candidates")
    good = []
    for row in month:
        w = row["user_id"].lower()
        if alltime.get(w, 0) <= 0:  # must also be profitable long-term
            print(w[:8], "not profitable all-time")
            continue
        try:
            res, why = evaluate(row)
        except Exception as e:
            print("error", w[:8], e, file=sys.stderr)
            continue
        print(w[:8], why)
        if res:
            good.append(res)
        time.sleep(0.2)
    good.sort(key=lambda x: -x["score"])
    picks = good[:PICK]
    if not picks:
        print("nothing qualified; keeping old watchlist")
        return
    path = Path("watchlist.json")
    old = {t["wallet"] for t in json.loads(path.read_text())} if path.exists() else set()
    path.write_text(json.dumps(picks, indent=1))
    print(f"watchlist: {len(picks)} traders")
    added = [t for t in picks if t["wallet"] not in old]
    topic = os.environ.get("NTFY_TOPIC")
    if topic and added:
        msg = "\n".join(f"{t['name']}: ROI {t['roi']:.0%}, win {t['win']:.0%}" for t in added)
        requests.post("https://ntfy.sh", json={"topic": topic, "title": "New traders on your watchlist",
                                               "message": msg}, timeout=20)


if __name__ == "__main__":
    main()
