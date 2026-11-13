"""Data models for BuildSite.

Defines normalized representations of contribution data, property state,
milestones, micro-progression, architectural variations, and configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ConstructionMilestone(str, Enum):
    """Major construction milestones based on verified GitHub contributions."""

    PLOT = "plot"                         # 0: Empty surveyed plot
    FOUNDATIONS = "foundations"           # 1-10: Excavation, rebar, footing slabs
    FRAMING = "framing"                   # 11-30: Structural columns, ground floor beams
    STRUCTURE = "structure"               # 31-60: Upper floor framing, staircase core
    ROOF_ENCLOSURE = "roof_enclosure"     # 61-100: Roof, facade sheathing, glazing
    FINISHING = "finishing"               # 101-150: Plaster, timber louvers, interior
    DRIVEWAY_GARAGE = "driveway_garage"   # 151-200: Paved driveway, garage, perimeter
    SWIMMING_POOL = "swimming_pool"       # 201-300: Excavated pool, azure water, deck
    GARDEN = "garden"                     # 301-450: Manicured lawn, mature trees, flora
    PATIO_PERGOLA = "patio_pergola"       # 451-600: Teak pergola, outdoor lounge, lights
    PREMIUM_UPGRADES = "premium_upgrades" # 601-900: Solar array, rooftop glass terrace
    ESTATE_EXPANSION = "estate_expansion" # 901-1500: Guesthouse pavilion, water feature
    MASTER_ESTATE = "master_estate"       # 1501+: Extended luxury estate & court


@dataclass(frozen=True)
class MilestoneSpec:
    """Specification defining milestone thresholds and architectural unlocks."""

    milestone: ConstructionMilestone
    min_contributions: int
    max_contributions: int
    title: str
    description: str
    unlocks: List[str]
    layers: List[str]


MILESTONE_SPECS: List[MilestoneSpec] = [
    MilestoneSpec(
        milestone=ConstructionMilestone.PLOT,
        min_contributions=0,
        max_contributions=0,
        title="Empty Plot",
        description="Surveyed residential plot ready for construction",
        unlocks=["plot_boundary", "surveyor_stakes"],
        layers=["plot_base"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.FOUNDATIONS,
        min_contributions=1,
        max_contributions=10,
        title="Excavation & Foundations",
        description="Groundwork, trenching, rebar cages and poured footing slabs",
        unlocks=["foundation_slab", "rebar_reinforcement", "excavation_earth"],
        layers=["plot_base", "foundations"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.FRAMING,
        min_contributions=11,
        max_contributions=30,
        title="Columns & Beams",
        description="Reinforced concrete pillars, ground floor beams and core walls",
        unlocks=["ground_columns", "support_beams", "concrete_core"],
        layers=["plot_base", "foundations", "columns_beams"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.STRUCTURE,
        min_contributions=31,
        max_contributions=60,
        title="Building Frame & Upper Floor",
        description="First floor concrete slab, upper level structural framing",
        unlocks=["first_floor_slab", "upper_columns", "cantilever_supports"],
        layers=["plot_base", "building_frame"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.ROOF_ENCLOSURE,
        min_contributions=61,
        max_contributions=100,
        title="Roofing & Glazing",
        description="Waterproofed flat roof, floor-to-ceiling glass and aluminum mullions",
        unlocks=["roof_deck", "panoramic_glazing", "balcony_glass"],
        layers=["plot_base", "roof_enclosure"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.FINISHING,
        min_contributions=101,
        max_contributions=150,
        title="Façade & Architectural Finishes",
        description="Mineral plaster, stone cladding, warm timber louvers & interior light",
        unlocks=["mineral_plaster", "timber_cladding", "interior_warm_lighting"],
        layers=["plot_base", "villa_finished"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.DRIVEWAY_GARAGE,
        min_contributions=151,
        max_contributions=200,
        title="Driveway, Garage & Boundary",
        description="Cobblestone driveway, covered garage and boundary wall",
        unlocks=["garage_structure", "paved_driveway", "boundary_wall"],
        layers=["plot_base", "villa_finished", "driveway_garage"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.SWIMMING_POOL,
        min_contributions=201,
        max_contributions=300,
        title="Luxury Swimming Pool",
        description="Turquoise-water pool, submerged LED illumination, and sun loungers",
        unlocks=["swimming_pool", "pool_deck", "underwater_lighting", "sun_loungers"],
        layers=["plot_base", "villa_finished", "driveway_garage", "swimming_pool"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.GARDEN,
        min_contributions=301,
        max_contributions=450,
        title="Lush Gardens & Landscaping",
        description="Manicured emerald lawn, mature cypress trees, flowering shrubs & stone path",
        unlocks=["manicured_lawn", "cypress_trees", "ornamental_shrubs", "stone_walkway"],
        layers=["plot_base", "villa_finished", "driveway_garage", "swimming_pool", "gardens"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.PATIO_PERGOLA,
        min_contributions=451,
        max_contributions=600,
        title="Outdoor Pergola & Night Lighting",
        description="Modern cedar pergola, outdoor dining table, and warm architectural landscape spotlights",
        unlocks=["cedar_pergola", "patio_dining", "landscape_lighting", "ambient_dusk_glow"],
        layers=["plot_base", "villa_finished", "driveway_garage", "swimming_pool", "gardens", "patio_pergola"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.PREMIUM_UPGRADES,
        min_contributions=601,
        max_contributions=900,
        title="Rooftop Terrace & Solar Array",
        description="Glass-balustrade rooftop lounge, rooftop solar micro-grid, and EV fast-charger",
        unlocks=["rooftop_terrace", "solar_panels", "ev_charger", "rooftop_planters"],
        layers=["plot_base", "villa_finished", "driveway_garage", "swimming_pool", "gardens", "patio_pergola", "upgrades"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.ESTATE_EXPANSION,
        min_contributions=901,
        max_contributions=1500,
        title="Private Guesthouse & Water Feature",
        description="Separate modern guest pavilion, architectural reflecting fountain and courtyard",
        unlocks=["guesthouse_pavilion", "reflecting_water_feature", "expanded_courtyard"],
        layers=["plot_base", "villa_finished", "driveway_garage", "swimming_pool", "gardens", "patio_pergola", "upgrades", "estate_guesthouse"]
    ),
    MilestoneSpec(
        milestone=ConstructionMilestone.MASTER_ESTATE,
        min_contributions=1501,
        max_contributions=999999,
        title="Master Luxury Residential Estate",
        description="Complete multi-wing villa estate with sports court, private grove and master lighting",
        unlocks=["estate_sports_court", "extended_orchard_grove", "master_estate_lighting", "perpetual_prestige"],
        layers=["plot_base", "villa_finished", "driveway_garage", "swimming_pool", "gardens", "patio_pergola", "upgrades", "estate_guesthouse", "master_expansion"]
    )
]


@dataclass
class MicroEvolution:
    """Micro-evolution state within the current milestone."""

    current_milestone: ConstructionMilestone
    next_milestone: Optional[ConstructionMilestone]
    milestone_title: str
    milestone_min: int
    milestone_max: int
    progress_ratio: float           # 0.0 to 1.0 within this milestone
    contributions_to_next: int
    micro_details_unlocked: List[str] = field(default_factory=list)
    next_upgrade_title: str = ""


@dataclass
class PropertyVariation:
    """Deterministic procedural property customization seeded by user account ID."""

    seed: str
    style_name: str                 # "modern_minimal", "warm_timber", "slate_stone", "nordic_concrete"
    primary_tint: str               # Hex or RGB
    accent_material: str            # "timber", "stone", "black_steel", "bronze"
    pool_water_tone: str            # "azure", "turquoise", "deep_blue"
    garden_species: str             # "mediterranean", "japanese_zen", "nordic_pine", "temperate_lush"
    lighting_temp_kelvin: int       # 2700K to 4000K
    roof_accent: str                # "anthracite", "slate", "timber_overhang"


@dataclass
class ContributionDay:
    """Single day of verified contribution activity."""

    date: str                       # YYYY-MM-DD
    count: int


@dataclass
class ContributionSnapshot:
    """Normalized snapshot of verified GitHub contributions."""

    user_id: int                    # Stable numeric account ID
    login: str                      # Current username
    total_contributions: int        # Official total counted
    active_days: int                # Days with at least 1 contribution
    calendar_days: List[ContributionDay] = field(default_factory=list)
    years: List[int] = field(default_factory=list)
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "graphql"         # "graphql", "rest", "cache", or "demo"


@dataclass
class PropertyState:
    """Persistent state representing the physical evolution of the property."""

    schema_version: int = 1
    user_id: int = 0
    login: str = ""
    seed: str = ""
    total_contributions: int = 0
    active_days: int = 0
    milestone: ConstructionMilestone = ConstructionMilestone.PLOT
    progress_ratio: float = 0.0
    active_layers: List[str] = field(default_factory=list)
    unlocked_features: List[str] = field(default_factory=list)
    variation: Optional[Dict[str, Any]] = None
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_contribution_count: int = 0
    hash_signature: str = ""


@dataclass
class UserConfig:
    """Configuration parsed from buildsite.yml or CLI flags."""

    username: str = ""
    token: Optional[str] = None
    visibility: str = "public"
    style: str = "modern"
    seed: str = "auto"
    palette: str = "natural"
    pool: bool = True
    garden: bool = True
    garage: bool = True
    lighting: str = "dusk"          # "daytime", "dusk", "night"
    width: int = 1280
    height: int = 640
    format: str = "svg"
    quality: str = "high"
    animation: str = "subtle"       # "subtle", "none"
    output_dir: str = "assets/buildsite"
    png_fallback: bool = True
    preserve_unlocks: bool = True
