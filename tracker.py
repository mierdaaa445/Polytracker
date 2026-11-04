import json, os, sys, time
from collections import defaultdict
from pathlib import Path
import requests

API = "https://data-api.polymarket.com/v2"
TOPIC = os.environ["NTFY_TOPIC"]
MIN_USD = float(os.environ.get("MIN_USD", "0"))             # ignore tiny trades
# single-trader signals (strict)
MIN_PRICE = float(os.environ.get("MIN_PRICE", "0.20"))
MAX_PRICE = float(os.environ.get("MAX_PRICE", "0.80"))
MAX_SLIP = float(os.environ.get("MAX_SLIP", "0.03"))        # skip if live price > 3c above their entry
# consensus signals: 2+ watchlisted traders buy the same outcome within the window (looser)
MIN_TRADERS = int(os.environ.get("MIN_TRADERS", "2"))
WINDOW_HOURS = float(os.environ.get("WINDOW_HOURS", "6"))
CONS_MIN_PRICE = float(os.environ.get("CONS_MIN_PRICE", "0.20"))
CONS_MAX_PRICE = float(os.environ.get("CONS_MAX_PRICE", "0.80"))
CONS_SLIP = float(os.environ.get("CONS_SLIP", "0.06"))
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


def combine(fills):
    """Merge fills of the same outcome+side (one order is often split into many fills)."""
    groups = {}
    for t in fills:
        k = (t["token_id"], t["side"])
        size, usd = float(t.get("size") or 0), float(t.get("usdc_size") or 0)
        if k not in groups:
            groups[k] = dict(t, size=size, usdc_size=usd, _n=1)
        else:
            g = groups[k]
            g["size"] += size
            g["usdc_size"] += usd
            g["_n"] += 1
    for g in groups.values():
        if g["size"] > 0 and g["usdc_size"] > 0:
            g["price"] = g["usdc_size"] / g["size"]  # average price paid
    return list(groups.values())


def notify(name, t, group):
    """group = names of all watchlisted traders who bought this outcome inside the window."""
    price = float(t.get("price") or 0)
    usd = float(t.get("usdc_size") or 0)
    n = t.get("_n", 1)
    fills = f", {n} fills combined" if n > 1 else ""
    base = f"{t.get('outcome', '?')} @ {price:.2f}  (${usd:,.0f}{fills})\n{t.get('title', '')}"
    if t["side"] == "SELL":
        push(f"EXIT: {name} SOLD", f"SELL {base}", t, 5)
        return
    consensus = len(group) >= MIN_TRADERS
    lo, hi, slip_cap = (CONS_MIN_PRICE, CONS_MAX_PRICE, CONS_SLIP) if consensus else (MIN_PRICE, MAX_PRICE, MAX_SLIP)
    if not (lo <= price <= hi):
        print(f"skip {name}: entry {price:.2f} outside {lo}-{hi}")
        return
    tag = f"CONSENSUS x{len(group)}" if consensus else "COPY"
    who = f"\nAlso bought by: {', '.join(n for n in group if n != name)}" if consensus else ""
    live = live_price(t["token_id"])
    if live is None:
        push(f"{tag} {name} (check live price)", f"BUY {base}{who}\nLive price unavailable: compare before buying.", t, 4)
        return
    slip = live - price
    if slip > slip_cap:
        push(f"SKIP {name}: price moved", f"BUY {base}{who}\nLive {live:.2f} = +{slip*100:.0f}c vs their entry. Too late.", t, 2)
    else:
        push(f"{tag}: {name}", f"BUY {base}{who}\nLive {live:.2f} ({slip*100:+.0f}c vs entry). Within limit.", t, 5 if consensus else 4)


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if isinstance(state, list):
        state = {"seen": state, "seeded": []}
    seen, seeded = set(state.get("seen", [])), set(state.get("seeded", []))
    traders = get_traders()
    rows_by = {}
    for wallet, name in traders.items():
        try:
            r = requests.get(f"{API}/activity", params={
                "user": wallet, "type": "TRADE", "limit": 50, "sort_direction": "DESC"}, timeout=30)
            if r.status_code in (429, 503):
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            r.raise_for_status()
            rows_by[wallet] = r.json()["data"]
        except Exception as e:
            print(f"skip {name}: {e}", file=sys.stderr)
    # who bought what recently (stateless: derived from each trader's latest trades)
    cutoff = time.time() - WINDOW_HOURS * 3600
    buyers = defaultdict(set)
    for wallet, rows in rows_by.items():
        for t in rows:
            if t["side"] == "BUY" and t["timestamp"] >= cutoff:
                buyers[t["token_id"]].add(traders[wallet])
    for wallet, rows in rows_by.items():
        name = traders[wallet]
        quiet = wallet not in seeded  # newly added trader: record history, don't alert
        fresh = []
        for t in reversed(rows):
            key = f"{t['transaction_hash']}:{t['token_id']}:{t['size']}"
            if key in seen:
                continue
            seen.add(key)
            fresh.append(t)
        if not quiet:
            for t in combine(fresh):
                if float(t.get("usdc_size") or 0) >= MIN_USD:
                    notify(name, t, sorted(buyers.get(t["token_id"], {name})))
        seeded.add(wallet)
    STATE.write_text(json.dumps({"seen": sorted(seen)[-5000:], "seeded": sorted(seeded)}))


if __name__ == "__main__":
    main()
