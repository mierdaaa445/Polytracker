import json, os, sys
from pathlib import Path
import requests

API = "https://data-api.polymarket.com"
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
    usd = float(t.get("usdcSize") or 0)
    msg = (f"{t['side']} {t.get('outcome', '?')} @ {float(t.get('price') or 0):.2f}  (${usd:,.0f})\n"
           f"{t.get('title', '')}")
    requests.post("https://ntfy.sh", json={
        "topic": TOPIC, "title": f"{name} placed a bet", "message": msg,
        "click": f"https://polymarket.com/event/{t.get('eventSlug') or t.get('slug', '')}",
        "priority": 4}, timeout=20)


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if isinstance(state, list):  # old format
        state = {"seen": state, "seeded": []}
    seen, seeded = set(state.get("seen", [])), set(state.get("seeded", []))
    for wallet, name in get_traders().items():
        try:
            r = requests.get(f"{API}/activity", params={
                "user": wallet, "type": "TRADE", "limit": 50,
                "sortBy": "TIMESTAMP", "sortDirection": "DESC"}, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"skip {name}: {e}", file=sys.stderr)
            continue
        quiet = wallet not in seeded  # newly added trader: record history, don't alert
        for t in reversed(r.json()):
            key = t.get("transactionHash", "") + str(t.get("asset", "")) + str(t.get("timestamp", ""))
            if key in seen:
                continue
            seen.add(key)
            if not quiet and float(t.get("usdcSize") or 0) >= MIN_USD:
                notify(name, t)
        seeded.add(wallet)
    STATE.write_text(json.dumps({"seen": sorted(seen)[-5000:], "seeded": sorted(seeded)}))


if __name__ == "__main__":
    main()
