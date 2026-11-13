"""Blender headless batch renderer for BuildSite.

Renders isolated architectural construction layers and lighting passes
with transparent alpha background and consistent perspective alignment.
Run via:
    blender -b -P blender/scripts/render_layers.py -- --output-dir assets
"""

import json
import os
import sys
from pathlib import Path
import bpy

# Add script directory to sys.path
sys.path.append(str(Path(__file__).parent))
import build_scene
import materials


def configure_render_engine(width=1280, height=640, samples=64):
    """Configure Cycles or Eevee with transparency."""
    scene = bpy.context.scene
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"

    # Try Cycles if available, fallback to Eevee
    if "CYCLES" in bpy.context.preferences.addons:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_adaptive_sampling = True
    else:
        scene.render.engine = "BLENDER_EEVEE_NEXT" if hasattr(bpy.types, "RenderSettings") else "BLENDER_EEVEE"


def render_all_layers(output_base_dir: Path):
    """Render each architectural layer to disk."""
    output_base_dir.mkdir(parents=True, exist_ok=True)
    build_scene.build_full_scene()
    configure_render_engine()

    scene = bpy.context.scene
    objects = scene.objects

    # Define layer configurations (name -> list of objects to keep visible)
    layer_configs = {
        "plot_base": ["Ground_Plane"],
        "foundations": ["Ground_Plane", "Foundation_Slab"],
        "columns_beams": ["Ground_Plane", "Foundation_Slab", "Column_1", "Column_2", "Column_3", "Column_4", "Column_5", "Column_6"],
        "building_frame": ["Ground_Plane", "Foundation_Slab", "Villa_GF_Mass", "Villa_FF_Cantilever"],
        "roof_enclosure": ["Ground_Plane", "Villa_GF_Mass", "Villa_FF_Cantilever", "Villa_Glass_Facade"],
        "villa_finished": ["Ground_Plane", "Villa_GF_Mass", "Villa_FF_Cantilever", "Villa_Stone_Wall", "Villa_Timber_Louvers", "Villa_Glass_Facade"],
        "swimming_pool": ["Pool_Basin", "Pool_Water_Surface", "Pool_Teak_Deck"],
    }

    manifest = {"layers": {}}

    for layer_name, visible_objs in layer_configs.items():
        # Set visibility
        for obj in objects:
            if obj.type == "CAMERA" or obj.type == "LIGHT":
                obj.hide_render = False
            else:
                obj.hide_render = (obj.name not in visible_objs)

        out_path = output_base_dir / f"{layer_name}.png"
        scene.render.filepath = str(out_path)
        print(f"Rendering layer: {layer_name} -> {out_path}")
        bpy.ops.render.render(write_still=True)

        manifest["layers"][layer_name] = {
            "file": f"{layer_name}.png",
            "width": 1280,
            "height": 640,
            "order": len(manifest["layers"]) + 1
        }

    # Save manifest
    manifest_path = output_base_dir / "manifests" / "layer_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Rendered all layers and saved manifest to {manifest_path}")


if __name__ == "__main__":
    out_dir = Path("assets")
    render_all_layers(out_dir)
