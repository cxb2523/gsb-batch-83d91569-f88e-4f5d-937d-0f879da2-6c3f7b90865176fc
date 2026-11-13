"""Command-line interface for BuildSite.

Provides commands to initialize configuration, validate assets, query GitHub
contributions, evolve residential property states, and export SVGs.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from buildsite.composer import composite_property, find_assets_directory
from buildsite.config import ConfigValidationError, load_config
from buildsite.github_api import (
    GitHubAPIError,
    RateLimitExceededError,
    UserNotFoundError,
    fetch_contributions_graphql,
    fetch_contributions_public_calendar,
    fetch_contributions_rest_fallback,
    get_demo_contributions,
)
from buildsite.models import ContributionSnapshot, PropertyState, UserConfig
from buildsite.progression import calculate_micro_evolution, calculate_property_state, get_milestone_spec
from buildsite.property import derive_property_variation
from buildsite.state import has_state_changed, load_state, save_state
from buildsite.svg_export import export_png_fallback, export_svg_to_file, generate_svg
from buildsite.turntable import generate_animated_turntable

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("buildsite")


SAMPLE_CONFIG_TEMPLATE = """# BuildSite Configuration
# Documentation: https://github.com/buildsite/buildsite

version: 1

github:
  username: {username}
  visibility: public

property:
  style: modern       # modern | timber | slate | coastal | auto
  seed: auto          # auto (derived from GitHub ID) or custom string
  palette: natural
  pool: true          # enable swimming pool unlock
  garden: true        # enable garden landscaping
  garage: true        # enable driveway & garage
  lighting: dusk      # dusk | daytime | night

render:
  width: 1280
  height: 640
  format: svg
  quality: high
  animation: subtle   # subtle | none

progression:
  mode: continuous
  preserve_unlocks: true

output:
  directory: assets/buildsite
  png_fallback: true
