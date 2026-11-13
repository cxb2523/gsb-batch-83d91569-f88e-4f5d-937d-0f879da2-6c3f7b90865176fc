---
title: Analyse PSX Sector Performance with Python
description: Fetch sector-wise summary data from PSX and analyse performance trends using pandas.
---

# Analyse PSX Sector Performance with Python

`psxdata.sectors()` returns a summary of all 37 PSX sectors including advance/decline counts, turnover, and market capitalisation.

## Fetch sector data

```python
import psxdata

df = psxdata.sectors()
print(df.columns.tolist())
# ['sector_code', 'sector_name', 'advance', 'decline', 'unchanged', 'turnover', 'market_cap_b']
print(df.shape)
# (37, 7)
```

## Top sectors by market cap

```python
import psxdata

df = psxdata.sectors()
top10 = df.sort_values("market_cap_b", ascending=False).head(10)
print(top10[["sector_name", "market_cap_b"]])
```

## Advance/decline ratio

```python
import psxdata

df = psxdata.sectors()
df["ad_ratio"] = df["advance"] / (df["decline"] + 1)  # +1 avoids ZeroDivisionError
bullish = df[df["ad_ratio"] > 2][["sector_name", "advance", "decline", "ad_ratio"]]
print(bullish.sort_values("ad_ratio", ascending=False))
```

## Find stocks in a specific sector

```python
import psxdata
import pandas as pd

# Find tickers in a specific sector via the screener
kse100 = psxdata.tickers(index="KSE100")
quotes = [psxdata.quote(t).assign(ticker=t) for t in kse100[:20]]

screener = pd.concat(quotes, ignore_index=True)
cemento = screener[screener["sector"].str.contains("Cement", na=False)]
print(cemento[["symbol", "sector", "ldcp"]])
```

## See also

- [`sectors()`](../api/client.md) — parameter reference
- [Indices guide](indices.md) — work with KSE-100 index data
