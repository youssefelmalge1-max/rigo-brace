"""UI regression test for the Reusable Correction Styles workflow (#48).

Proves a user can create, commit, name, save, list, re-import, update and
delete a reusable correction THROUGH THE PANEL: it executes the real
_draw_guided_box code with a recording layout at every workflow state and
asserts which controls are emitted, their poll (enabled) state and the inline
reason labels — then walks the operators the buttons call.

Writes regionuitest_result.txt (last line PASS=True/False).  GUI only:
  & blender.exe --app-template rigo_brace --python tools\regionuitest.py
"""

import importlib
import traceback

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\regionuitest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []
_CHECKS = {}
_STYLE_LABEL = "QA UI Style"


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _check(name, ok, detail=""):
    _CHECKS[name] = bool(ok)
    _mark(f"CHECK {name}={'ok' if ok else 'FAIL'} {detail}")


class _Props:
    """Permissive stand-in for the operator-properties return of operator()."""

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


class _Rec:
    """Recording UILayout stand-in: every sub-layout shares one log."""

    def __init__(self, log):
        object.__setattr__(self, "log", log)

    def __getattr__(self, name):
        log = self.log

        def call(*args, **kwargs):
            if name == "operator" and args:
                log["ops"].append(args[0])
                return _Props()
            if name == "prop" and len(args) >= 2:
                log["props"].append(args[1])
            if name == "label":
                log["labels"].append(kwargs.get("text", args[0] if args else ""))
            if name == "template_list":
                log["lists"] += 1
            return _Rec(log)

        return call


def _draw_state(panels, context):
    log = {"ops": [], "props": [], "labels": [], "lists": 0}
    panels._draw_guided_box(_Rec(log), context)
    return log


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    panels = importlib.import_module("bl_ext.user_default.rigo_brace.ui.panels")
    region_library = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    context = bpy.context
    settings = context.scene.rigo_brace
    try:
        _mark("phase=start")

        # The guided box must be wired into the wizard's stage dispatch.
        wired = "_draw_guided_box" in panels._draw_mesh.__code__.co_names
        staged = panels._draw_mesh in panels._STAGE_DRAW.values()
        _check("stage_wiring", wired and staged,
               f"in_draw_mesh={wired} draw_mesh_staged={staged}")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = context.active_object
        settings.scan_object = scan
        context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        # ---- state 0: scan, no region ---- #
        log = _draw_state(panels, context)
        for op in (
            "rigo.region_add", "rigo.region_add_circle",
            "rigo.region_style_save", "rigo.region_style_import",
            "rigo.region_style_delete",
        ):
            _check(f"s0.visible.{op}", op in log["ops"])
        for propname in ("region_kind", "region_magnitude", "region_feather",
                         "region_falloff", "region_style"):
            _check(f"s0.prop.{propname}", propname in log["props"])
        _check(
            "s0.save_disabled_with_reason",
            not bpy.ops.rigo.region_style_save.poll()
            and any("Create or import a region" in t for t in log["labels"]),
            f"labels={[t for t in log['labels'] if 'region' in t.lower()]}",
        )
        # Import/Delete are enabled exactly when a real saved style is
        # selected (the user's library may already hold styles — reuse
        # without creating a region first is the point of the library).
        has_style = region_library.get_entry(settings.region_style) is not None
        _check(
            "s0.import_poll_matches_selection",
            bpy.ops.rigo.region_style_import.poll() == has_style,
            f"has_style={has_style}",
        )
        _check(
            "s0.delete_poll_matches_selection",
            bpy.ops.rigo.region_style_delete.poll() == has_style,
            f"has_style={has_style}",
        )

        # ---- state 1: create the correction (steps 1-2) ---- #
        seed = scan.data.vertices[9000]
        context.scene.cursor.location = scan.matrix_world @ seed.co
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 12.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        settings.region_radius = 30.0
        bpy.ops.rigo.region_add_circle()
        log = _draw_state(panels, context)
        _check("s1.region_list_shown", log["lists"] == 1)
        _check(
            "s1.save_visible_but_disabled",
            "rigo.region_style_save" in log["ops"]
            and not bpy.ops.rigo.region_style_save.poll()
            and any("Commit the region" in t for t in log["labels"]),
        )
        _check("s1.commit_visible", "rigo.region_apply" in log["ops"])

        # ---- state 2: commit (step 3) ---- #
        bpy.ops.rigo.region_apply()
        log = _draw_state(panels, context)
        _check(
            "s2.save_enabled",
            "rigo.region_style_save" in log["ops"]
            and bpy.ops.rigo.region_style_save.poll(),
        )
        _check(
            "s2.no_stale_reason",
            not any("Commit the region" in t for t in log["labels"]),
        )

        # ---- steps 4-5: name + save (the dialog's OK runs exactly this) ---- #
        st = bpy.ops.rigo.region_style_save(style_name=_STYLE_LABEL)
        style_id = settings.region_style
        entry = region_library.get_entry(style_id)
        _check(
            "s3.saved",
            st == {"FINISHED"} and entry is not None
            and entry["label"] == _STYLE_LABEL
            and abs(entry["magnitude_mm"] - 12.0) < 1e-6
            and entry.get("field") is not None
            and entry.get("schema_version") == 2,
            f"id={style_id}",
        )

        # ---- step 6: listed in the library enum ---- #
        items = region_library.enum_items(settings, context)
        _check(
            "s4.listed",
            any(item[0] == style_id and _STYLE_LABEL in item[1] for item in items),
            f"items={[i[1] for i in items]}",
        )

        # update semantics: re-saving the same name must NOT duplicate.
        count_before = len(region_library.load_library())
        bpy.ops.rigo.region_style_save(style_name=_STYLE_LABEL)
        _check(
            "s5.same_name_updates",
            len(region_library.load_library()) == count_before
            and settings.region_style == style_id,
        )

        # ---- step 7: import it again at the cursor ---- #
        # Vertex 20000 sits outside the committed footprint, but #49 commits
        # may renumber/densify — use a position captured NOW, not an index.
        context.scene.cursor.location = (
            scan.matrix_world @ scan.data.vertices[20000].co.copy()
        )
        regions_before = len(scan.rigo_regions)
        _check("s6.import_enabled", bpy.ops.rigo.region_style_import.poll())
        st = bpy.ops.rigo.region_style_import()
        imported = scan.rigo_regions[scan.rigo_region_index]
        _check(
            "s6.imported",
            st == {"FINISHED"}
            and len(scan.rigo_regions) == regions_before + 1
            and imported.name == _STYLE_LABEL
            and abs(imported.magnitude_mm - 12.0) < 1e-6
            and scan.modifiers.get(
                f"RIGO_REGION_PREVIEW_{imported.surface_mask}"
            ) is not None,
        )

        # ---- step 8: delete the saved style ---- #
        settings.region_style = style_id
        _check("s7.delete_enabled", bpy.ops.rigo.region_style_delete.poll())
        st = bpy.ops.rigo.region_style_delete()
        _check(
            "s7.deleted",
            st == {"FINISHED"} and region_library.get_entry(style_id) is None
            and all(
                item["label"] != _STYLE_LABEL
                for item in region_library.load_library(force=True)
            ),
        )

        failed = [k for k, v in _CHECKS.items() if not v]
        _mark(f"failed_checks={failed}")
        _mark(f"PASS={not failed and len(_CHECKS) > 15}")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    finally:
        for e in list(region_library.load_library(force=True)):
            if e.get("label") == _STYLE_LABEL:
                region_library.delete_entry(e["id"])
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
