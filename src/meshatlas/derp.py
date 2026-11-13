"""Approximate coordinates of Tailscale DERP regions.

A node's *home DERP region* (``Relay`` in ``tailscale status --json``) is the relay with the lowest latency from that
node, which makes it a decent zero-config guess for where the node is. Custom regions (self-hosted DERP) are not in
this table: such nodes fall back to the hub's location until you set ``location`` for them in the config.
"""

# code: (display name, latitude, longitude)
DERP_REGIONS = {
    "nyc": ("New York", 40.71, -74.01),
    "sfo": ("San Francisco", 37.77, -122.42),
    "sea": ("Seattle", 47.61, -122.33),
    "lax": ("Los Angeles", 34.05, -118.24),
    "dfw": ("Dallas", 32.78, -96.80),
    "den": ("Denver", 39.74, -104.99),
    "ord": ("Chicago", 41.88, -87.63),
    "iad": ("Ashburn", 39.04, -77.49),
    "mia": ("Miami", 25.76, -80.19),
    "tor": ("Toronto", 43.65, -79.38),
    "hnl": ("Honolulu", 21.31, -157.86),
    "sao": ("São Paulo", -23.55, -46.63),
    "lhr": ("London", 51.51, -0.13),
    "ams": ("Amsterdam", 52.37, 4.90),
    "fra": ("Frankfurt", 50.11, 8.68),
    "nue": ("Nuremberg", 49.45, 11.08),
    "par": ("Paris", 48.86, 2.35),
    "mad": ("Madrid", 40.42, -3.70),
    "waw": ("Warsaw", 52.23, 21.01),
    "hel": ("Helsinki", 60.17, 24.94),
    "dbi": ("Dubai", 25.20, 55.27),
    "jnb": ("Johannesburg", -26.20, 28.05),
    "nai": ("Nairobi", -1.29, 36.82),
    "blr": ("Bangalore", 12.97, 77.59),
    "bom": ("Mumbai", 19.08, 72.88),
    "sin": ("Singapore", 1.35, 103.82),
    "hkg": ("Hong Kong", 22.32, 114.17),
    "tok": ("Tokyo", 35.68, 139.69),
    "syd": ("Sydney", -33.87, 151.21),
}


def region(code):
    """Return (name, lat, lon) for a DERP region code, or None if it is unknown (e.g. a custom region)."""
    return DERP_REGIONS.get((code or "").lower())
