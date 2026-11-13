"""Procedural architectural property variations for BuildSite.

Derives deterministic, persistent architectural styles, material palettes,
pool tones, landscaping flora, and lighting temperatures from the developer's
stable GitHub identifier.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, NamedTuple

from buildsite.models import PropertyVariation


class StyleDefinition(NamedTuple):
    name: str
    display_title: str
    primary_tint: str
    accent_material: str
    pool_water_tone: str
    garden_species: str
    lighting_temp_kelvin: int
    roof_accent: str
    wall_color_hex: str
    accent_color_hex: str
    glass_tint_hex: str
    pool_water_hex: str


STYLES: List[StyleDefinition] = [
    StyleDefinition(
        name="modern_minimal",
        display_title="Ultra-Modern Minimalist Villa",
        primary_tint="#F4F4F6",
        accent_material="black_steel",
        pool_water_tone="turquoise",
        garden_species="mediterranean",
        lighting_temp_kelvin=3200,
        roof_accent="anthracite",
        wall_color_hex="#E8ECEF",
        accent_color_hex="#2B2D42",
        glass_tint_hex="#3A86FF",
        pool_water_hex="#00B4D8"
    ),
    StyleDefinition(
        name="warm_timber",
        display_title="Contemporary Timber & Glass Villa",
        primary_tint="#FAF8F5",
        accent_material="cedar_timber",
        pool_water_tone="azure",
        garden_species="japanese_zen",
        lighting_temp_kelvin=2700,
        roof_accent="timber_overhang",
        wall_color_hex="#F0ECE1",
        accent_color_hex="#8D5B4C",
        glass_tint_hex="#48CAE4",
        pool_water_hex="#0096C7"
    ),
    StyleDefinition(
        name="slate_stone",
        display_title="Cantilevered Stone & Concrete Villa",
        primary_tint="#ECEFF1",
        accent_material="natural_slate",
        pool_water_tone="deep_blue",
        garden_species="nordic_pine",
        lighting_temp_kelvin=3500,
        roof_accent="slate",
        wall_color_hex="#DFE3E6",
        accent_color_hex="#4A5568",
        glass_tint_hex="#0077B6",
        pool_water_hex="#03045E"
    ),
    StyleDefinition(
        name="coastal_white",
        display_title="Coastal Horizon Luxury Residence",
        primary_tint="#FFFFFF",
        accent_material="teak_wood",
        pool_water_tone="caribbean_cyan",
        garden_species="temperate_lush",
        lighting_temp_kelvin=3000,
        roof_accent="white_trim",
        wall_color_hex="#F7F9FB",
        accent_color_hex="#C29B38",
        glass_tint_hex="#00B4D8",
        pool_water_hex="#48CAE4"
    ),
]


def derive_property_variation(seed: str, preferred_style: str = "auto") -> PropertyVariation:
    """Deterministically derive a property variation from a seed string.

    Args:
        seed: Unique string, typically "{user_id}:{login}" or custom seed.
        preferred_style: Optional user style override ("auto", "modern", "timber", etc.).

    Returns:
        PropertyVariation with deterministic styling attributes.
    """
    # Deterministic integer from SHA-256
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    int_seed = int(digest[:12], 16)

    # Match user style preference or select deterministically
    matched_style: StyleDefinition
    if preferred_style and preferred_style != "auto":
        pref = preferred_style.lower()
        candidates = [s for s in STYLES if pref in s.name or pref in s.display_title.lower()]
        if candidates:
            matched_style = candidates[0]
        else:
            style_idx = int_seed % len(STYLES)
            matched_style = STYLES[style_idx]
    else:
        style_idx = int_seed % len(STYLES)
        matched_style = STYLES[style_idx]

    # Micro variations in lighting temperature
    # ± 150K variation
    temp_jitter = ((int_seed >> 4) % 7 - 3) * 50
    final_kelvin = max(2500, min(4200, matched_style.lighting_temp_kelvin + temp_jitter))

    return PropertyVariation(
        seed=seed,
        style_name=matched_style.name,
        primary_tint=matched_style.primary_tint,
        accent_material=matched_style.accent_material,
        pool_water_tone=matched_style.pool_water_tone,
        garden_species=matched_style.garden_species,
        lighting_temp_kelvin=final_kelvin,
        roof_accent=matched_style.roof_accent
    )


def get_style_palette_by_name(style_name: str) -> StyleDefinition:
    """Return the StyleDefinition matching style_name, or default to modern_minimal."""
    for style in STYLES:
        if style.name == style_name:
            return style
    return STYLES[0]