"""


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a default buildsite.yml configuration."""
    cfg_file = Path("buildsite.yml")
    if cfg_file.exists() and not args.force:
        logger.warning("Configuration file buildsite.yml already exists. Use --force to overwrite.")
        return 0

    user = args.user or "YOUR_GITHUB_USERNAME"
    content = SAMPLE_CONFIG_TEMPLATE.format(username=user)
    cfg_file.write_text(content, encoding="utf-8")
    logger.info("Initialized BuildSite configuration in %s", cfg_file.resolve())
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate configuration file and asset manifests."""
    logger.info("Validating BuildSite setup...")
    errors = 0

    # 1. Config validation
    try:
        cfg = load_config(args.config)
        logger.info("[OK] Configuration is valid (user: '%s', lighting: '%s')", cfg.username or "unspecified", cfg.lighting)
    except ConfigValidationError as exc:
        logger.error("[ERROR] Configuration validation failed: %s", exc)
        errors += 1

    # 2. Asset validation
    assets_dir = find_assets_directory()
    if not assets_dir.is_dir():
        logger.error("[ERROR] Assets directory not found at: %s", assets_dir)
        errors += 1
    else:
        manifest_file = assets_dir / "manifests" / "layer_manifest.json"
        if manifest_file.is_file():
            logger.info("[OK] Asset manifest present at %s", manifest_file)
        else:
            logger.warning("[WARN] Asset manifest missing at %s", manifest_file)

        # Check essential layers
        essential = ["plot_base", "foundations", "villa_finished", "swimming_pool"]
        missing = []
        for l in essential:
            found = False
            for sub in ["architecture", "environment", "landscaping", "pool", ""]:
                if (assets_dir / sub / f"{l}.png").is_file():
                    found = True
                    break
            if not found:
                missing.append(l)

        if missing:
            logger.error("[ERROR] Missing essential render layers: %s", ", ".join(missing))
            errors += 1
        else:
            logger.info("[OK] Essential architectural render layers verified.")

    if errors == 0:
        logger.info("BuildSite validation passed with 0 errors.")
        return 0
    else:
        logger.error("BuildSite validation failed with %d error(s).", errors)
        return 1


def fetch_snapshot_with_fallbacks(
    username: str,
    token: Optional[str] = None,
    allow_demo: bool = False
) -> ContributionSnapshot:
    """Fetch snapshot via GraphQL, public calendar scraper, REST fallback, or demo."""
    if allow_demo:
        return get_demo_contributions(327, username=username or "demo-user")

    # 1. Attempt GraphQL first if token provided
    if token:
        try:
            return fetch_contributions_graphql(username, token=token)
        except UserNotFoundError:
            raise
        except Exception as exc:
            logger.warning("GraphQL query with token failed (%s); trying public calendar...", exc)

    # 2. Query GitHub public contributions calendar (returns exact verified count without auth)
    try:
        return fetch_contributions_public_calendar(username)
    except UserNotFoundError:
        raise
    except Exception as cal_exc:
        logger.warning("Public calendar query failed (%s); trying GraphQL/REST...", cal_exc)

    # 3. Attempt unauthenticated GraphQL
    try:
        return fetch_contributions_graphql(username, token=token)
    except UserNotFoundError:
        raise
    except (RateLimitExceededError, GitHubAPIError) as exc:
        logger.warning("GraphQL query failed (%s); trying REST API fallback...", exc)

    # 4. Attempt REST fallback
    try:
        return fetch_contributions_rest_fallback(username, token=token)
    except Exception as rest_exc:
        raise GitHubAPIError(f"All contribution retrieval methods failed: {rest_exc}") from rest_exc


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate or update the evolved property SVG."""
    config = load_config(args.config)

    # CLI flag overrides
    target_user = args.user or config.username
    if not target_user and not args.demo:
        logger.error("No GitHub username provided. Pass --user <username> or configure buildsite.yml")
        return 1

    token = args.token or config.token or os.environ.get("GITHUB_TOKEN")
    out_dir_path = Path(args.output_dir or config.output_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    state_file = out_dir_path / "buildsite_state.json"

    logger.info("Fetching contributions for @%s...", target_user or "demo")
    try:
        snapshot = fetch_snapshot_with_fallbacks(
            username=target_user or "demo-developer",
            token=token,
            allow_demo=args.demo
        )
    except Exception as exc:
        logger.error("Contribution retrieval failed: %s", exc)
        return 1

    logger.info("Retrieved %d contributions across %d active days.", snapshot.total_contributions, snapshot.active_days)

    # Load existing state if available
    prev_state = load_state(state_file)
    new_state = calculate_property_state(snapshot, config, prev_state)

    if not args.force and prev_state and not has_state_changed(prev_state, new_state):
        logger.info("Property state unchanged (%d contributions, %s). No update required.", new_state.total_contributions, new_state.milestone.value)
        return 0

    variation = derive_property_variation(new_state.seed, config.style)
    logger.info("Compositing property: Style '%s', Milestone '%s'...", variation.style_name, new_state.milestone.value)

    # Composite layers
    assets_dir = find_assets_directory()
    composite_img = composite_property(new_state, config, assets_dir=assets_dir, variation=variation)

    # Generate and export SVG
    svg_str = generate_svg(new_state, config, composite_img)
    svg_file = out_dir_path / "buildsite.svg"
    export_svg_to_file(svg_str, svg_file)
    logger.info("Generated SVG: %s", svg_file.resolve())

    # Export PNG fallback if enabled
    if config.png_fallback:
        png_file = out_dir_path / "buildsite.png"
        export_png_fallback(composite_img, png_file)
        logger.info("Generated PNG fallback: %s", png_file.resolve())

    # Generate 360-degree rotating turntable animation
    webp_360 = out_dir_path / "buildsite_360.webp"
    svg_360 = out_dir_path / "buildsite_360.svg"
    try:
        generate_animated_turntable(new_state, config, webp_360, svg_360, num_frames=16)
        logger.info("Generated 360 Turntable: %s", webp_360.resolve())
    except Exception as tt_exc:
        logger.warning("Could not generate 360 turntable: %s", tt_exc)

    # Save state
    save_state(new_state, state_file)
    logger.info("Saved persistent state: %s", state_file.resolve())

    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Generate demo property without querying live GitHub."""
    count = args.count if args.count is not None else 327
    user = args.user or "demo-architect"
    logger.info("Running BuildSite Demo with %d simulated contributions for @%s...", count, user)

    snapshot = get_demo_contributions(count=count, username=user)
    config = load_config(args.config)

    out_dir_path = Path(args.output_dir or "examples/demo_output")
    out_dir_path.mkdir(parents=True, exist_ok=True)
    state_file = out_dir_path / "buildsite_state.json"

    new_state = calculate_property_state(snapshot, config)
    variation = derive_property_variation(new_state.seed, config.style)

    assets_dir = find_assets_directory()
    composite_img = composite_property(new_state, config, assets_dir=assets_dir, variation=variation)

    svg_str = generate_svg(new_state, config, composite_img)
    svg_file = out_dir_path / "buildsite.svg"
    export_svg_to_file(svg_str, svg_file)

    png_file = out_dir_path / "buildsite.png"
    export_png_fallback(composite_img, png_file)

    save_state(new_state, state_file)
    logger.info("Demo property created successfully at: %s", svg_file.resolve())
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Display current property progression and next upgrades."""
    config = load_config(args.config)
    out_dir_path = Path(args.output_dir or config.output_dir)
    state_file = out_dir_path / "buildsite_state.json"
    state = load_state(state_file)

    if not state:
        logger.warning("No state found at %s. Run 'buildsite generate' first.", state_file)
        return 1

    micro = calculate_micro_evolution(state.total_contributions)
    spec = get_milestone_spec(state.milestone)

    print("\n==================================================")
    print(f"  BUILDSITE STATUS: @{state.login}")
    print("==================================================")
    print(f"  Verified Contributions: {state.total_contributions:,}")
    print(f"  Active Contribution Days: {state.active_days}")
    print(f"  Active Milestone:       {spec.title} ({state.milestone.value})")
    print(f"  Progress to Next:       {int(micro.progress_ratio * 100)}% ({micro.contributions_to_next:,} contributions needed)")
    print(f"  Next Upgrade:           {micro.next_upgrade_title}")
    print(f"  Active Layers:          {', '.join(state.active_layers)}")
    print("\n  Unlocked Features:")
    for feat in state.unlocked_features[-6:]:
        print(f"    * {feat}")
    print("==================================================\n")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    """Open the generated SVG in the default web browser."""
    config = load_config(args.config)
    out_dir_path = Path(args.output_dir or config.output_dir)
    svg_file = out_dir_path / "buildsite.svg"

    if not svg_file.is_file():
        logger.info("Output file not found. Generating first...")
        ret = cmd_generate(args)
        if ret != 0:
            return ret

    if svg_file.is_file():
        logger.info("Opening %s in default browser...", svg_file.resolve())
        webbrowser.open(svg_file.resolve().as_uri())
        return 0
    logger.error("Could not find SVG at %s", svg_file)
    return 1


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="buildsite",
        description="Your GitHub Builds Your Home. Photorealistic residential property evolution engine."
    )
    parser.add_argument("--config", "-c", help="Path to buildsite.yml config file", default=None)
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = subparsers.add_parser("init", help="Create sample buildsite.yml configuration")
    p_init.add_argument("--user", "-u", help="GitHub username")
    p_init.add_argument("--force", "-f", action="store_true", help="Overwrite existing configuration")

    # validate
    subparsers.add_parser("validate", help="Validate configuration and rendering assets")

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate or update property SVG from contributions")
    p_gen.add_argument("--user", "-u", help="GitHub username to query")
    p_gen.add_argument("--token", "-t", help="GitHub token (defaults to GITHUB_TOKEN env var)")
    p_gen.add_argument("--output-dir", "-o", help="Output directory for generated files")
    p_gen.add_argument("--demo", action="store_true", help="Use labeled demo data instead of querying live GitHub")
    p_gen.add_argument("--force", "-f", action="store_true", help="Force regeneration even if state is unchanged")

    # demo
    p_demo = subparsers.add_parser("demo", help="Generate sample property with specified contribution count")
    p_demo.add_argument("--count", "-n", type=int, default=327, help="Number of simulated contributions (default: 327)")
    p_demo.add_argument("--user", "-u", default="demo-developer", help="Demo username")
    p_demo.add_argument("--output-dir", "-o", default="examples/demo_output", help="Output directory for demo")

    # status
    p_stat = subparsers.add_parser("status", help="Display current property status and unlocked features")
    p_stat.add_argument("--output-dir", "-o", help="Directory where buildsite_state.json resides")

    # preview
    p_prev = subparsers.add_parser("preview", help="Open generated property SVG in web browser")
    p_prev.add_argument("--output-dir", "-o", help="Output directory containing buildsite.svg")
    p_prev.add_argument("--user", "-u", help="GitHub username (if generating first)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "init": cmd_init,
        "validate": cmd_validate,
        "generate": cmd_generate,
        "demo": cmd_demo,
        "status": cmd_status,
        "preview": cmd_preview,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        return cmd_fn(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
