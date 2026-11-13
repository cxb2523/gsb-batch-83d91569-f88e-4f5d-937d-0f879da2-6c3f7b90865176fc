# BuildSite Architecture & System Design

BuildSite translates verified GitHub contribution history into an evolving, photorealistic residential villa. This document details the software architecture, graphics pipeline, data flow, deterministic seed variation, and security principles.

---

## 1. High-Level System Architecture

```text
┌─────────────────────────┐
│   GitHub GraphQL/REST   │
│       API Engine        │
└────────────┬────────────┘
             │ (Verified Calendar, Commits, PRs, Issues)
             ▼
┌─────────────────────────┐
│  Contribution Normalizer │  --> UTC normalized, rate-limit resilient
└────────────┬────────────┘
             │ ContributionSnapshot
             ▼
┌─────────────────────────┐
│     Evolution Engine    │  --> Milestone specs, micro-evolution,
└────────────┬────────────┘      non-regression lock, feature unlocks
             │ PropertyState
             ▼
┌─────────────────────────┐
│ Procedural Variation    │  --> Deterministic SHA-256 hash
│      Generator          │      (materials, palette, flora, lighting)
└────────────┬────────────┘
             │
             ├────────────────────────────────┐
             ▼                                ▼
┌─────────────────────────┐      ┌─────────────────────────┐
│     Blender Pipeline    │      │    Fast User Compositor │
│ (Stage 1 - Offline Asset│      │ (Stage 2 - Headless CI) │
│  Generation & 3D PBR)   │      │ (Pillow + Alpha Passes) │
└────────────┬────────────┘      └────────────┬────────────┘
             │                                │
             └────────────────► Assets Dir ───┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │   SVG & Fallback Exporter │
                        │  (Self-Contained Base64   │
                        │   + Native Vector HUD     │
                        │   + CSS Keyframe Anims)   │
                        │  (1280x640 responsive)    │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ GitHub Action Git Commits │
                        │  Only commits on changes  │
                        └───────────────────────────┘
```

---

## 2. Two-Stage Graphics Pipeline

### Stage 1: Asset Production (Blender 4.x)
- Defined in `blender/scripts/build_scene.py` and `blender/scripts/materials.py`.
- Physically based materials (PBR): polished concrete, Low-E architectural glass, natural stone cladding, cedar timber slats, translucent turquoise pool water with Fresnel reflections.
- Camera: Elevated 3/4 perspective axonometric architectural view positioned at `(24.0, -28.0, 18.0)`.
- Renders isolated, transparency-masked layers with consistent lighting and shadow angles into `assets/`.
- Accompanied by `assets/builder.py` for procedural headless asset generation without local Blender binaries.

### Stage 2: Fast User Compositor (Pillow / Pure Python)
- Implemented in `src/buildsite/composer.py`.
- Reusable across GitHub Actions runners in < 200 milliseconds.
- Reads `assets/manifests/layer_manifest.json`.
- Layers are blended in strict architectural z-order (plot -> foundations -> framing -> villa -> pool -> gardens -> lighting).
- Evaluates lighting pass: Daytime (crisp sun) vs Dusk (twilight sky gradient, warm window emission, underwater pool LEDs, landscape ground uplights).

---

## 3. Real SVG Generation & Typography

- Standards-compliant `<svg>` with `viewBox="0 0 1280 640"`.
- Photographic rendering embedded as high-density `data:image/png;base64,...`.
- Restrained, modern architectural HUD:
  - Top-left card: Active construction project, status indicator, milestone progress bar, next unlock.
  - Top-right card: Verified contributions counter with subtle glassmorphic backdrop.
  - Bottom-right: Clean minimal tagline.
- Native typography using system UI fonts:
  `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`
  No external font web-requests, zero latency, zero layout shift.
- Declarative CSS keyframe animations:
  - Subtle glowing pulse on pool and architectural highlights.
  - Breathing dot on active construction indicator.
  - Strictly wrapped in `@media (prefers-reduced-motion: reduce)` to disable motion for sensitive users.
- Zero JavaScript, zero iframes, zero foreign objects.

---

## 4. Deterministic Procedural Variation

Every user gets a personalized property that remains stable across builds.
Derived from `SHA-256(user_id:login)`:
- Palette: Modern Minimalist, Contemporary Timber, Slate Stone, or Coastal White.
- Lighting: Correlated color temperature (2700K warm golden to 3800K gallery white).
- Landscaping flora: Mediterranean cypress, Japanese zen maple, or Nordic pine.
- Roof trim & pool water tint.

---

## 5. Security & Privacy Model

1. **Least Privilege**: The GitHub Action runs with only `contents: write` to commit the generated asset.
2. **Safe Input Sanitization**: Config values are parsed strictly; output paths outside the repository are rejected.
3. **No Secret Leaks**: Tokens are passed only to GitHub's official API in HTTP headers; never echoed or embedded in SVG or logs.
4. **No-Op Commits**: An atomic state file (`buildsite_state.json`) with cryptographic hash signatures prevents unnecessary commits when contribution data is unchanged.
