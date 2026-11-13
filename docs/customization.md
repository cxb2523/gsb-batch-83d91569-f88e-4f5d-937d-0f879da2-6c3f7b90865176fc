# Customization & Configuration Reference

BuildSite is configured via `buildsite.yml` in the root of your repository or CLI flags.

---

## Configuration Schema

```yaml
version: 1

github:
  username: "your-github-username"
  visibility: "public" # public | private

property:
  style: "modern"      # modern | timber | slate | coastal | auto
  seed: "auto"         # "auto" uses numeric user_id, or specify a custom string
  palette: "natural"
  pool: true           # toggle swimming pool unlock
  garden: true         # toggle garden landscaping
  garage: true         # toggle driveway and garage
  lighting: "dusk"     # dusk | daytime | night

render:
  width: 1280
  height: 640
  format: "svg"        # svg | png
  quality: "high"
  animation: "subtle"  # subtle | none
  png_fallback: true

progression:
  mode: "continuous"
  preserve_unlocks: true # prevents accidental loss if contributions temporarily drop

output:
  directory: "assets/buildsite"
  png_fallback: true
```

---

## Architectural Styles

| Style | Description | Accent Material | Pool Tone | Vegetation |
|---|---|---|---|---|
| `modern` | Ultra-Modern Minimalist Villa | Black anodized steel & concrete | Turquoise | Mediterranean Cypress |
| `timber` | Contemporary Timber & Glass Villa | Architectural Cedar slats | Azure Blue | Japanese Zen Flora |
| `slate` | Cantilevered Stone Villa | Natural dark slate feature wall | Deep Alpine Blue | Nordic Pine |
| `coastal` | Coastal Horizon Residence | Teak decking & white trim | Caribbean Cyan | Lush Temperate |
| `auto` | Deterministically derived from your GitHub account ID | Varies | Varies | Varies |

---

## Lighting Ambience

- **`dusk` (Default & Recommended)**: Twilight ambiance with warm 2700K interior lighting shining through panoramic glazing, submerged turquoise LED pool illumination, outdoor pendant lights, and cypress tree spotlights.
- **`daytime`**: Bright Mediterranean sunlight with sharp architectural shadows and clear azure sky.
- **`night`**: Dramatic high-contrast nocturnal architectural rendering.

---

## Animation Settings

- **`subtle` (Default)**: Pure-CSS declarative keyframe effects. Subtle caustics shimmer on pool water, soft breathing pulse on lights and active status indicator.
- **`none`**: Completely static rendering with zero animations.
- **Accessibility**: When the client device has "Reduce Motion" enabled in system settings, all animations are automatically disabled via `@media (prefers-reduced-motion: reduce)`.
