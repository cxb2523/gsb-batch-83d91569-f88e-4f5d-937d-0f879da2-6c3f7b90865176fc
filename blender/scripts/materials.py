"""Blender shader and material generator for BuildSite architectural scene.

Creates physically-based materials (PBR) for concrete, glass, natural stone,
cedar timber, water surface, pool tiles, and architectural lighting emitters.
Compatible with Blender 4.x Cycles and Eevee Next.
"""

import bpy


def clean_materials():
    """Remove unused materials."""
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)


def create_pbr_material(name: str, color=(0.8, 0.8, 0.8, 1.0), roughness=0.5, metallic=0.0, specular=0.5):
    """Create standard Principled BSDF material."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = specular
        elif "Specular" in bsdf.inputs:
            bsdf.inputs["Specular"].default_value = specular
    return mat


def create_concrete_material():
    """Architectural polished concrete with subtle roughness variation."""
    mat = create_pbr_material("Concrete_Structural", color=(0.78, 0.80, 0.82, 1.0), roughness=0.65)
    return mat


def create_white_plaster_material():
    """Smooth architectural white mineral plaster."""
    mat = create_pbr_material("Plaster_Mineral_White", color=(0.95, 0.95, 0.96, 1.0), roughness=0.45)
    return mat


def create_cedar_timber_material():
    """Warm architectural cedar timber slats."""
    mat = create_pbr_material("Timber_Cedar", color=(0.55, 0.35, 0.22, 1.0), roughness=0.38)
    return mat


def create_stone_cladding_material():
    """Natural dark slate stone cladding."""
    mat = create_pbr_material("Stone_Slate", color=(0.28, 0.30, 0.33, 1.0), roughness=0.75)
    return mat


def create_glass_material():
    """Architectural Low-E architectural architectural glass."""
    mat = bpy.data.materials.new(name="Glass_Architectural")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    glass = nodes.new("ShaderNodeBsdfGlass")
    glass.inputs["Color"].default_value = (0.85, 0.95, 1.0, 1.0)
    glass.inputs["Roughness"].default_value = 0.02
    glass.inputs["IOR"].default_value = 1.52
    mat.node_tree.links.new(glass.outputs["BSDF"], output.inputs["Surface"])
    mat.blend_method = "BLEND" if hasattr(mat, "blend_method") else None
    return mat


def create_pool_water_material():
    """Translucent swimming pool water with cyan absorption."""
    mat = bpy.data.materials.new(name="Water_Pool_Azure")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    glass = nodes.new("ShaderNodeBsdfGlass")
    glass.inputs["Color"].default_value = (0.15, 0.75, 0.90, 1.0)
    glass.inputs["Roughness"].default_value = 0.05
    glass.inputs["IOR"].default_value = 1.333
    mat.node_tree.links.new(glass.outputs["BSDF"], output.inputs["Surface"])
    return mat


def create_emissive_light_material(name: str, color=(1.0, 0.85, 0.60, 1.0), strength=15.0):
    """Interior warm light and exterior spotlight emissive material."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = strength
    mat.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def setup_all_materials():
    """Generate and return all materials for the scene."""
    return {
        "concrete": create_concrete_material(),
        "plaster": create_white_plaster_material(),
        "timber": create_cedar_timber_material(),
        "stone": create_stone_cladding_material(),
        "glass": create_glass_material(),
        "water": create_pool_water_material(),
        "interior_light": create_emissive_light_material("Light_Interior_Warm", (1.0, 0.88, 0.65, 1.0), strength=12.0),
        "pool_light": create_emissive_light_material("Light_Pool_LED", (0.2, 0.9, 1.0, 1.0), strength=20.0),
        "landscape_light": create_emissive_light_material("Light_Spotlight_Warm", (1.0, 0.9, 0.7, 1.0), strength=18.0),
    }
