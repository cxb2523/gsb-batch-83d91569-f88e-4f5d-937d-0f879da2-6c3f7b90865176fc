---
title: Get Live PSX Trading Board Snapshots with Python
description: Fetch point-in-time live trading board data from PSX using psxdata -- no browser required.
---

# Get Live PSX Trading Board Snapshots with Python

`psxdata.quote()` returns a live screener snapshot for any PSX-listed stock — current price, sector, market cap, and more. This data is fetched in real time from PSX during market hours.

!!! note
    PSX does not expose tick-by-tick or minute-bar data via its public website.
    `quote()` gives you a point-in-time snapshot — suitable for dashboards and
    portfolio monitors that refresh every few minutes.

## Single stock snapshot

```python
import psxdata

q = psxdata.quote("ENGRO")
print(q.T)   # transpose so columns become rows for easier reading
```

## Build a portfolio monitor

```python
import psxdata
import time
from datetime import datetime

portfolio = ["ENGRO", "LUCK", "HBL", "OGDC"]

while True:
    print(f"\n--- Snapshot at {datetime.now().strftime('%H:%M:%S')} ---")
    for ticker in portfolio:
        q = psxdata.quote(ticker, cache=False)   # cache=False forces a fresh fetch
        if not q.empty:
            row = q.iloc[0]
            print(f"{ticker:8s}  {row['ldcp']}")
    time.sleep(300)   # wait 5 minutes between polls
```

!!! warning
    The PSX screener is a heavy page. Use `cache=False` sparingly — the default
    15-minute cache means psxdata fetches the screener at most 4 times per hour
    for all symbols combined, not once per symbol.

## Check if market is open

```python
from datetime import datetime

def market_open() -> bool:
    """Returns True if PSX market is currently open (Mon-Fri, 09:15-15:30 PKT)."""
    now = datetime.utcnow()
    # PKT is UTC+5
    pkt_hour = (now.hour + 5) % 24
    pkt_minute = now.minute
    pkt_time = pkt_hour * 60 + pkt_minute
    open_time = 9 * 60 + 15
    close_time = 15 * 60 + 30
    return now.weekday() < 5 and open_time <= pkt_time <= close_time

if market_open():
    q = psxdata.quote("ENGRO", cache=False)
    print(q)
else:
    print("Market is closed.")
```

## See also

- [`quote()`](../api/client.md) — full parameter reference
- [Stock Screener guide](stock-screener.md) — screen multiple stocks at once
