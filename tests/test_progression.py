"""Unit tests for the BuildSite progression and evolution engine."""

import pytest

from buildsite.models import (
    ConstructionMilestone,
    ContributionSnapshot,
    PropertyState,
    UserConfig,
)
from buildsite.progression import (
    calculate_micro_evolution,
    calculate_milestone,
    calculate_property_state,
    determine_active_layers,
    get_micro_details,
    get_milestone_spec,
)


def test_milestone_thresholds():
    """Verify exact milestones map accurately according to requirements."""
    assert calculate_milestone(0).milestone == ConstructionMilestone.PLOT
    assert calculate_milestone(1).milestone == ConstructionMilestone.FOUNDATIONS
    assert calculate_milestone(10).milestone == ConstructionMilestone.FOUNDATIONS
    assert calculate_milestone(11).milestone == ConstructionMilestone.FRAMING
    assert calculate_milestone(30).milestone == ConstructionMilestone.FRAMING
    assert calculate_milestone(31).milestone == ConstructionMilestone.STRUCTURE
    assert calculate_milestone(60).milestone == ConstructionMilestone.STRUCTURE
    assert calculate_milestone(61).milestone == ConstructionMilestone.ROOF_ENCLOSURE
    assert calculate_milestone(100).milestone == ConstructionMilestone.ROOF_ENCLOSURE
    assert calculate_milestone(101).milestone == ConstructionMilestone.FINISHING
    assert calculate_milestone(150).milestone == ConstructionMilestone.FINISHING
    assert calculate_milestone(151).milestone == ConstructionMilestone.DRIVEWAY_GARAGE
    assert calculate_milestone(200).milestone == ConstructionMilestone.DRIVEWAY_GARAGE
    assert calculate_milestone(201).milestone == ConstructionMilestone.SWIMMING_POOL
    assert calculate_milestone(300).milestone == ConstructionMilestone.SWIMMING_POOL
    assert calculate_milestone(301).milestone == ConstructionMilestone.GARDEN
    assert calculate_milestone(450).milestone == ConstructionMilestone.GARDEN
    assert calculate_milestone(451).milestone == ConstructionMilestone.PATIO_PERGOLA
    assert calculate_milestone(600).milestone == ConstructionMilestone.PATIO_PERGOLA
    assert calculate_milestone(601).milestone == ConstructionMilestone.PREMIUM_UPGRADES
    assert calculate_milestone(900).milestone == ConstructionMilestone.PREMIUM_UPGRADES
    assert calculate_milestone(901).milestone == ConstructionMilestone.ESTATE_EXPANSION
    assert calculate_milestone(1500).milestone == ConstructionMilestone.ESTATE_EXPANSION
    assert calculate_milestone(1501).milestone == ConstructionMilestone.MASTER_ESTATE
    assert calculate_milestone(10000).milestone == ConstructionMilestone.MASTER_ESTATE


def test_negative_contributions_handled_safely():
    """Negative contribution counts must safely map to empty plot."""
    spec = calculate_milestone(-50)
    assert spec.milestone == ConstructionMilestone.PLOT


def test_micro_evolution_calculations():
    """Verify micro evolution percentages and remaining counts."""
    # Plot (0)
    micro_0 = calculate_micro_evolution(0)
    assert micro_0.current_milestone == ConstructionMilestone.PLOT
    assert micro_0.progress_ratio == 0.0
    assert micro_0.contributions_to_next == 1

    # Foundations midway (5 of 1-10)
    micro_5 = calculate_micro_evolution(5)
    assert micro_5.current_milestone == ConstructionMilestone.FOUNDATIONS
    assert 0.4 <= micro_5.progress_ratio <= 0.5
    assert micro_5.contributions_to_next == 6

    # Swimming pool (250 of 201-300)
    micro_pool = calculate_micro_evolution(250)
    assert micro_pool.current_milestone == ConstructionMilestone.SWIMMING_POOL
    assert 0.45 <= micro_pool.progress_ratio <= 0.55
    assert micro_pool.contributions_to_next == 51


def test_long_term_endless_progression():
    """Verify users with 1,501+ contributions continue unlocking progression tiers."""
    micro_2000 = calculate_micro_evolution(2000)
    assert micro_2000.current_milestone == ConstructionMilestone.MASTER_ESTATE
    assert "Prestige Estate" in micro_2000.next_upgrade_title
    assert micro_2000.contributions_to_next > 0


def test_layer_dependencies():
    """Verify architectural layers are added in dependency order."""
    cfg = UserConfig()
    plot_layers = determine_active_layers(ConstructionMilestone.PLOT, cfg)
    assert plot_layers == ["plot_base"]

    pool_layers = determine_active_layers(ConstructionMilestone.SWIMMING_POOL, cfg)
    assert "plot_base" in pool_layers
    assert "villa_finished" in pool_layers
    assert "swimming_pool" in pool_layers

    # User disabled pool
    cfg_no_pool = UserConfig(pool=False)
    no_pool_layers = determine_active_layers(ConstructionMilestone.SWIMMING_POOL, cfg_no_pool)
    assert "swimming_pool" not in no_pool_layers


def test_non_regression_protection():
    """Verify that a temporary drop in reported contributions does not wipe progress."""
    snapshot_high = ContributionSnapshot(
        user_id=100, login="alice", total_contributions=350, active_days=100
    )
    cfg = UserConfig(preserve_unlocks=True)
    state_high = calculate_property_state(snapshot_high, cfg)
    assert state_high.milestone == ConstructionMilestone.GARDEN

    # Temporary drop to 50
    snapshot_low = ContributionSnapshot(
        user_id=100, login="alice", total_contributions=50, active_days=20
    )
    state_recovered = calculate_property_state(snapshot_low, cfg, previous_state=state_high)
    assert state_recovered.milestone == ConstructionMilestone.GARDEN
    assert state_recovered.total_contributions == 350


def test_deterministic_idempotence():
    """Verify duplicate runs with identical data produce identical state and signatures."""
    snap = ContributionSnapshot(user_id=42, login="bob", total_contributions=250, active_days=90)
    cfg = UserConfig()
    s1 = calculate_property_state(snap, cfg)
    s2 = calculate_property_state(snap, cfg)
    assert s1.hash_signature == s2.hash_signature
    assert s1.milestone == s2.milestone
    assert s1.active_layers == s2.active_layers


def test_progression_handles_none_and_malformed_inputs():
    """Verify progression calculations safely handle None, floats, strings, and default configs."""
    assert calculate_milestone(None).milestone == ConstructionMilestone.PLOT
    assert calculate_milestone("invalid").milestone == ConstructionMilestone.PLOT
    assert calculate_micro_evolution(None).current_milestone == ConstructionMilestone.PLOT
    assert calculate_micro_evolution("bad").current_milestone == ConstructionMilestone.PLOT

    # None config in determine_active_layers defaults to all layers
    layers = determine_active_layers(ConstructionMilestone.SWIMMING_POOL, None)
    assert "swimming_pool" in layers

    # None snapshot raises ValueError
    with pytest.raises(ValueError, match="snapshot must not be None"):
        calculate_property_state(None)

    # None config in calculate_property_state creates default UserConfig
    snap = ContributionSnapshot(user_id=1, login="test", total_contributions=10, active_days=5)
    state = calculate_property_state(snap, None)
    assert state.milestone == ConstructionMilestone.FOUNDATIONS
