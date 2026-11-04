# Backtest: last 30 days, $100 per copied buy

Rules: their buy >= $50, entry 0.20-0.80, skip if your price is >3c above theirs. Positions held to resolution (sells ignored).

## You buy 5 min after them
- Copied buys: 346 (242 resolved, 104 still open)
- Resolved: 126 won / 116 lost (52% win rate)
- Resolved P&L: $1,330 on $24,200 staked (+5.5%)
- Open positions marked to market: $755

## You buy 20 min after them
- Copied buys: 325 (222 resolved, 103 still open)
- Resolved: 108 won / 114 lost (49% win rate)
- Resolved P&L: $350 on $22,200 staked (+1.6%)
- Open positions marked to market: $358

## Skipped
- no price data (20m): 1
- outside 0.20-0.80: 881
- price moved >3c (20m): 35
- price moved >3c (5m): 15

## Per-trader qualifying buys (0.20-0.80 range)
- TheReturnOfDarthMaul: 382
- flawfence: 743
- ArielFilipino: 421
- rdba: 1
- Elaran1993: 219
- chongchong37: 1390
- 0xb4F978BE63cDF75554b0B46a4262a6dB597cc9A7-1779258330186: 1084
- fantasy7788: 204
- juice-fruit: 544
- dromedaryy: 578

## Consensus signals (2+ watchlist traders, same outcome, within 6h)
Signals found: 48. Entry = price 20 min after the 2nd trader. No price cap applied, grouped by entry price:

- Entry under 50c: 20 resolved, 13 won / 7 lost, P&L $1,312 (+65.6%)
- Entry 50-70c: 19 resolved, 13 won / 6 lost, P&L $416 (+21.9%)
- Entry 70-85c: 4 resolved, 3 won / 1 lost, P&L $6 (+1.5%)
- Entry over 85c: 2 resolved, 2 won / 0 lost, P&L $3 (+1.3%)

Caveats: resolved trades are biased toward short-dated markets; open trades are not final; sample is small; past results do not predict future results.