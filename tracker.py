import json, os, sys, time
from pathlib import Path
import requests

API = "https://data-api.polymarket.com/v2"
TOPIC = os.environ["NTFY_TOPIC"]
MIN_USD = float(os.environ.get("MIN_USD", "0"))            # ignore tiny trades
MIN_PRICE = float(os.environ.get("MIN_PRICE", "0.30"))     # copy only mid-odds entries...
MAX_PRICE = float(os.environ.get("MAX_PRICE", "0.70"))     # ...30c to 70c
MAX_SLIP = float(os.environ.get("MAX_SLIP", "0.03"))       # skip if live price is >3c above their entry
STATE = Path("seen.json")


def get_traders():
    manual = [w.strip().lower() for w in os.environ.get("WALLETS", "").split(",") if w.strip()]
    if manual:
        return {w: w[:8] for w in manual}
    wl = Path("watchlist.json")
    if not wl.exists():
        sys.exit("No watchlist yet - run the 'select' workflow first.")
    return {t["wallet"]: t["name"] for t in json.loads(wl.read_text())}


def live_price(token_id):
    try:
        r = requests.get(f"{API}/prices-history", params={
            "token_id": token_id, "as_of": int(time.time())}, timeout=20)
        r.raise_for_status()
        pts = r.json()["data"]
        return float(pts[-1]["price"]) if pts else None
    except Exception as e:
        print(f"live price failed: {e}", file=sys.stderr)
        return None


def push(title, msg, t, priority):
    requests.post("https://ntfy.sh", json={
        "topic": TOPIC, "title": title, "message": msg,
        "click": f"https://polymarket.com/event/{t.get('event_slug', '')}",
        "priority": priority}, timeout=20)


def notify(name, t):
    price = float(t.get("price") or 0)
    usd = float(t.get("usdc_size") or 0)
    base = f"{t.get('outcome', '?')} @ {price:.2f}  (${usd:,.0f})\n{t.get('title', '')}"
    if t["side"] == "SELL":
        # the trader is exiting or scaling out: consider closing yours too
        push(f"EXIT: {name} SOLD", f"SELL {base}", t, 5)
        return
    if not (MIN_PRICE <= price <= MAX_PRICE):
        print(f"skip {name}: entry {price:.2f} outside {MIN_PRICE}-{MAX_PRICE}")
        return
    live = live_price(t["token_id"])
    if live is None:
        push(f"{name} BUY (check live price)", f"BUY {base}\nLive price unavailable: compare before buying.", t, 4)
        return
    slip = live - price
    if slip > MAX_SLIP:
        push(f"SKIP {name}: price moved", f"BUY {base}\nLive {live:.2f} = +{slip*100:.0f}c vs their entry. Too late.", t, 2)
    else:
        push(f"COPY {name}", f"BUY {base}\nLive {live:.2f} ({slip*100:+.0f}c vs entry). Within limit.", t, 4)


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if isinstance(state, list):
        state = {"seen": state, "seeded": []}
    seen, seeded = set(state.get("seen", [])), set(state.get("seeded", []))
    for wallet, name in get_traders().items():
        try:
            r = requests.get(f"{API}/activity", params={
                "user": wallet, "type": "TRADE", "limit": 50, "sort_direction": "DESC"}, timeout=30)
            if r.status_code in (429, 503):
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            r.raise_for_status()
            rows = r.json()["data"]
        except Exception as e:
            print(f"skip {name}: {e}", file=sys.stderr)
            continue
        quiet = wallet not in seeded  # newly added trader: record history, don't alert
        for t in reversed(rows):
            key = f"{t['transaction_hash']}:{t['token_id']}:{t['size']}"
            if key in seen:
                continue
            seen.add(key)
            if not quiet and float(t.get("usdc_size") or 0) >= MIN_USD:
                notify(name, t)
        seeded.add(wallet)
    STATE.write_text(json.dumps({"seen": sorted(seen)[-5000:], "seeded": sorted(seeded)}))


if __name__ == "__main__":
    main()
