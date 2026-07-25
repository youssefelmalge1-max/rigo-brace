"""Rigo Brace Designer — a Blender add-on for fast Rigo-Cheneau spinal brace design.

This package wires together the pipeline used by orthotists:
    Import scan -> Remesh -> Smooth -> Landmarks -> Thickness -> Trimlines ->
    Pads/Library -> Export print-ready brace.

Phase 0 (this build) provides the clean skeleton: a single tidy side panel that
walks through every stage with big buttons, plus working import / export and the
core mesh operations (remesh, smooth, thickness) and the anatomical landmark
system that the later design tools will be driven from.
"""

from . import core
from . import operators
from . import ui
from . import keymaps

# Modules whose register()/unregister() we fan out to, in order.
# keymaps must register after operators (it references their bl_idnames).
_MODULES = (core, operators, ui, keymaps)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
