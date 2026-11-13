---
title: How to Use the Free PSX Data API with Python
description: Step-by-step guide to downloading free Pakistan Stock Exchange data with the psxdata Python library.
---

# How to Use the Free PSX Data API with Python

`psxdata` is a free, open-source Python library that gives you programmatic access to Pakistan Stock Exchange (PSX) data — no API key, no subscription, no browser.

## What data is available?

| Data type | Function | What you get |
|---|---|---|
| Historical prices | `psxdata.stocks()` | OHLCV for any listed stock, all history |
| Live snapshot | `psxdata.quote()` | Current price, sector, market cap |
| Tickers | `psxdata.tickers()` | All PSX symbols, filterable by index |
| Index data | `psxdata.indices()` | KSE-100 and 17 other indices |
| Sectors | `psxdata.sectors()` | 37 sector breakdowns |
| Financials | `psxdata.fundamentals()` | Financial report filing list |

## Install

```bash
pip install psxdata
```

## How it works

psxdata scrapes the public PSX website (`dps.psx.com.pk`) using `requests` and `BeautifulSoup`. All endpoints are plain HTTP — no JavaScript rendering, no Selenium, no Playwright. Data is returned as pandas DataFrames.

Results are cached locally at `~/.psxdata/cache/` in parquet format. Historical data never re-downloads. Today's prices refresh every 15 minutes.

## Example: portfolio snapshot

```python
import psxdata
import pandas as pd

# Define a simple portfolio
portfolio = ["ENGRO", "LUCK", "HBL", "OGDC", "PSO"]

# Fetch the latest quote for each stock
rows = []
for ticker in portfolio:
    q = psxdata.quote(ticker)
    if not q.empty:
        rows.append(q.iloc[0])

snapshot = pd.DataFrame(rows).reset_index(drop=True)
print(snapshot[["symbol", "sector", "ldcp"]])
```

## Next steps

- [Download historical prices](historical-data.md)
- [Screen PSX stocks](stock-screener.md)
- [Full API reference](../api/client.md)
