"""Fixture: a chart script that reads its data from the checker's fetch cache.

check_chart.py fetches the sources declared in a .sources.json manifest and
points EVIDENT_DATA_PATHS at the cached files before running this script.
"""
import json
import os

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from _clean import new

paths = json.loads(os.environ["EVIDENT_DATA_PATHS"])

years, values = [], []
with open(paths["values"], encoding="utf-8") as f:
    for row in f.read().strip().splitlines()[1:]:
        year, value = row.split(",")
        years.append(int(year))
        values.append(float(value))

fig, ax = new("Revenue doubled after the 2020 launch")
ax.plot(years, values, color="#1f77b4", lw=2)
ax.xaxis.set_major_locator(MaxNLocator(integer=True))
ax.set_ylabel("Revenue ($M)", fontsize=12)
ax.tick_params(labelsize=11)
fig.text(0.01, 0.01, "Source: Example Bureau, test dataset", fontsize=9)
fig.savefig("out.png")
