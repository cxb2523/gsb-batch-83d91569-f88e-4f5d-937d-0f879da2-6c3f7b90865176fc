# Contributing Architectural & Graphics Assets

BuildSite welcomes 3D artists, architectural visualizers, and graphics engineers. This guide explains the technical standards for contributing new 3D models, textures, layers, and lighting passes.

---

## 1. Architectural Standards

- **Style**: Contemporary luxury residential architecture (modernist, cantilevered concrete, timber accents, clean horizontal geometry, floor-to-ceiling glass).
- **Proportions**: Physically plausible dimensions (3.2m floor heights, 20-30cm structural slabs, 12-15m building spans).
- **Plausibility**: No floating disconnected geometry, impossible structural cantilevers, or cartoon textures.

---

## 2. Fixed Camera & Projection System

To ensure all modular construction layers composite with sub-pixel alignment, every render layer must adhere to the standard camera setup:

```python
# Blender Camera Setup
cam_data = bpy.data.cameras.new(name="ArchCamera")
cam_data.lens = 58.0
cam_data.sensor_width = 36.0
cam_obj.location = (24.0, -28.0, 18.0)
cam_obj.rotation_euler = (math.radians(62.0), 0.0, math.radians(40.0))
```

- Resolution: **1280 × 640 px**
- Color Profile: **sRGB**
- Format: **PNG with 8-bit Alpha Channel (RGBA)**

---

## 3. Lighting Standards

- **Main Sun (Daytime)**:
  - Energy: 4.5
  - Color: (1.0, 0.96, 0.92)
  - Sun Angle: 1.5° (soft shadow edges)
  - Rotation: (45°, 25°, 65°)
- **Dusk / Emissive Pass**:
  - Rendered against black/transparent background.
  - Windows: Emissive Principled BSDF with warm 2700K color (1.0, 0.85, 0.60) and 12-18 strength.
  - Pool LEDs: (0.1, 0.9, 1.0) with subtle caustic transmission.

---

## 4. Layer Manifest Integration

Every new asset must be registered in `assets/manifests/layer_manifest.json`:

```json
{
  "layers": {
    "your_new_layer": {
      "file": "architecture/your_new_layer.png",
      "order": 14,
      "width": 1280,
      "height": 640
    }
  }
}
```

---

## 5. Automated Headless Verification

Before submitting a Pull Request, verify your changes with the test suite:

```bash
python assets/builder.py
buildsite validate
pytest
```
