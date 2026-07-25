"""Shared installed-copy fixture for the unified A-brace workflow tests."""

import collections

import bpy


A_SCAN = r"C:\Projects\Blender Add-on Braces\A type model.stl"
B_SCAN = r"C:\Projects\Blender Add-on Braces\B type model.stl"


def _place(settings, landmark, location):
    settings.active_landmark = landmark
    bpy.context.scene.cursor.location = location
    bpy.ops.rigo.place_landmark()


def _fixture_landmarks(scan):
    coordinates = [vertex.co for vertex in scan.data.vertices]
    z_min = min(co.z for co in coordinates)
    z_max = max(co.z for co in coordinates)
    x_min, x_max = min(co.x for co in coordinates), max(co.x for co in coordinates)
    y_min, y_max = min(co.y for co in coordinates), max(co.y for co in coordinates)
    center_x, center_y = (x_min + x_max) * 0.5, (y_min + y_max) * 0.5
    slabs = collections.defaultdict(list)
    for coordinate in coordinates:
        slabs[round(coordinate.z / 0.01)].append(coordinate)
    middle_slabs = (
        (key * 0.01, slab)
        for key, slab in slabs.items()
        if z_min + 0.25 * (z_max - z_min) < key * 0.01 < z_min + 0.75 * (z_max - z_min)
    )
    waist_z = min(
        middle_slabs,
        key=lambda pair: max(co.x for co in pair[1]) - min(co.x for co in pair[1]),
    )[0]
    return {
        "TROCHANTER_L": (center_x - 0.10, center_y, z_min + 0.02),
        "TROCHANTER_R": (center_x + 0.10, center_y, z_min + 0.02),
        "WAISTLINE": (center_x, center_y, waist_z),
        "ACROMION_L": (center_x - 0.08, center_y, z_max - 0.015),
        "ACROMION_R": (center_x + 0.08, center_y, z_max - 0.015),
        "ASIS_L": (center_x - 0.05, y_min + 0.25 * (y_max - y_min), z_min + 0.06),
        "ASIS_R": (center_x + 0.05, y_min + 0.25 * (y_max - y_min), z_min + 0.06),
        "PSIS_L": (center_x - 0.04, y_max - 0.25 * (y_max - y_min), z_min + 0.08),
        "PSIS_R": (center_x + 0.04, y_max - 0.25 * (y_max - y_min), z_min + 0.08),
    }


def prepare_design(scan_path, trim_type, opening_width=40.0):
    bpy.ops.wm.stl_import(filepath=scan_path)
    scan = bpy.context.object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = scan
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    for landmark, location in _fixture_landmarks(scan).items():
        _place(settings, landmark, location)
    settings.trim_type = trim_type
    settings.opening_width = opening_width
    bpy.ops.rigo.auto_trimline()
    return scan, settings


def prepare_a_design():
    return prepare_design(A_SCAN, "A")


def prepare_b_design():
    return prepare_design(B_SCAN, "B")


def prepare_reference_design():
    return prepare_design(A_SCAN, "RIGO_CHENEAU", opening_width=25.0)
