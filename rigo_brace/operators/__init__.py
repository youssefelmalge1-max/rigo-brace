"""All operators for the Rigo Brace pipeline."""

from . import ui_ops
from . import history_ops
from . import qa_ops
from . import io_ops
from . import scan_ops
from . import clean_ops
from . import mesh_ops
from . import landmark_ops
from . import remold_ops
from . import deform_ops
from . import pad_ops
from . import correction_ops
from . import design_ops
from . import select_ops
from . import region_ops
from . import lattice_ops
from . import trim_ops
from . import vent_ops
from . import rivet_ops
from . import pattern_ops
from . import trimline_ops
from . import custom_trim_ops
from . import trimsmooth_ops
from . import trimverify_ops
from . import curve_build_ops

_MODULES = (
    ui_ops,
    history_ops,
    qa_ops,
    io_ops,
    scan_ops,
    clean_ops,
    mesh_ops,
    landmark_ops,
    remold_ops,
    deform_ops,
    pad_ops,
    correction_ops,
    design_ops,
    select_ops,
    region_ops,
    lattice_ops,
    trim_ops,
    vent_ops,
    rivet_ops,
    pattern_ops,
    trimline_ops,
    custom_trim_ops,
    trimsmooth_ops,
    trimverify_ops,
    curve_build_ops,
)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
