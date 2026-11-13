# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-11-06

### Added
- **Core Progression Engine**:
  - Deterministic 13-tier construction milestone model (Plot -> Foundations -> Structure -> Roof -> Villa -> Garage -> Swimming Pool -> Garden -> Pergola -> Rooftop Upgrades -> Guesthouse -> Master Luxury Estate).
  - Continuous micro-evolution mechanics with granular milestone unlock tracking.
  - Endless prestige expansion tiers for developers with 1,501+ contributions.
  - Non-regression safety lock (`preserve_unlocks: true`) to prevent property degradation during API anomalies.
- **GitHub Contribution Engine**:
  - Official GitHub GraphQL API collector querying contribution calendar and exact verified counts.
  - Resilient REST API fallback when GraphQL access is restricted.
  - Deterministic demo generator (`buildsite demo`) for offline preview and testing.
  - UTC timestamp normalization and rate-limit error handling.
- **Procedural Property Customization**:
  - Deterministic property variations seeded from the user's stable numeric GitHub ID and username.
  - 4 curated architectural style palettes: Modern Minimalist, Warm Timber, Slate Stone, and Coastal White.
- **Graphics & Rendering Pipeline**:
  - Complete Blender 4.x Python scripts (`build_scene.py`, `materials.py`, `render_layers.py`) with PBR shaders.
  - High-performance headless Pillow compositor (< 200ms per run) for GitHub Actions.
  - 14 bundled high-resolution architectural layers and manifest at 1280x640 resolution.
  - Daytime sunlight and atmospheric dusk/night emissive lighting passes.
- **Self-Contained SVG & PNG Exporter**:
  - Standards-compliant, responsive SVG export (`viewBox="0 0 1280 640"`) with base64 embedded imagery.
  - Native vector HUD with glassmorphic backdrop, milestone progress bar, and contributions counter.
  - Pure-CSS declarative keyframe animations (pool caustics shimmer, breathing status indicator, warm window glow).
  - Accessibility compliant with `@media (prefers-reduced-motion: reduce)`, `<title>`, and `<desc>`.
  - PNG fallback exporter for environments that restrict SVG embedding.
- **Automation & CLI**:
  - Full-featured CLI: `init`, `validate`, `generate`, `demo`, `status`, `preview`.
  - Reusable GitHub Action (`action.yml`) with automated scheduling, minimal permissions, and atomic bot commits.
- **Testing & Documentation**:
  - 23 automated pytest tests covering progression, rendering, SVG compliance, state persistence, and CLI.
  - Visual regression fixtures covering 0 to 10,000 contributions.
  - Complete documentation suite in `docs/` and root repository guides.
