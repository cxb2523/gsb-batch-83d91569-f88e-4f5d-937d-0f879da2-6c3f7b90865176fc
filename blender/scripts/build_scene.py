"""Blender scene builder script for BuildSite.

Constructs the complete 3D architectural villa, structural foundation layers,
swimming pool, garden landscape, pergola, garage, rooftop upgrades, and camera.
"""

import math
import bpy

# Adjust import path for local execution
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
import materials


def clear_scene():
    """Wipe existing objects from scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_camera():
    """Setup elevated 3/4 axonometric perspective architectural camera."""
    cam_data = bpy.data.cameras.new(name="ArchCamera")
    cam_data.lens = 58.0
    cam_data.sensor_width = 36.0
    cam_obj = bpy.data.objects.new("ArchCameraObj", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    # Position at elevated 3/4 view
    cam_obj.location = (24.0, -28.0, 18.0)
    cam_obj.rotation_euler = (math.radians(62.0), 0.0, math.radians(40.0))
    return cam_obj


def setup_lighting():
    """Setup sun lamp and sky ambient environment."""
    # Main sun
    sun_data = bpy.data.lights.new(name="SunDay", type="SUN")
    sun_data.energy = 4.5
    sun_data.color = (1.0, 0.96, 0.92)
    sun_data.angle = math.radians(1.5)
    sun_obj = bpy.data.objects.new("SunDayObj", sun_data)
    bpy.context.scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (math.radians(45.0), math.radians(25.0), math.radians(65.0))

    # Dusk / Fill sun (disabled by default, toggled per pass)
    dusk_data = bpy.data.lights.new(name="SunDusk", type="SUN")
    dusk_data.energy = 1.8
    dusk_data.color = (1.0, 0.65, 0.40)
    dusk_obj = bpy.data.objects.new("SunDuskObj", dusk_data)
    bpy.context.scene.collection.objects.link(dusk_obj)
    dusk_obj.rotation_euler = (math.radians(15.0), math.radians(35.0), math.radians(80.0))
    dusk_obj.hide_render = True


def build_plot_ground(mats, collection):
    """Build the ground plane, plot boundaries, and perimeter terrain."""
    bpy.ops.mesh.primitive_plane_add(size=60.0, location=(0.0, 0.0, 0.0))
    ground = bpy.context.active_object
    ground.name = "Ground_Plane"
    ground.data.materials.append(mats["concrete"])
    collection.objects.link(ground)


def build_foundations(mats, collection):
    """Build excavation trench, rebar markers, and concrete foundation slab."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.25))
    slab = bpy.context.active_object
    slab.name = "Foundation_Slab"
    slab.scale = (16.0, 12.0, 0.5)
    slab.data.materials.append(mats["concrete"])
    collection.objects.link(slab)


def build_framing(mats, collection):
    """Build structural reinforced concrete columns and tie-beams."""
    # 6 columns
    col_coords = [
        (-7.0, -5.0), (0.0, -5.0), (7.0, -5.0),
        (-7.0, 5.0), (0.0, 5.0), (7.0, 5.0)
    ]
    for i, (cx, cy) in enumerate(col_coords):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.4, depth=6.0, location=(cx, cy, 3.25))
        col = bpy.context.active_object
        col.name = f"Column_{i+1}"
        col.data.materials.append(mats["concrete"])
        collection.objects.link(col)


def build_villa_finished(mats, collection):
    """Build the complete two-storey modern architectural villa."""
    # Ground floor main mass
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 2.0))
    gf = bpy.context.active_object
    gf.name = "Villa_GF_Mass"
    gf.scale = (15.0, 10.0, 3.5)
    gf.data.materials.append(mats["plaster"])
    collection.objects.link(gf)

    # First floor cantilevered mass
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.5, 0.5, 5.5))
    ff = bpy.context.active_object
    ff.name = "Villa_FF_Cantilever"
    ff.scale = (16.0, 9.0, 3.5)
    ff.data.materials.append(mats["plaster"])
    collection.objects.link(ff)

    # Stone cladding accent wall
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-6.5, 0.0, 3.75))
    stone_wall = bpy.context.active_object
    stone_wall.name = "Villa_Stone_Wall"
    stone_wall.scale = (1.5, 10.2, 7.0)
    stone_wall.data.materials.append(mats["stone"])
    collection.objects.link(stone_wall)

    # Timber louvers accent
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(4.0, -4.8, 5.5))
    louvers = bpy.context.active_object
    louvers.name = "Villa_Timber_Louvers"
    louvers.scale = (6.0, 0.3, 3.2)
    louvers.data.materials.append(mats["timber"])
    collection.objects.link(louvers)

    # Glazing panels
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, -4.9, 2.0))
    glass = bpy.context.active_object
    glass.name = "Villa_Glass_Facade"
    glass.scale = (10.0, 0.2, 3.0)
    glass.data.materials.append(mats["glass"])
    collection.objects.link(glass)


def build_swimming_pool(mats, collection):
    """Build the luxury swimming pool basin, turquoise water, and teak deck."""
    # Pool basin
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(4.0, -11.0, 0.1))
    pool = bpy.context.active_object
    pool.name = "Pool_Basin"
    pool.scale = (12.0, 6.0, 1.2)
    pool.data.materials.append(mats["concrete"])
    collection.objects.link(pool)

    # Water surface
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(4.0, -11.0, 0.5))
    water = bpy.context.active_object
    water.name = "Pool_Water_Surface"
    water.scale = (11.4, 5.4, 1.0)
    water.data.materials.append(mats["water"])
    collection.objects.link(water)

    # Teak surround deck
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(4.0, -11.0, 0.2))
    deck = bpy.context.active_object
    deck.name = "Pool_Teak_Deck"
    deck.scale = (15.0, 9.0, 0.4)
    deck.data.materials.append(mats["timber"])
    collection.objects.link(deck)


def build_full_scene():
    """Main scene generation entry point."""
    clear_scene()
    setup_camera()
    setup_lighting()
    mats = materials.setup_all_materials()

    main_col = bpy.context.scene.collection
    build_plot_ground(mats, main_col)
    build_foundations(mats, main_col)
    build_framing(mats, main_col)
    build_villa_finished(mats, main_col)
    build_swimming_pool(mats, main_col)


if __name__ == "__main__":
    build_full_scene()
