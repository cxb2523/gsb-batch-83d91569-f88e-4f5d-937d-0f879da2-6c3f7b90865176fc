"""Evolution and progression engine for BuildSite.

Calculates deterministic construction milestones, micro-evolution steps,
architectural unlocks, and layer composition rules based on verified
GitHub contributions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from buildsite.models import (
    MILESTONE_SPECS,
    ConstructionMilestone,
    ContributionSnapshot,
    MicroEvolution,
    MilestoneSpec,
    PropertyState,
    UserConfig,
)


def get_milestone_spec(milestone: ConstructionMilestone) -> MilestoneSpec:
    """Retrieve the MilestoneSpec corresponding to a milestone enum."""
    for spec in MILESTONE_SPECS:
        if spec.milestone == milestone:
            return spec
    return MILESTONE_SPECS[0]


def calculate_milestone(contributions: int) -> MilestoneSpec:
    """Determine the major milestone for a given contribution count."""
    try:
        safe_contributions = max(0, int(contributions or 0))
    except (TypeError, ValueError):
        safe_contributions = 0
    for spec in MILESTONE_SPECS:
        if spec.min_contributions <= safe_contributions <= spec.max_contributions:
            return spec
    # Beyond highest defined max (1501+)
    return MILESTONE_SPECS[-1]


def get_micro_details(milestone: ConstructionMilestone, contributions: int) -> List[str]:
    """Return fine-grained architectural details unlocked within the milestone."""
    try:
        contributions = max(0, int(contributions or 0))
    except (TypeError, ValueError):
        contributions = 0
    details: List[str] = []

    if milestone == ConstructionMilestone.PLOT:
        details.append("Site surveyed and cleared")
        details.append("Perimeter stakes placed")

    elif milestone == ConstructionMilestone.FOUNDATIONS:
        if contributions >= 1:
            details.append("Perimeter trenches excavated")
        if contributions >= 4:
            details.append("Steel rebar reinforcement grid laid")
        if contributions >= 8:
            details.append("Structural concrete foundation slab cured")

    elif milestone == ConstructionMilestone.FRAMING:
        if contributions >= 11:
            details.append("Ground-level reinforced concrete pillars erected")
        if contributions >= 18:
            details.append("Primary horizontal tie-beams secured")
        if contributions >= 25:
            details.append("Elevator core and ground shear walls cast")

    elif milestone == ConstructionMilestone.STRUCTURE:
        if contributions >= 31:
            details.append("First floor suspended concrete slab poured")
        if contributions >= 41:
            details.append("Upper storey architectural framing assembled")
        if contributions >= 51:
            details.append("Cantilevered balcony structures reinforced")

    elif milestone == ConstructionMilestone.ROOF_ENCLOSURE:
        if contributions >= 61:
            details.append("Flat roofing deck waterproofed with membrane")
        if contributions >= 75:
            details.append("Dark anodized aluminum window mullions fitted")
        if contributions >= 90:
            details.append("Floor-to-ceiling panoramic Low-E double glazing installed")

    elif milestone == ConstructionMilestone.FINISHING:
        if contributions >= 101:
            details.append("Exterior smooth mineral plaster applied")
        if contributions >= 118:
            details.append("Natural stone facade cladding mounted")
        if contributions >= 135:
            details.append("Warm cedar timber louvers and interior lighting active")

    elif milestone == ConstructionMilestone.DRIVEWAY_GARAGE:
        if contributions >= 151:
            details.append("Driveway sub-base graded and rolled")
        if contributions >= 168:
            details.append("Granite paver driveway surface laid")
        if contributions >= 185:
            details.append("Motorized sectional garage door & boundary walls finished")

    elif milestone == ConstructionMilestone.SWIMMING_POOL:
        if contributions >= 201:
            details.append("Pool basin excavated and shotcrete shell formed")
        if contributions >= 235:
            details.append("Turquoise mosaic glass tiles and coping stone installed")
        if contributions >= 270:
            details.append("Pool filled with filtered water, underwater LEDs and teak deck")

    elif milestone == ConstructionMilestone.GARDEN:
        if contributions >= 301:
            details.append("Topsoil graded and emerald sod lawn rolled out")
        if contributions >= 350:
            details.append("Mature Italian cypress and ornamental trees planted")
        if contributions >= 400:
            details.append("Natural flagstone garden pathways and flowerbeds arranged")

    elif milestone == ConstructionMilestone.PATIO_PERGOLA:
        if contributions >= 451:
            details.append("Modern slatted cedar pergola assembled over patio")
        if contributions >= 500:
            details.append("Outdoor dining lounge furniture and fire table placed")
        if contributions >= 550:
            details.append("Architectural dusk spotlights and tree uplighting turned on")

    elif milestone == ConstructionMilestone.PREMIUM_UPGRADES:
        if contributions >= 601:
            details.append("Rooftop terrace observation lounge with frameless balustrade")
        if contributions >= 700:
            details.append("Rooftop monocrystalline solar photovoltaic array commissioned")
        if contributions >= 800:
            details.append("Level-2 electric vehicle high-speed charging dock installed")

    elif milestone == ConstructionMilestone.ESTATE_EXPANSION:
        if contributions >= 901:
            details.append("Separate modern guest pavilion structure framed")
        if contributions >= 1100:
            details.append("Linear architectural reflecting water feature installed")
        if contributions >= 1300:
            details.append("Paved central courtyard connecting main villa and pavilion")

    elif milestone == ConstructionMilestone.MASTER_ESTATE:
        details.append("Master residential estate fully unlocked")
        if contributions >= 1700:
            details.append("Private acrylic hardcourt sports/tennis court completed")
        if contributions >= 2500:
            details.append("Extended private olive and cypress orchard grove matured")
        if contributions >= 5000:
            details.append("Grand illuminated estate gateway and illuminated fountain")
        if contributions >= 10000:
            details.append("Perpetual architectural prestige landmark achieved")

    return details


def calculate_micro_evolution(contributions: int) -> MicroEvolution:
    """Calculate the micro-progression within the active milestone."""
    try:
        safe_c = max(0, int(contributions or 0))
    except (TypeError, ValueError):
        safe_c = 0
    spec = calculate_milestone(safe_c)

    spec_index = MILESTONE_SPECS.index(spec)
    next_spec: Optional[MilestoneSpec] = (
        MILESTONE_SPECS[spec_index + 1] if spec_index + 1 < len(MILESTONE_SPECS) else None
    )

    if spec.milestone == ConstructionMilestone.MASTER_ESTATE:
        # Endless progression beyond 1500
        # Loops in tiers of 500 contributions
        tier_size = 500
        excess = safe_c - spec.min_contributions
        ratio = min(1.0, (excess % tier_size) / float(tier_size))
        to_next = tier_size - (excess % tier_size)
        next_title = f"Prestige Estate Expansion Tier {(excess // tier_size) + 2}"
        next_milestone = None
    elif spec.milestone == ConstructionMilestone.PLOT:
        ratio = 0.0
        to_next = 1
        next_title = next_spec.title if next_spec else "Foundations"
        next_milestone = next_spec.milestone if next_spec else None
    else:
        span = spec.max_contributions - spec.min_contributions + 1
        curr_offset = safe_c - spec.min_contributions
        ratio = min(1.0, max(0.0, curr_offset / float(span)))
        to_next = (spec.max_contributions - safe_c) + 1
        next_title = next_spec.title if next_spec else "Complete"
        next_milestone = next_spec.milestone if next_spec else None

    micro_details = get_micro_details(spec.milestone, safe_c)

    return MicroEvolution(
        current_milestone=spec.milestone,
        next_milestone=next_milestone,
        milestone_title=spec.title,
        milestone_min=spec.min_contributions,
        milestone_max=spec.max_contributions,
        progress_ratio=ratio,
        contributions_to_next=to_next,
        micro_details_unlocked=micro_details,
        next_upgrade_title=next_title
    )


def determine_active_layers(milestone: ConstructionMilestone, config: Optional[UserConfig] = None) -> List[str]:
    """Determine the ordered rendering layers needed for this milestone and config."""
    if config is None:
        config = UserConfig()
    spec = get_milestone_spec(milestone)
    layers = list(spec.layers)

    # Honor user configuration toggles if user disabled specific additions
    if not config.pool:
        layers = [layer for layer in layers if layer != "swimming_pool"]
    if not config.garden:
        layers = [layer for layer in layers if layer != "gardens"]
    if not config.garage:
        layers = [layer for layer in layers if layer != "driveway_garage"]

    return layers


def calculate_property_state(
    snapshot: ContributionSnapshot,
    config: Optional[UserConfig] = None,
    previous_state: Optional[PropertyState] = None
) -> PropertyState:
    """Evolve property state from contribution snapshot and user config.

    Guarantees:
    - Deterministic progression
    - Non-regression: Previous unlocks are preserved if preserve_unlocks is True
    - Idempotence: Duplicate runs yield identical state and signature
    """
    if snapshot is None:
        raise ValueError("snapshot must not be None")
    if config is None:
        config = UserConfig()

    try:
        total_c = max(0, int(snapshot.total_contributions or 0))
    except (TypeError, ValueError):
        total_c = 0

    # Preserve previous achievements if total contributions temporarily reduced
    if previous_state and config.preserve_unlocks:
        if previous_state.total_contributions > total_c:
            total_c = previous_state.total_contributions

    spec = calculate_milestone(total_c)
    micro = calculate_micro_evolution(total_c)
    layers = determine_active_layers(spec.milestone, config)

    # Aggregate unlocked features
    all_unlocked: List[str] = []
    for s in MILESTONE_SPECS:
        if s.min_contributions <= total_c:
            all_unlocked.extend(s.unlocks)
        else:
            break
    all_unlocked.extend(micro.micro_details_unlocked)
    # Deduplicate while preserving order
    unique_unlocked = list(dict.fromkeys(all_unlocked))

    # Compute property variation seed
    seed_source = config.seed
    if not seed_source or seed_source == "auto":
        seed_source = f"{snapshot.user_id}:{snapshot.login}"

    # Generate deterministic hash signature of the current state
    sig_payload = {
        "user_id": snapshot.user_id,
        "login": snapshot.login,
        "contributions": total_c,
        "milestone": spec.milestone.value,
        "layers": layers,
        "seed": seed_source,
        "lighting": config.lighting,
        "style": config.style,
        "palette": config.palette,
    }
    hash_sig = hashlib.sha256(json.dumps(sig_payload, sort_keys=True).encode()).hexdigest()

    return PropertyState(
        schema_version=1,
        user_id=snapshot.user_id,
        login=snapshot.login,
        seed=seed_source,
        total_contributions=total_c,
        active_days=snapshot.active_days,
        milestone=spec.milestone,
        progress_ratio=micro.progress_ratio,
        active_layers=layers,
        unlocked_features=unique_unlocked,
        last_updated=datetime.now(timezone.utc).isoformat(),
        last_contribution_count=total_c,
        hash_signature=hash_sig
    )
