---
title: Fetch KSE-100 and PSX Index Data with Python
description: Download KSE-100, KSE-30, and all PSX index data programmatically using psxdata.
---

# Fetch KSE-100 and PSX Index Data with Python

`psxdata.indices()` returns constituent data for any of the 18 PSX indices, including index weights and market cap.

## Fetch KSE-100 constituents

```python
import psxdata

df = psxdata.indices("KSE100")
print(df.columns.tolist())
# ['symbol', 'current_index', 'idx_weight', 'idx_point', 'market_cap_m', 'freefloat_m']
print(df.head())
```

## Available indices

Pass the index name as a string:

| Index name string | Description |
| --- | --- |
| `"KSE100"` | KSE-100 Index |
| `"KSE30"` | KSE-30 Index |
| `"KMIALLSHR"` | KMI All Shares Index |
| `"KMI30"` | KMI-30 Index |
| `"BKTI"` | Banking Index |
| `"NITPGE"` | NIT PSX Governance Index |

See `psxdata/constants.py` for the complete list.

## Top 10 by index weight

```python
import psxdata

df = psxdata.indices("KSE100")
top10 = df.nlargest(10, "idx_weight")[["symbol", "idx_weight", "market_cap_m"]]
print(top10)
```

## Get tickers for an index

To get just the symbol list (cheaper than fetching full constituent data):

```python
import psxdata

tickers = psxdata.tickers(index="KSE100")
print(f"{len(tickers)} stocks in KSE-100")
```

!!! note
    `tickers(index="KSE100")` and `indices("KSE100")` share the same cache key.
    Calling both in the same session makes only one network request.

## See also

- [`indices()`](../api/client.md) — parameter reference
- [`tickers()`](../api/client.md) — symbol-only list by index
- [Historical Data guide](historical-data.md) — download prices for index constituents
