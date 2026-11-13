"""BuildSite: Your GitHub Builds Your Home.

Transform verified GitHub contributions into an evolving, photorealistic
residential property directly inside your GitHub profile README.
"""

__version__ = "1.0.0"
__author__ = "BuildSite Maintainers"

from buildsite.composer import composite_property
from buildsite.config import load_config
from buildsite.github_api import fetch_contributions_graphql, fetch_contributions_rest_fallback
from buildsite.models import (
    ConstructionMilestone,
    ContributionSnapshot,
    MilestoneSpec,
    PropertyState,
    UserConfig,
)
from buildsite.progression import calculate_micro_evolution, calculate_milestone, calculate_property_state
from buildsite.svg_export import export_png_fallback, export_svg_to_file, generate_svg

__all__ = [
    "__version__",
    "calculate_milestone",
    "calculate_micro_evolution",
    "calculate_property_state",
    "composite_property",
    "generate_svg",
    "export_svg_to_file",
    "export_png_fallback",
    "load_config",
    "fetch_contributions_graphql",
    "fetch_contributions_rest_fallback",
    "ConstructionMilestone",
    "ContributionSnapshot",
    "MilestoneSpec",
    "PropertyState",
    "UserConfig",
]
