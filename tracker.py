import json, os, sys, time
from pathlib import Path
import requests

API = "https://data-api.polymarket.com/v2"
TOPIC = os.environ["NTFY_TOPIC"]
MIN_USD = float(os.environ.get("MIN_USD", "0"))
STATE = Path("seen.json")


def get_traders():
    manual = [w.strip().lower() for w in os.environ.get("WALLETS", "").split(",") if w.strip()]
    if manual:
        return {w: w[:8] for w in manual}
    wl = Path("watchlist.json")
    if not wl.exists():
        sys.exit("No watchlist yet - run the 'select' workflow first.")
    return {t["wallet"]: t["name"] for t in json.loads(wl.read_text())}


def notify(name, t):
    msg = (f"{t['side']} {t.get('outcome', '?')} @ {float(t.get('price') or 0):.2f}  "
           f"(${float(t.get('usdc_size') or 0):,.0f})\n{t.get('title', '')}")
    requests.post("https://ntfy.sh", json={
        "topic": TOPIC, "title": f"{name} placed a bet", "message": msg,
        "click": f"https://polymarket.com/event/{t.get('event_slug', '')}",
        "priority": 4}, timeout=20)


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
