"""VisualARQ BIM tools — styles, walls, openings, hierarchy, and IFC.

Every tool degrades gracefully when VisualARQ is not installed: the
response carries `available: false` plus a hint instead of crashing.
Check `va_status` first.
"""
import json
import math
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok
from rhinoclaw.utils.visualarq import run_va, va_unavailable, warm_va

_UNAVAILABLE_HINT = (
    "VisualARQ is not loaded in the connected Rhino. Install/enable the "
    "VisualARQ plugin (visualarq.com), restart Rhino, then re-run va_status."
)

IfcSchema = Literal["IFC4", "IFC2x3"]
SlabAlignment = Literal["top", "center", "bottom"]
VisualArqObjectKind = Literal[
    "all", "wall", "door", "window", "column", "beam", "slab",
    "stair", "railing", "roof", "curtain_wall", "opening", "space",
    "section", "generic_element", "element", "furniture", "product",
    "building_element",
]
_VA_OBJECT_KINDS = {
    "all", "wall", "door", "window", "column", "beam", "slab",
    "stair", "railing", "roof", "curtain_wall", "opening", "space",
    "section", "generic_element", "element", "furniture", "product",
    "building_element",
}


_STYLE_SCRIPT_HELPERS = r"""
def va_style_ids(kind):
    inventory_methods = {
        "wall": "GetAllWallStyleIds",
        "door": "GetAllDoorStyleIds",
        "window": "GetAllWindowStyleIds",
        "slab": "GetAllSlabStyleIds",
        "space": "GetAllSpaceStyleIds",
    }
    method_name = inventory_methods.get(kind)
    if method_name is None or not va_method_available(method_name):
        return []
    return list(getattr(va, method_name)() or [])

def va_style_kind(style_id):
    # `Is*Style` classifies GUID shape even after deletion in VA 3.7.2.
    # Membership in the per-kind document inventory is authoritative.
    errors = []
    matches = []
    for kind in ["wall", "door", "window", "slab", "space"]:
        try:
            if style_id in va_style_ids(kind):
                matches.append(kind)
        except Exception as error:
            errors.append(kind + ": " + va_text(error))
    if errors:
        raise Exception(
            "VisualARQ style inventory could not be read: " +
            "; ".join(errors))
    if len(matches) > 1:
        raise Exception(
            "VisualARQ style Guid belongs to multiple kind inventories: " +
            ", ".join(matches))
    if len(matches) == 1:
        return matches[0]
    return None

def va_style_component_name(component_id):
    try:
        if va_method_available("GetStyleComponentName"):
            value = va.GetStyleComponentName(component_id)
            if value is not None:
                return va_text(value)
    except Exception:
        pass
    return None

def va_style_presence(style_id, expected_kind=None):
    # Tri-state: True/False are inventory-proven, None means unreadable.
    try:
        kinds = [expected_kind] if expected_kind is not None \
            else ["wall", "door", "window", "slab", "space"]
        for kind in kinds:
            if style_id in va_style_ids(kind):
                return True
        return False
    except Exception:
        return None

def va_valid_double(value):
    try:
        if Rhino.RhinoMath.IsValidDouble(value):
            normalized = float(value)
            # VisualARQ 3.7.2 uses approximately -1e307 as its unset/
            # inherited-value sentinel. RhinoMath considers it finite, but it
            # is not a document measurement and must never escape as one.
            if abs(normalized) < 1e300:
                return normalized
    except Exception:
        pass
    return None

def va_resolve_style(reference, expected_kind):
    text = va_text(reference).Trim() if reference is not None else ""
    inventory_methods = {
        "wall": "GetAllWallStyleIds",
        "door": "GetAllDoorStyleIds",
        "window": "GetAllWindowStyleIds",
        "slab": "GetAllSlabStyleIds",
        "space": "GetAllSpaceStyleIds",
    }
    expected_inventory_method = inventory_methods.get(expected_kind)
    missing_inventory_methods = [
        expected_inventory_method
        for method_name in [expected_inventory_method]
        if method_name is None or not va_method_available(method_name)
    ]
    if missing_inventory_methods:
        return None, {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "message": "VisualARQ style inventory API is incomplete",
            "missing_methods": missing_inventory_methods,
        }
    candidate_id = Guid.Empty
    try:
        candidate_id = Guid(text)
    except Exception:
        pass
    if candidate_id != Guid.Empty:
        try:
            actual_kind = va_style_kind(candidate_id)
        except Exception as error:
            return None, {
                "status": "error", "code": "VERIFICATION_FAILED",
                "message": "Style GUID ownership is not unique",
                "style_id": str(candidate_id),
                "error": va_text(error),
            }
        if actual_kind == expected_kind:
            return candidate_id, None
        return None, {
            "status": "error", "code": "INVALID_ID",
            "message": "Style GUID is not a " + expected_kind + " style",
            "style_id": str(candidate_id), "actual_kind": actual_kind,
        }

    if not va_method_available("GetStyleName"):
        return None, {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "message": "VisualARQ style-name lookup is unavailable",
            "missing_methods": ["GetStyleName"],
        }
    exact_matches = []
    folded_matches = []
    name_read_errors = []
    for style_id in va_style_ids(expected_kind):
        try:
            style_name = va_text(va.GetStyleName(style_id))
            if style_name == text:
                exact_matches.append(style_id)
            if va_text_key(style_name) == va_text_key(text):
                folded_matches.append(style_id)
        except Exception as name_error:
            name_read_errors.append({
                "style_id": str(style_id),
                "error": va_text(name_error),
            })
    matches = exact_matches if len(exact_matches) > 0 else folded_matches
    if name_read_errors:
        return None, {
            "status": "error", "code": "VERIFICATION_FAILED",
            "message": (
                "Style name resolution is incomplete; pass a style GUID"),
            "reference": text,
            "readable_candidates": [str(style_id) for style_id in matches],
            "name_read_errors": name_read_errors,
        }
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, {
            "status": "error", "code": "AMBIGUOUS_REFERENCE",
            "message": "Style name is ambiguous; pass a style GUID",
            "reference": text,
            "candidates": [str(style_id) for style_id in matches],
        }
    return None, {
        "status": "error", "code": "INVALID_ID",
        "message": expected_kind.capitalize() + " style not found: " + text,
        "reference": text,
    }

def va_wall_layer_snapshot(layer_id):
    errors = []
    layer_type = None
    wrapping = None
    thickness = None
    try:
        layer_type = va.GetWallLayerType(layer_id)
    except Exception as error:
        errors.append({"method": "GetWallLayerType", "error": va_text(error)})
    try:
        wrapping = va.GetWallLayerWrapping(layer_id)
    except Exception as error:
        errors.append({
            "method": "GetWallLayerWrapping", "error": va_text(error)})
    try:
        thickness = va_valid_double(va.GetWallLayerThickness(layer_id))
        if thickness is None:
            errors.append({
                "method": "GetWallLayerThickness",
                "error": "invalid or unset measurement",
            })
    except Exception as error:
        errors.append({
            "method": "GetWallLayerThickness", "error": va_text(error)})
    type_value = int(layer_type) if layer_type is not None else None
    wrapping_value = int(wrapping) if wrapping is not None else None
    type_name = "normal" if type_value == 0 else \
        ("core" if type_value == 1 else "unknown")
    component_name = va_style_component_name(layer_id)
    if component_name is None:
        errors.append({
            "method": "GetStyleComponentName",
            "error": "component name is unavailable",
        })
    snapshot = {
        "id": str(layer_id),
        "name": component_name,
        "thickness": thickness,
        "type": type_name,
        "type_value": type_value,
        "wrapping": {
            "ends": bool(wrapping_value & 1) \
                if wrapping_value is not None else None,
            "openings": bool(wrapping_value & 2) \
                if wrapping_value is not None else None,
            "value": wrapping_value,
        },
        "readback_errors": errors,
    }
    snapshot["readback_complete"] = len(errors) == 0
    return snapshot

def va_wall_layer_ids(style_id):
    reported_ids = []
    subcomponent_ids = []
    reported_error = None
    subcomponent_error = None
    reported_attempted = va_method_available("GetWallLayers")
    subcomponent_attempted = \
        va_method_available("GetSubStyleComponents") and \
        va_method_available("IsWallLayer")
    reported_succeeded = False
    subcomponent_succeeded = False
    try:
        if reported_attempted:
            reported_ids = list(va.GetWallLayers(style_id) or [])
            reported_succeeded = True
        else:
            reported_error = "method unavailable"
    except Exception as error:
        reported_error = va_text(error)
    try:
        if subcomponent_attempted:
            subcomponent_ids = [
                component_id
                for component_id in list(
                    va.GetSubStyleComponents(style_id) or [])
                if va.IsWallLayer(component_id)
            ]
            subcomponent_succeeded = True
        else:
            subcomponent_error = "method unavailable"
    except Exception as error:
        subcomponent_error = va_text(error)
    reported_text = [str(value) for value in reported_ids]
    subcomponent_text = [str(value) for value in subcomponent_ids]
    sources_agree = reported_text == subcomponent_text \
        if reported_succeeded and subcomponent_succeeded else None
    conflicting_nonempty_sources = reported_succeeded and \
        subcomponent_succeeded and bool(reported_ids) and \
        bool(subcomponent_ids) and not sources_agree
    if conflicting_nonempty_sources:
        ids = []
        source = None
    elif subcomponent_succeeded and subcomponent_ids:
        ids = subcomponent_ids
        source = "GetSubStyleComponents"
    elif reported_succeeded and reported_ids:
        ids = reported_ids
        source = "GetWallLayers"
    elif subcomponent_succeeded:
        ids = subcomponent_ids
        source = "GetSubStyleComponents"
    elif reported_succeeded:
        ids = reported_ids
        source = "GetWallLayers"
    else:
        ids = []
        source = None
    read_complete = (reported_succeeded or subcomponent_succeeded) and \
        not conflicting_nonempty_sources
    return {
        "ids": ids, "source": source,
        "read_complete": read_complete,
        "conflicting_nonempty_sources": conflicting_nonempty_sources,
        "get_wall_layers_attempted": reported_attempted,
        "get_wall_layers_succeeded": reported_succeeded,
        "subcomponents_attempted": subcomponent_attempted,
        "subcomponents_succeeded": subcomponent_succeeded,
        "get_wall_layers_ids": reported_text,
        "subcomponent_ids": subcomponent_text,
        "sources_agree": sources_agree,
        "get_wall_layers_error": reported_error,
        "subcomponent_error": subcomponent_error,
    }

def va_slab_layer_snapshot(layer_id):
    errors = []
    layer_type = None
    thickness = None
    try:
        layer_type = va.GetSlabLayerType(layer_id)
    except Exception as error:
        errors.append({
            "method": "GetSlabLayerType", "error": va_text(error)})
    try:
        thickness = va_valid_double(va.GetSlabLayerThickness(layer_id))
        if thickness is None:
            errors.append({
                "method": "GetSlabLayerThickness",
                "error": "invalid or unset measurement",
            })
    except Exception as error:
        errors.append({
            "method": "GetSlabLayerThickness", "error": va_text(error)})
    component_name = va_style_component_name(layer_id)
    if component_name is None:
        errors.append({
            "method": "GetStyleComponentName",
            "error": "component name is unavailable",
        })
    type_text = va_text(layer_type) if layer_type is not None else None
    type_key = type_text.Trim().ToLowerInvariant() \
        if type_text is not None else None
    if type_key is not None and type_key.EndsWith(".normal"):
        type_key = "normal"
    elif type_key is not None and type_key.EndsWith(".core"):
        type_key = "core"
    type_name = type_key if type_key in ["normal", "core"] else "unknown"
    snapshot = {
        "id": str(layer_id),
        "name": component_name,
        "thickness": thickness,
        "type": type_name if layer_type is not None else None,
        "type_raw": type_text,
        "type_value": int(layer_type) if layer_type is not None else None,
        "readback_errors": errors,
    }
    snapshot["readback_complete"] = len(errors) == 0
    return snapshot

def va_slab_layer_ids(style_id):
    # VA 3.7.2 can report an empty GetSlabLayers result even though the typed
    # layer is present. The typed subcomponent inventory is the proven
    # fallback; disagreeing non-empty sources fail closed.
    reported_ids = []
    subcomponent_ids = []
    reported_error = None
    subcomponent_error = None
    reported_attempted = va_method_available("GetSlabLayers")
    subcomponent_attempted = \
        va_method_available("GetSubStyleComponents") and \
        va_method_available("IsSlabLayer")
    reported_succeeded = False
    subcomponent_succeeded = False
    try:
        if reported_attempted:
            reported_ids = list(va.GetSlabLayers(style_id) or [])
            reported_succeeded = True
        else:
            reported_error = "method unavailable"
    except Exception as error:
        reported_error = va_text(error)
    try:
        if subcomponent_attempted:
            subcomponent_ids = [
                component_id
                for component_id in list(
                    va.GetSubStyleComponents(style_id) or [])
                if va.IsSlabLayer(component_id)
            ]
            subcomponent_succeeded = True
        else:
            subcomponent_error = "method unavailable"
    except Exception as error:
        subcomponent_error = va_text(error)
    reported_text = [str(value) for value in reported_ids]
    subcomponent_text = [str(value) for value in subcomponent_ids]
    sources_agree = reported_text == subcomponent_text \
        if reported_succeeded and subcomponent_succeeded else None
    conflicting_nonempty_sources = reported_succeeded and \
        subcomponent_succeeded and bool(reported_ids) and \
        bool(subcomponent_ids) and not sources_agree
    if conflicting_nonempty_sources:
        ids = []
        source = None
    elif subcomponent_succeeded and subcomponent_ids:
        ids = subcomponent_ids
        source = "GetSubStyleComponents"
    elif reported_succeeded and reported_ids:
        ids = reported_ids
        source = "GetSlabLayers"
    elif subcomponent_succeeded:
        ids = subcomponent_ids
        source = "GetSubStyleComponents"
    elif reported_succeeded:
        ids = reported_ids
        source = "GetSlabLayers"
    else:
        ids = []
        source = None
    read_complete = (reported_succeeded or subcomponent_succeeded) and \
        not conflicting_nonempty_sources
    return {
        "ids": ids, "source": source,
        "read_complete": read_complete,
        "conflicting_nonempty_sources": conflicting_nonempty_sources,
        "get_slab_layers_attempted": reported_attempted,
        "get_slab_layers_succeeded": reported_succeeded,
        "subcomponents_attempted": subcomponent_attempted,
        "subcomponents_succeeded": subcomponent_succeeded,
        "get_slab_layers_ids": reported_text,
        "subcomponent_ids": subcomponent_text,
        "sources_agree": sources_agree,
        "get_slab_layers_error": reported_error,
        "subcomponent_error": subcomponent_error,
    }

def va_global_style_inventory():
    # Discover every installed public style inventory. This avoids proving
    # ownership only inside the target wall style while a returned Guid may
    # already belong to another VisualARQ style or component kind.
    errors = []
    inventory_methods = set()
    beam_inventory_name = "GetAllBeamStyle"
    beam_inventory_aliases = ["GetAllBeamStyleIds"]
    try:
        method_flags = System.Reflection.BindingFlags.Public | \
            System.Reflection.BindingFlags.Static | \
            System.Reflection.BindingFlags.DeclaredOnly
        for reflected_type in va_assembly.GetTypes():
            for method in reflected_type.GetMethods(method_flags):
                name = str(method.Name)
                if name.startswith("GetAll") and \
                        name.endswith("StyleIds") and \
                        name not in beam_inventory_aliases and \
                        len(method.GetParameters()) == 0 and \
                        not method.IsGenericMethod and \
                        not method.ContainsGenericParameters:
                    inventory_methods.add(name)
    except Exception as error:
        errors.append({
            "stage": "reflection", "error": va_text(error)})

    # VisualARQ 3.7.2 exposes beams through the historical singularly named
    # `Guid[] GetAllBeamStyle()` API. It does not match GetAll*StyleIds, so it
    # must be admitted explicitly and only after an exact CLR-shape check.
    # A similarly named plural alias is deliberately not accepted here: this
    # global mutation guard is version-pinned and must fail closed on API
    # drift rather than silently reducing its ownership coverage.
    beam_inventory_shape = None
    beam_inventory_method = None
    try:
        shape = va_exact_method_shape(
            beam_inventory_name, [], "System.Guid[]")
        beam_inventory_shape = {
            "verified": shape.get("verified") is True,
            "match_count": shape.get("match_count"),
        }
        if shape.get("verified") is True:
            beam_inventory_method = beam_inventory_name
    except Exception as error:
        beam_inventory_shape = {
            "verified": False,
            "match_count": None,
            "error": va_text(error),
        }
    if beam_inventory_method is None:
        errors.append({
            "stage": "inventory_discovery",
            "method": beam_inventory_name,
            "error": (
                "exact public static Guid[] GetAllBeamStyle() was not "
                "reflected"),
            "method_shape": beam_inventory_shape,
        })
    else:
        inventory_methods.add(beam_inventory_method)
    if not inventory_methods:
        errors.append({
            "stage": "inventory_discovery",
            "error": "no supported public style inventory was reflected",
        })
    required_methods = ["GetStyleName", "GetSubStyleComponents"]
    missing_methods = [
        method_name for method_name in required_methods
        if not va_method_available(method_name)
    ]

    entries = []
    inventory_counts = {}
    style_owners = {}
    component_owners = {}
    for method_name in sorted(inventory_methods):
        try:
            style_ids = list(getattr(va, method_name)() or [])
        except Exception as error:
            errors.append({
                "stage": "style_inventory", "method": method_name,
                "error": va_text(error),
            })
            continue
        inventory_counts[method_name] = len(style_ids)
        local_style_texts = [str(style_id) for style_id in style_ids]
        duplicate_style_ids = sorted(
            set(value for value in local_style_texts
                if local_style_texts.count(value) > 1))
        if duplicate_style_ids:
            errors.append({
                "stage": "style_inventory", "method": method_name,
                "error": "duplicate style Guid",
                "style_ids": duplicate_style_ids,
            })
        for style_id in style_ids:
            style_text = str(style_id)
            local_errors = []
            if style_id == Guid.Empty:
                local_errors.append({
                    "method": method_name, "error": "empty style Guid"})
            if style_text in style_owners:
                local_errors.append({
                    "method": method_name,
                    "error": "style Guid appears in multiple inventories",
                    "other_method": style_owners[style_text],
                })
            else:
                style_owners[style_text] = method_name
            name = None
            try:
                name = va_text(va.GetStyleName(style_id))
                if name is None or not name.Trim():
                    raise Exception("style name is empty")
            except Exception as error:
                local_errors.append({
                    "method": "GetStyleName", "error": va_text(error)})
            component_ids = []
            try:
                raw_components = list(
                    va.GetSubStyleComponents(style_id) or [])
                component_ids = sorted(
                    str(component_id) for component_id in raw_components)
                if len(component_ids) != len(set(component_ids)):
                    raise Exception("duplicate sub-style component Guid")
                if str(Guid.Empty) in component_ids:
                    raise Exception("empty sub-style component Guid")
                for component_id in component_ids:
                    if component_id in component_owners:
                        raise Exception(
                            "component Guid belongs to multiple styles")
                    component_owners[component_id] = style_text
            except Exception as error:
                local_errors.append({
                    "method": "GetSubStyleComponents",
                    "error": va_text(error),
                })
            entry = {
                "key": method_name + "|" + style_text,
                "id": style_text,
                "inventory_method": method_name,
                "name": name,
                "component_ids": component_ids,
                "readback_complete": not local_errors,
                "readback_errors": local_errors,
            }
            entries.append(entry)
            for local_error in local_errors:
                errors.append({
                    "stage": "style_readback",
                    "style_id": style_text,
                    "method": local_error.get("method"),
                    "error": local_error.get("error"),
                    "other_method": local_error.get("other_method"),
                })
    collisions = sorted(set(style_owners) & set(component_owners))
    if collisions:
        errors.append({
            "stage": "global_guid_ownership",
            "error": "Guid is both a style and sub-style component",
            "ids": collisions,
        })
    entries.sort(key=lambda item: item["key"])
    return {
        "styles": entries,
        "all_style_ids": sorted(style_owners),
        "all_component_ids": sorted(component_owners),
        "style_owners": style_owners,
        "component_owners": component_owners,
        "inventory_methods": sorted(inventory_methods),
        "inventory_counts": inventory_counts,
        "beam_inventory_method": beam_inventory_method,
        "beam_inventory_shape": beam_inventory_shape,
        "style_count": len(style_owners),
        "component_count": len(component_owners),
        "missing_methods": missing_methods,
        "readback_errors": errors,
        "read_complete": (
            bool(inventory_methods) and not missing_methods and not errors),
        "coverage": (
            "all public zero-argument VisualARQ.Script "
            "GetAll*StyleIds inventories plus exact Guid[] "
            "GetAllBeamStyle(), names, and component Guid sets"),
    }

def va_global_style_rename_contract(before, after, style_id, new_name):
    style_text = str(style_id)
    expected_styles = []
    target_count = 0
    for entry in before.get("styles", []):
        expected_entry = dict(entry)
        if expected_entry.get("id") == style_text:
            target_count += 1
            expected_entry["name"] = new_name
        expected_styles.append(expected_entry)
    checks = {
        "before_complete": before.get("read_complete") is True,
        "after_complete": after.get("read_complete") is True,
        "target_owned_once": target_count == 1,
        "styles_exact": after.get("styles") == expected_styles,
        "style_ids_unchanged": after.get("all_style_ids") ==
            before.get("all_style_ids"),
        "component_ids_unchanged": after.get("all_component_ids") ==
            before.get("all_component_ids"),
        "style_owners_unchanged": after.get("style_owners") ==
            before.get("style_owners"),
        "component_owners_unchanged": after.get("component_owners") ==
            before.get("component_owners"),
        "inventory_methods_unchanged": after.get("inventory_methods") ==
            before.get("inventory_methods"),
        "inventory_counts_unchanged": after.get("inventory_counts") ==
            before.get("inventory_counts"),
        "counts_unchanged": after.get("style_count") ==
            before.get("style_count") and after.get("component_count") ==
            before.get("component_count"),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "expected_styles": expected_styles,
    }

def va_global_style_delete_contract(before, after, style_id):
    style_text = str(style_id)
    target_entries = [
        entry for entry in before.get("styles", [])
        if entry.get("id") == style_text]
    target_entry = target_entries[0] if len(target_entries) == 1 else None
    target_component_ids = list(
        target_entry.get("component_ids") or []) \
        if target_entry is not None else []
    expected_styles = [
        entry for entry in before.get("styles", [])
        if entry.get("id") != style_text]
    expected_style_ids = [
        value for value in before.get("all_style_ids", [])
        if value != style_text]
    expected_component_ids = [
        value for value in before.get("all_component_ids", [])
        if value not in target_component_ids]
    expected_style_owners = dict(before.get("style_owners") or {})
    expected_style_owners.pop(style_text, None)
    expected_component_owners = dict(before.get("component_owners") or {})
    for component_id in target_component_ids:
        expected_component_owners.pop(component_id, None)
    expected_inventory_counts = dict(before.get("inventory_counts") or {})
    if target_entry is not None:
        inventory_method = target_entry.get("inventory_method")
        if inventory_method in expected_inventory_counts:
            expected_inventory_counts[inventory_method] -= 1
    checks = {
        "before_complete": before.get("read_complete") is True,
        "after_complete": after.get("read_complete") is True,
        "target_owned_once": target_entry is not None,
        "styles_exact": after.get("styles") == expected_styles,
        "style_ids_exact": after.get("all_style_ids") == expected_style_ids,
        "component_ids_exact": after.get("all_component_ids") ==
            expected_component_ids,
        "style_owners_exact": after.get("style_owners") ==
            expected_style_owners,
        "component_owners_exact": after.get("component_owners") ==
            expected_component_owners,
        "inventory_methods_unchanged": after.get("inventory_methods") ==
            before.get("inventory_methods"),
        "inventory_counts_exact": after.get("inventory_counts") ==
            expected_inventory_counts,
        "style_count_exact": after.get("style_count") ==
            before.get("style_count") - 1,
        "component_count_exact": after.get("component_count") ==
            before.get("component_count") - len(target_component_ids),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "target_entry": target_entry,
        "target_component_ids": target_component_ids,
        "expected_styles": expected_styles,
    }

def va_global_style_create_contract(
        before, after, style_id, expected_inventory_method, expected_name,
        expected_component_ids):
    style_text = str(style_id)
    expected_components = sorted(
        str(value) for value in expected_component_ids)
    before_entries = dict(
        (entry["id"], entry) for entry in before.get("styles", []))
    after_entries = dict(
        (entry["id"], entry) for entry in after.get("styles", []))
    new_style_ids = sorted(
        set(after.get("all_style_ids", [])) -
        set(before.get("all_style_ids", [])))
    removed_style_ids = sorted(
        set(before.get("all_style_ids", [])) -
        set(after.get("all_style_ids", [])))
    new_component_ids = sorted(
        set(after.get("all_component_ids", [])) -
        set(before.get("all_component_ids", [])))
    removed_component_ids = sorted(
        set(before.get("all_component_ids", [])) -
        set(after.get("all_component_ids", [])))
    entry = after_entries.get(style_text)
    unchanged_entries = all(
        after_entries.get(entry_id) == before_entry
        for entry_id, before_entry in before_entries.items())
    expected_counts = dict(before.get("inventory_counts") or {})
    if expected_inventory_method in expected_counts:
        expected_counts[expected_inventory_method] += 1
    checks = {
        "before_complete": before.get("read_complete") is True,
        "after_complete": after.get("read_complete") is True,
        "one_new_expected_style": new_style_ids == [style_text],
        "no_removed_style": not removed_style_ids,
        "new_components_exact": new_component_ids == expected_components,
        "no_removed_component": not removed_component_ids,
        "preexisting_entries_unchanged": unchanged_entries,
        "new_entry_owned_once": entry is not None,
        "new_entry_inventory_matches": entry is not None and
            entry.get("inventory_method") == expected_inventory_method,
        "new_entry_name_matches": entry is not None and
            entry.get("name") == expected_name,
        "new_entry_components_match": entry is not None and
            entry.get("component_ids") == expected_components,
        "new_entry_readback_complete": entry is not None and
            entry.get("readback_complete") is True,
        "inventory_methods_unchanged": after.get("inventory_methods") ==
            before.get("inventory_methods"),
        "inventory_counts_exact": after.get("inventory_counts") ==
            expected_counts,
        "style_count_exact": after.get("style_count") ==
            before.get("style_count") + 1,
        "component_count_exact": after.get("component_count") ==
            before.get("component_count") + len(expected_components),
        "style_owner_exact": after.get("style_owners", {}).get(style_text) ==
            expected_inventory_method,
        "component_owners_exact": all(
            after.get("component_owners", {}).get(component_id) == style_text
            for component_id in expected_components),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "new_style_ids": new_style_ids,
        "removed_style_ids": removed_style_ids,
        "new_component_ids": new_component_ids,
        "removed_component_ids": removed_component_ids,
        "entry": entry,
    }

def va_style_component_presence(
        component_id, expected_parent_id, expected_kind="wall"):
    # VA 3.7.2 keeps IsStyleComponent/IsWallLayer and even the parent GUID true
    # after successful deletion. Only membership in a currently live style's
    # canonical child inventory is document-resident proof.
    try:
        if expected_kind == "wall":
            for wall_style_id in va_style_ids("wall"):
                inventory = va_wall_layer_ids(wall_style_id)
                if not inventory["read_complete"]:
                    return None
                if component_id in inventory["ids"]:
                    return True
        elif expected_kind == "slab":
            for slab_style_id in va_style_ids("slab"):
                inventory = va_slab_layer_ids(slab_style_id)
                if not inventory["read_complete"]:
                    return None
                if component_id in inventory["ids"]:
                    return True
        elif expected_kind in ["door", "window"]:
            if not va_method_available("GetOpeningStyleSizeProfiles"):
                return None
            for opening_kind in ["door", "window"]:
                for opening_style_id in va_style_ids(opening_kind):
                    profile_ids = list(
                        va.GetOpeningStyleSizeProfiles(opening_style_id) or [])
                    if component_id in profile_ids:
                        return True
        else:
            return None
        return False
    except Exception:
        return None

def va_opening_profile_shape_contract():
    shapes = {
        "GetAllDoorStyleIds": va_exact_method_shape(
            "GetAllDoorStyleIds", [], "System.Guid[]"),
        "GetAllWindowStyleIds": va_exact_method_shape(
            "GetAllWindowStyleIds", [], "System.Guid[]"),
        "GetOpeningStyleSizeProfiles": va_exact_method_shape(
            "GetOpeningStyleSizeProfiles", ["System.Guid"],
            "System.Guid[]"),
        "GetOpeningStyleFromSizeProfile": va_exact_method_shape(
            "GetOpeningStyleFromSizeProfile", ["System.Guid"],
            "System.Guid"),
        "IsOpeningStyleSizeProfile": va_exact_method_shape(
            "IsOpeningStyleSizeProfile", ["System.Guid", "System.Guid"],
            "System.Boolean"),
        "GetProfileName": va_exact_method_shape(
            "GetProfileName", ["System.Guid"], "System.String"),
        "IsProfile": va_exact_method_shape(
            "IsProfile", ["System.Guid"], "System.Boolean"),
        "IsRectangularProfile": va_exact_method_shape(
            "IsRectangularProfile", ["System.Guid"], "System.Boolean"),
        "GetRectangularProfileSize": va_exact_method_shape(
            "GetRectangularProfileSize", ["System.Guid"],
            "VisualARQ.Script+RectangularProfileSize"),
        "GetOpeningStyleProfileTemplate": va_exact_method_shape(
            "GetOpeningStyleProfileTemplate", ["System.Guid"],
            "System.Guid"),
        "IsProfileTemplate": va_exact_method_shape(
            "IsProfileTemplate", ["System.Guid"], "System.Boolean"),
    }
    failed = sorted(
        name for name in shapes if shapes[name]["verified"] is not True)
    return {
        "pass": not failed,
        "failed_methods": failed,
        "shapes": shapes,
    }

def va_rectangular_profile_size_constructor_contract():
    reflected_type = None
    matching_constructors = []
    fields = {}
    errors = []
    try:
        for candidate in va_assembly.GetTypes():
            if str(candidate.FullName) == \
                    "VisualARQ.Script+RectangularProfileSize":
                reflected_type = candidate
                break
        if reflected_type is None:
            raise Exception("RectangularProfileSize CLR type was not found")
        flags = System.Reflection.BindingFlags.Public | \
            System.Reflection.BindingFlags.Instance
        for constructor in reflected_type.GetConstructors(flags):
            parameters = list(constructor.GetParameters())
            if len(parameters) == 2 and \
                    [str(parameter.ParameterType.FullName)
                     for parameter in parameters] == \
                    ["System.Double", "System.Double"] and \
                    not any(parameter.ParameterType.IsByRef or
                            parameter.IsOptional for parameter in parameters):
                matching_constructors.append(constructor)
        for field in reflected_type.GetFields(flags):
            fields[str(field.Name)] = {
                "type": str(field.FieldType.FullName),
                "readonly": bool(field.IsInitOnly),
            }
        if len(matching_constructors) != 1:
            errors.append(
                "expected exactly one public (Double, Double) constructor")
        for field_name in ["Width", "Height"]:
            field = fields.get(field_name)
            if field is None or field["type"] != "System.Double" or \
                    field["readonly"]:
                errors.append(
                    field_name + " must be a writable System.Double field")
    except Exception as error:
        errors.append(va_text(error))
    return {
        "pass": not errors,
        "type": "VisualARQ.Script+RectangularProfileSize",
        "matching_constructor_count": len(matching_constructors),
        "fields": fields,
        "errors": errors,
    }

def va_opening_profile_snapshot(expected_style_id, profile_id):
    errors = []
    diagnostic_warnings = []
    name = None
    owner_id = Guid.Empty
    membership = None
    is_profile = None
    is_opening_profile = None
    is_rectangular = None
    dimensions = None
    shape_contract = va_opening_profile_shape_contract()
    if shape_contract["pass"] is not True:
        errors.append({
            "stage": "signature_contract",
            "error": "opening profile CLR signatures are not exact",
            "failed_methods": shape_contract["failed_methods"],
        })
    else:
        try:
            name = va_text(va.GetProfileName(profile_id))
            if name is None or not name.Trim():
                raise Exception("profile name is empty")
        except Exception as error:
            errors.append({"stage": "name", "error": va_text(error)})
        try:
            owner_id = va.GetOpeningStyleFromSizeProfile(profile_id)
            if owner_id is None or owner_id == Guid.Empty:
                raise Exception("profile owner is empty")
        except Exception as error:
            errors.append({"stage": "owner", "error": va_text(error)})
        try:
            membership = bool(va.IsOpeningStyleSizeProfile(
                expected_style_id, profile_id))
            if membership is not True:
                raise Exception("profile is not a member of the style")
        except Exception as error:
            errors.append({
                "stage": "membership", "error": va_text(error)})
        try:
            is_profile = bool(va.IsProfile(profile_id))
            if is_profile is not True:
                raise Exception("Guid is not a VisualARQ profile")
        except Exception as error:
            errors.append({
                "stage": "profile_classification", "error": va_text(error)})
        # `IsOpeningProfile` is an independent profile-family classifier, not
        # a style-size membership predicate. Probe it only when available and
        # never let that diagnostic weaken the authoritative owner/membership
        # contract above.
        if va_method_available("IsOpeningProfile"):
            try:
                is_opening_profile = bool(va.IsOpeningProfile(profile_id))
            except Exception as error:
                diagnostic_warnings.append({
                    "stage": "opening_profile_family_probe",
                    "error": va_text(error),
                })
        try:
            is_rectangular = bool(va.IsRectangularProfile(profile_id))
            if is_rectangular:
                size = va.GetRectangularProfileSize(profile_id)
                width_value = va_valid_double(size.Width)
                height_value = va_valid_double(size.Height)
                if width_value is None or height_value is None or \
                        width_value <= 0.0 or height_value <= 0.0:
                    raise Exception(
                        "rectangular profile has invalid dimensions")
                dimensions = {
                    "width": width_value,
                    "height": height_value,
                }
        except Exception as error:
            errors.append({
                "stage": "shape_and_dimensions", "error": va_text(error)})
    owner_matches = owner_id == expected_style_id
    if owner_id != Guid.Empty and not owner_matches:
        errors.append({
            "stage": "owner",
            "error": "profile owner does not match expected style",
        })
    return {
        "id": str(profile_id),
        "name": name,
        "style_id": str(owner_id) if owner_id != Guid.Empty else None,
        "expected_style_id": str(expected_style_id),
        "membership_verified": membership,
        "owner_matches": owner_matches,
        "is_profile": is_profile,
        "is_opening_profile": is_opening_profile,
        "is_opening_profile_semantics": \
            "profile_family_diagnostic_non_gating",
        "shape": "rectangular" if is_rectangular is True else \
            ("other" if is_rectangular is False else None),
        "rectangular": is_rectangular,
        "dimensions": dimensions,
        "measurement_complete": (
            is_rectangular is not True or dimensions is not None),
        "readback_complete": not errors,
        "readback_errors": errors,
        "diagnostic_warnings": diagnostic_warnings,
    }

def va_opening_template_snapshot(style_id):
    errors = []
    template_id = Guid.Empty
    available = False
    name = None
    is_profile = None
    is_template = None
    is_rectangular = None
    shape_contract = va_opening_profile_shape_contract()
    if shape_contract["pass"] is not True:
        errors.append({
            "stage": "signature_contract",
            "error": "opening profile CLR signatures are not exact",
            "failed_methods": shape_contract["failed_methods"],
        })
    else:
        try:
            template_id = va.GetOpeningStyleProfileTemplate(style_id)
            if template_id is None:
                raise Exception("style profile template result is null")
            available = template_id != Guid.Empty
        except Exception as error:
            errors.append({"stage": "template", "error": va_text(error)})
        if template_id != Guid.Empty:
            try:
                name = va_text(va.GetProfileName(template_id))
                if name is None or not name.Trim():
                    raise Exception("template name is empty")
            except Exception as error:
                errors.append({
                    "stage": "template_name", "error": va_text(error)})
            try:
                is_profile = bool(va.IsProfile(template_id))
                is_template = bool(va.IsProfileTemplate(template_id))
                is_rectangular = bool(va.IsRectangularProfile(template_id))
                if not is_profile or not is_template:
                    raise Exception("style template classification is invalid")
            except Exception as error:
                errors.append({
                    "stage": "template_classification",
                    "error": va_text(error),
                })
    return {
        "id": str(template_id) if template_id != Guid.Empty else None,
        "available": available,
        "name": name,
        "is_profile": is_profile,
        "is_profile_template": is_template,
        "shape": "rectangular" if is_rectangular is True else \
            ("other" if is_rectangular is False else None),
        "rectangular": is_rectangular,
        "readback_complete": not errors,
        "readback_errors": errors,
    }

def va_opening_profile_inventory():
    shape_contract = va_opening_profile_shape_contract()
    errors = []
    entries = []
    profile_owners = {}
    if shape_contract["pass"] is not True:
        errors.append({
            "stage": "signature_contract",
            "error": "opening profile CLR signatures are not exact",
            "failed_methods": shape_contract["failed_methods"],
        })
    else:
        for kind in ["door", "window"]:
            try:
                style_ids = va_style_ids(kind)
            except Exception as error:
                errors.append({
                    "stage": "style_inventory", "kind": kind,
                    "error": va_text(error),
                })
                continue
            for style_id in style_ids:
                style_text = str(style_id)
                local_errors = []
                profile_ids = []
                try:
                    profile_ids = list(
                        va.GetOpeningStyleSizeProfiles(style_id) or [])
                    profile_texts = [str(value) for value in profile_ids]
                    if len(profile_texts) != len(set(profile_texts)):
                        raise Exception("duplicate profile Guid in style")
                    if str(Guid.Empty) in profile_texts:
                        raise Exception("empty profile Guid in style")
                except Exception as error:
                    local_errors.append({
                        "stage": "profile_inventory", "error": va_text(error)})
                profiles = []
                for profile_id in profile_ids:
                    profile = va_opening_profile_snapshot(style_id, profile_id)
                    profiles.append(profile)
                    profile_text = str(profile_id)
                    if profile_text in profile_owners:
                        local_errors.append({
                            "stage": "global_profile_ownership",
                            "profile_id": profile_text,
                            "error": "profile Guid belongs to multiple styles",
                            "other_style_id": profile_owners[profile_text],
                        })
                    else:
                        profile_owners[profile_text] = style_text
                    if profile["readback_complete"] is not True:
                        local_errors.append({
                            "stage": "profile_readback",
                            "profile_id": profile_text,
                            "error": "profile readback is incomplete",
                        })
                entry = {
                    "key": kind + "|" + style_text,
                    "kind": kind,
                    "style_id": style_text,
                    "profile_ids": [str(value) for value in profile_ids],
                    "profiles": profiles,
                    "readback_complete": not local_errors,
                    "readback_errors": local_errors,
                }
                entries.append(entry)
                for local_error in local_errors:
                    reported = dict(local_error)
                    reported["style_id"] = style_text
                    reported["kind"] = kind
                    errors.append(reported)
    entries.sort(key=lambda item: item["key"])
    return {
        "styles": entries,
        "all_profile_ids": sorted(profile_owners),
        "profile_owners": profile_owners,
        "profile_count": len(profile_owners),
        "shape_contract": shape_contract,
        "readback_errors": errors,
        "read_complete": shape_contract["pass"] is True and not errors,
        "coverage": (
            "all GetOpeningStyleSizeProfiles entries from every document "
            "door and window style"),
    }

def va_style_snapshot(style_id):
    kind = va_style_kind(style_id)
    if kind is None:
        return None
    readback_errors = []
    style_name = None
    try:
        style_name = va_text(va.GetStyleName(style_id))
        if style_name is None:
            readback_errors.append({
                "method": "GetStyleName", "error": "name is unavailable"})
    except Exception as error:
        readback_errors.append({
            "method": "GetStyleName", "error": va_text(error)})
    snapshot = {
        "id": str(style_id),
        "kind": kind,
        "name": style_name,
    }
    snapshot["product_count"] = None
    snapshot["product_count_read_complete"] = False
    if va_method_available("GetProductsByStyle"):
        try:
            products = va.GetProductsByStyle(style_id, False) or []
            snapshot["product_count"] = len(products)
            snapshot["product_count_read_complete"] = True
        except Exception as error:
            readback_errors.append({
                "method": "GetProductsByStyle", "error": va_text(error)})
    else:
        readback_errors.append({
            "method": "GetProductsByStyle", "error": "method unavailable"})
    if kind == "wall":
        layer_inventory = va_wall_layer_ids(style_id)
        layer_ids = layer_inventory["ids"]
        snapshot["height"] = None
        snapshot["height_read_complete"] = False
        if va_method_available("GetWallStyleHeight"):
            try:
                snapshot["height"] = va_valid_double(
                    va.GetWallStyleHeight(style_id))
                snapshot["height_read_complete"] = \
                    snapshot["height"] is not None
                if not snapshot["height_read_complete"]:
                    readback_errors.append({
                        "method": "GetWallStyleHeight",
                        "error": "invalid or unset measurement",
                    })
            except Exception as error:
                readback_errors.append({
                    "method": "GetWallStyleHeight", "error": va_text(error)})
        else:
            readback_errors.append({
                "method": "GetWallStyleHeight", "error": "method unavailable"})
        snapshot["layer_inventory"] = {
            "source": layer_inventory["source"],
            "read_complete": layer_inventory["read_complete"],
            "conflicting_nonempty_sources": \
                layer_inventory["conflicting_nonempty_sources"],
            "get_wall_layers_attempted": \
                layer_inventory["get_wall_layers_attempted"],
            "get_wall_layers_succeeded": \
                layer_inventory["get_wall_layers_succeeded"],
            "subcomponents_attempted": \
                layer_inventory["subcomponents_attempted"],
            "subcomponents_succeeded": \
                layer_inventory["subcomponents_succeeded"],
            "get_wall_layers_ids": layer_inventory["get_wall_layers_ids"],
            "subcomponent_ids": layer_inventory["subcomponent_ids"],
            "sources_agree": layer_inventory["sources_agree"],
            "get_wall_layers_error": \
                layer_inventory["get_wall_layers_error"],
            "subcomponent_error": layer_inventory["subcomponent_error"],
        }
        snapshot["layer_inventory_complete"] = \
            layer_inventory["read_complete"]
        if layer_inventory["read_complete"]:
            layers = [
                va_wall_layer_snapshot(layer_id) for layer_id in layer_ids]
            snapshot["layers"] = layers
            snapshot["layer_count"] = len(layers)
            valid_thicknesses = [
                layer["thickness"] for layer in layers
                if layer["thickness"] is not None
            ]
            snapshot["total_layer_thickness"] = sum(valid_thicknesses) \
                if len(valid_thicknesses) == len(layers) else None
            snapshot["layer_measurements_complete"] = all(
                layer["readback_complete"] for layer in layers)
        else:
            snapshot["layers"] = None
            snapshot["layer_count"] = None
            snapshot["total_layer_thickness"] = None
            snapshot["layer_measurements_complete"] = False
        snapshot["readback_complete"] = \
            snapshot["name"] is not None and \
            snapshot["product_count_read_complete"] and \
            snapshot["height_read_complete"] and \
            snapshot["layer_inventory_complete"] and \
            snapshot["layer_measurements_complete"]
    elif kind == "slab":
        layer_inventory = va_slab_layer_ids(style_id)
        layer_ids = layer_inventory["ids"]
        snapshot["layer_inventory"] = {
            "source": layer_inventory["source"],
            "read_complete": layer_inventory["read_complete"],
            "conflicting_nonempty_sources":
                layer_inventory["conflicting_nonempty_sources"],
            "get_slab_layers_attempted":
                layer_inventory["get_slab_layers_attempted"],
            "get_slab_layers_succeeded":
                layer_inventory["get_slab_layers_succeeded"],
            "subcomponents_attempted":
                layer_inventory["subcomponents_attempted"],
            "subcomponents_succeeded":
                layer_inventory["subcomponents_succeeded"],
            "get_slab_layers_ids": layer_inventory["get_slab_layers_ids"],
            "subcomponent_ids": layer_inventory["subcomponent_ids"],
            "sources_agree": layer_inventory["sources_agree"],
            "get_slab_layers_error":
                layer_inventory["get_slab_layers_error"],
            "subcomponent_error": layer_inventory["subcomponent_error"],
        }
        snapshot["layer_inventory_complete"] = \
            layer_inventory["read_complete"]
        if layer_inventory["read_complete"]:
            layers = [
                va_slab_layer_snapshot(layer_id) for layer_id in layer_ids]
            snapshot["layers"] = layers
            snapshot["layer_count"] = len(layers)
            valid_thicknesses = [
                layer["thickness"] for layer in layers
                if layer["thickness"] is not None
            ]
            snapshot["total_layer_thickness"] = sum(valid_thicknesses) \
                if len(valid_thicknesses) == len(layers) else None
            snapshot["layer_measurements_complete"] = all(
                layer["readback_complete"] for layer in layers)
        else:
            snapshot["layers"] = None
            snapshot["layer_count"] = None
            snapshot["total_layer_thickness"] = None
            snapshot["layer_measurements_complete"] = False
        if snapshot["layer_count"] is not None and \
                snapshot["layer_count"] < 1:
            readback_errors.append({
                "method": "slab layer inventory",
                "error": "slab style has no typed layer",
            })
        if snapshot["total_layer_thickness"] is not None and \
                snapshot["total_layer_thickness"] <= 0.0:
            readback_errors.append({
                "method": "GetSlabLayerThickness",
                "error": "slab style thickness is not positive",
            })
        snapshot["readback_complete"] = \
            snapshot["name"] is not None and \
            snapshot["product_count_read_complete"] and \
            snapshot["layer_inventory_complete"] and \
            snapshot["layer_measurements_complete"] and \
            snapshot["layer_count"] is not None and \
            snapshot["layer_count"] >= 1 and \
            snapshot["total_layer_thickness"] is not None and \
            snapshot["total_layer_thickness"] > 0.0
    elif kind == "space":
        snapshot["readback_complete"] = \
            snapshot["name"] is not None and \
            snapshot["product_count_read_complete"]
    elif kind == "door" or kind == "window":
        try:
            profile_ids = list(
                va.GetOpeningStyleSizeProfiles(style_id) or [])
            snapshot["size_profiles"] = [
                va_opening_profile_snapshot(style_id, profile_id)
                for profile_id in profile_ids
            ]
            snapshot["profile_template"] = \
                va_opening_template_snapshot(style_id)
            snapshot["readback_complete"] = \
                snapshot["name"] is not None and \
                snapshot["product_count_read_complete"] and \
                snapshot["profile_template"]["readback_complete"] and all(
                    profile["readback_complete"]
                    for profile in snapshot["size_profiles"])
            if snapshot["readback_complete"] is not True:
                readback_errors.append({
                    "method": "opening profile helpers",
                    "error": "opening style profile readback is incomplete",
                })
        except Exception as profile_error:
            snapshot["size_profiles"] = None
            snapshot["profile_template"] = None
            snapshot["size_profile_error"] = va_text(profile_error)
            snapshot["readback_complete"] = False
            readback_errors.append({
                "method": "GetOpeningStyleSizeProfiles",
                "error": va_text(profile_error),
            })
    snapshot["readback_errors"] = readback_errors
    return snapshot
"""


_OBJECT_SCRIPT_HELPERS = r"""
def va_object_classification_probe(object_id):
    # Specific kinds precede their broad bases so `kind` remains actionable.
    checks = [
        ("curtain_wall", "IsCurtainWall"),
        ("door", "IsDoor"), ("window", "IsWindow"),
        ("wall", "IsWall"), ("column", "IsColumn"),
        ("beam", "IsBeam"), ("slab", "IsSlab"),
        ("stair", "IsStair"), ("railing", "IsRailing"),
        ("roof", "IsRoof"), ("space", "IsSpace"),
        ("section", "IsSection"),
        ("furniture", "IsFurniture"),
        ("generic_element", "IsGenericElement"),
        ("opening", "IsOpening"), ("element", "IsElement"),
        ("product", "IsProduct"),
        ("building_element", "IsBuildingElement"),
    ]
    classifications = []
    errors = []
    for kind, method_name in checks:
        if not va_method_available(method_name):
            errors.append({
                "kind": kind, "method": method_name,
                "error": "method unavailable",
            })
            continue
        try:
            if getattr(va, method_name)(object_id):
                classifications.append(kind)
        except Exception as error:
            errors.append({
                "kind": kind, "method": method_name,
                "error": va_text(error),
            })
    return {
        "classifications": classifications,
        "errors": errors,
        "complete": len(errors) == 0,
    }

def va_primary_kind(classifications):
    broad = ["opening", "element", "product", "building_element"]
    for kind in classifications:
        if kind not in broad:
            return kind
    for kind in classifications:
        if kind == "opening" or kind == "element":
            return kind
    for kind in classifications:
        if kind == "product" or kind == "building_element":
            return kind
    return None

def va_visualarq_identity_probe(object_id):
    errors = []
    for method_name in ["IsProduct", "IsSection"]:
        if not va_method_available(method_name):
            errors.append({
                "method": method_name, "error": "method unavailable"})
            continue
        try:
            if getattr(va, method_name)(object_id):
                return {"match": True, "errors": errors}
        except Exception as error:
            errors.append({"method": method_name, "error": va_text(error)})
    return {
        "match": None if errors else False,
        "errors": errors,
    }

def va_matches_kind(object_id, kind):
    method_names = {
        "wall": "IsWall", "door": "IsDoor", "window": "IsWindow",
        "column": "IsColumn", "beam": "IsBeam", "slab": "IsSlab",
        "stair": "IsStair", "railing": "IsRailing", "roof": "IsRoof",
        "curtain_wall": "IsCurtainWall", "opening": "IsOpening",
        "space": "IsSpace", "section": "IsSection",
        "generic_element": "IsGenericElement", "element": "IsElement",
        "furniture": "IsFurniture", "product": "IsProduct",
        "building_element": "IsBuildingElement",
    }
    method_name = method_names.get(kind)
    if method_name is None:
        return {"match": None, "error": "unknown kind"}
    if not va_method_available(method_name):
        return {
            "match": None, "method": method_name,
            "error": "method unavailable",
        }
    try:
        return {
            "match": bool(getattr(va, method_name)(object_id)),
            "method": method_name, "error": None,
        }
    except Exception as error:
        return {
            "match": None, "method": method_name, "error": va_text(error),
        }

def va_point(point):
    return [float(point.X), float(point.Y), float(point.Z)]

def va_geometry_snapshot(geometry, include_volume=True):
    if geometry is None:
        return None
    bbox = geometry.GetBoundingBox(True)
    volume = None
    volume_properties = None
    if include_volume:
        try:
            volume_properties = rg.VolumeMassProperties.Compute(geometry)
            if volume_properties is not None:
                volume = float(volume_properties.Volume)
        except Exception:
            pass
        finally:
            if volume_properties is not None:
                try:
                    volume_properties.Dispose()
                except Exception:
                    pass
    is_solid = None
    try:
        is_solid = bool(geometry.IsSolid)
    except Exception:
        pass
    bbox_valid = bool(bbox.IsValid)
    return {
        "type": str(geometry.GetType().FullName),
        "is_valid": bool(geometry.IsValid),
        "is_solid": is_solid,
        "bbox_valid": bbox_valid,
        "bbox_diagonal": float(bbox.Diagonal.Length) if bbox_valid else None,
        "bbox_min": va_point(bbox.Min) if bbox_valid else None,
        "bbox_max": va_point(bbox.Max) if bbox_valid else None,
        "volume_included": bool(include_volume),
        "volume": volume,
        "volume_verified": volume is not None,
    }

def va_bbox_snapshot(geometry):
    if geometry is None or not bool(geometry.IsValid):
        raise Exception("geometry is missing or invalid")
    bbox = geometry.GetBoundingBox(True)
    if not bool(bbox.IsValid):
        raise Exception("geometry bounding box is invalid")
    return {
        "min": va_point(bbox.Min),
        "max": va_point(bbox.Max),
        "diagonal": float(bbox.Diagonal.Length),
    }

def va_horizontal_curve_snapshot(curve, tolerance):
    if curve is None or not isinstance(curve, rg.Curve):
        raise Exception("semantic boundary is not a Curve")
    if not bool(curve.IsValid) or not bool(curve.IsClosed) or \
            not bool(curve.IsPlanar(tolerance)):
        raise Exception("semantic boundary is not valid, closed and planar")
    bbox = va_bbox_snapshot(curve)
    if abs(float(bbox["max"][2]) - float(bbox["min"][2])) > tolerance:
        raise Exception("semantic boundary is not horizontal")
    properties = rg.AreaMassProperties.Compute(curve, tolerance)
    if properties is None:
        raise Exception("semantic boundary area is unavailable")
    try:
        area = va_valid_double(properties.Area)
        centroid = va_point(properties.Centroid)
    finally:
        properties.Dispose()
    perimeter = va_valid_double(curve.GetLength())
    if area is None or area <= tolerance * tolerance or \
            perimeter is None or perimeter <= tolerance:
        raise Exception("semantic boundary has no positive area/perimeter")
    return {
        "kind": "closed_planar_curve",
        "geometry_type": str(curve.GetType().FullName),
        "bbox": bbox,
        "area": area,
        "perimeter": perimeter,
        "centroid": centroid,
    }

def va_slab_contour_snapshot(contour, tolerance):
    if isinstance(contour, rg.Curve):
        return va_horizontal_curve_snapshot(contour, tolerance)
    if not isinstance(contour, rg.Brep) or not bool(contour.IsValid):
        type_name = "None" if contour is None else \
            str(contour.GetType().FullName)
        raise Exception("unsupported Slab contour type: " + type_name)
    faces = list(contour.Faces)
    loops = list(contour.Loops)
    if len(faces) != 1 or len(loops) != 1:
        raise Exception("Slab Brep contour must have one face and one loop")
    face = faces[0]
    loop = loops[0]
    if face is None or not bool(face.IsValid) or \
            not bool(face.IsPlanar(tolerance)) or loop is None or \
            loop.LoopType != rg.BrepLoopType.Outer:
        raise Exception("Slab Brep contour is not one planar outer footprint")
    u_domain = face.Domain(0)
    v_domain = face.Domain(1)
    normal = face.NormalAt(
        (float(u_domain.T0) + float(u_domain.T1)) / 2.0,
        (float(v_domain.T0) + float(v_domain.T1)) / 2.0)
    normal_length = float(normal.Length)
    if normal_length <= 0.0 or \
            abs(float(normal.Z)) / normal_length < 0.999999:
        raise Exception("Slab Brep contour face is not horizontal")
    trims = list(loop.Trims)
    if len(trims) < 3:
        raise Exception("Slab Brep contour has fewer than three trims")
    perimeter = 0.0
    for trim in trims:
        edge = trim.Edge
        curve = edge.DuplicateCurve() if edge is not None else None
        if trim.TrimType != rg.BrepTrimType.Boundary or curve is None or \
                not bool(curve.IsValid) or \
                not bool(curve.IsLinear(tolerance)) or \
                abs(float(curve.PointAtStart.Z) -
                    float(curve.PointAtEnd.Z)) > tolerance:
            raise Exception("Slab Brep contour trim is not linear/boundary")
        perimeter += float(curve.GetLength())
    bbox = va_bbox_snapshot(contour)
    if abs(float(bbox["max"][2]) - float(bbox["min"][2])) > tolerance:
        raise Exception("Slab Brep contour is not horizontal")
    properties = rg.AreaMassProperties.Compute(
        contour, True, False, False, False, 1.0e-6, tolerance)
    if properties is None:
        raise Exception("Slab Brep contour area is unavailable")
    try:
        area = va_valid_double(properties.Area)
        centroid = va_point(properties.Centroid)
    finally:
        properties.Dispose()
    if area is None or area <= tolerance * tolerance or \
            perimeter <= tolerance:
        raise Exception("Slab Brep contour has no positive area/perimeter")
    return {
        "kind": "single_face_planar_brep",
        "geometry_type": str(contour.GetType().FullName),
        "bbox": bbox,
        "area": area,
        "perimeter": perimeter,
        "centroid": centroid,
    }

def va_semantic_vertical_bbox(footprint_bbox, bottom, top):
    bottom_value = va_valid_double(bottom)
    top_value = va_valid_double(top)
    if bottom_value is None or top_value is None or top_value <= bottom_value:
        raise Exception("semantic vertical bounds are invalid")
    return {
        "min": [float(footprint_bbox["min"][0]),
                float(footprint_bbox["min"][1]), bottom_value],
        "max": [float(footprint_bbox["max"][0]),
                float(footprint_bbox["max"][1]), top_value],
    }

def va_transform_fingerprint(transform):
    values = list(transform.ToDoubleArray(True) or [])
    normalized = [va_valid_double(value) for value in values]
    if len(normalized) != 16 or any(value is None for value in normalized):
        raise Exception(
            "Instance transform is not a finite 16-value row-major matrix")
    return normalized

def va_object_attributes_fingerprint(attributes):
    if attributes is None:
        raise Exception("Rhino object attributes are unavailable")
    user_strings = []
    values = attributes.GetUserStrings()
    if values is not None:
        keys = list(values.AllKeys or [])
        for key in sorted(str(value) for value in keys):
            user_strings.append([key, va_text(values[key])])
    object_color = attributes.ObjectColor
    plot_color = attributes.PlotColor
    return {
        "name": va_text(attributes.Name) if attributes.Name else None,
        "layer_index": int(attributes.LayerIndex),
        "linetype_index": int(attributes.LinetypeIndex),
        "linetype_source": int(attributes.LinetypeSource),
        "material_index": int(attributes.MaterialIndex),
        "material_source": int(attributes.MaterialSource),
        "color_source": int(attributes.ColorSource),
        "object_color_argb": int(object_color.ToArgb()),
        "plot_color_source": int(attributes.PlotColorSource),
        "plot_color_argb": int(plot_color.ToArgb()),
        "plot_weight": va_valid_double(attributes.PlotWeight),
        "plot_weight_source": int(attributes.PlotWeightSource),
        "visible": bool(attributes.Visible),
        "mode": int(attributes.Mode),
        "object_decoration": int(attributes.ObjectDecoration),
        "display_order": int(getattr(attributes, "DisplayOrder", 0)),
        "user_strings": user_strings,
    }

def va_instance_definition_fingerprints_match(before, after):
    return before is not None and after is not None and \
        before.get("complete") is True and \
        after.get("complete") is True and \
        before.get("leaf_count") == after.get("leaf_count") and \
        before.get("canonical_leaves") == after.get("canonical_leaves")

def va_instance_definition_volume_snapshot(obj):
    # VisualARQ products are Rhino instance objects whose outer
    # InstanceReferenceGeometry has no directly measurable volume. Their block
    # definition contains the independently generated Breps, meshes or
    # extrusions. Geometry is duplicated in memory and transformed to world
    # coordinates; the document and definition objects remain untouched.
    source = "instance_definition_solid_geometry"
    if not isinstance(obj, Rhino.DocObjects.InstanceObject):
        return {
            "source": source, "applicable": False,
            "volume": None, "partial_volume": None,
            "volume_verified": False, "measurement_complete": False,
            "volume_geometry_count": 0,
            "measured_volume_geometry_count": 0,
            "ignored_geometry_types": {}, "components": [], "errors": [],
            "error_count": 0, "components_truncated": False,
            "errors_truncated": False,
            "definition_fingerprint": {
                "applicable": False, "complete": False,
                "leaf_count": 0, "canonical_leaves": [],
                "diagnostic_leaves": [], "errors": [
                    "object is not an InstanceObject"],
            },
        }

    components = []
    errors = []
    error_count = [0]
    ignored_geometry_types = {}
    volume_geometry_count = [0]
    measured_count = [0]
    total_volume = [0.0]
    fingerprint_leaves = []
    fingerprint_diagnostics = []
    fingerprint_errors = []

    def add_error(stage, message, object_id=None):
        error_count[0] += 1
        if len(errors) < 50:
            error = {"stage": stage, "error": va_text(message)}
            if object_id is not None:
                error["object_id"] = str(object_id)
            errors.append(error)

    def record_fingerprint_leaf(leaf, instance_path, diagnostic_path):
        geometry = leaf.Geometry
        if geometry is None:
            raise Exception("definition leaf geometry is unavailable")
        bbox = geometry.GetBoundingBox(True)
        if not bbox.IsValid:
            raise Exception("definition leaf bounding box is invalid")
        record = {
            "geometry_type": str(geometry.GetType().FullName),
            "geometry_crc": int(geometry.DataCRC(System.UInt32(0))),
            "geometry_valid": bool(geometry.IsValid),
            "bbox_min": va_point(bbox.Min),
            "bbox_max": va_point(bbox.Max),
            "instance_path": list(instance_path),
            "attributes": va_object_attributes_fingerprint(leaf.Attributes),
        }
        fingerprint_leaves.append(record)
        fingerprint_diagnostics.append({
            "leaf_id": str(leaf.Id),
            "object_path": list(diagnostic_path),
            "geometry_type": record["geometry_type"],
        })

    def measure_leaf(leaf, transforms, instance_path, diagnostic_path):
        geometry = leaf.Geometry
        geometry_type = str(geometry.GetType().FullName)
        candidate = None
        solid = False
        # Every definition leaf is fingerprinted before the volume-type
        # switch. Curves, points and annotations are therefore part of
        # cleanup identity even though they contribute no volume.
        try:
            record_fingerprint_leaf(
                leaf, instance_path, diagnostic_path)
        except Exception as fingerprint_error:
            fingerprint_errors.append(va_text(fingerprint_error))
            add_error("definition_fingerprint", fingerprint_error, leaf.Id)
        try:
            if isinstance(geometry, rg.Brep):
                volume_geometry_count[0] += 1
                solid = bool(geometry.IsValid and geometry.IsSolid)
                candidate = geometry.DuplicateBrep()
            elif isinstance(geometry, rg.Mesh):
                volume_geometry_count[0] += 1
                solid = bool(geometry.IsValid and geometry.IsClosed)
                candidate = geometry.DuplicateMesh()
            elif isinstance(geometry, rg.Extrusion):
                volume_geometry_count[0] += 1
                solid = bool(geometry.IsValid and geometry.IsSolid)
                candidate = geometry.ToBrep()
            elif hasattr(rg, "SubD") and isinstance(geometry, rg.SubD):
                volume_geometry_count[0] += 1
                solid = bool(geometry.IsValid and geometry.IsSolid)
                candidate = geometry.ToBrep()
            else:
                ignored_geometry_types[geometry_type] = \
                    ignored_geometry_types.get(geometry_type, 0) + 1
                return

            component = {
                "object_id": str(leaf.Id),
                "geometry_type": geometry_type,
                "is_solid": solid,
                "transform_count": len(transforms),
                "volume": None,
            }
            if len(components) < 100:
                components.append(component)
            if not solid or candidate is None:
                add_error(
                    "solid_validation",
                    "Volume-capable definition geometry is not a valid solid",
                    leaf.Id)
                return
            for transform in transforms:
                if not candidate.Transform(transform):
                    add_error(
                        "transform", "Definition transform failed", leaf.Id)
                    return
            properties = None
            try:
                properties = rg.VolumeMassProperties.Compute(candidate)
                volume = va_valid_double(properties.Volume) \
                    if properties is not None else None
                if volume is None:
                    add_error(
                        "volume", "VolumeMassProperties returned no volume",
                        leaf.Id)
                    return
                volume = abs(volume)
                component["volume"] = volume
                total_volume[0] += volume
                measured_count[0] += 1
            except Exception as error:
                add_error("volume", error, leaf.Id)
            finally:
                if properties is not None:
                    try:
                        properties.Dispose()
                    except Exception:
                        pass
        except Exception as error:
            add_error("geometry", error, leaf.Id)
        finally:
            if candidate is not None:
                try:
                    candidate.Dispose()
                except Exception:
                    pass

    def visit(current, outer_transforms, definition_path, depth,
              instance_path, diagnostic_path):
        if depth > 32:
            add_error("recursion", "Instance nesting exceeds 32 levels")
            return
        if isinstance(current, Rhino.DocObjects.InstanceObject):
            definition = current.InstanceDefinition
            if definition is None:
                add_error(
                    "definition", "Instance definition is unavailable",
                    current.Id)
                return
            definition_id = str(definition.Id)
            if definition_id in definition_path:
                add_error(
                    "definition", "Cyclic instance definition detected",
                    current.Id)
                return
            children = list(definition.GetObjects() or [])
            if not children:
                add_error(
                    "definition", "Instance definition has no objects",
                    current.Id)
                return
            transforms = [current.InstanceXform]
            transforms.extend(outer_transforms)
            path = list(definition_path)
            path.append(definition_id)
            current_node = {
                "transform": va_transform_fingerprint(current.InstanceXform),
                "attributes": va_object_attributes_fingerprint(
                    current.Attributes),
            }
            next_instance_path = list(instance_path)
            next_instance_path.append(current_node)
            next_diagnostic_path = list(diagnostic_path)
            next_diagnostic_path.append({
                "instance_object_id": str(current.Id),
                "definition_id": definition_id,
            })
            for child in children:
                visit(
                    child, transforms, path, depth + 1,
                    next_instance_path, next_diagnostic_path)
            return
        measure_leaf(
            current, outer_transforms, instance_path, diagnostic_path)

    try:
        visit(obj, [], [], 0, [], [])
    except Exception as fingerprint_error:
        fingerprint_errors.append(va_text(fingerprint_error))
        add_error("definition_fingerprint", fingerprint_error, obj.Id)
    fingerprint_leaves.sort(
        key=lambda item: json.dumps(
            item, sort_keys=True, separators=(",", ":")))
    fingerprint_diagnostics.sort(
        key=lambda item: json.dumps(
            item, sort_keys=True, separators=(",", ":")))
    definition_fingerprint = {
        "applicable": True,
        "complete": bool(fingerprint_leaves) and not fingerprint_errors and
            len(fingerprint_leaves) == len(fingerprint_diagnostics) and
            error_count[0] == 0,
        "leaf_count": len(fingerprint_leaves),
        "canonical_leaves": fingerprint_leaves,
        "diagnostic_leaves": fingerprint_diagnostics,
        "errors": fingerprint_errors,
    }
    measurement_complete = volume_geometry_count[0] > 0 and \
        measured_count[0] == volume_geometry_count[0] and error_count[0] == 0
    verified_volume = total_volume[0] if measurement_complete else None
    return {
        "source": source, "applicable": True,
        "volume": verified_volume,
        "partial_volume": total_volume[0] if measured_count[0] > 0 else None,
        "volume_verified": measurement_complete,
        "measurement_complete": measurement_complete,
        "volume_geometry_count": volume_geometry_count[0],
        "measured_volume_geometry_count": measured_count[0],
        "ignored_geometry_types": ignored_geometry_types,
        "components": components, "errors": errors,
        "error_count": error_count[0],
        "components_truncated": volume_geometry_count[0] > len(components),
        "errors_truncated": error_count[0] > len(errors),
        "definition_fingerprint": definition_fingerprint,
    }

def va_enum_snapshot(value):
    if value is None:
        return None
    numeric = None
    try:
        numeric = int(value)
    except Exception:
        pass
    return {"name": va_text(value), "value": numeric}

def va_try_method(method_name, *args):
    if not va_method_available(method_name):
        return None, "method unavailable"
    try:
        return getattr(va, method_name)(*args), None
    except Exception as error:
        return None, va_text(error)

def va_product_snapshot(obj, known_probe=None, include_quantity=True,
                        include_detail=True, style_cache=None):
    import scriptcontext as sc
    classification_probe = known_probe or \
        va_object_classification_probe(obj.Id)
    classifications = classification_probe["classifications"]
    kind = va_primary_kind(classifications)
    if kind is None:
        return None
    layer_name = None
    if obj.Attributes.LayerIndex >= 0:
        layer = sc.doc.Layers[obj.Attributes.LayerIndex]
        if layer is not None:
            layer_name = va_text(layer.FullPath)
    snapshot = {
        "id": str(obj.Id), "kind": kind,
        "runtime_serial_number": int(obj.RuntimeSerialNumber),
        "classifications": classifications,
        "classification_complete": classification_probe["complete"],
        "classification_errors": classification_probe["errors"],
        "name": va_text(obj.Attributes.Name) if obj.Attributes.Name else None,
        "layer": layer_name,
        "detail_included": bool(include_detail),
        "geometry": va_geometry_snapshot(obj.Geometry, include_detail),
    }
    readback_errors = []
    if not classification_probe["complete"]:
        readback_errors.append({
            "method": "classification",
            "error": "one or more classification probes failed",
        })
    if snapshot["geometry"] is None:
        readback_errors.append({
            "method": "RhinoObject.Geometry", "error": "geometry unavailable"})
    style_id, style_error = va_try_method("GetProductStyle", obj.Id)
    if style_error is not None:
        readback_errors.append({
            "method": "GetProductStyle", "error": style_error})
    elif style_id is None or style_id == Guid.Empty:
        readback_errors.append({
            "method": "GetProductStyle", "error": "empty style Guid"})
    else:
        style_text = str(style_id)
        style_snapshot = style_cache.get(style_text) \
            if style_cache is not None else None
        if style_snapshot is None:
            style_name_value, style_name_error = va_try_method(
                "GetStyleName", style_id)
            style_name = va_text(style_name_value) \
                if style_name_error is None else None
            if style_name_error is not None or style_name is None:
                readback_errors.append({
                    "method": "GetStyleName",
                    "error": style_name_error or "name unavailable",
                })
            style_kind = None
            try:
                style_kind = va_style_kind(style_id) \
                    if include_detail else (
                        kind if kind in [
                            "wall", "door", "window", "slab", "space"
                        ] else None)
            except Exception as style_kind_error:
                readback_errors.append({
                    "method": "style inventory",
                    "error": va_text(style_kind_error),
                })
            style_snapshot = {
                "id": style_text, "name": style_name, "kind": style_kind}
            if style_cache is not None:
                style_cache[style_text] = style_snapshot
        snapshot["style_id"] = style_text
        snapshot["style_name"] = style_snapshot["name"]
        snapshot["style"] = style_snapshot
    if kind == "wall":
        height_value, height_error = va_try_method("GetWallHeight", obj.Id)
        snapshot["height"] = va_valid_double(height_value) \
            if height_error is None else None
        if height_error is not None or snapshot["height"] is None:
            readback_errors.append({
                "method": "GetWallHeight",
                "error": height_error or "invalid or unset measurement",
            })
        snapshot["height_source"] = va_enum_snapshot(
            va.GetWallHeightSource(obj.Id)) \
            if include_detail and \
                va_method_available("GetWallHeightSource") else None
        thickness_value, thickness_error = va_try_method(
            "GetWallThickness", obj.Id)
        snapshot["thickness"] = va_valid_double(thickness_value) \
            if thickness_error is None else None
        if thickness_error is not None or snapshot["thickness"] is None:
            readback_errors.append({
                "method": "GetWallThickness",
                "error": thickness_error or "invalid or unset measurement",
            })
        snapshot["alignment"] = va_enum_snapshot(
            va.GetWallAlignment(obj.Id)) \
            if include_detail and va_method_available("GetWallAlignment") \
            else None
        snapshot["alignment_offset"] = va_valid_double(
            va.GetWallAlignmentOffset(obj.Id)) \
            if include_detail and \
                va_method_available("GetWallAlignmentOffset") else None
        snapshot["quantity_included"] = bool(include_quantity)
        snapshot["quantity"] = va_instance_definition_volume_snapshot(obj) \
            if include_quantity else None
        path, path_error = va_try_method("GetWallPathCurve", obj.Id)
        if path_error is not None or path is None:
            readback_errors.append({
                "method": "GetWallPathCurve",
                "error": path_error or "path unavailable",
            })
        else:
            snapshot["path"] = {
                "start": va_point(path.PointAtStart),
                "end": va_point(path.PointAtEnd),
                "length": float(path.GetLength()),
                "type": str(path.GetType().FullName),
                "is_valid": bool(path.IsValid),
            }
        instance_layers = []
        style_text = snapshot.get("style_id")
        if include_detail and style_text is not None:
            wall_layer_inventory = va_wall_layer_ids(Guid(style_text))
            snapshot["wall_layer_inventory"] = {
                "source": wall_layer_inventory["source"],
                "read_complete": wall_layer_inventory["read_complete"],
                "conflicting_nonempty_sources": \
                    wall_layer_inventory["conflicting_nonempty_sources"],
                "sources_agree": wall_layer_inventory["sources_agree"],
            }
            if not wall_layer_inventory["read_complete"]:
                readback_errors.append({
                    "method": "wall layer inventory",
                    "error": "wall layer inventory is unverified",
                })
            for layer_id in wall_layer_inventory["ids"] \
                    if wall_layer_inventory["read_complete"] else []:
                layer = {
                    "id": str(layer_id),
                    "name": va_style_component_name(layer_id),
                }
                if va_method_available("GetWallLayerThickness"):
                    layer["style_thickness"] = va_valid_double(
                        va.GetWallLayerThickness(layer_id))
                    layer["object_thickness"] = va_valid_double(
                        va.GetWallLayerThickness(obj.Id, layer_id))
                if va_method_available("GetWallLayerThicknessSource"):
                    layer["thickness_source"] = va_enum_snapshot(
                        va.GetWallLayerThicknessSource(obj.Id, layer_id))
                thickness_source = layer.get("thickness_source")
                if layer.get("object_thickness") is not None:
                    layer["thickness"] = layer["object_thickness"]
                elif thickness_source is not None and \
                        thickness_source.get("name") == "Style":
                    layer["thickness"] = layer.get("style_thickness")
                else:
                    layer["thickness"] = None
                if va_method_available("GetWallLayerTopOffset"):
                    layer["object_top_offset"] = va_valid_double(
                        va.GetWallLayerTopOffset(obj.Id, layer_id))
                    layer["top_offset"] = layer["object_top_offset"]
                if va_method_available("GetWallLayerTopOffsetSource"):
                    layer["top_offset_source"] = va_enum_snapshot(
                        va.GetWallLayerTopOffsetSource(obj.Id, layer_id))
                if va_method_available("GetWallLayerBottomOffset"):
                    layer["object_bottom_offset"] = va_valid_double(
                        va.GetWallLayerBottomOffset(obj.Id, layer_id))
                    layer["bottom_offset"] = layer["object_bottom_offset"]
                if va_method_available("GetWallLayerBottomOffsetSource"):
                    layer["bottom_offset_source"] = va_enum_snapshot(
                        va.GetWallLayerBottomOffsetSource(obj.Id, layer_id))
                instance_layers.append(layer)
        if include_detail:
            snapshot["layers"] = instance_layers \
                if style_text is None or \
                    wall_layer_inventory["read_complete"] else None
        else:
            snapshot["layers"] = None
    elif kind == "slab":
        tolerance = float(sc.doc.ModelAbsoluteTolerance)
        contour, contour_error = va_try_method("GetSlabContour", obj.Id)
        if contour_error is not None or contour is None:
            snapshot["contour"] = None
            readback_errors.append({
                "method": "GetSlabContour",
                "error": contour_error or "contour unavailable",
            })
        else:
            try:
                snapshot["contour"] = va_slab_contour_snapshot(
                    contour, tolerance)
            except Exception as error:
                snapshot["contour"] = None
                readback_errors.append({
                    "method": "GetSlabContour", "error": va_text(error)})
        thickness_value, thickness_error = va_try_method(
            "GetSlabThickness", obj.Id)
        snapshot["thickness"] = va_valid_double(thickness_value) \
            if thickness_error is None else None
        if thickness_error is not None or snapshot["thickness"] is None or \
                snapshot["thickness"] <= tolerance:
            readback_errors.append({
                "method": "GetSlabThickness",
                "error": thickness_error or "thickness is not positive",
            })
        alignment_value, alignment_error = va_try_method(
            "GetSlabAlignment", obj.Id)
        snapshot["alignment"] = va_enum_snapshot(alignment_value) \
            if alignment_error is None else None
        if alignment_error is not None or snapshot["alignment"] is None:
            readback_errors.append({
                "method": "GetSlabAlignment",
                "error": alignment_error or "alignment unavailable",
            })
        contour_snapshot = snapshot.get("contour")
        alignment_name = (snapshot.get("alignment") or {}).get("name")
        thickness = snapshot.get("thickness")
        snapshot["semantic_bbox"] = None
        if contour_snapshot is not None and thickness is not None and \
                alignment_name is not None:
            contour_bbox = contour_snapshot["bbox"]
            if alignment_name == "Top":
                top = float(contour_bbox["max"][2])
                bottom = top - thickness
            elif alignment_name == "Bottom":
                bottom = float(contour_bbox["min"][2])
                top = bottom + thickness
            elif alignment_name in [
                    "Center", "Centre", "Centered", "Centred", "Middle"]:
                center = (float(contour_bbox["min"][2]) +
                          float(contour_bbox["max"][2])) / 2.0
                bottom = center - thickness / 2.0
                top = center + thickness / 2.0
            else:
                readback_errors.append({
                    "method": "GetSlabAlignment",
                    "error": "unsupported alignment: " + alignment_name,
                })
                bottom = None
                top = None
            if bottom is not None and top is not None:
                try:
                    snapshot["semantic_bbox"] = va_semantic_vertical_bbox(
                        contour_bbox, bottom, top)
                except Exception as error:
                    readback_errors.append({
                        "method": "semantic slab bbox",
                        "error": va_text(error),
                    })
        if snapshot["semantic_bbox"] is None:
            readback_errors.append({
                "method": "semantic slab bbox",
                "error": "semantic slab bounds are unavailable",
            })
    elif kind == "space":
        tolerance = float(sc.doc.ModelAbsoluteTolerance)
        boundary, boundary_error = va_try_method("GetSpaceCurve", obj.Id)
        if boundary_error is not None or boundary is None:
            snapshot["boundary"] = None
            readback_errors.append({
                "method": "GetSpaceCurve",
                "error": boundary_error or "boundary unavailable",
            })
        else:
            try:
                snapshot["boundary"] = va_horizontal_curve_snapshot(
                    boundary, tolerance)
            except Exception as error:
                snapshot["boundary"] = None
                readback_errors.append({
                    "method": "GetSpaceCurve", "error": va_text(error)})
        for key, method_name in [
                ("area", "GetSpaceArea"),
                ("perimeter", "GetSpacePerimeter"),
                ("height", "GetSpaceHeight"),
                ("elevation", "GetSpaceElevation")]:
            value, value_error = va_try_method(method_name, obj.Id)
            snapshot[key] = va_valid_double(value) \
                if value_error is None else None
            positive_required = key in ["area", "perimeter", "height"]
            invalid = snapshot[key] is None or (
                positive_required and snapshot[key] <= (
                    tolerance * tolerance if key == "area" else tolerance))
            if value_error is not None or invalid:
                readback_errors.append({
                    "method": method_name,
                    "error": value_error or "measurement is invalid",
                })
        label_value, label_error = va_try_method(
            "GetSpaceLabelPosition", obj.Id)
        snapshot["label_position"] = va_point(label_value) \
            if label_error is None and label_value is not None else None
        if label_error is not None or snapshot["label_position"] is None:
            readback_errors.append({
                "method": "GetSpaceLabelPosition",
                "error": label_error or "label position unavailable",
            })
        if include_detail:
            for key, method_name in [
                    ("effective_height", "GetSpaceEffectiveHeight"),
                    ("volume", "GetSpaceVolume")]:
                value, value_error = va_try_method(method_name, obj.Id)
                snapshot[key] = va_valid_double(value) \
                    if value_error is None else None
                if value_error is not None or snapshot[key] is None:
                    readback_errors.append({
                        "method": method_name,
                        "error": value_error or "measurement is invalid",
                    })
            point_value, point_error = va_try_method("GetSpacePoint", obj.Id)
            snapshot["reference_point"] = va_point(point_value) \
                if point_error is None and point_value is not None else None
            if point_error is not None or snapshot["reference_point"] is None:
                readback_errors.append({
                    "method": "GetSpacePoint",
                    "error": point_error or "reference point unavailable",
                })
        boundary_snapshot = snapshot.get("boundary")
        elevation = snapshot.get("elevation")
        height = snapshot.get("height")
        snapshot["semantic_bbox"] = None
        if boundary_snapshot is not None and elevation is not None and \
                height is not None:
            boundary_bbox = boundary_snapshot["bbox"]
            if abs(float(boundary_bbox["min"][2]) - elevation) > tolerance or \
                    abs(float(boundary_bbox["max"][2]) -
                        elevation) > tolerance:
                readback_errors.append({
                    "method": "GetSpaceCurve/GetSpaceElevation",
                    "error": "boundary elevation does not match Space",
                })
            else:
                try:
                    snapshot["semantic_bbox"] = va_semantic_vertical_bbox(
                        boundary_bbox, elevation, elevation + height)
                except Exception as error:
                    readback_errors.append({
                        "method": "semantic Space bbox",
                        "error": va_text(error),
                    })
            measured_area = boundary_snapshot.get("area")
            measured_perimeter = boundary_snapshot.get("perimeter")
            if measured_area is not None and snapshot.get("area") is not None \
                    and abs(measured_area - snapshot["area"]) > max(
                        tolerance * tolerance, measured_area * 0.001):
                readback_errors.append({
                    "method": "GetSpaceArea",
                    "error": "Space area disagrees with semantic boundary",
                })
            if measured_perimeter is not None and \
                    snapshot.get("perimeter") is not None and \
                    abs(measured_perimeter - snapshot["perimeter"]) > max(
                        tolerance, measured_perimeter * 0.001):
                readback_errors.append({
                    "method": "GetSpacePerimeter",
                    "error": (
                        "Space perimeter disagrees with semantic boundary"),
                })
        if snapshot["semantic_bbox"] is None:
            readback_errors.append({
                "method": "semantic Space bbox",
                "error": "semantic Space bounds are unavailable",
            })
    if kind == "door" or kind == "window":
        host_readbacks = []
        valid_host_ids = []
        for host_method in [
                "GetOpeningHost", "GetDoorHostId", "GetDoorWallId"]:
            if not va_method_available(host_method):
                continue
            host_id, host_error = va_try_method(host_method, obj.Id)
            host_text = str(host_id) if host_error is None and \
                host_id is not None and host_id != Guid.Empty else None
            host_readbacks.append({
                "source": host_method, "id": host_text,
                "error": host_error,
            })
            if host_text is not None:
                valid_host_ids.append(host_text)
        unique_host_ids = sorted(set(valid_host_ids))
        snapshot["host_id"] = unique_host_ids[0] \
            if len(unique_host_ids) == 1 else None
        snapshot["host_readbacks"] = host_readbacks
        if len(unique_host_ids) != 1:
            readback_errors.append({
                "method": "opening host getters",
                "error": "no unique non-empty host Guid",
            })
        profile_id, profile_error = va_try_method("GetOpeningProfile", obj.Id)
        snapshot["profile_id"] = str(profile_id) \
            if profile_error is None and profile_id is not None and \
                profile_id != Guid.Empty else None
        if profile_error is not None or snapshot["profile_id"] is None:
            readback_errors.append({
                "method": "GetOpeningProfile",
                "error": profile_error or "empty profile Guid",
            })
    snapshot["readback_complete"] = len(readback_errors) == 0
    snapshot["readback_errors"] = readback_errors
    return snapshot
"""


_PLANAR_PRODUCT_CREATION_BODY = r"""
import scriptcontext as sc

def va_near(left, right, tolerance):
    return abs(float(left) - float(right)) <= float(tolerance)

def va_point_near(left, right, tolerance):
    return left is not None and right is not None and len(left) == 3 and \
        len(right) == 3 and all(
            va_near(left[index], right[index], tolerance)
            for index in range(3))

def va_bbox_near(left, right, tolerance):
    return left is not None and right is not None and \
        va_point_near(left.get("min"), right.get("min"), tolerance) and \
        va_point_near(left.get("max"), right.get("max"), tolerance)

def va_active_id_set():
    return set(str(obj.Id) for obj in sc.doc.Objects)

def va_new_kind_candidates(runtime_floor, kind, style_id):
    candidates = []
    errors = []
    predicate_name = "IsSlab" if kind == "slab" else "IsSpace"
    try:
        recent_objects = sc.doc.Objects.AllObjectsSince(
            max(int(runtime_floor) - 1, 0)) or []
        for recent in recent_objects:
            current = sc.doc.Objects.FindId(recent.Id)
            if current is None or int(current.RuntimeSerialNumber) != int(
                    recent.RuntimeSerialNumber):
                continue
            try:
                if getattr(va, predicate_name)(current.Id) and \
                        va.GetProductStyle(current.Id) == style_id:
                    candidates.append({
                        "id": str(current.Id),
                        "runtime_serial_number": int(
                            current.RuntimeSerialNumber),
                    })
            except Exception as error:
                errors.append({
                    "object_id": str(current.Id), "error": va_text(error)})
    except Exception as error:
        errors.append({"stage": "AllObjectsSince", "error": va_text(error)})
    candidates.sort(key=lambda item: (
        item["runtime_serial_number"], item["id"]))
    return candidates, errors

kind = params["kind"]
style_id, style_error = va_resolve_style(params["style"], kind)
if style_error is not None:
    result = style_error
else:
    if kind == "slab":
        add_shape = va_exact_method_shape("AddSlabFromCurve", [
            "System.Guid", "Rhino.Geometry.Curve",
            "VisualARQ.Script+SlabAlignment"])
        required_methods = [
            "AddSlabFromCurve", "IsSlab", "IsProduct",
            "GetProductStyle", "GetStyleName", "GetProductsByStyle",
            "GetSlabContour", "GetSlabThickness", "GetSlabAlignment",
            "GetSlabLayers", "IsSlabLayer", "GetSlabLayerThickness",
            "GetSlabLayerType", "GetSubStyleComponents",
            "GetStyleComponentName",
        ]
        setter_shapes = {}
    else:
        add_shape = va_exact_method_shape("AddSpaceFromCurve", [
            "System.Guid", "Rhino.Geometry.Curve"])
        required_methods = [
            "AddSpaceFromCurve", "IsSpace", "IsProduct",
            "GetProductStyle", "GetStyleName", "GetProductsByStyle",
            "GetSpaceCurve", "GetSpaceArea", "GetSpacePerimeter",
            "GetSpaceHeight", "GetSpaceElevation",
            "GetSpaceLabelPosition", "SetSpaceHeight",
            "SetSpaceElevation", "SetSpaceLabelPosition",
        ]
        setter_shapes = {
            "SetSpaceHeight": va_exact_method_shape(
                "SetSpaceHeight", ["System.Guid", "System.Double"],
                "System.Boolean"),
            "SetSpaceElevation": va_exact_method_shape(
                "SetSpaceElevation", ["System.Guid", "System.Double"],
                "System.Boolean"),
            "SetSpaceLabelPosition": va_exact_method_shape(
                "SetSpaceLabelPosition", [
                    "System.Guid", "Rhino.Geometry.Point3d"],
                "System.Boolean"),
        }
    missing_methods = [
        method_name for method_name in required_methods
        if not va_method_available(method_name)]
    unverified_setters = [
        method_name for method_name in sorted(setter_shapes.keys())
        if setter_shapes[method_name]["verified"] is not True]
    style_actual = va_style_snapshot(style_id) \
        if not missing_methods and add_shape["verified"] else None
    if add_shape["verified"] is not True:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": kind + "_add_signature_unverified",
            "message": (
                "VisualARQ " + kind +
                " creation has no unique supported CLR signature; " +
                "the document was not mutated"),
            "shape": add_shape,
        }
    elif missing_methods or unverified_setters:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": kind + "_creation_contract_api_incomplete",
            "message": (
                "VisualARQ " + kind +
                " API cannot satisfy verified creation"),
            "missing_methods": missing_methods,
            "unverified_setter_shapes": unverified_setters,
            "setter_shapes": setter_shapes,
        }
    elif style_actual is None or \
            style_actual.get("readback_complete") is not True:
        result = {
            "status": "error", "code": "VERIFICATION_FAILED",
            "reason": kind + "_style_readback_unverified",
            "message": (
                "Resolved VisualARQ " + kind +
                " style could not be read back completely"),
            "style": style_actual,
        }
    elif kind == "slab" and (
            style_actual.get("layer_count") is None or
            style_actual.get("layer_count") < 1 or
            style_actual.get("total_layer_thickness") is None or
            style_actual.get("total_layer_thickness") <= 0.0):
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": "slab_style_has_no_measurable_layers",
            "message": (
                "Slab style needs at least one positive-thickness layer"),
            "style": style_actual,
        }
    else:
        tolerance = float(sc.doc.ModelAbsoluteTolerance)
        points = [
            rg.Point3d(float(item[0]), float(item[1]), float(item[2]))
            for item in params["boundary"]]
        boundary = rg.Polyline(points).ToNurbsCurve()
        try:
            expected_boundary = va_horizontal_curve_snapshot(
                boundary, tolerance)
        except Exception as error:
            result = {
                "status": "error", "code": "INVALID_PARAMS",
                "message": (
                    "Boundary fails the connected document tolerance: " +
                    va_text(error)),
                "tolerance": tolerance,
            }
        else:
            expected_elevation = float(params["boundary"][0][2])
            expected_alignment = params.get("alignment")
            label_point = rg.Point3d(
                float(params["label_point"][0]),
                float(params["label_point"][1]),
                float(params["label_point"][2])) \
                if kind == "space" else None
            ids_before = va_active_id_set()
            modified_before = bool(sc.doc.Modified)
            runtime_floor = int(
                Rhino.DocObjects.RhinoObject.NextRuntimeSerialNumber)
            created_id = Guid.Empty
            created_serial = None
            mutation_error = None
            try:
                if kind == "slab":
                    alignment_value = {
                        "top": va.SlabAlignment.Top,
                        "center": va.SlabAlignment.Center,
                        "bottom": va.SlabAlignment.Bottom,
                    }[params["alignment"]]
                    created_id = va.AddSlabFromCurve(
                        style_id, boundary, alignment_value)
                else:
                    created_id = va.AddSpaceFromCurve(style_id, boundary)
                if created_id is None or created_id == Guid.Empty:
                    raise Exception(
                        "VisualARQ creation returned an empty Guid")
                if str(created_id) in ids_before:
                    raise Exception(
                        "VisualARQ creation returned a pre-existing Guid")
                created_obj = sc.doc.Objects.FindId(created_id)
                if created_obj is None:
                    raise Exception("Created object is not document-resident")
                created_serial = int(created_obj.RuntimeSerialNumber)
                if created_serial < runtime_floor:
                    raise Exception(
                        "Created object generation predates this command")
                if kind == "space":
                    current_elevation = va_valid_double(
                        va.GetSpaceElevation(created_id))
                    if current_elevation is None:
                        raise Exception(
                            "GetSpaceElevation returned an invalid value")
                    # VA 3.7.2 returns false for a no-op elevation assignment.
                    # Treat matching readback as success and mutate only when
                    # the requested elevation actually differs.
                    if not va_near(
                            current_elevation, expected_elevation,
                            tolerance) and not bool(va.SetSpaceElevation(
                                created_id, expected_elevation)):
                        raise Exception("SetSpaceElevation returned false")
                    if not bool(va.SetSpaceHeight(
                            created_id, float(params["height"]))):
                        raise Exception("SetSpaceHeight returned false")
                    if not bool(va.SetSpaceLabelPosition(
                            created_id, label_point)):
                        raise Exception("SetSpaceLabelPosition returned false")
                sc.doc.Views.Redraw()
            except Exception as error:
                mutation_error = va_text(error)

            candidates, candidate_errors = va_new_kind_candidates(
                runtime_floor, kind, style_id)
            ids_after = va_active_id_set()
            delta_ids = sorted(ids_after - ids_before)
            created_obj = sc.doc.Objects.FindId(created_id) \
                if created_id is not None and created_id != Guid.Empty \
                else None
            current_serial = int(created_obj.RuntimeSerialNumber) \
                if created_obj is not None else None
            generation_matches = created_serial is not None and \
                current_serial == created_serial
            snapshot = None
            snapshot_error = None
            if created_obj is not None and generation_matches:
                try:
                    snapshot = va_product_snapshot(
                        created_obj, None, False, False)
                except Exception as error:
                    snapshot_error = va_text(error)

            checks = {
                "mutation_raised_no_error": mutation_error is None,
                "returned_guid_is_new": (
                    created_id is not None and created_id != Guid.Empty and
                    str(created_id) not in ids_before),
                "document_object_exists": created_obj is not None,
                "runtime_generation_matches": generation_matches,
                "exactly_one_matching_new_generation": (
                    len(candidates) == 1 and created_id != Guid.Empty and
                    candidates[0]["id"] == str(created_id) and
                    candidates[0]["runtime_serial_number"] ==
                        created_serial),
                "no_candidate_scan_errors": len(candidate_errors) == 0,
                "top_level_delta_is_exact": (
                    created_id != Guid.Empty and
                    delta_ids == [str(created_id)]),
                "snapshot_complete": (
                    snapshot is not None and
                    snapshot.get("readback_complete") is True),
                "kind_matches": (
                    snapshot is not None and snapshot.get("kind") == kind),
                "style_matches": (
                    snapshot is not None and
                    snapshot.get("style_id") == str(style_id)),
            }
            if kind == "slab":
                actual_boundary = (snapshot or {}).get("contour") or {}
                actual_alignment = (
                    (snapshot or {}).get("alignment") or {}).get("name")
                checks.update({
                    "boundary_area_matches": (
                        actual_boundary.get("area") is not None and
                        va_near(
                            actual_boundary["area"],
                            expected_boundary["area"],
                            max(tolerance * tolerance,
                                expected_boundary["area"] * 0.001))),
                    "boundary_bbox_matches": va_bbox_near(
                        actual_boundary.get("bbox"),
                        expected_boundary["bbox"], tolerance),
                    "alignment_matches": (
                        actual_alignment is not None and
                        va_text_key(actual_alignment) ==
                        va_text_key(expected_alignment)),
                    "thickness_is_positive": (
                        (snapshot or {}).get("thickness") is not None and
                        (snapshot or {}).get("thickness") > tolerance),
                    "semantic_bbox_available": (
                        (snapshot or {}).get("semantic_bbox") is not None),
                })
            else:
                actual_boundary = (snapshot or {}).get("boundary") or {}
                checks.update({
                    "boundary_area_matches": (
                        actual_boundary.get("area") is not None and
                        va_near(
                            actual_boundary["area"],
                            expected_boundary["area"],
                            max(tolerance * tolerance,
                                expected_boundary["area"] * 0.001))),
                    "boundary_bbox_matches": va_bbox_near(
                        actual_boundary.get("bbox"),
                        expected_boundary["bbox"], tolerance),
                    "height_matches": (
                        (snapshot or {}).get("height") is not None and
                        va_near((snapshot or {})["height"],
                                params["height"], tolerance)),
                    "elevation_matches": (
                        (snapshot or {}).get("elevation") is not None and
                        va_near((snapshot or {})["elevation"],
                                expected_elevation, tolerance)),
                    "label_position_matches": va_point_near(
                        (snapshot or {}).get("label_position"),
                        params["label_point"], tolerance),
                    "semantic_bbox_available": (
                        (snapshot or {}).get("semantic_bbox") is not None),
                })
            verification_pass = all(checks.values())
            if verification_pass:
                result = {
                    "status": "success", "kind": kind,
                    "object_id": str(created_id),
                    "runtime_serial_number": created_serial,
                    "style": style_actual,
                    "object": snapshot,
                    "requested": {
                        "style": params["style"],
                        "boundary": params["boundary"],
                        "alignment": expected_alignment,
                        "height": params.get("height"),
                        "label_point": params.get("label_point"),
                    },
                    "verification": {
                        "pass": True,
                        "checks": checks,
                        "candidate_scan_errors": candidate_errors,
                        "top_level_delta_ids": delta_ids,
                        "snapshot_error": snapshot_error,
                        "document_tolerance": tolerance,
                    },
                }
            else:
                cleanup_obj = sc.doc.Objects.FindId(created_id) \
                    if created_id is not None and created_id != Guid.Empty \
                    else None
                cleanup_serial = int(cleanup_obj.RuntimeSerialNumber) \
                    if cleanup_obj is not None else None
                cleanup_owned = cleanup_obj is not None and \
                    created_serial is not None and \
                    cleanup_serial == created_serial and \
                    str(created_id) not in ids_before
                cleanup_deleted = False
                if cleanup_owned:
                    cleanup_deleted = bool(
                        sc.doc.Objects.Delete(created_id, True))
                sc.doc.Views.Redraw()
                residual_ids = sorted(va_active_id_set() - ids_before)
                cleanup_exists = created_id is not None and \
                    created_id != Guid.Empty and \
                    sc.doc.Objects.FindId(created_id) is not None
                cleanup_verified = not residual_ids and not cleanup_exists
                if cleanup_verified:
                    sc.doc.Modified = modified_before
                result = {
                    "status": "error",
                    "code": "VERIFICATION_FAILED"
                        if cleanup_verified else "PARTIAL_MUTATION",
                    "message": (
                        "VisualARQ " + kind +
                        " failed independent post-creation verification; " +
                        ("the command-owned object was removed"
                         if cleanup_verified else
                         "a document delta remains for user review")),
                    "kind": kind,
                    "object_id": str(created_id)
                        if created_id is not None and
                            created_id != Guid.Empty else None,
                    "style": style_actual,
                    "object": snapshot,
                    "verification": {
                        "pass": False,
                        "checks": checks,
                        "mutation_error": mutation_error,
                        "candidate_scan_errors": candidate_errors,
                        "matching_candidates": candidates,
                        "top_level_delta_ids": delta_ids,
                        "snapshot_error": snapshot_error,
                        "document_tolerance": tolerance,
                    },
                    "cleanup": {
                        "ownership_proven": cleanup_owned,
                        "deleted": cleanup_deleted,
                        "object_exists": cleanup_exists,
                        "residual_delta_ids": residual_ids,
                        "verified": cleanup_verified,
                        "modified_restored": (
                            cleanup_verified and
                            bool(sc.doc.Modified) == modified_before),
                    },
                }
"""


_OPENING_HOST_SCRIPT_HELPERS = r"""
def va_opening_host_wall_state(wall_obj):
    errors = []
    geometry_crc = None
    bbox_values = None
    style_text = None
    height_value = None
    thickness_value = None
    path_values = None
    outer_attributes = None
    try:
        geometry = wall_obj.Geometry
        geometry_crc = int(geometry.DataCRC(System.UInt32(0)))
        bbox = geometry.GetBoundingBox(True)
        if not bbox.IsValid:
            raise Exception("host wall bounding box is invalid")
        bbox_values = {
            "min": [bbox.Min.X, bbox.Min.Y, bbox.Min.Z],
            "max": [bbox.Max.X, bbox.Max.Y, bbox.Max.Z],
        }
    except Exception as error:
        errors.append({
            "stage": "geometry_state", "error": va_text(error)})
    try:
        outer_attributes = va_object_attributes_fingerprint(
            wall_obj.Attributes)
    except Exception as error:
        errors.append({
            "stage": "outer_attributes", "error": va_text(error)})
    try:
        candidate_style_id = va.GetProductStyle(wall_obj.Id)
        if candidate_style_id is None or candidate_style_id == Guid.Empty:
            raise Exception("host wall style Guid is empty")
        style_text = str(candidate_style_id)
    except Exception as error:
        errors.append({"stage": "style", "error": va_text(error)})
    try:
        height_value = va_valid_double(va.GetWallHeight(wall_obj.Id))
        thickness_value = va_valid_double(va.GetWallThickness(wall_obj.Id))
        if height_value is None or thickness_value is None:
            raise Exception("host height or thickness is invalid/unset")
    except Exception as error:
        errors.append({
            "stage": "wall_dimensions", "error": va_text(error)})
    try:
        path = va.GetWallPathCurve(wall_obj.Id)
        if path is None or not path.IsValid:
            raise Exception("host wall path is invalid")
        path_values = {
            "start": va_point(path.PointAtStart),
            "end": va_point(path.PointAtEnd),
            "length": float(path.GetLength()),
            "type": str(path.GetType().FullName),
        }
    except Exception as error:
        errors.append({"stage": "wall_path", "error": va_text(error)})
    quantity = va_instance_definition_volume_snapshot(wall_obj)
    definition_fingerprint = quantity.get("definition_fingerprint")
    if definition_fingerprint is None or \
            definition_fingerprint.get("complete") is not True:
        errors.append({
            "stage": "definition_fingerprint",
            "error": (
                "host wall instance-definition fingerprint is incomplete"),
            "fingerprint_errors": definition_fingerprint.get("errors")
                if definition_fingerprint is not None else None,
        })
    if quantity.get("measurement_complete") is not True or \
            quantity.get("volume_verified") is not True or \
            quantity.get("volume") is None:
        errors.append({
            "stage": "host_volume",
            "error": "host wall solid volume is not verified",
            "quantity_errors": quantity.get("errors"),
        })
    return {
        "id": str(wall_obj.Id),
        "runtime_serial_number": int(wall_obj.RuntimeSerialNumber),
        "geometry_crc": geometry_crc,
        "outer_attributes": outer_attributes,
        "bbox": bbox_values,
        "style_id": style_text,
        "height": height_value,
        "thickness": thickness_value,
        "path": path_values,
        "volume": quantity.get("volume"),
        "volume_source": quantity.get("source"),
        "quantity": quantity,
        "definition_fingerprint": definition_fingerprint,
        "readback_complete": not errors,
        "readback_errors": errors,
    }

def va_opening_host_wall_semantics_match(
        before_state, after_state, tolerance):
    if before_state is None or after_state is None or \
            before_state.get("readback_complete") is not True or \
            after_state.get("readback_complete") is not True:
        return False
    if before_state.get("id") != after_state.get("id") or \
            before_state.get("style_id") != after_state.get("style_id") or \
            before_state.get("outer_attributes") != \
                after_state.get("outer_attributes"):
        return False
    for field in ["height", "thickness"]:
        if before_state.get(field) is None or \
                after_state.get(field) is None or abs(
                    before_state[field] - after_state[field]
                ) > tolerance:
            return False
    before_path = before_state.get("path")
    after_path = after_state.get("path")
    if before_path is None or after_path is None or \
            before_path.get("type") != after_path.get("type") or abs(
                before_path["length"] - after_path["length"]
            ) > tolerance:
        return False
    for key in ["start", "end"]:
        if rg.Point3d(*before_path[key]).DistanceTo(
                rg.Point3d(*after_path[key])) > tolerance:
            return False
    before_bbox = before_state.get("bbox")
    after_bbox = after_state.get("bbox")
    if before_bbox is None or after_bbox is None:
        return False
    for key in ["min", "max"]:
        if rg.Point3d(*before_bbox[key]).DistanceTo(
                rg.Point3d(*after_bbox[key])) > tolerance:
            return False
    return True

def va_opening_host_wall_state_matches(
        before_state, after_state, tolerance):
    return va_opening_host_wall_semantics_match(
        before_state, after_state, tolerance) and \
        va_instance_definition_fingerprints_match(
            before_state.get("definition_fingerprint"),
            after_state.get("definition_fingerprint"))
"""


_HIERARCHY_SCRIPT_HELPERS = r"""
def va_hierarchy_guid_text(value):
    if value is None or value == Guid.Empty:
        return None
    return str(value)

def va_hierarchy_snapshot():
    required_methods = [
        "GetAllBuildingIds", "GetBuildingLevelIds", "GetBuildingName",
        "GetBuildingElevation", "IsBuilding", "GetLevelName",
        "GetLevelElevation", "IsLevel",
    ]
    missing_methods = [
        method_name for method_name in required_methods
        if not va_method_available(method_name)
    ]
    snapshot = {
        "buildings": [], "levels": [],
        "verification": {
            "pass": False,
            "source": (
                "VisualARQ GetAllBuildingIds/GetBuildingLevelIds plus "
                "optional GetAllLevelIds and getter readback"),
            "missing_methods": missing_methods,
            "global_level_inventory_available": \
                va_method_available("GetAllLevelIds"),
            "inventory_scope": "global" \
                if va_method_available("GetAllLevelIds") \
                else "building_reachable",
            "orphan_check_available": \
                va_method_available("GetAllLevelIds"),
            "mutation_baseline_complete": \
                va_method_available("GetAllLevelIds"),
            "state_fields": [
                "name", "elevation", "owner", "classification"] + (
                    ["cut_elevation"]
                    if va_method_available("GetLevelCutElevation") else []),
            "unavailable_state_fields": []
                if va_method_available("GetLevelCutElevation")
                else ["cut_elevation"],
            "duplicate_building_ids": [],
            "duplicate_level_ids": [],
            "duplicate_membership_edges": [],
            "orphan_level_ids": [],
            "unknown_member_level_ids": [],
            "duplicate_owner_level_ids": [],
            "cross_kind_guid_collisions": [],
            "owner_conflicts": [],
            "readback_errors": [],
        },
    }
    if missing_methods:
        return snapshot

    verification = snapshot["verification"]
    readback_errors = verification["readback_errors"]

    def add_error(stage, message, object_id=None, method=None):
        item = {"stage": stage, "error": va_text(message)}
        if object_id is not None:
            item["id"] = str(object_id)
        if method is not None:
            item["method"] = method
        readback_errors.append(item)

    try:
        raw_building_ids = list(va.GetAllBuildingIds() or [])
    except Exception as error:
        add_error("building_inventory", error, method="GetAllBuildingIds")
        return snapshot
    raw_level_ids = []
    if va_method_available("GetAllLevelIds"):
        try:
            raw_level_ids = list(va.GetAllLevelIds() or [])
        except Exception as error:
            add_error("level_inventory", error, method="GetAllLevelIds")
            return snapshot

    building_values = {}
    building_texts = []
    for building_id in raw_building_ids:
        building_text = va_hierarchy_guid_text(building_id)
        if building_text is None:
            add_error("building_inventory", "empty building Guid")
            continue
        building_texts.append(building_text)
        if building_text not in building_values:
            building_values[building_text] = building_id
    verification["duplicate_building_ids"] = sorted(
        set(value for value in building_texts
            if building_texts.count(value) > 1))

    level_values = {}
    level_texts = []
    for level_id in raw_level_ids:
        level_text = va_hierarchy_guid_text(level_id)
        if level_text is None:
            add_error("level_inventory", "empty level Guid")
            continue
        level_texts.append(level_text)
        if level_text not in level_values:
            level_values[level_text] = level_id
    verification["duplicate_level_ids"] = sorted(
        set(value for value in level_texts if level_texts.count(value) > 1))

    memberships = {}
    membership_edges = []
    duplicate_edges = []
    building_snapshots = {}
    for building_text in sorted(building_values):
        building_id = building_values[building_text]
        local_errors = []

        def building_error(method_name, message):
            item = {"method": method_name, "error": va_text(message)}
            local_errors.append(item)
            add_error("building_readback", message, building_text, method_name)

        name = None
        elevation = None
        classified = None
        member_texts = []
        try:
            name = va_text(va.GetBuildingName(building_id))
            if name is None or not name.Trim():
                building_error("GetBuildingName", "building name is empty")
        except Exception as error:
            building_error("GetBuildingName", error)
        try:
            elevation = va_valid_double(va.GetBuildingElevation(building_id))
            if elevation is None:
                building_error(
                    "GetBuildingElevation", "invalid or unset elevation")
        except Exception as error:
            building_error("GetBuildingElevation", error)
        try:
            classified = bool(va.IsBuilding(building_id))
            if not classified:
                building_error("IsBuilding", "building classification is false")
        except Exception as error:
            building_error("IsBuilding", error)
        try:
            raw_members = list(va.GetBuildingLevelIds(building_id) or [])
            for member_id in raw_members:
                member_text = va_hierarchy_guid_text(member_id)
                if member_text is None:
                    building_error(
                        "GetBuildingLevelIds", "empty member level Guid")
                    continue
                edge = (building_text, member_text)
                if edge in membership_edges:
                    duplicate_edges.append(edge)
                else:
                    membership_edges.append(edge)
                member_texts.append(member_text)
                memberships.setdefault(member_text, []).append(building_text)
                if not verification["global_level_inventory_available"] and \
                        member_text not in level_values:
                    level_values[member_text] = member_id
                    level_texts.append(member_text)
        except Exception as error:
            building_error("GetBuildingLevelIds", error)

        building_snapshot = {
            "id": building_text,
            "name": name,
            "elevation": elevation,
            "classified_as_building": classified,
            "level_ids": sorted(set(member_texts)),
            "readback_complete": len(local_errors) == 0,
            "readback_errors": local_errors,
        }
        building_snapshots[building_text] = building_snapshot
        snapshot["buildings"].append(building_snapshot)

    verification["duplicate_membership_edges"] = [
        {"building_id": building_id, "level_id": level_id}
        for building_id, level_id in sorted(set(duplicate_edges))
    ]
    verification["duplicate_level_ids"] = sorted(
        set(value for value in level_texts if level_texts.count(value) > 1))
    global_level_ids = set(level_values)
    member_level_ids = set(memberships)
    verification["orphan_level_ids"] = sorted(
        global_level_ids - member_level_ids)
    verification["unknown_member_level_ids"] = sorted(
        member_level_ids - global_level_ids)
    verification["duplicate_owner_level_ids"] = sorted(
        level_id for level_id, owner_ids in memberships.items()
        if len(set(owner_ids)) > 1)
    verification["cross_kind_guid_collisions"] = sorted(
        set(building_values) & set(level_values))

    owner_getters = [
        method_name for method_name in
        ["GetLevelBuildingId", "GetLevelBuidlingId"]
        if va_method_available(method_name)
    ]
    owner_conflicts = []
    for level_text in sorted(level_values):
        level_id = level_values[level_text]
        local_errors = []

        def level_error(method_name, message):
            item = {"method": method_name, "error": va_text(message)}
            local_errors.append(item)
            add_error("level_readback", message, level_text, method_name)

        name = None
        elevation = None
        classified = None
        cut_elevation = None
        cut_elevation_error = None
        try:
            name = va_text(va.GetLevelName(level_id))
            if name is None or not name.Trim():
                level_error("GetLevelName", "level name is empty")
        except Exception as error:
            level_error("GetLevelName", error)
        try:
            elevation = va_valid_double(va.GetLevelElevation(level_id))
            if elevation is None:
                level_error("GetLevelElevation", "invalid or unset elevation")
        except Exception as error:
            level_error("GetLevelElevation", error)
        try:
            classified = bool(va.IsLevel(level_id))
            if not classified:
                level_error("IsLevel", "level classification is false")
        except Exception as error:
            level_error("IsLevel", error)
        if va_method_available("GetLevelCutElevation"):
            try:
                cut_elevation = va_valid_double(
                    va.GetLevelCutElevation(level_id))
                if cut_elevation is None:
                    cut_elevation_error = "invalid or unset cut elevation"
                    level_error(
                        "GetLevelCutElevation", cut_elevation_error)
            except Exception as error:
                cut_elevation_error = va_text(error)
                level_error("GetLevelCutElevation", error)

        membership_owner_ids = sorted(set(memberships.get(level_text, [])))
        direct_owner_readbacks = []
        direct_owner_ids = []
        for owner_getter in owner_getters:
            try:
                owner_id = getattr(va, owner_getter)(level_id)
                owner_text = va_hierarchy_guid_text(owner_id)
                if owner_text is None:
                    raise Exception("owner getter returned an empty Guid")
                direct_owner_ids.append(owner_text)
                direct_owner_readbacks.append({
                    "method": owner_getter,
                    "building_id": owner_text,
                    "error": None,
                })
            except Exception as error:
                direct_owner_readbacks.append({
                    "method": owner_getter,
                    "building_id": None,
                    "error": va_text(error),
                })
                level_error(owner_getter, error)

        membership_owner = membership_owner_ids[0] \
            if len(membership_owner_ids) == 1 else None
        owner_verified = membership_owner is not None and all(
            owner_id == membership_owner for owner_id in direct_owner_ids)
        owner_conflict = not owner_verified or \
            len(set(direct_owner_ids)) > 1
        if owner_conflict:
            owner_conflicts.append({
                "level_id": level_text,
                "membership_owner_ids": membership_owner_ids,
                "direct_owner_ids": sorted(set(direct_owner_ids)),
            })
        building = building_snapshots.get(membership_owner) \
            if membership_owner is not None else None
        level_snapshot = {
            "id": level_text,
            "name": name,
            "elevation": elevation,
            "cut_elevation": cut_elevation,
            "cut_elevation_error": cut_elevation_error,
            "classified_as_level": classified,
            "owner_building_id": membership_owner,
            "owner_building_name": building.get("name") \
                if building is not None else None,
            "owner_building_elevation": building.get("elevation") \
                if building is not None else None,
            "owner_sources": ["GetBuildingLevelIds"] + owner_getters,
            "owner_verified": owner_verified,
            "direct_owner_readbacks": direct_owner_readbacks,
            "readback_complete": len(local_errors) == 0 and owner_verified,
            "readback_errors": local_errors,
        }
        snapshot["levels"].append(level_snapshot)

    verification["owner_conflicts"] = owner_conflicts
    verification["pass"] = not missing_methods and not readback_errors and \
        not verification["duplicate_building_ids"] and \
        not verification["duplicate_level_ids"] and \
        not verification["duplicate_membership_edges"] and \
        not verification["orphan_level_ids"] and \
        not verification["unknown_member_level_ids"] and \
        not verification["duplicate_owner_level_ids"] and \
        not verification["cross_kind_guid_collisions"] and \
        not owner_conflicts and all(
            building["readback_complete"]
            for building in snapshot["buildings"]) and all(
            level["readback_complete"] for level in snapshot["levels"])
    return snapshot

def va_hierarchy_state(snapshot):
    buildings = {}
    for building in snapshot.get("buildings") or []:
        buildings[building["id"]] = {
            "name": building.get("name"),
            "elevation": building.get("elevation"),
            "classified_as_building": building.get("classified_as_building"),
        }
    levels = {}
    edges = []
    for level in snapshot.get("levels") or []:
        levels[level["id"]] = {
            "name": level.get("name"),
            "elevation": level.get("elevation"),
            "cut_elevation": level.get("cut_elevation"),
            "classified_as_level": level.get("classified_as_level"),
            "owner_building_id": level.get("owner_building_id"),
        }
        if level.get("owner_building_id") is not None:
            edges.append((level["owner_building_id"], level["id"]))
    return {"buildings": buildings, "levels": levels, "edges": sorted(edges)}

def va_hierarchy_diff(before, after):
    before_state = va_hierarchy_state(before)
    after_state = va_hierarchy_state(after)

    def map_delta(before_values, after_values):
        before_ids = set(before_values)
        after_ids = set(after_values)
        return {
            "added_ids": sorted(after_ids - before_ids),
            "removed_ids": sorted(before_ids - after_ids),
            "changed_ids": sorted(
                value_id for value_id in before_ids & after_ids
                if before_values[value_id] != after_values[value_id]),
        }

    building_delta = map_delta(
        before_state["buildings"], after_state["buildings"])
    level_delta = map_delta(before_state["levels"], after_state["levels"])
    before_edges = set(before_state["edges"])
    after_edges = set(after_state["edges"])
    added_edges = sorted(after_edges - before_edges)
    removed_edges = sorted(before_edges - after_edges)
    mutation_detected = any([
        building_delta["added_ids"], building_delta["removed_ids"],
        building_delta["changed_ids"], level_delta["added_ids"],
        level_delta["removed_ids"], level_delta["changed_ids"],
        added_edges, removed_edges,
    ])
    return {
        "added_building_ids": building_delta["added_ids"],
        "removed_building_ids": building_delta["removed_ids"],
        "changed_building_ids": building_delta["changed_ids"],
        "added_level_ids": level_delta["added_ids"],
        "removed_level_ids": level_delta["removed_ids"],
        "changed_level_ids": level_delta["changed_ids"],
        "added_membership_edges": [
            {"building_id": edge[0], "level_id": edge[1]}
            for edge in added_edges],
        "removed_membership_edges": [
            {"building_id": edge[0], "level_id": edge[1]}
            for edge in removed_edges],
        "mutation_detected": bool(mutation_detected),
    }
"""


_IFC_VALIDATION_SCRIPT_HELPERS = r"""
import math
import re
import scriptcontext as sc
from System import BitConverter
from System.IO import (
    File, FileAccess, FileInfo, FileMode, FileShare, Path, StreamReader)
from System.Security.Cryptography import SHA256

def file_sha256(file_path):
    stream = File.OpenRead(file_path)
    algorithm = SHA256.Create()
    try:
        digest = algorithm.ComputeHash(stream)
        return BitConverter.ToString(digest).Replace(
            "-", "").ToLowerInvariant()
    finally:
        stream.Close()
        algorithm.Dispose()

def va_file_evidence(file_path):
    try:
        exists = bool(File.Exists(file_path))
    except Exception as error:
        return {
            "exists": None, "sha256": None, "read_complete": False,
            "error": va_text(error),
        }
    if not exists:
        return {
            "exists": False, "sha256": None, "read_complete": True,
            "error": None,
        }
    try:
        return {
            "exists": True, "sha256": file_sha256(file_path),
            "read_complete": True, "error": None,
        }
    except Exception as error:
        return {
            "exists": True, "sha256": None, "read_complete": False,
            "error": va_text(error),
        }

def va_same_file_state(left, right):
    return left is not None and right is not None and \
        left.get("read_complete") is True and \
        right.get("read_complete") is True and \
        left.get("exists") == right.get("exists") and \
        left.get("sha256") == right.get("sha256")

def step_statements(content):
    statements = []
    current = []
    in_string = False
    in_comment = False
    index = 0
    while index < len(content):
        character = content[index]
        if in_comment:
            if character == "*" and index + 1 < len(content) and \
                    content[index + 1] == "/":
                in_comment = False
                index += 2
                continue
            index += 1
            continue
        if not in_string and character == "/" and \
                index + 1 < len(content) and content[index + 1] == "*":
            current.append(" ")
            in_comment = True
            index += 2
            continue
        current.append(character)
        if character == "'":
            if in_string and index + 1 < len(content) and \
                    content[index + 1] == "'":
                current.append(content[index + 1])
                index += 1
            else:
                in_string = not in_string
        elif character == ";" and not in_string:
            statements.append("".join(current))
            current = []
        index += 1
    if "".join(current).strip():
        statements.append("".join(current))
    return statements, not in_string and not in_comment

def step_references(statement):
    references = []
    in_string = False
    index = 0
    while index < len(statement):
        character = statement[index]
        if character == "'":
            if in_string and index + 1 < len(statement) and \
                    statement[index + 1] == "'":
                index += 2
                continue
            in_string = not in_string
            index += 1
            continue
        if not in_string and character == "#":
            end = index + 1
            while end < len(statement) and statement[end].isdigit():
                end += 1
            if end > index + 1:
                references.append(statement[index + 1:end])
                index = end
                continue
        index += 1
    return references

def step_entity_arguments(statement, match):
    stripped = statement.strip()
    if not stripped.endswith(");"):
        return None
    opening_index = statement.find("(", match.start())
    closing_index = statement.rfind(")")
    if opening_index < 0 or closing_index <= opening_index:
        return None
    if statement[closing_index + 1:].strip() != ";":
        return None
    depth = 0
    in_string = False
    index = opening_index
    while index <= closing_index:
        character = statement[index]
        if character == "'":
            if in_string and index + 1 <= closing_index and \
                    statement[index + 1] == "'":
                index += 2
                continue
            in_string = not in_string
        elif not in_string:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0 or (depth == 0 and index != closing_index):
                    return None
        index += 1
    if in_string or depth != 0:
        return None

    body = statement[opening_index + 1:closing_index]
    if not body.strip():
        return []
    arguments = []
    current = []
    nested_depth = 0
    in_string = False
    index = 0
    while index < len(body):
        character = body[index]
        if character == "'":
            current.append(character)
            if in_string and index + 1 < len(body) and \
                    body[index + 1] == "'":
                current.append(body[index + 1])
                index += 2
                continue
            in_string = not in_string
        elif not in_string and character == "(":
            nested_depth += 1
            current.append(character)
        elif not in_string and character == ")":
            nested_depth -= 1
            if nested_depth < 0:
                return None
            current.append(character)
        elif not in_string and character == "," and nested_depth == 0:
            arguments.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        index += 1
    if in_string or nested_depth != 0:
        return None
    arguments.append("".join(current).strip())
    if any(not argument for argument in arguments):
        return None
    return arguments

def valid_ifc_global_id(argument):
    # An IFC-GUID is the base-64 compression of exactly 128 bits. The first
    # digit therefore carries only two bits and must be 0..3; accepting the
    # remaining alphabet would admit values outside the UUID domain.
    return re.match(
        r"^'[0-3][0-9A-Za-z_$]{21}'$", argument.strip()) is not None

def valid_step_string(argument, require_nonempty=False):
    text = argument.strip()
    if re.match(r"^'(?:[^']|'')*'$", text) is None:
        return False
    if not require_nonempty:
        return True
    return bool(text[1:-1].replace("''", "'").strip())

def step_string_list(argument, minimum_count=0):
    text = argument.strip()
    if not text.startswith("(") or not text.endswith(")"):
        return None
    body = text[1:-1].strip()
    if not body:
        return [] if minimum_count == 0 else None
    values = []
    current = []
    in_string = False
    index = 0
    while index < len(body):
        character = body[index]
        current.append(character)
        if character == "'":
            if in_string and index + 1 < len(body) and body[index + 1] == "'":
                current.append(body[index + 1])
                index += 2
                continue
            in_string = not in_string
        elif character == "," and not in_string:
            current.pop()
            value = "".join(current).strip()
            if not valid_step_string(value):
                return None
            values.append(value)
            current = []
        index += 1
    value = "".join(current).strip()
    if in_string or not valid_step_string(value):
        return None
    values.append(value)
    return values if len(values) >= minimum_count else None

def step_header_inventory(header_statements):
    header_pattern = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*\(", re.I)
    required_names = ["FILE_DESCRIPTION", "FILE_NAME", "FILE_SCHEMA"]
    parsed = []
    errors = []
    for index, statement in enumerate(header_statements):
        match = header_pattern.match(statement)
        arguments = step_entity_arguments(statement, match) \
            if match is not None else None
        if match is None or arguments is None:
            errors.append({
                "index": index,
                "reason": "invalid header entity syntax",
                "excerpt": statement.strip()[:160],
            })
            continue
        parsed.append({
            "name": match.group(1).upper(),
            "arguments": arguments,
            "index": index,
        })

    names = [item["name"] for item in parsed]
    if names[:3] != required_names:
        errors.append({
            "reason": "required header entities are missing or out of order",
            "expected": required_names,
            "actual": names[:3],
        })
    for required_name in required_names:
        if names.count(required_name) != 1:
            errors.append({
                "reason": "required header entity count mismatch",
                "entity": required_name,
                "count": names.count(required_name),
            })

    actual_schema = None
    if len(parsed) >= 3 and parsed[0]["name"] == "FILE_DESCRIPTION":
        arguments = parsed[0]["arguments"]
        if len(arguments) != 2 or step_string_list(arguments[0], 1) is None or \
                not valid_step_string(arguments[1], True):
            errors.append({"reason": "invalid FILE_DESCRIPTION contract"})
    if len(parsed) >= 3 and parsed[1]["name"] == "FILE_NAME":
        arguments = parsed[1]["arguments"]
        file_name_valid = len(arguments) == 7 and \
            valid_step_string(arguments[0], True) and \
            valid_step_string(arguments[1], True) and \
            step_string_list(arguments[2], 1) is not None and \
            step_string_list(arguments[3], 1) is not None and all(
                valid_step_string(argument) for argument in arguments[4:])
        if not file_name_valid:
            errors.append({"reason": "invalid FILE_NAME contract"})
    if len(parsed) >= 3 and parsed[2]["name"] == "FILE_SCHEMA":
        arguments = parsed[2]["arguments"]
        schema_match = re.match(
            r"^\s*\(\s*'([A-Z0-9_]+)'\s*\)\s*$",
            arguments[0], re.I) if len(arguments) == 1 else None
        if schema_match is None:
            errors.append({"reason": "invalid FILE_SCHEMA contract"})
        else:
            actual_schema = schema_match.group(1).upper()

    supported_schemas = [
        "IFC2X3", "IFC4", "IFC4_ADD1", "IFC4_ADD2",
        "IFC4_ADD2_TC1", "IFC4X1", "IFC4X2", "IFC4X3",
        "IFC4X3_ADD1", "IFC4X3_ADD2",
    ]
    schema_supported = actual_schema in supported_schemas
    if actual_schema is not None and not schema_supported:
        errors.append({
            "reason": "unsupported FILE_SCHEMA identifier",
            "actual_schema": actual_schema,
            "supported_schemas": supported_schemas,
        })
    return {
        "valid": not errors,
        "actual_schema": actual_schema,
        "schema_supported": schema_supported,
        "supported_schemas": supported_schemas,
        "entity_names": names,
        "errors": errors,
    }

def step_single_reference(argument):
    match = re.match(r"^\s*#([0-9]+)\s*$", argument)
    return match.group(1) if match is not None else None

def step_reference_list(argument):
    if re.match(
            r"^\s*\(\s*#[0-9]+(?:\s*,\s*#[0-9]+)*\s*\)\s*$",
            argument) is None:
        return None
    return step_references(argument)

def step_finite_number(argument):
    try:
        value = float(argument.strip())
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    except Exception:
        return None

def step_number_list(argument, minimum_count=1, maximum_count=None):
    text = argument.strip()
    if not text.startswith("(") or not text.endswith(")"):
        return None
    values = [step_finite_number(value) for value in text[1:-1].split(",")]
    if any(value is None for value in values) or \
            len(values) < minimum_count or (
                maximum_count is not None and len(values) > maximum_count):
        return None
    return values

def step_entity_inventory(data_statements, actual_schema=None):
    entity_pattern = re.compile(
        r"^\s*#([0-9]+)\s*=\s*([A-Z][A-Z0-9_]*)\s*\(", re.I)
    entities = {}
    counts = {}
    duplicate_entity_ids = set()
    matched_entity_ids = set()
    unrecognized_data_statements = []
    invalid_entity_statements = []
    for statement_index, statement in enumerate(data_statements):
        match = entity_pattern.match(statement)
        if match is None:
            unrecognized_data_statements.append({
                "index": statement_index,
                "excerpt": statement.strip()[:160],
            })
            continue
        entity_id = match.group(1)
        entity_type = match.group(2).upper()
        if entity_id in matched_entity_ids:
            duplicate_entity_ids.add(entity_id)
            continue
        matched_entity_ids.add(entity_id)
        arguments = step_entity_arguments(statement, match)
        if arguments is None:
            invalid_entity_statements.append({
                "id": "#" + entity_id,
                "index": statement_index,
                "excerpt": statement.strip()[:160],
            })
            continue
        references = step_references(",".join(arguments))
        entities[entity_id] = {
            "type": entity_type,
            "references": references,
            "arguments": arguments,
        }
        counts[entity_type] = counts.get(entity_type, 0) + 1

    dangling_reference_ids = set()
    for entity in entities.values():
        for reference_id in entity["references"]:
            if reference_id not in entities:
                dangling_reference_ids.add(reference_id)

    invalid_semantic_entity_ids = set()
    invalid_semantic_reasons = []

    def mark_semantic_invalid(entity_id, reason):
        invalid_semantic_entity_ids.add(entity_id)
        invalid_semantic_reasons.append({
            "id": "#" + entity_id,
            "reason": reason,
        })

    schema_name = actual_schema.upper() if actual_schema is not None else ""
    is_ifc2x3 = schema_name.startswith("IFC2X3")
    is_ifc4_final = schema_name == "IFC4"
    is_ifc4x3 = schema_name.startswith("IFC4X3")
    project_ids = set(
        entity_id for entity_id, entity in entities.items()
        if entity["type"] == "IFCPROJECT")
    valid_project_ids = set()
    for project_id in project_ids:
        project = entities[project_id]
        arguments = project["arguments"]
        project_valid = len(arguments) == 9 and \
            valid_ifc_global_id(arguments[0]) and \
            valid_step_string(arguments[2], True)
        context_ids = None
        unit_id = None
        if len(arguments) == 9:
            context_argument = arguments[7].strip()
            unit_argument = arguments[8].strip()
            context_ids = [] if context_argument == "$" else \
                step_reference_list(context_argument)
            unit_id = None if unit_argument == "$" else \
                step_single_reference(unit_argument)
            if context_ids is None or (
                    unit_argument != "$" and unit_id is None):
                project_valid = False
            if is_ifc2x3 and (not context_ids or unit_id is None):
                project_valid = False
        if project_valid and context_ids:
            for context_id in context_ids:
                context = entities.get(context_id)
                if context is None or not context["type"].endswith(
                        "REPRESENTATIONCONTEXT"):
                    project_valid = False
                    break
        if project_valid and unit_id is not None:
            unit = entities.get(unit_id)
            if unit is None or unit["type"] != "IFCUNITASSIGNMENT":
                project_valid = False
        if project_valid:
            valid_project_ids.add(project_id)
        else:
            mark_semantic_invalid(
                project_id,
                "IfcProject requires 9 attributes, a valid GlobalId, a "
                "non-empty Name, and schema-valid optional/required "
                "representation contexts and units")

    wall_entity_types = ["IFCWALL", "IFCWALLSTANDARDCASE"]
    if not is_ifc2x3 and not is_ifc4x3:
        wall_entity_types.append("IFCWALLELEMENTEDCASE")
    wall_ids = set(
        entity_id for entity_id, entity in entities.items()
        if entity["type"] in wall_entity_types)
    wall_type_ids = set(
        entity_id for entity_id, entity in entities.items()
        if entity["type"] == "IFCWALLTYPE")
    layer_set_ids = set(
        entity_id for entity_id, entity in entities.items()
        if entity["type"] == "IFCMATERIALLAYERSET")
    layer_usage_ids = set(
        entity_id for entity_id, entity in entities.items()
        if entity["type"] == "IFCMATERIALLAYERSETUSAGE")
    material_layer_entity_types = ["IFCMATERIALLAYER"]
    if not is_ifc2x3:
        material_layer_entity_types.append("IFCMATERIALLAYERWITHOFFSETS")
    material_layer_ids = set(
        entity_id for entity_id, entity in entities.items()
        if entity["type"] in material_layer_entity_types)
    material_ids = set(
        entity_id for entity_id, entity in entities.items()
        if entity["type"] == "IFCMATERIAL")

    targeted_ifc_root_types = set(
        ["IFCPROJECT", "IFCWALLTYPE", "IFCRELDEFINESBYTYPE",
         "IFCRELASSOCIATESMATERIAL"] + wall_entity_types)
    global_id_owners = {}
    for entity_id, entity in entities.items():
        arguments = entity["arguments"]
        if entity["type"] in targeted_ifc_root_types and arguments and \
                valid_ifc_global_id(arguments[0]):
            global_id = arguments[0].strip()[1:-1]
            global_id_owners.setdefault(global_id, []).append(entity_id)
    duplicate_global_ids = []
    for global_id in sorted(global_id_owners):
        owner_ids = sorted(global_id_owners[global_id])
        if len(owner_ids) > 1:
            duplicate_global_ids.append({
                "global_id": global_id,
                "entity_ids": ["#" + value for value in owner_ids],
            })
            for entity_id in owner_ids:
                mark_semantic_invalid(
                    entity_id,
                    "IfcRoot GlobalId is duplicated across targeted entities")

    for entity_id, entity in entities.items():
        if is_ifc4x3 and entity["type"] == "IFCWALLELEMENTEDCASE":
            mark_semantic_invalid(
                entity_id,
                "IfcWallElementedCase was deleted from the IFC4X3 schema")
        if is_ifc2x3 and \
                entity["type"] == "IFCMATERIALLAYERWITHOFFSETS":
            mark_semantic_invalid(
                entity_id,
                "IfcMaterialLayerWithOffsets is not part of IFC2X3")

    wall_attribute_count = 8 if is_ifc2x3 else 9
    wall_type_attribute_count = 10
    material_layer_attribute_count = 3 if is_ifc2x3 else 7
    layer_set_attribute_count = 2 if is_ifc2x3 else 3
    layer_usage_attribute_count = 4 if is_ifc2x3 else 5

    for wall_id in wall_ids:
        arguments = entities[wall_id]["arguments"]
        if len(arguments) != wall_attribute_count or \
                not valid_ifc_global_id(arguments[0]):
            mark_semantic_invalid(
                wall_id,
                "IfcWall requires exactly " + str(wall_attribute_count) +
                " attributes for the declared schema and a valid GlobalId")
    for wall_type_id in wall_type_ids:
        arguments = entities[wall_type_id]["arguments"]
        if len(arguments) != wall_type_attribute_count or \
                not valid_ifc_global_id(arguments[0]):
            mark_semantic_invalid(
                wall_type_id,
                "IfcWallType requires exactly " +
                str(wall_type_attribute_count) +
                " attributes and a valid GlobalId")
    valid_material_layer_ids = set()
    offset_material_layer_ids = set()
    material_layer_offset_directions = {}
    material_layer_thicknesses = {}
    for material_layer_id in material_layer_ids:
        layer_entity = entities[material_layer_id]
        arguments = layer_entity["arguments"]
        is_offset_layer = \
            layer_entity["type"] == "IFCMATERIALLAYERWITHOFFSETS"
        expected_attribute_count = 9 if is_offset_layer \
            else material_layer_attribute_count
        thickness = step_finite_number(arguments[1]) \
            if len(arguments) == expected_attribute_count else None
        ventilation = arguments[2].strip().upper() \
            if len(arguments) == expected_attribute_count else None
        material_reference = step_single_reference(arguments[0]) \
            if len(arguments) == expected_attribute_count and \
                arguments[0].strip() != "$" else None
        material_valid = len(arguments) == expected_attribute_count and (
            arguments[0].strip() == "$" or material_reference in material_ids)
        layer_valid = len(arguments) == expected_attribute_count and \
            material_valid and \
            thickness is not None and thickness >= 0.0 and \
            ventilation in ["$", ".T.", ".F.", ".U."]
        if layer_valid and not is_ifc2x3:
            priority = arguments[6].strip()
            if priority != "$":
                priority_value = step_finite_number(priority)
                if is_ifc4_final:
                    # FILE_SCHEMA(('IFC4')) is also emitted by common
                    # ADD1/ADD2 exporters. Accept the compatible union of
                    # FINAL's ratio and the addenda's normalized integer.
                    layer_valid = priority_value is not None and (
                        0.0 <= priority_value <= 1.0 or (
                            priority_value == int(priority_value) and
                            0 <= int(priority_value) <= 100))
                else:
                    layer_valid = priority_value is not None and \
                        priority_value == int(priority_value) and \
                        0 <= int(priority_value) <= 100
        if layer_valid and is_offset_layer:
            offset_direction = arguments[7].strip().upper()
            offset_values = step_number_list(arguments[8], 2, 2)
            layer_valid = offset_direction in [
                ".AXIS1.", ".AXIS2.", ".AXIS3."] and \
                offset_values is not None
        if layer_valid:
            valid_material_layer_ids.add(material_layer_id)
            material_layer_thicknesses[material_layer_id] = thickness
            if is_offset_layer:
                offset_material_layer_ids.add(material_layer_id)
                material_layer_offset_directions[material_layer_id] = \
                    offset_direction
        else:
            mark_semantic_invalid(
                material_layer_id,
                "IfcMaterialLayer requires exactly " +
                str(expected_attribute_count) +
                " schema attributes, an optional IfcMaterial reference, a "
                "finite non-negative thickness, valid ventilation/priority, "
                "and valid offsets for an offset subtype")

    valid_layer_set_ids = set()
    layer_sets_requiring_extent = set()
    layer_set_offset_directions = {}
    for layer_set_id in layer_set_ids:
        layer_set = entities[layer_set_id]
        arguments = layer_set["arguments"]
        layer_ids = step_reference_list(arguments[0]) \
            if len(arguments) == layer_set_attribute_count else None
        total_thickness = sum(
            material_layer_thicknesses.get(reference_id, 0.0)
            for reference_id in (layer_ids or []))
        if layer_ids and all(
                reference_id in valid_material_layer_ids
                for reference_id in layer_ids) and total_thickness > 0.0:
            valid_layer_set_ids.add(layer_set_id)
            if any(reference_id in offset_material_layer_ids
                   for reference_id in layer_ids):
                layer_sets_requiring_extent.add(layer_set_id)
                layer_set_offset_directions[layer_set_id] = set(
                    material_layer_offset_directions[reference_id]
                    for reference_id in layer_ids
                    if reference_id in material_layer_offset_directions)
        else:
            mark_semantic_invalid(
                layer_set_id,
                "IfcMaterialLayerSet requires exactly " +
                str(layer_set_attribute_count) +
                " attributes and a non-empty list containing only existing "
                "valid IfcMaterialLayer references with positive total "
                "thickness")
    valid_layer_usage_ids = set()
    wall_compatible_layer_usage_ids = set()
    for layer_usage_id in layer_usage_ids:
        usage = entities[layer_usage_id]
        arguments = usage["arguments"]
        layer_set_id = step_single_reference(arguments[0]) \
            if len(arguments) == layer_usage_attribute_count else None
        direction = arguments[1].strip().upper() \
            if len(arguments) == layer_usage_attribute_count else None
        sense = arguments[2].strip().upper() \
            if len(arguments) == layer_usage_attribute_count else None
        offset = step_finite_number(arguments[3]) \
            if len(arguments) == layer_usage_attribute_count else None
        reference_extent_valid = True
        if not is_ifc2x3 and len(arguments) == layer_usage_attribute_count:
            reference_extent = arguments[4].strip()
            if reference_extent != "$":
                extent_value = step_finite_number(reference_extent)
                reference_extent_valid = extent_value is not None and \
                    extent_value > 0.0
            elif layer_set_id in layer_sets_requiring_extent:
                reference_extent_valid = False
        offset_direction_compatible = direction not in \
            layer_set_offset_directions.get(layer_set_id, set())
        usage_valid = layer_set_id in valid_layer_set_ids and \
            direction in [".AXIS1.", ".AXIS2.", ".AXIS3."] and \
            sense in [".POSITIVE.", ".NEGATIVE."] and \
            offset is not None and reference_extent_valid and \
            offset_direction_compatible
        if usage_valid:
            valid_layer_usage_ids.add(layer_usage_id)
            if direction == ".AXIS2.":
                wall_compatible_layer_usage_ids.add(layer_usage_id)
        else:
            mark_semantic_invalid(
                layer_usage_id,
                "IfcMaterialLayerSetUsage requires exactly " +
                str(layer_usage_attribute_count) +
                " attributes, a valid layer-set reference, valid axis/sense "
                "enums, a finite offset, an optional positive extent, and "
                "offset-layer directions perpendicular to LayerSetDirection")

    relation_types = [
        "IFCRELDEFINESBYTYPE", "IFCRELASSOCIATESMATERIAL"]
    valid_relation_ids = set()
    for relation_id, relation in entities.items():
        if relation["type"] not in relation_types:
            continue
        arguments = relation["arguments"]
        related_ids = step_reference_list(arguments[-2]) \
            if len(arguments) == 6 else None
        relating_id = step_single_reference(arguments[-1]) \
            if len(arguments) == 6 else None
        if len(arguments) == 6 and \
                valid_ifc_global_id(arguments[0]) and related_ids and \
                len(set(related_ids)) == len(related_ids) and \
                relating_id is not None:
            valid_relation_ids.add(relation_id)
        else:
            mark_semantic_invalid(
                relation_id,
                relation["type"] +
                " requires 6 attributes, a valid GlobalId, a non-empty "
                "RelatedObjects list, and one Relating reference")

    wall_types_by_wall = {}
    wall_type_relation_counts = {}
    invalid_wall_type_target_ids = set()
    layered_material_wall_targets = set()
    layered_material_wall_type_targets = set()
    wall_material_association_counts = {}
    wall_type_material_association_counts = {}
    for relation_id, entity in entities.items():
        if relation_id not in valid_relation_ids:
            continue
        arguments = entity["arguments"]
        related_ids = step_reference_list(arguments[-2]) or []
        relating_id = step_single_reference(arguments[-1])
        if entity["type"] == "IFCRELDEFINESBYTYPE":
            relating_type_id = relating_id
            for related_id in related_ids:
                if related_id in wall_ids:
                    wall_type_relation_counts[related_id] = \
                        wall_type_relation_counts.get(related_id, 0) + 1
                    if relating_type_id in wall_type_ids:
                        wall_types_by_wall.setdefault(
                            related_id, set()).add(relating_type_id)
                    else:
                        invalid_wall_type_target_ids.add(related_id)
                        mark_semantic_invalid(
                            relation_id,
                            "IfcRelDefinesByType targeting an IfcWall must "
                            "reference an existing IfcWallType")
                        mark_semantic_invalid(
                            related_id,
                            "IfcWall has an IfcRelDefinesByType assignment "
                            "whose RelatingType is not an IfcWallType")
        elif entity["type"] == "IFCRELASSOCIATESMATERIAL":
            relating_material_id = relating_id
            for related_id in related_ids:
                if related_id in wall_ids:
                    wall_material_association_counts[related_id] = \
                        wall_material_association_counts.get(related_id, 0) + 1
                    if relating_material_id in valid_layer_set_ids or \
                            relating_material_id in \
                            wall_compatible_layer_usage_ids:
                        layered_material_wall_targets.add(related_id)
                elif related_id in wall_type_ids:
                    wall_type_material_association_counts[related_id] = \
                        wall_type_material_association_counts.get(
                            related_id, 0) + 1
                    if relating_material_id in valid_layer_set_ids:
                        layered_material_wall_type_targets.add(related_id)

    associated_wall_ids = []
    ambiguous_material_wall_ids = []
    ambiguous_wall_type_ids = []
    for wall_id in sorted(wall_ids):
        wall_types = wall_types_by_wall.get(wall_id, set())
        wall_type_id = next(iter(wall_types)) \
            if len(wall_types) == 1 else None
        if wall_type_relation_counts.get(wall_id, 0) > 1:
            ambiguous_wall_type_ids.append(wall_id)
        occurrence_association_count = \
            wall_material_association_counts.get(wall_id, 0)
        type_association_count = wall_type_material_association_counts.get(
            wall_type_id, 0) if wall_type_id is not None else 0
        if occurrence_association_count > 1 or (
                occurrence_association_count == 0 and
                type_association_count > 1):
            ambiguous_material_wall_ids.append(wall_id)
        elif occurrence_association_count == 1 and \
                wall_id in layered_material_wall_targets:
            associated_wall_ids.append(wall_id)
        elif occurrence_association_count == 0 and \
                wall_id not in ambiguous_wall_type_ids and \
                type_association_count == 1 and \
                wall_type_id in layered_material_wall_type_targets:
            associated_wall_ids.append(wall_id)
    unassociated_wall_ids = sorted(wall_ids - set(associated_wall_ids))
    for wall_id in ambiguous_wall_type_ids:
        mark_semantic_invalid(
            wall_id,
            "IfcWall has multiple effective IfcRelDefinesByType assignments")
    for wall_id in ambiguous_material_wall_ids:
        mark_semantic_invalid(
            wall_id,
            "IfcWall has multiple effective material associations")
    material_judgement_pass = bool(wall_ids) and \
        not unassociated_wall_ids and \
        not ambiguous_wall_type_ids and \
        not invalid_wall_type_target_ids and \
        not ambiguous_material_wall_ids
    return {
        "data_instance_count": len(entities),
        "duplicate_entity_ids": [
            "#" + value for value in sorted(duplicate_entity_ids)],
        "duplicate_global_ids": duplicate_global_ids,
        "unrecognized_data_statements": unrecognized_data_statements,
        "invalid_entity_statements": invalid_entity_statements,
        "dangling_reference_ids": [
            "#" + value for value in sorted(dangling_reference_ids)],
        "invalid_semantic_entity_ids": [
            "#" + value for value in sorted(invalid_semantic_entity_ids)],
        "invalid_semantic_reasons": invalid_semantic_reasons,
        "entity_counts": counts,
        "project_count": counts.get("IFCPROJECT", 0),
        "valid_project_count": len(valid_project_ids),
        "wall_count": len(wall_ids),
        "wall_ids": ["#" + value for value in sorted(wall_ids)],
        "material_layer_set_count": len(layer_set_ids),
        "valid_material_layer_set_count": len(valid_layer_set_ids),
        "material_layer_set_usage_count": len(layer_usage_ids),
        "valid_material_layer_set_usage_count": len(valid_layer_usage_ids),
        "material_layer_count": len(material_layer_ids),
        "material_association_count": counts.get(
            "IFCRELASSOCIATESMATERIAL", 0),
        "walls_with_material_layer_association": len(associated_wall_ids),
        "unassociated_wall_ids": [
            "#" + value for value in unassociated_wall_ids],
        "ambiguous_material_wall_ids": [
            "#" + value for value in ambiguous_material_wall_ids],
        "ambiguous_wall_type_ids": [
            "#" + value for value in ambiguous_wall_type_ids],
        "invalid_wall_type_target_ids": [
            "#" + value for value in sorted(invalid_wall_type_target_ids)],
        "wall_material_layer_association_pass": material_judgement_pass,
    }

def validate_ifc(file_path, require_wall_material_layers):
    exists = File.Exists(file_path)
    size = int(FileInfo(file_path).Length) if exists else 0
    max_validation_bytes = 536870912
    size_within_limit = size <= max_validation_bytes
    content = ""
    if exists and size > 0 and size_within_limit:
        reader = StreamReader(file_path)
        try:
            content = reader.ReadToEnd()
        finally:
            reader.Close()
    statements, lexical_complete = step_statements(content)
    # Keep interior whitespace intact. Removing all whitespace can glue tokens
    # across a removed comment (for example HEA/*...*/DER) into a keyword.
    normalized = [statement.strip().upper() for statement in statements]
    header_markers_valid = len(normalized) >= 2 and \
        normalized[0] == "ISO-10303-21;" and normalized[1] == "HEADER;"
    header_end_index = normalized.index("ENDSEC;") \
        if "ENDSEC;" in normalized else -1
    data_index = normalized.index("DATA;", header_end_index + 1) \
        if header_end_index >= 0 and "DATA;" in normalized[header_end_index + 1:] \
        else -1
    data_end_index = normalized.index("ENDSEC;", data_index + 1) \
        if data_index >= 0 and "ENDSEC;" in normalized[data_index + 1:] \
        else -1
    final_marker = "END-ISO-10303-21;"
    final_index = normalized.index(final_marker, data_end_index + 1) \
        if data_end_index >= 0 and \
            final_marker in normalized[data_end_index + 1:] else -1
    header_statements = statements[2:header_end_index] \
        if header_end_index >= 0 else []
    header_inventory = step_header_inventory(header_statements)
    header_valid = header_markers_valid and header_inventory["valid"]
    complete_step_structure = lexical_complete and header_valid and \
        header_end_index > 1 and data_index == header_end_index + 1 and \
        data_end_index > data_index and final_index == data_end_index + 1 and \
        final_index == len(normalized) - 1 and \
        normalized.count("HEADER;") == 1 and \
        normalized.count("DATA;") == 1 and \
        normalized.count("ENDSEC;") == 2 and \
        normalized.count(final_marker) == 1
    actual_schema = header_inventory["actual_schema"]
    schema_valid = header_inventory["schema_supported"]
    data_statements = statements[data_index + 1:data_end_index] \
        if complete_step_structure else []
    inventory = step_entity_inventory(data_statements, actual_schema) \
        if complete_step_structure \
        else {
            "data_instance_count": 0, "entity_counts": {},
            "duplicate_entity_ids": [],
            "duplicate_global_ids": [],
            "unrecognized_data_statements": [],
            "invalid_entity_statements": [],
            "dangling_reference_ids": [],
            "invalid_semantic_entity_ids": [],
            "invalid_semantic_reasons": [],
            "project_count": 0, "valid_project_count": 0,
            "wall_count": 0, "wall_ids": [],
            "material_layer_set_count": 0,
            "valid_material_layer_set_count": 0,
            "material_layer_set_usage_count": 0,
            "valid_material_layer_set_usage_count": 0,
            "material_layer_count": 0,
            "material_association_count": 0,
            "walls_with_material_layer_association": 0,
            "unassociated_wall_ids": [],
            "ambiguous_material_wall_ids": [],
            "ambiguous_wall_type_ids": [],
            "invalid_wall_type_target_ids": [],
            "wall_material_layer_association_pass": False,
        }
    semantic_core_valid = inventory["data_instance_count"] > 0 and \
        inventory["project_count"] == 1 and \
        inventory["valid_project_count"] == 1 and \
        not inventory["duplicate_entity_ids"] and \
        not inventory["duplicate_global_ids"] and \
        not inventory["unrecognized_data_statements"] and \
        not inventory["invalid_entity_statements"] and \
        not inventory["dangling_reference_ids"] and \
        not inventory["invalid_semantic_entity_ids"]
    material_gate_pass = not require_wall_material_layers or \
        inventory["wall_material_layer_association_pass"]
    return {
        "file_exists": exists, "file_size": size,
        "max_validation_bytes": max_validation_bytes,
        "file_size_within_limit": size_within_limit,
        "header_valid": header_valid, "actual_schema": actual_schema,
        "schema_valid": schema_valid,
        "header_entity_names": header_inventory["entity_names"],
        "header_errors": header_inventory["errors"],
        "supported_schemas": header_inventory["supported_schemas"],
        "lexical_complete": lexical_complete,
        "complete_step_structure": complete_step_structure,
        "data_instance_count": inventory["data_instance_count"],
        "duplicate_entity_ids": inventory["duplicate_entity_ids"],
        "duplicate_global_ids": inventory["duplicate_global_ids"],
        "unrecognized_data_statements":
            inventory["unrecognized_data_statements"],
        "invalid_entity_statements": inventory["invalid_entity_statements"],
        "dangling_reference_ids": inventory["dangling_reference_ids"],
        "invalid_semantic_entity_ids":
            inventory["invalid_semantic_entity_ids"],
        "invalid_semantic_reasons": inventory["invalid_semantic_reasons"],
        "entity_counts": inventory["entity_counts"],
        "project_count": inventory["project_count"],
        "valid_project_count": inventory["valid_project_count"],
        "wall_count": inventory["wall_count"],
        "wall_ids": inventory["wall_ids"],
        "material_layer_set_count": inventory["material_layer_set_count"],
        "valid_material_layer_set_count":
            inventory["valid_material_layer_set_count"],
        "material_layer_set_usage_count":
            inventory["material_layer_set_usage_count"],
        "valid_material_layer_set_usage_count":
            inventory["valid_material_layer_set_usage_count"],
        "material_layer_count": inventory["material_layer_count"],
        "material_association_count":
            inventory["material_association_count"],
        "walls_with_material_layer_association":
            inventory["walls_with_material_layer_association"],
        "unassociated_wall_ids": inventory["unassociated_wall_ids"],
        "ambiguous_material_wall_ids":
            inventory["ambiguous_material_wall_ids"],
        "ambiguous_wall_type_ids": inventory["ambiguous_wall_type_ids"],
        "invalid_wall_type_target_ids":
            inventory["invalid_wall_type_target_ids"],
        "wall_material_layer_association_pass":
            inventory["wall_material_layer_association_pass"],
        "wall_material_layers_required": require_wall_material_layers,
        "semantic_core_valid": semantic_core_valid,
        "valid": exists and size > 0 and size_within_limit and
            complete_step_structure and
            schema_valid and semantic_core_valid and
            material_gate_pass,
    }
"""


_IFC_IMPORT_SCRIPT_HELPERS = r"""
def va_ifc_import_identity(object_id):
    errors = []
    matches = []
    for method_name in ["IsProduct", "IsSection"]:
        if not va_method_available(method_name):
            errors.append({
                "method": method_name, "error": "method unavailable"})
            continue
        try:
            if bool(getattr(va, method_name)(object_id)):
                matches.append(method_name)
        except Exception as error:
            errors.append({
                "method": method_name, "error": va_text(error)})
    return {
        "match": bool(matches) if not errors else None,
        "classifiers": matches,
        "readback_complete": not errors,
        "readback_errors": errors,
    }

def va_ifc_import_object_inventory():
    entries = []
    errors = []
    required_methods = ["IsProduct", "IsSection"]
    missing_methods = [
        method_name for method_name in required_methods
        if not va_method_available(method_name)
    ]
    try:
        next_runtime_serial = int(
            Rhino.DocObjects.RhinoObject.NextRuntimeSerialNumber)
    except Exception as error:
        next_runtime_serial = None
        errors.append({
            "stage": "next_runtime_serial", "error": va_text(error)})

    for obj in sc.doc.Objects:
        local_errors = []
        geometry_crc = None
        try:
            geometry = obj.Geometry
            geometry_crc = int(geometry.DataCRC(System.UInt32(0))) \
                if geometry is not None else None
        except Exception as error:
            local_errors.append({
                "stage": "geometry_crc", "error": va_text(error)})
        attributes = None
        try:
            attrs = obj.Attributes
            attributes = {
                "layer_index": int(attrs.LayerIndex),
                "name": va_text(attrs.Name),
                "visible": bool(attrs.Visible),
                "locked": bool(obj.IsLocked),
                "material_index": int(attrs.MaterialIndex),
                "material_source": va_text(attrs.MaterialSource),
                "color_source": va_text(attrs.ColorSource),
                "object_color_argb": int(attrs.ObjectColor.ToArgb()),
                "linetype_index": int(attrs.LinetypeIndex),
                "plot_weight": float(attrs.PlotWeight),
            }
        except Exception as error:
            local_errors.append({
                "stage": "attributes", "error": va_text(error)})
        identity = va_ifc_import_identity(obj.Id)
        if identity["readback_complete"] is not True:
            local_errors.extend(identity["readback_errors"])
        entry = {
            "id": str(obj.Id),
            "runtime_serial_number": int(obj.RuntimeSerialNumber),
            "object_type": va_text(obj.ObjectType),
            "geometry_crc": geometry_crc,
            "attributes": attributes,
            "visualarq_identity": identity["match"],
            "visualarq_classifiers": identity["classifiers"],
            "readback_complete": not local_errors,
            "readback_errors": local_errors,
        }
        entries.append(entry)
        for local_error in local_errors:
            errors.append({
                "object_id": entry["id"],
                "stage": local_error.get("stage"),
                "method": local_error.get("method"),
                "error": local_error.get("error"),
            })
    entries.sort(key=lambda item: item["id"])
    ids = [entry["id"] for entry in entries]
    duplicate_ids = sorted(
        set(value for value in ids if ids.count(value) > 1))
    return {
        "objects": entries,
        "count": len(entries),
        "next_runtime_serial_number": next_runtime_serial,
        "duplicate_ids": duplicate_ids,
        "missing_methods": missing_methods,
        "readback_errors": errors,
        "read_complete": (
            next_runtime_serial is not None and not missing_methods and
            not duplicate_ids and not errors),
        "coverage": {
            "identity": ["IsProduct", "IsSection"],
            "state": [
                "Guid", "RuntimeSerialNumber", "ObjectType", "Geometry.DataCRC",
                "core ObjectAttributes",
            ],
        },
    }

def va_ifc_import_style_inventory():
    return va_global_style_inventory()


def va_ifc_import_snapshot():
    objects = va_ifc_import_object_inventory()
    styles = va_ifc_import_style_inventory()
    hierarchy = va_hierarchy_snapshot()
    hierarchy_verification = hierarchy.get("verification") or {}
    hierarchy_read_complete = \
        hierarchy_verification.get("pass") is True and \
        hierarchy_verification.get("mutation_baseline_complete") is True
    return {
        "objects": objects,
        "styles": styles,
        "hierarchy": hierarchy,
        "read_complete": (
            objects["read_complete"] and styles["read_complete"] and
            hierarchy_read_complete),
        "coverage": {
            "objects": objects["coverage"],
            "styles": styles["coverage"],
            "hierarchy_scope": hierarchy_verification.get("inventory_scope"),
            "global_level_inventory_required": True,
        },
    }

def va_ifc_import_map_delta(before_items, after_items, key_name):
    before_map = dict((item[key_name], item) for item in before_items)
    after_map = dict((item[key_name], item) for item in after_items)
    before_ids = set(before_map)
    after_ids = set(after_map)
    return {
        "added": [after_map[value] for value in sorted(after_ids - before_ids)],
        "removed_ids": sorted(before_ids - after_ids),
        "changed_ids": sorted(
            value for value in before_ids & after_ids
            if before_map[value] != after_map[value]),
    }

def va_ifc_import_delta(before, after):
    object_delta = va_ifc_import_map_delta(
        before["objects"]["objects"], after["objects"]["objects"], "id")
    style_delta = va_ifc_import_map_delta(
        before["styles"]["styles"], after["styles"]["styles"], "key")
    hierarchy_delta = va_hierarchy_diff(
        before["hierarchy"], after["hierarchy"])
    hierarchy_removed_or_changed = any([
        hierarchy_delta["removed_building_ids"],
        hierarchy_delta["changed_building_ids"],
        hierarchy_delta["removed_level_ids"],
        hierarchy_delta["changed_level_ids"],
        hierarchy_delta["removed_membership_edges"],
    ])
    additive = not any([
        object_delta["removed_ids"], object_delta["changed_ids"],
        style_delta["removed_ids"], style_delta["changed_ids"],
        hierarchy_removed_or_changed,
    ])
    visualarq_object_additions = [
        item for item in object_delta["added"]
        if item.get("visualarq_identity") is True]
    added_building_ids = hierarchy_delta["added_building_ids"]
    added_level_ids = hierarchy_delta["added_level_ids"]
    verified_va_addition = bool(
        visualarq_object_additions or style_delta["added"] or
        added_building_ids or added_level_ids)
    mutation_detected = bool(
        object_delta["added"] or object_delta["removed_ids"] or
        object_delta["changed_ids"] or style_delta["added"] or
        style_delta["removed_ids"] or style_delta["changed_ids"] or
        hierarchy_delta["mutation_detected"])
    return {
        "objects": object_delta,
        "styles": style_delta,
        "hierarchy": hierarchy_delta,
        "visualarq_object_additions": visualarq_object_additions,
        "mutation_detected": mutation_detected,
        "additive": additive,
        "verified_visualarq_addition": verified_va_addition,
    }
"""


def _require_name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")


def _require_finite_number(value: float, field: str) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value))):
        raise ValueError(f"{field} must be a finite number")


def _require_positive(value: float, field: str) -> None:
    _require_finite_number(value, field)
    if value <= 0:
        raise ValueError(f"{field} must be positive")


def _require_point3(value: List[float], field: str) -> None:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field} must be [x, y, z]")
    for coordinate in value:
        _require_finite_number(coordinate, f"{field} coordinate")


def _point_on_segment_2d(
    point: List[float],
    start: List[float],
    end: List[float],
    tolerance: float = 1e-10,
) -> bool:
    cross = (
        (point[0] - start[0]) * (end[1] - start[1])
        - (point[1] - start[1]) * (end[0] - start[0])
    )
    scale = max(
        1.0,
        abs(end[0] - start[0]),
        abs(end[1] - start[1]),
    )
    if abs(cross) > tolerance * scale:
        return False
    return (
        min(start[0], end[0]) - tolerance <= point[0]
        <= max(start[0], end[0]) + tolerance
        and min(start[1], end[1]) - tolerance <= point[1]
        <= max(start[1], end[1]) + tolerance
    )


def _segments_intersect_2d(
    left_start: List[float],
    left_end: List[float],
    right_start: List[float],
    right_end: List[float],
) -> bool:
    def orientation(a: List[float], b: List[float], c: List[float]) -> float:
        return (
            (b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0])
        )

    values = (
        orientation(left_start, left_end, right_start),
        orientation(left_start, left_end, right_end),
        orientation(right_start, right_end, left_start),
        orientation(right_start, right_end, left_end),
    )
    if (values[0] > 0 > values[1] or values[0] < 0 < values[1]) and (
        values[2] > 0 > values[3] or values[2] < 0 < values[3]
    ):
        return True
    return any((
        abs(values[0]) <= 1e-10
        and _point_on_segment_2d(right_start, left_start, left_end),
        abs(values[1]) <= 1e-10
        and _point_on_segment_2d(right_end, left_start, left_end),
        abs(values[2]) <= 1e-10
        and _point_on_segment_2d(left_start, right_start, right_end),
        abs(values[3]) <= 1e-10
        and _point_on_segment_2d(left_end, right_start, right_end),
    ))


def _normalize_planar_boundary(
    boundary: List[List[float]],
    field: str = "boundary",
) -> List[List[float]]:
    if not isinstance(boundary, list) or len(boundary) < 3:
        raise ValueError(f"{field} must contain at least three [x, y, z] points")
    points = []
    for index, point in enumerate(boundary):
        _require_point3(point, f"{field}[{index}]")
        points.append([float(value) for value in point])
    if points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        raise ValueError(f"{field} must contain at least three unique vertices")
    elevation = points[0][2]
    elevation_tolerance = max(1e-9, abs(elevation) * 1e-12)
    if any(abs(point[2] - elevation) > elevation_tolerance for point in points):
        raise ValueError(f"{field} must be horizontal (all z values equal)")
    edge_count = len(points)
    for index in range(edge_count):
        if points[index][:2] == points[(index + 1) % edge_count][:2]:
            raise ValueError(f"{field} has a zero-length edge at index {index}")
    for left_index in range(edge_count):
        left_end_index = (left_index + 1) % edge_count
        for right_index in range(left_index + 1, edge_count):
            right_end_index = (right_index + 1) % edge_count
            if (
                left_index == right_index
                or left_end_index == right_index
                or right_end_index == left_index
            ):
                continue
            if _segments_intersect_2d(
                points[left_index],
                points[left_end_index],
                points[right_index],
                points[right_end_index],
            ):
                raise ValueError(f"{field} is self-intersecting")
    signed_double_area = sum(
        points[index][0] * points[(index + 1) % edge_count][1]
        - points[(index + 1) % edge_count][0] * points[index][1]
        for index in range(edge_count)
    )
    if abs(signed_double_area) <= 1e-12:
        raise ValueError(f"{field} has zero planar area")
    return points + [list(points[0])]


def _require_label_inside_boundary(
    label_point: List[float],
    boundary: List[List[float]],
) -> None:
    _require_point3(label_point, "label_point")
    point = [float(value) for value in label_point]
    elevation = boundary[0][2]
    if abs(point[2] - elevation) > max(1e-9, abs(elevation) * 1e-12):
        raise ValueError("label_point z must match the boundary elevation")
    vertices = boundary[:-1]
    for index, start in enumerate(vertices):
        if _point_on_segment_2d(point, start, vertices[(index + 1) % len(vertices)]):
            raise ValueError("label_point must be strictly inside the boundary")
    inside = False
    previous = vertices[-1]
    for current in vertices:
        if (
            (current[1] > point[1]) != (previous[1] > point[1])
            and point[0]
            < (previous[0] - current[0])
            * (point[1] - current[1])
            / (previous[1] - current[1])
            + current[0]
        ):
            inside = not inside
        previous = current
    if not inside:
        raise ValueError("label_point must be strictly inside the boundary")


def _require_guid(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a GUID string")
    try:
        parsed = UUID(value.strip().strip("{}"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid GUID") from None
    if parsed.int == 0:
        raise ValueError(f"{field} must not be the empty GUID")


def _normalize_wall_layers(layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(layers, list) or not layers:
        raise ValueError("layers must be a non-empty list")

    normalized = []
    names = set()
    allowed = {
        "name", "thickness", "type", "core",
        "wrapping_ends", "wrapping_openings",
    }
    unsupported = {"function", "top_offset", "bottom_offset"}
    for index, layer in enumerate(layers):
        field = f"layers[{index}]"
        if not isinstance(layer, dict):
            raise ValueError(f"{field} must be an object")
        requested_unsupported = sorted(
            key for key in unsupported
            if key in layer and layer[key] is not None
        )
        if requested_unsupported:
            raise NotImplementedError(
                f"{field} fields are not style-level in VisualARQ 3.7.2: "
                + ", ".join(requested_unsupported)
            )
        unknown = sorted(set(layer) - allowed - unsupported)
        if unknown:
            raise ValueError(f"{field} has unknown fields: {', '.join(unknown)}")

        name = layer.get("name")
        _require_name(name, f"{field}.name")
        canonical_name = name.strip()
        if canonical_name.casefold() in names:
            raise ValueError(f"duplicate wall-layer name: {canonical_name}")
        names.add(canonical_name.casefold())

        thickness = layer.get("thickness")
        _require_positive(thickness, f"{field}.thickness")
        layer_type = layer.get("type")
        core = layer.get("core")
        if core is not None and not isinstance(core, bool):
            raise ValueError(f"{field}.core must be boolean")
        if layer_type is not None:
            if not isinstance(layer_type, str) or layer_type.lower() not in {
                "normal", "core",
            }:
                raise ValueError(f"{field}.type must be 'normal' or 'core'")
            type_name = layer_type.lower()
            if core is not None and bool(core) != (type_name == "core"):
                raise ValueError(f"{field}.type and .core disagree")
        else:
            type_name = "core" if core else "normal"

        wrapping_ends = layer.get("wrapping_ends", False)
        wrapping_openings = layer.get("wrapping_openings", False)
        if not isinstance(wrapping_ends, bool):
            raise ValueError(f"{field}.wrapping_ends must be boolean")
        if not isinstance(wrapping_openings, bool):
            raise ValueError(f"{field}.wrapping_openings must be boolean")
        if type_name == "core" and (wrapping_ends or wrapping_openings):
            raise ValueError(
                f"{field}: VisualARQ core layers cannot wrap at ends or openings"
            )
        normalized.append({
            "name": canonical_name,
            "thickness": float(thickness),
            "type": type_name,
            "wrapping_ends": wrapping_ends,
            "wrapping_openings": wrapping_openings,
        })
    return normalized


def _normalize_slab_layers(layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(layers, list) or not layers:
        raise ValueError("layers must be a non-empty list")
    normalized = []
    names = set()
    for index, layer in enumerate(layers):
        field = f"layers[{index}]"
        if not isinstance(layer, dict):
            raise ValueError(f"{field} must be an object")
        unknown = sorted(set(layer) - {"name", "thickness", "type", "core"})
        if unknown:
            raise ValueError(f"{field} has unknown fields: {', '.join(unknown)}")
        name = layer.get("name")
        _require_name(name, f"{field}.name")
        canonical_name = name.strip()
        if canonical_name.casefold() in names:
            raise ValueError(f"duplicate slab-layer name: {canonical_name}")
        names.add(canonical_name.casefold())
        thickness = layer.get("thickness")
        _require_positive(thickness, f"{field}.thickness")
        layer_type = layer.get("type")
        core = layer.get("core")
        if core is not None and not isinstance(core, bool):
            raise ValueError(f"{field}.core must be boolean")
        if layer_type is not None:
            if not isinstance(layer_type, str) or layer_type.lower() not in {
                "normal", "core",
            }:
                raise ValueError(f"{field}.type must be 'normal' or 'core'")
            type_name = layer_type.lower()
            if core is not None and bool(core) != (type_name == "core"):
                raise ValueError(f"{field}.type and .core disagree")
        else:
            type_name = "core" if core else "normal"
        normalized.append({
            "name": canonical_name,
            "thickness": float(thickness),
            "type": type_name,
        })
    return normalized


_STYLE_CREATION_BODY = r"""
import scriptcontext as sc

kind = params["kind"]
requested_name = params["name"]
requested_layers = params.get("layers") or []
inventory_method = "GetAllSlabStyleIds" if kind == "slab" \
    else "GetAllSpaceStyleIds"
classifier_method = "IsSlabStyle" if kind == "slab" else "IsSpaceStyle"

# Mutation and verification dispatch is allowed only against the exact public
# static CLR contract proven on the assembly loaded in this Rhino process.
shape_specs = [
    ["GetAllWallStyleIds", [], "System.Guid[]"],
    ["GetAllDoorStyleIds", [], "System.Guid[]"],
    ["GetAllWindowStyleIds", [], "System.Guid[]"],
    ["GetAllSlabStyleIds", [], "System.Guid[]"],
    ["GetAllSpaceStyleIds", [], "System.Guid[]"],
    ["GetAllBeamStyle", [], "System.Guid[]"],
    ["GetStyleName", ["System.Guid"], "System.String"],
    ["GetSubStyleComponents", ["System.Guid"], "System.Guid[]"],
    ["GetProductsByStyle", ["System.Guid", "System.Boolean"],
        "System.Guid[]"],
    ["GetParentStyleComponent", ["System.Guid"], "System.Guid"],
    ["DeleteStyle", ["System.Guid"], "System.Boolean"],
    ["DeleteStyleComponent", ["System.Guid"], "System.Boolean"],
]
if kind == "slab":
    shape_specs.extend([
        ["AddSlabStyle", ["System.String", "System.Guid"],
            "System.Guid"],
        ["GetRectangularProfileTemplate", [], "System.Guid"],
        ["IsProfileTemplate", ["System.Guid"], "System.Boolean"],
        ["IsSlabStyle", ["System.Guid"], "System.Boolean"],
        ["AddSlabLayer", ["System.Guid", "System.String", "System.Double"],
            "System.Guid"],
        ["GetSlabLayers", ["System.Guid"], "System.Guid[]"],
        ["IsSlabLayer", ["System.Guid"], "System.Boolean"],
        ["GetSlabLayerThickness", ["System.Guid"], "System.Double"],
        ["GetSlabLayerType", ["System.Guid"],
            "VisualARQ.Script+SlabLayerType"],
        ["SetSlabLayerType", [
            "System.Guid", "VisualARQ.Script+SlabLayerType"],
            "System.Boolean"],
        ["GetStyleComponentName", ["System.Guid"], "System.String"],
    ])
else:
    shape_specs.extend([
        ["AddSpaceStyle", ["System.String"], "System.Guid"],
        ["IsSpaceStyle", ["System.Guid"], "System.Boolean"],
    ])

shape_contract = {}
for shape_spec in shape_specs:
    shape_contract[shape_spec[0]] = va_exact_method_shape(
        shape_spec[0], shape_spec[1], shape_spec[2])
failed_shapes = sorted(
    method_name for method_name in shape_contract
    if shape_contract[method_name]["verified"] is not True)

if failed_shapes:
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "message": (
            "VisualARQ " + kind + "-style API has no unique supported " +
            "CLR shape"),
        "failed_shapes": failed_shapes,
        "shape_contract": shape_contract,
    }
else:
    global_before = va_global_style_inventory()
    if global_before["read_complete"] is not True:
        result = {
            "status": "error", "code": "VERIFICATION_FAILED",
            "message": (
                "Global VisualARQ style/component baseline is incomplete; " +
                kind + " style creation was refused before mutation"),
            "global_inventory_before": global_before,
            "shape_contract": shape_contract,
        }
    else:
        duplicate_style_ids = sorted(
            entry["id"] for entry in global_before["styles"]
            if entry["inventory_method"] == inventory_method and
            va_text_key(entry["name"]) == va_text_key(requested_name))
        if duplicate_style_ids:
            result = {
                "status": "error", "code": "ALREADY_EXISTS",
                "message": (
                    "A " + kind + " style with this name already exists"),
                "name": requested_name,
                "style_ids": duplicate_style_ids,
                "global_inventory_before": global_before,
            }
        else:
            template_id = Guid.Empty
            template_evidence = None
            template_verified = kind != "slab"
            if kind == "slab":
                try:
                    template_id = va.GetRectangularProfileTemplate()
                    template_evidence = {
                        "id": str(template_id)
                            if template_id != Guid.Empty else None,
                        "is_profile_template": bool(
                            va.IsProfileTemplate(template_id))
                            if template_id != Guid.Empty else False,
                    }
                    template_verified = template_id != Guid.Empty and \
                        template_evidence["is_profile_template"] is True
                except Exception as template_error:
                    template_evidence = {
                        "id": None, "error": va_text(template_error)}
            if not template_verified:
                result = {
                    "status": "error", "code": "VERIFICATION_FAILED",
                    "message": (
                        "The canonical rectangular VisualARQ profile " +
                        "template could not be verified; slab style " +
                        "creation was refused before mutation"),
                    "template": template_evidence,
                }
            else:
                created_id = Guid.Empty
                style_ownership_verified = False
                automatic_component_ids = []
                created_layer_ids = []
                style_add_contract = None
                final_delta_contract = None
                global_after_style = None
                global_final = None
                try:
                    baseline_guid_union = set(
                        global_before["all_style_ids"] +
                        global_before["all_component_ids"])
                    if kind == "slab":
                        created_id = va.AddSlabStyle(
                            requested_name, template_id)
                    else:
                        created_id = va.AddSpaceStyle(requested_name)
                    if created_id is None or created_id == Guid.Empty:
                        raise Exception(
                            "Add" + kind.capitalize() +
                            "Style returned an empty Guid")
                    if str(created_id) in baseline_guid_union:
                        raise Exception(
                            "Style creation returned a pre-existing Guid")

                    global_after_style = va_global_style_inventory()
                    if global_after_style["read_complete"] is not True:
                        raise Exception(
                            "global inventory is incomplete after style add")
                    automatic_component_ids = sorted(
                        set(global_after_style["all_component_ids"]) -
                        set(global_before["all_component_ids"]))
                    style_add_contract = va_global_style_create_contract(
                        global_before, global_after_style, created_id,
                        inventory_method, requested_name,
                        automatic_component_ids)
                    if style_add_contract["pass"] is not True:
                        raise Exception(
                            "style-add global delta/identity is not isolated")
                    if not bool(getattr(va, classifier_method)(created_id)):
                        raise Exception(
                            "created Guid failed the " + classifier_method +
                            " classifier")
                    style_ownership_verified = True

                    tolerance = float(sc.doc.ModelAbsoluteTolerance)
                    if kind == "slab":
                        initial_layer_inventory = va_slab_layer_ids(created_id)
                        if initial_layer_inventory["read_complete"] is not True:
                            raise Exception(
                                "initial slab-layer inventory is incomplete")
                        if initial_layer_inventory["ids"]:
                            raise Exception(
                                "AddSlabStyle created unexpected automatic " +
                                "typed layers; exact requested layers cannot " +
                                "be proven")

                        for requested_layer in requested_layers:
                            global_layer_before = va_global_style_inventory()
                            layer_inventory_before = va_slab_layer_ids(
                                created_id)
                            if global_layer_before["read_complete"] is not True \
                                    or layer_inventory_before[
                                        "read_complete"] is not True:
                                raise Exception(
                                    "pre-AddSlabLayer inventory is incomplete")
                            layer_id = va.AddSlabLayer(
                                created_id, requested_layer["name"],
                                requested_layer["thickness"])
                            if layer_id is None or layer_id == Guid.Empty:
                                raise Exception(
                                    "AddSlabLayer returned an empty Guid for " +
                                    requested_layer["name"])

                            global_layer_after = va_global_style_inventory()
                            layer_inventory_after = va_slab_layer_ids(
                                created_id)
                            if global_layer_after["read_complete"] is not True \
                                    or layer_inventory_after[
                                        "read_complete"] is not True:
                                raise Exception(
                                    "post-AddSlabLayer inventory is incomplete")
                            before_layer_text = [
                                str(value) for value in
                                layer_inventory_before["ids"]]
                            after_layer_text = [
                                str(value) for value in
                                layer_inventory_after["ids"]]
                            new_global_components = sorted(
                                set(global_layer_after["all_component_ids"]) -
                                set(global_layer_before["all_component_ids"]))
                            removed_global_components = sorted(
                                set(global_layer_before["all_component_ids"]) -
                                set(global_layer_after["all_component_ids"]))
                            before_entries = dict(
                                (entry["id"], entry)
                                for entry in global_layer_before["styles"])
                            after_entries = dict(
                                (entry["id"], entry)
                                for entry in global_layer_after["styles"])
                            other_entries_unchanged = all(
                                after_entries.get(style_id) == entry
                                for style_id, entry in before_entries.items()
                                if style_id != str(created_id))
                            expected_target_components = sorted(
                                list(before_entries[str(created_id)][
                                    "component_ids"]) + [str(layer_id)])
                            layer_delta_checks = {
                                "layer_order_exact": after_layer_text ==
                                    before_layer_text + [str(layer_id)],
                                "one_new_global_component":
                                    new_global_components == [str(layer_id)],
                                "no_removed_global_component":
                                    not removed_global_components,
                                "style_ids_unchanged":
                                    global_layer_after["all_style_ids"] ==
                                    global_layer_before["all_style_ids"],
                                "style_owners_unchanged":
                                    global_layer_after["style_owners"] ==
                                    global_layer_before["style_owners"],
                                "other_style_entries_unchanged":
                                    other_entries_unchanged,
                                "target_components_exact":
                                    after_entries.get(
                                        str(created_id), {}).get(
                                            "component_ids") ==
                                    expected_target_components,
                                "component_owner_exact":
                                    global_layer_after[
                                        "component_owners"].get(
                                            str(layer_id)) == str(created_id),
                                "parent_exact":
                                    va.GetParentStyleComponent(layer_id) ==
                                    created_id,
                                "typed_as_slab_layer": bool(
                                    va.IsSlabLayer(layer_id)),
                                "inventory_methods_unchanged":
                                    global_layer_after[
                                        "inventory_methods"] ==
                                    global_layer_before["inventory_methods"],
                                "inventory_counts_unchanged":
                                    global_layer_after["inventory_counts"] ==
                                    global_layer_before["inventory_counts"],
                                "style_count_unchanged":
                                    global_layer_after["style_count"] ==
                                    global_layer_before["style_count"],
                                "component_count_plus_one":
                                    global_layer_after["component_count"] ==
                                    global_layer_before["component_count"] + 1,
                            }
                            if not all(layer_delta_checks.values()):
                                raise Exception(
                                    "AddSlabLayer global delta/parent/order " +
                                    "contract failed")
                            created_layer_ids.append(layer_id)

                            layer_type = va.SlabLayerType.Core \
                                if requested_layer["type"] == "core" \
                                else va.SlabLayerType.Normal
                            if va.SetSlabLayerType(
                                    layer_id, layer_type) is False:
                                raise Exception(
                                    "SetSlabLayerType returned false for " +
                                    requested_layer["name"])
                            actual_layer = va_slab_layer_snapshot(layer_id)
                            if actual_layer["readback_complete"] is not True or \
                                    actual_layer["name"] != \
                                        requested_layer["name"] or \
                                    actual_layer["thickness"] is None or \
                                    abs(actual_layer["thickness"] -
                                        requested_layer["thickness"]) > \
                                        tolerance or \
                                    actual_layer["type"] != \
                                        requested_layer["type"]:
                                raise Exception(
                                    "slab-layer persistent readback mismatch")

                    global_final = va_global_style_inventory()
                    if global_final["read_complete"] is not True:
                        raise Exception("final global inventory is incomplete")
                    expected_component_ids = sorted(
                        list(automatic_component_ids) +
                        [str(value) for value in created_layer_ids])
                    final_delta_contract = va_global_style_create_contract(
                        global_before, global_final, created_id,
                        inventory_method, requested_name,
                        expected_component_ids)
                    actual = va_style_snapshot(created_id)
                    verification_checks = {
                        "global_additive_delta_exact":
                            final_delta_contract["pass"] is True,
                        "style_snapshot_complete": actual is not None and
                            actual.get("readback_complete") is True,
                        "kind_matches": actual is not None and
                            actual.get("kind") == kind,
                        "name_matches": actual is not None and
                            actual.get("name") == requested_name,
                        "classifier_matches": bool(
                            getattr(va, classifier_method)(created_id)),
                        "product_count_read_complete": actual is not None and
                            actual.get("product_count_read_complete") is True,
                        "product_count_zero": actual is not None and
                            actual.get("product_count") == 0,
                    }
                    requested_total = None
                    if kind == "slab":
                        requested_total = sum(
                            layer["thickness"] for layer in requested_layers)
                        verification_checks.update({
                            "layer_count_exact": actual is not None and
                                actual.get("layer_count") ==
                                len(requested_layers),
                            "layer_ids_and_order_exact": actual is not None and
                                [layer["id"] for layer in
                                 actual.get("layers", [])] ==
                                [str(value) for value in created_layer_ids],
                            "total_thickness_exact": actual is not None and
                                actual.get("total_layer_thickness") is not
                                None and abs(
                                    actual["total_layer_thickness"] -
                                    requested_total) <= tolerance,
                        })
                        if actual is not None and \
                                isinstance(actual.get("layers"), list) and \
                                len(actual["layers"]) == len(requested_layers):
                            for index in range(len(requested_layers)):
                                requested_layer = requested_layers[index]
                                actual_layer = actual["layers"][index]
                                verification_checks[
                                    "layer_" + str(index) + "_exact"] = \
                                    actual_layer.get("name") == \
                                        requested_layer["name"] and \
                                    actual_layer.get("thickness") is not None \
                                    and abs(actual_layer["thickness"] -
                                            requested_layer["thickness"]) <= \
                                        tolerance and \
                                    actual_layer.get("type") == \
                                        requested_layer["type"]
                        else:
                            verification_checks["all_layers_exact"] = False
                    if not all(verification_checks.values()):
                        raise Exception(
                            "created " + kind +
                            " style failed persistent verification")

                    result = {
                        "status": "success",
                        "style_id": str(created_id),
                        "requested": {
                            "name": requested_name,
                            "layers": requested_layers
                                if kind == "slab" else None,
                            "total_layer_thickness": requested_total,
                            "layer_order": "VisualARQ component order"
                                if kind == "slab" else None,
                        },
                        "actual": actual,
                        "automatic_component_ids": automatic_component_ids,
                        "created_layer_ids": [
                            str(value) for value in created_layer_ids],
                        "template": template_evidence,
                        "verification": {
                            "pass": True,
                            "checks": verification_checks,
                            "tolerance": tolerance,
                            "source": (
                                "VisualARQ.Script persistent readback plus " +
                                "global exact additive inventory delta"),
                        },
                        "shape_contract": shape_contract,
                        "style_add_contract": style_add_contract,
                        "final_delta_contract": final_delta_contract,
                        "global_inventory_before": global_before,
                        "global_inventory_after": global_final,
                    }
                except Exception as creation_error:
                    global_failure = None
                    ownership_probe = None
                    cleanup_attempts = []
                    cleanup_refused_reason = None
                    try:
                        global_failure = va_global_style_inventory()
                        returned_text = str(created_id) \
                            if created_id != Guid.Empty else None
                        if global_failure["read_complete"] is True and \
                                returned_text is not None and \
                                returned_text not in baseline_guid_union:
                            failure_components = sorted(
                                set(global_failure["all_component_ids"]) -
                                set(global_before["all_component_ids"]))
                            ownership_probe = va_global_style_create_contract(
                                global_before, global_failure, created_id,
                                inventory_method, requested_name,
                                failure_components)
                            if ownership_probe["pass"] is True:
                                style_ownership_verified = True
                    except Exception as ownership_error:
                        cleanup_refused_reason = \
                            "ownership probe failed: " + \
                            va_text(ownership_error)

                    if style_ownership_verified:
                        products = None
                        try:
                            products = list(
                                va.GetProductsByStyle(created_id, False) or [])
                        except Exception as products_error:
                            cleanup_refused_reason = \
                                "product ownership probe failed: " + \
                                va_text(products_error)
                        if products:
                            cleanup_refused_reason = \
                                "created style is already in use"
                        elif products is not None:
                            try:
                                cleanup_attempts.append({
                                    "operation": "DeleteStyle",
                                    "id": str(created_id),
                                    "result": bool(va.DeleteStyle(created_id)),
                                })
                            except Exception as cleanup_error:
                                cleanup_attempts.append({
                                    "operation": "DeleteStyle",
                                    "id": str(created_id),
                                    "error": va_text(cleanup_error),
                                })

                            # VisualARQ 3.7.2 may reject DeleteStyle for the
                            # last Slab Style. Only components that remain a
                            # proven new child of our style are then removed,
                            # followed by one explicit DeleteStyle retry.
                            cleanup_mid = va_global_style_inventory()
                            if cleanup_mid["read_complete"] is True and \
                                    str(created_id) in \
                                    cleanup_mid["all_style_ids"]:
                                owned_component_ids = sorted(
                                    set(cleanup_mid["all_component_ids"]) -
                                    set(global_before["all_component_ids"]))
                                for component_text in reversed(
                                        owned_component_ids):
                                    parent_verified = False
                                    try:
                                        component_id = Guid(component_text)
                                        parent_verified = \
                                            cleanup_mid[
                                                "component_owners"].get(
                                                    component_text) == \
                                                str(created_id) and \
                                            va.GetParentStyleComponent(
                                                component_id) == created_id
                                        if parent_verified:
                                            cleanup_attempts.append({
                                                "operation":
                                                    "DeleteStyleComponent",
                                                "id": component_text,
                                                "parent_verified": True,
                                                "result": bool(
                                                    va.DeleteStyleComponent(
                                                        component_id)),
                                            })
                                        else:
                                            cleanup_attempts.append({
                                                "operation":
                                                    "DeleteStyleComponent",
                                                "id": component_text,
                                                "parent_verified": False,
                                                "refused": True,
                                            })
                                    except Exception as cleanup_error:
                                        cleanup_attempts.append({
                                            "operation":
                                                "DeleteStyleComponent",
                                            "id": component_text,
                                            "parent_verified":
                                                parent_verified,
                                            "error": va_text(cleanup_error),
                                        })
                                try:
                                    cleanup_attempts.append({
                                        "operation": "DeleteStyleRetry",
                                        "id": str(created_id),
                                        "result": bool(
                                            va.DeleteStyle(created_id)),
                                    })
                                except Exception as cleanup_error:
                                    cleanup_attempts.append({
                                        "operation": "DeleteStyleRetry",
                                        "id": str(created_id),
                                        "error": va_text(cleanup_error),
                                    })
                    elif cleanup_refused_reason is None:
                        cleanup_refused_reason = \
                            "returned Guid ownership was not proven"

                    global_cleanup = va_global_style_inventory()
                    cleanup_verified = \
                        global_cleanup["read_complete"] is True and \
                        global_cleanup == global_before
                    result = {
                        "status": "error",
                        "code": "RHINO_ERROR" if cleanup_verified else
                            "PARTIAL_MUTATION",
                        "message": (
                            kind.capitalize() + " style creation failed: " +
                            va_text(creation_error)),
                        "created_style_id": str(created_id)
                            if created_id != Guid.Empty else None,
                        "ownership_verified": style_ownership_verified,
                        "ownership_probe": ownership_probe,
                        "created_layer_ids": [
                            str(value) for value in created_layer_ids],
                        "automatic_component_ids": automatic_component_ids,
                        "cleanup_attempts": cleanup_attempts,
                        "cleanup_refused_reason": cleanup_refused_reason,
                        "cleanup_verified": cleanup_verified,
                        "global_inventory_before": global_before,
                        "global_inventory_after_style": global_after_style,
                        "global_inventory_after_failure": global_failure,
                        "global_inventory_after_cleanup": global_cleanup,
                        "residual_style_ids": sorted(
                            set(global_cleanup.get("all_style_ids", [])) -
                            set(global_before["all_style_ids"])),
                        "residual_component_ids": sorted(
                            set(global_cleanup.get("all_component_ids", [])) -
                            set(global_before["all_component_ids"])),
                    }
"""


def _respond(result: Dict[str, Any], success_message: str) -> str:
    if va_unavailable(result):
        return json.dumps(error(
            _UNAVAILABLE_HINT, code=ErrorCode.RHINO_ERROR,
            data={"available": False},
        ))
    if result.get("status") == "error":
        return json.dumps(error(
            result.get("message", "VisualARQ operation failed"),
            code=result.get("code", ErrorCode.RHINO_ERROR), data=result,
        ))
    return json.dumps(ok(message=success_message, data=result))


def _query_method_flags(rhino: Any, names: List[str]) -> Dict[str, Any]:
    """Read method availability without mutating the Rhino document."""
    return run_va(rhino, """
methods = {}
for method_name in params["names"]:
    methods[method_name] = va_method_available(method_name)
result = {"status": "success", "methods": methods}
""", {"names": names})


def _finite_float(value: Any) -> Optional[float]:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return float(value)
    return None


def _point_matches(
    actual: Any,
    expected: List[float],
    tolerance: float,
) -> bool:
    if not isinstance(actual, (list, tuple)) or len(actual) != 3:
        return False
    coordinates = [_finite_float(value) for value in actual]
    if any(value is None for value in coordinates):
        return False
    return math.sqrt(sum(
        (float(value) - float(target)) ** 2
        for value, target in zip(coordinates, expected)
    )) <= tolerance


def _wall_creation_checks(
    actual: Dict[str, Any],
    expected_style_id: Optional[str],
    expected_style_thickness: Any,
    expected_start: List[float],
    expected_end: List[float],
    expected_height: float,
    tolerance: float,
) -> Dict[str, bool]:
    path = actual.get("path") if isinstance(actual, dict) else None
    geometry = actual.get("geometry") if isinstance(actual, dict) else None
    path = path if isinstance(path, dict) else {}
    geometry = geometry if isinstance(geometry, dict) else {}
    actual_height = _finite_float(actual.get("height")) \
        if isinstance(actual, dict) else None
    actual_thickness = _finite_float(actual.get("thickness")) \
        if isinstance(actual, dict) else None
    style_thickness = _finite_float(expected_style_thickness)
    path_length = _finite_float(path.get("length"))
    bbox_diagonal = _finite_float(geometry.get("bbox_diagonal"))
    expected_path_length = math.sqrt(sum(
        (float(end_value) - float(start_value)) ** 2
        for start_value, end_value in zip(expected_start, expected_end)
    ))
    classifications = actual.get("classifications", []) \
        if isinstance(actual, dict) else []
    return {
        "object_readable": isinstance(actual, dict),
        "readback_complete": actual.get("readback_complete") is True,
        "classified_as_wall": (
            isinstance(classifications, list) and "wall" in classifications
        ),
        "style_matches": (
            expected_style_id is not None
            and actual.get("style_id") == expected_style_id
        ),
        "height_matches": (
            actual_height is not None
            and abs(actual_height - float(expected_height)) <= tolerance
        ),
        "path_start_matches": _point_matches(
            path.get("start"), expected_start, tolerance
        ),
        "path_end_matches": _point_matches(
            path.get("end"), expected_end, tolerance
        ),
        "path_length_matches": (
            path_length is not None
            and abs(path_length - expected_path_length) <= tolerance
        ),
        "geometry_valid": geometry.get("is_valid") is True,
        "bbox_nondegenerate": (
            geometry.get("bbox_valid") is True
            and bbox_diagonal is not None
            and bbox_diagonal > tolerance
        ),
        "thickness_matches_style": (
            actual_thickness is not None
            and style_thickness is not None
            and abs(actual_thickness - style_thickness) <= tolerance
        ),
    }


def _cleanup_created_wall(
    rhino: Any,
    wall_id: str,
    runtime_serial_number: Any,
    creation_runtime_serial_floor: Any = None,
) -> Dict[str, Any]:
    """Delete one exact object generation and prove document absence."""
    if (
        not isinstance(runtime_serial_number, int)
        or isinstance(runtime_serial_number, bool)
        or runtime_serial_number < 1
    ):
        return {
            "status": "error",
            "message": "Wall cleanup refused without a runtime serial number",
            "cleanup_verified": False,
        }
    try:
        return run_va(rhino, r"""
import scriptcontext as sc
object_id = Guid(params["object_id"])
obj = sc.doc.Objects.FindId(object_id)
expected_serial = int(params["runtime_serial_number"])
actual_serial = int(obj.RuntimeSerialNumber) if obj is not None else None
serial_matches = obj is None or actual_serial == expected_serial
deleted = False
if obj is not None and serial_matches:
    deleted = bool(sc.doc.Objects.Delete(object_id, True))
object_exists = sc.doc.Objects.FindId(object_id) is not None
residual_generations = []
serial_floor = params.get("creation_runtime_serial_floor")
if serial_floor is not None:
    for recent_obj in list(sc.doc.Objects.AllObjectsSince(
            max(int(serial_floor) - 1, 0)) or []):
        current_obj = sc.doc.Objects.FindId(recent_obj.Id)
        if current_obj is not None and int(
                current_obj.RuntimeSerialNumber) == int(
                    recent_obj.RuntimeSerialNumber):
            residual_generations.append({
                "id": str(current_obj.Id),
                "runtime_serial_number": int(
                    current_obj.RuntimeSerialNumber),
                "object_type": str(current_obj.GetType().FullName),
            })
is_wall = None
try:
    is_wall = bool(va.IsWall(object_id))
except Exception:
    pass
result = {
    "status": "error" if object_exists or not serial_matches or \
        residual_generations else "success",
    "deleted": deleted, "object_exists": object_exists,
    "expected_runtime_serial_number": expected_serial,
    "actual_runtime_serial_number": actual_serial,
    "runtime_serial_matches": serial_matches,
    "replacement_detected": not serial_matches,
    "is_wall_diagnostic": is_wall,
    "residual_new_generations": residual_generations,
    "cleanup_verified": object_exists is False and serial_matches and \
        not residual_generations,
}
if not serial_matches:
    result["message"] = (
        "Cleanup refused because the GUID now identifies a replacement object")
elif object_exists:
    result["message"] = "Failed postcondition wall still exists"
""", {
            "object_id": wall_id,
            "runtime_serial_number": runtime_serial_number,
            "creation_runtime_serial_floor": creation_runtime_serial_floor,
        })
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Wall cleanup command failed: {exc}",
            "cleanup_verified": False,
        }


def _refresh_wall_quantity(
    rhino: Any,
    result: Dict[str, Any],
    expected_start: List[float],
    expected_end: List[float],
    expected_height: float,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """Refresh VisualARQ's asynchronously populated instance definition.

    ``AddWall`` returns before VisualARQ 3.7.2 has populated the instance
    definition's solid leaves. A bounded follow-up command gives VisualARQ a
    chance to finish between calls and provides a fresh independent readback,
    without sleeping or mutating the document again. Because control has
    returned to the user between commands, this refresh is strictly read-only:
    it never claims or deletes any RhinoObject generation.
    """
    verification = result.get("verification")
    wall_id = result.get("wall_id")
    if (
        result.get("status") != "success"
        or not wall_id
        or not isinstance(verification, dict)
        or verification.get("creation_pass") is not True
        or verification.get("quantity_verification_pass") is True
    ):
        return result

    tolerance = verification.get("tolerance", 0.0)
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
        tolerance = 0.0
    tolerance = max(float(tolerance), 0.0)
    style = result.get("style")
    style = style if isinstance(style, dict) else {}
    expected_style_id = style.get("id")
    expected_style_thickness = style.get("total_layer_thickness")
    initial_actual = result.get("actual")
    initial_actual = initial_actual if isinstance(initial_actual, dict) else {}
    initial_runtime_serial = initial_actual.get("runtime_serial_number")
    initial_command_owned_runtime_serial = result.get(
        "owned_runtime_serial_number", initial_runtime_serial)
    creation_runtime_serial_floor = result.get(
        "creation_runtime_serial_floor")
    generation_history = list(result.get("runtime_generation_history", []))
    if not generation_history and isinstance(initial_runtime_serial, int):
        generation_history.append(initial_runtime_serial)
    verification["runtime_generation"] = {
        "initial_runtime_serial_number": initial_runtime_serial,
        "initial_command_owned_runtime_serial_number":
            initial_command_owned_runtime_serial,
        "readback_runtime_serial_number": initial_runtime_serial,
        "creation_runtime_serial_floor": creation_runtime_serial_floor,
        "history": generation_history,
        "replacement_verified_for_readback": False,
        "cross_command_cleanup_authorized": False,
    }
    refresh_meta: Dict[str, Any] = {
        "attempted": True,
        "attempt_count": 0,
        "complete": False,
        "reason": "visualarq_instance_definition_is_populated_asynchronously",
    }
    if (
        not isinstance(initial_runtime_serial, int)
        or isinstance(initial_runtime_serial, bool)
        or initial_runtime_serial < 1
    ):
        refresh_meta["last_error"] = (
            "initial wall runtime serial number is unavailable"
        )
        verification["post_creation_readback"] = refresh_meta
        warnings = list(result.get("warnings", []))
        if not any(
            warning.startswith("Independent positive volume is not verified")
            for warning in warnings
        ):
            warnings.append(
                "Independent positive volume is not verified; verify through "
                "instance-definition solids or IFC before quantity use"
            )
        result["warnings"] = warnings
        verification["pass"] = False
        result.update({
            "status": "error", "code": "PARTIAL_MUTATION",
            "message": (
                "Created wall remains in the document, but its runtime "
                "generation could not be verified for quantity readback"),
            "cleanup_deleted": False,
            "cleanup_object_exists": True,
            "cleanup_verified": False,
            "cleanup_refused_reason": "cross_command_readback_is_read_only",
        })
        return result

    classification_unverified = False
    for attempt in range(1, max_attempts + 1):
        refresh_meta["attempt_count"] = attempt
        try:
            refreshed = run_va(
                rhino,
                _STYLE_SCRIPT_HELPERS + _OBJECT_SCRIPT_HELPERS + r"""
import scriptcontext as sc
object_id = Guid(params["object_id"])
obj = sc.doc.Objects.FindId(object_id)
if obj is None:
    result = {
        "status": "error", "code": "INVALID_ID",
        "message": "Created wall is no longer present",
        "object_id": params["object_id"],
    }
else:
    classification_probe = va_object_classification_probe(object_id)
    snapshot = va_product_snapshot(obj, classification_probe)
    if snapshot is None:
        classifications = classification_probe["classifications"]
        classification_complete = classification_probe["complete"]
        result = {
            "status": "error",
            "code": "KIND_MISMATCH" if classification_complete \
                else "CLASSIFICATION_UNVERIFIED",
            "message": "Created object is no longer a VisualARQ wall" \
                if classification_complete else \
                "Created wall classification could not be verified",
            "object_exists": True,
            "classifications": classifications,
            "classification_complete": classification_complete,
            "classification_errors": classification_probe["errors"],
            "runtime_serial_number": int(obj.RuntimeSerialNumber),
        }
    else:
        result = {"status": "success", "object": snapshot}
""",
                {"object_id": wall_id},
            )
        except Exception as exc:
            refresh_meta["last_error"] = (
                f"post-creation readback command failed: {exc}"
            )
            continue
        if (
            refreshed.get("status") == "error"
            and refreshed.get("code") == "INVALID_ID"
        ):
            creation_checks = dict(
                verification.get("creation_checks") or {}
            )
            creation_checks["object_readable"] = False
            verification["creation_checks"] = creation_checks
            verification["creation_pass"] = False
            verification["quantity_verification_pass"] = False
            verification["pass"] = False
            refresh_meta["last_error"] = refreshed.get("message")
            verification["post_creation_readback"] = refresh_meta
            result.update({
                "status": "error",
                "code": "VERIFICATION_FAILED",
                "message": "Created wall disappeared before final readback",
                "cleanup_verified": True,
                "cleanup_object_exists": False,
            })
            return result
        if (
            refreshed.get("status") == "error"
            and refreshed.get("code") == "KIND_MISMATCH"
        ):
            current_serial = refreshed.get("runtime_serial_number")
            if (
                isinstance(current_serial, int)
                and not isinstance(current_serial, bool)
                and current_serial not in generation_history
            ):
                generation_history.append(current_serial)
            result["readback_runtime_serial_number"] = current_serial
            result["runtime_generation_history"] = generation_history
            verification["runtime_generation"].update({
                "readback_runtime_serial_number": current_serial,
                "history": generation_history,
                "replacement_verified_for_readback": False,
            })
            creation_checks = dict(
                verification.get("creation_checks") or {}
            )
            creation_checks["classified_as_wall"] = False
            verification["creation_checks"] = creation_checks
            verification["creation_pass"] = False
            verification["quantity_verification_pass"] = False
            verification["pass"] = False
            refresh_meta["last_error"] = refreshed.get("message")
            verification["post_creation_readback"] = refresh_meta
            result.update({
                "status": "error",
                "code": "PARTIAL_MUTATION",
                "message": (
                    "Created object failed final wall classification; the "
                    "cross-command readback retained it for user review"),
                "cleanup_deleted": False,
                "cleanup_object_exists": True,
                "cleanup_verified": False,
                "cleanup_refused_reason":
                    "cross_command_readback_is_read_only",
                "classification_errors": refreshed.get(
                    "classification_errors", []),
            })
            return result
        if (
            refreshed.get("status") == "error"
            and refreshed.get("code") == "CLASSIFICATION_UNVERIFIED"
        ):
            current_serial = refreshed.get("runtime_serial_number")
            if (
                isinstance(current_serial, int)
                and not isinstance(current_serial, bool)
                and current_serial not in generation_history
            ):
                generation_history.append(current_serial)
            result["readback_runtime_serial_number"] = current_serial
            result["runtime_generation_history"] = generation_history
            verification["runtime_generation"].update({
                "readback_runtime_serial_number": current_serial,
                "history": generation_history,
                "replacement_verified_for_readback": False,
            })
            classification_unverified = True
            refresh_meta["last_error"] = refreshed.get("message")
            refresh_meta["classification_errors"] = refreshed.get(
                "classification_errors", [])
            continue
        if va_unavailable(refreshed) or refreshed.get("status") == "error":
            refresh_meta["last_error"] = refreshed.get(
                "message", "post-creation readback failed"
            )
            continue
        actual = refreshed.get("object")
        if not isinstance(actual, dict):
            refresh_meta["last_error"] = (
                "post-creation readback returned no object snapshot"
            )
            continue
        current_serial = actual.get("runtime_serial_number")
        classification_unverified = False

        result["actual"] = actual
        if actual.get("height") is not None:
            result["actual_height"] = actual["height"]
        if actual.get("height_source") is not None:
            result["height_source"] = actual["height_source"]

        creation_checks = _wall_creation_checks(
            actual,
            expected_style_id,
            expected_style_thickness,
            expected_start,
            expected_end,
            expected_height,
            tolerance,
        )
        creation_pass = all(creation_checks.values())
        serial_matches_initial = current_serial == initial_runtime_serial
        replacement_is_readback_candidate = (
            not serial_matches_initial
            and isinstance(current_serial, int)
            and not isinstance(current_serial, bool)
            and isinstance(creation_runtime_serial_floor, int)
            and not isinstance(creation_runtime_serial_floor, bool)
            and current_serial >= creation_runtime_serial_floor
        )
        if (
            isinstance(current_serial, int)
            and not isinstance(current_serial, bool)
            and current_serial not in generation_history
        ):
            generation_history.append(current_serial)
        result["readback_runtime_serial_number"] = current_serial
        result["runtime_generation_history"] = generation_history
        verification["runtime_generation"].update({
            "readback_runtime_serial_number": current_serial,
            "history": generation_history,
            "replacement_verified_for_readback":
                replacement_is_readback_candidate and creation_pass,
        })
        result["replacement_detected"] = not serial_matches_initial
        refresh_meta["readback_runtime_serial_number"] = current_serial
        verification["creation_checks"] = creation_checks
        if replacement_is_readback_candidate and creation_pass:
            refresh_meta["generation_verified_for_readback"] = True
        elif not serial_matches_initial:
            verification["creation_pass"] = False
            verification["quantity_verification_pass"] = False
            verification["pass"] = False
            refresh_meta["last_error"] = (
                "wall GUID now identifies an unowned runtime object"
            )
            verification["post_creation_readback"] = refresh_meta
            result.update({
                "status": "error", "code": "PARTIAL_MUTATION",
                "message": (
                    "Wall generation changed without matching the verified "
                    "creation contract; cleanup was refused"),
                "replacement_detected": True,
                "initial_runtime_serial_number": initial_runtime_serial,
                "owned_runtime_serial_number":
                    initial_command_owned_runtime_serial,
                "actual_runtime_serial_number": current_serial,
                "creation_runtime_serial_floor": \
                    creation_runtime_serial_floor,
                "cleanup_verified": False,
                "cleanup_deleted": False,
            })
            return result
        verification["creation_pass"] = creation_pass
        if not creation_pass:
            verification["quantity_verification_pass"] = False
            verification["pass"] = False
            refresh_meta["last_error"] = (
                "fresh wall creation postconditions do not match"
            )
            verification["post_creation_readback"] = refresh_meta
            result.update({
                "status": "error",
                "code": "PARTIAL_MUTATION",
                "message": (
                    "Wall no longer matched the creation contract at final "
                    "readback; it was retained for user review"),
                "cleanup_deleted": False,
                "cleanup_object_exists": True,
                "cleanup_verified": False,
                "cleanup_refused_reason":
                    "cross_command_readback_is_read_only",
            })
            return result

        geometry = actual.get("geometry") or {}
        quantity = actual.get("quantity") or {}
        direct_volume = geometry.get("volume")
        definition_volume = quantity.get("volume") \
            if quantity.get("volume_verified") is True else None
        volume = None
        volume_source = None
        direct_volume = _finite_float(direct_volume)
        definition_volume = _finite_float(definition_volume)
        if direct_volume is not None:
            volume = direct_volume
            volume_source = "object_geometry"
        elif definition_volume is not None:
            volume = definition_volume
            volume_source = quantity.get("source")

        quantity_checks = {
            "volume_available": volume is not None,
            "volume_positive": (
                volume is not None and volume > tolerance * tolerance * tolerance
            ),
        }
        quantity_pass = all(quantity_checks.values())
        verification["quantity_checks"] = quantity_checks
        verification["quantity_verification_pass"] = quantity_pass
        verification["pass"] = creation_pass and quantity_pass
        verification["volume_verified"] = volume is not None
        verification["volume"] = volume
        verification["volume_source"] = volume_source
        refresh_meta["complete"] = quantity_pass
        if quantity_pass:
            refresh_meta.pop("last_error", None)
            break
        refresh_meta["last_error"] = (
            "instance-definition volume is not available yet"
        )

    verification["post_creation_readback"] = refresh_meta
    if classification_unverified:
        verification["creation_pass"] = False
        verification["quantity_verification_pass"] = False
        verification["pass"] = False
        result.update({
            "status": "error", "code": "PARTIAL_MUTATION",
            "message": (
                "Created wall still exists, but final classification "
                "remained unverified; object was not deleted"),
            "cleanup_deleted": False,
            "cleanup_object_exists": True,
            "cleanup_verified": False,
        })
        return result
    warnings = [
        warning for warning in result.get("warnings", [])
        if not warning.startswith("Independent positive volume is not verified")
    ]
    if verification.get("quantity_verification_pass") is not True:
        warnings.append(
            "Independent positive volume is not verified; verify through "
            "instance-definition solids or IFC before quantity use"
        )
        verification["pass"] = False
        result.update({
            "status": "error", "code": "PARTIAL_MUTATION",
            "message": (
                "Created wall remains in the document, but independent "
                "positive volume was not verified after bounded readback"),
            "cleanup_deleted": False,
            "cleanup_object_exists": True,
            "cleanup_verified": False,
            "cleanup_refused_reason": "cross_command_readback_is_read_only",
        })
    result["warnings"] = warnings
    return result


@mcp.tool()
def va_status(ctx: Context) -> str:
    """Check VisualARQ availability and document BIM inventory.

    Run this BEFORE other `va_*` tools. Reports whether the VisualARQ
    plugin is loaded plus style/level counts of the active document.

    Returns:
        {"success": true, "data": {"available": true,
            "wall_styles": 4, "door_styles": 6, "window_styles": 5,
            "slab_styles": 3, "space_styles": 2, "levels": 2}}
        or {"success": true, "data": {"available": false, "hint": "..."}}.
    """
    try:
        rhino = get_rhino_connection()
        # VisualARQ's cold bootstrap has two phases: assembly load and the
        # first Script API call. The probe absorbs the former. The status body
        # is read-only, so it alone may be retried once when Rhino reports a
        # successful script invocation without the RESULT marker. Mutators are
        # never retried by run_va.
        warm_va(rhino)
        status_body = """
def safe(fn):
    try:
        return fn()
    except Exception:
        return None
def count_levels():
    if hasattr(va, "GetAllLevelIds"):
        return len(va.GetAllLevelIds() or [])
    n = 0
    for bid in (va.GetAllBuildingIds() or []):
        n += len(va.GetBuildingLevelIds(bid) or [])
    return n
def version_info():
    assembly_version = safe(lambda: str(va_assembly.GetName().Version))
    file_version = None
    product_version = None
    try:
        from System.Diagnostics import FileVersionInfo
        info = FileVersionInfo.GetVersionInfo(va_assembly.Location)
        file_version = str(info.FileVersion or "") or None
        product_version = str(info.ProductVersion or "") or None
    except Exception:
        pass
    return {
        "version": product_version or file_version or assembly_version,
        "product_version": product_version,
        "file_version": file_version,
        "assembly_version": assembly_version,
    }
method_names = [
    "AddWall", "SetWallHeight", "GetWallHeight", "GetWallThickness",
    "GetWallHeightSource", "GetWallPathCurve", "GetWallLayers",
    "GetWallAlignment", "GetWallAlignmentOffset",
    "GetWallLayerThickness", "GetWallLayerType", "GetWallLayerWrapping",
    "GetWallLayerThicknessSource", "GetWallLayerTopOffset",
    "GetWallLayerTopOffsetSource", "GetWallLayerBottomOffset",
    "GetWallLayerBottomOffsetSource", "GetProductStyle",
    "GetProductsByStyle", "GetStyleName",
    "AddWallStyle", "SetWallStyleHeight", "GetWallStyleHeight",
    "AddWallLayer", "GetSubStyleComponents", "GetStyleComponentName",
    "GetParentStyleComponent", "IsWallLayer", "SetWallLayerType",
    "SetWallLayerWrapping", "RenameStyle", "DeleteStyle",
    "DeleteStyleComponent",
    "AddDoor", "SetDoorWidth", "SetDoorHeight",
    "GetDoorWidth", "GetDoorHeight", "GetOpeningHost",
    "GetDoorHostId", "GetDoorWallId",
    "GetOpeningProfile", "SetOpeningProfile", "AddDoorStyle",
    "AddOpeningStyleSizeProfile", "FindOpeningStyleSizeProfile",
    "GetOpeningStyleSizeProfiles", "GetOpeningStyleFromSizeProfile",
    "IsOpeningStyleSizeProfile", "GetOpeningStyleProfileTemplate",
    "GetRectangularProfileTemplate", "GetRectangularProfileSize",
    "SetRectangularProfileSize", "DeleteProfile",
    "FindOpeningsBySizeProfile",
    "AddSlabFromCurve", "GetSlabContour", "GetSlabThickness",
    "GetSlabAlignment", "GetSlabLayers", "GetSlabLayerThickness",
    "GetSlabLayerType", "IsSlab", "IsSlabLayer", "IsSlabStyle",
    "AddSlabStyle", "AddSlabLayer", "SetSlabLayerType",
    "AddSpaceFromCurve", "GetSpaceCurve", "GetSpaceArea",
    "GetSpacePerimeter", "GetSpaceHeight", "GetSpaceEffectiveHeight",
    "GetSpaceElevation", "GetSpaceVolume", "GetSpaceLabelPosition",
    "GetSpacePoint", "SetSpaceHeight", "SetSpaceElevation",
    "SetSpaceLabelPosition", "GetAllSlabStyleIds", "GetAllSpaceStyleIds",
    "GetAllBeamStyle",
    "AddSpaceStyle", "IsSpaceStyle", "IsProfileTemplate",
    "AddWindow", "AddWindowStyle", "AddBuilding", "DeleteBuilding",
    "IsBuilding",
    "GetAllBuildingIds", "GetBuildingLevelIds", "GetBuildingName",
    "GetBuildingElevation", "AddLevel", "DeleteLevel", "IsLevel",
    "GetAllLevelIds", "GetLevelName", "GetLevelElevation",
    "GetLevelCutElevation",
    "GetLevelBuildingId", "GetLevelBuidlingId",
    "ExportIFC", "ImportIFC",
    "IsProduct", "IsBuildingElement", "IsOpening", "IsGenericElement",
    "IsSpace", "IsSection", "GetActiveSection", "SetActiveSection",
    "IsPlanModeEnabled", "EnablePlanMode",
]
methods = {}
for method_name in method_names:
    methods[method_name] = va_method_available(method_name)
wall_modern_shape = va_exact_method_shape("AddWall", [
    "System.Guid", "Rhino.Geometry.Point3d", "Rhino.Geometry.Point3d"])
door_modern_shape = va_exact_method_shape("AddDoor", [
    "System.Guid", "Rhino.Geometry.Point3d", "System.Double"])
window_modern_shape = va_exact_method_shape("AddWindow", [
    "System.Guid", "Rhino.Geometry.Point3d", "System.Double"])
slab_curve_shape = va_exact_method_shape("AddSlabFromCurve", [
    "System.Guid", "Rhino.Geometry.Curve",
    "VisualARQ.Script+SlabAlignment"])
space_curve_shape = va_exact_method_shape("AddSpaceFromCurve", [
    "System.Guid", "Rhino.Geometry.Curve"])
level_modern_shape = va_exact_method_shape("AddLevel", [
    "System.Guid", "System.String", "System.Double"])
door_style_shape = va_exact_method_shape("AddDoorStyle", [
    "System.String", "System.Guid"], "System.Guid")
window_style_shape = va_exact_method_shape("AddWindowStyle", [
    "System.String", "System.Guid"], "System.Guid")
slab_style_shape = va_exact_method_shape("AddSlabStyle", [
    "System.String", "System.Guid"], "System.Guid")
slab_layer_shape = va_exact_method_shape("AddSlabLayer", [
    "System.Guid", "System.String", "System.Double"], "System.Guid")
slab_layer_type_shape = va_exact_method_shape("SetSlabLayerType", [
    "System.Guid", "VisualARQ.Script+SlabLayerType"], "System.Boolean")
space_style_shape = va_exact_method_shape(
    "AddSpaceStyle", ["System.String"], "System.Guid")
style_creation_shared_shapes = {
    "GetAllBeamStyle": va_exact_method_shape(
        "GetAllBeamStyle", [], "System.Guid[]"),
    "GetAllWallStyleIds": va_exact_method_shape(
        "GetAllWallStyleIds", [], "System.Guid[]"),
    "GetAllDoorStyleIds": va_exact_method_shape(
        "GetAllDoorStyleIds", [], "System.Guid[]"),
    "GetAllWindowStyleIds": va_exact_method_shape(
        "GetAllWindowStyleIds", [], "System.Guid[]"),
    "GetAllSlabStyleIds": va_exact_method_shape(
        "GetAllSlabStyleIds", [], "System.Guid[]"),
    "GetAllSpaceStyleIds": va_exact_method_shape(
        "GetAllSpaceStyleIds", [], "System.Guid[]"),
    "GetStyleName": va_exact_method_shape(
        "GetStyleName", ["System.Guid"], "System.String"),
    "GetSubStyleComponents": va_exact_method_shape(
        "GetSubStyleComponents", ["System.Guid"], "System.Guid[]"),
    "GetProductsByStyle": va_exact_method_shape(
        "GetProductsByStyle", ["System.Guid", "System.Boolean"],
        "System.Guid[]"),
    "GetParentStyleComponent": va_exact_method_shape(
        "GetParentStyleComponent", ["System.Guid"], "System.Guid"),
    "DeleteStyle": va_exact_method_shape(
        "DeleteStyle", ["System.Guid"], "System.Boolean"),
    "DeleteStyleComponent": va_exact_method_shape(
        "DeleteStyleComponent", ["System.Guid"], "System.Boolean"),
}
slab_style_contract_shapes = dict(style_creation_shared_shapes)
slab_style_contract_shapes.update({
    "AddSlabStyle": slab_style_shape,
    "AddSlabLayer": slab_layer_shape,
    "SetSlabLayerType": slab_layer_type_shape,
    "GetRectangularProfileTemplate": va_exact_method_shape(
        "GetRectangularProfileTemplate", [], "System.Guid"),
    "IsProfileTemplate": va_exact_method_shape(
        "IsProfileTemplate", ["System.Guid"], "System.Boolean"),
    "IsSlabStyle": va_exact_method_shape(
        "IsSlabStyle", ["System.Guid"], "System.Boolean"),
    "GetSlabLayers": va_exact_method_shape(
        "GetSlabLayers", ["System.Guid"], "System.Guid[]"),
    "IsSlabLayer": va_exact_method_shape(
        "IsSlabLayer", ["System.Guid"], "System.Boolean"),
    "GetSlabLayerThickness": va_exact_method_shape(
        "GetSlabLayerThickness", ["System.Guid"], "System.Double"),
    "GetSlabLayerType": va_exact_method_shape(
        "GetSlabLayerType", ["System.Guid"],
        "VisualARQ.Script+SlabLayerType"),
    "GetStyleComponentName": va_exact_method_shape(
        "GetStyleComponentName", ["System.Guid"], "System.String"),
})
space_style_contract_shapes = dict(style_creation_shared_shapes)
space_style_contract_shapes.update({
    "AddSpaceStyle": space_style_shape,
    "IsSpaceStyle": va_exact_method_shape(
        "IsSpaceStyle", ["System.Guid"], "System.Boolean"),
})
opening_size_profile_shape = va_exact_method_shape(
    "AddOpeningStyleSizeProfile", ["System.Guid", "System.String"],
    "System.Guid")
result = {
    "available": True,
    "visualarq": version_info(),
    "document": safe(lambda: {
        "units": str(__import__("scriptcontext").doc.ModelUnitSystem),
        "absolute_tolerance": float(
            __import__("scriptcontext").doc.ModelAbsoluteTolerance),
        "relative_tolerance": float(
            __import__("scriptcontext").doc.ModelRelativeTolerance),
        "angle_tolerance_radians": float(
            __import__("scriptcontext").doc.ModelAngleToleranceRadians),
    }),
    "capabilities": {
        "methods": methods,
        "method_shapes": {
            "AddWall": va_method_parameter_sets("AddWall"),
            "AddDoor": va_method_parameter_sets("AddDoor"),
            "AddWindow": va_method_parameter_sets("AddWindow"),
            "AddSlabFromCurve": va_method_parameter_sets(
                "AddSlabFromCurve"),
            "AddSpaceFromCurve": va_method_parameter_sets(
                "AddSpaceFromCurve"),
            "AddDoorStyle": va_method_parameter_sets("AddDoorStyle"),
            "AddWindowStyle": va_method_parameter_sets("AddWindowStyle"),
            "AddSlabStyle": va_method_parameter_sets("AddSlabStyle"),
            "AddSlabLayer": va_method_parameter_sets("AddSlabLayer"),
            "SetSlabLayerType": va_method_parameter_sets(
                "SetSlabLayerType"),
            "AddSpaceStyle": va_method_parameter_sets("AddSpaceStyle"),
            "AddOpeningStyleSizeProfile": va_method_parameter_sets(
                "AddOpeningStyleSizeProfile"),
            "AddLevel": va_method_parameter_sets("AddLevel"),
        },
        "method_signatures": {
            "AddWall": va_method_signatures("AddWall"),
            "AddDoor": va_method_signatures("AddDoor"),
            "AddWindow": va_method_signatures("AddWindow"),
            "AddSlabFromCurve": va_method_signatures("AddSlabFromCurve"),
            "AddSpaceFromCurve": va_method_signatures("AddSpaceFromCurve"),
            "AddDoorStyle": va_method_signatures("AddDoorStyle"),
            "AddWindowStyle": va_method_signatures("AddWindowStyle"),
            "AddSlabStyle": va_method_signatures("AddSlabStyle"),
            "AddSlabLayer": va_method_signatures("AddSlabLayer"),
            "SetSlabLayerType": va_method_signatures(
                "SetSlabLayerType"),
            "AddSpaceStyle": va_method_signatures("AddSpaceStyle"),
            "AddOpeningStyleSizeProfile": va_method_signatures(
                "AddOpeningStyleSizeProfile"),
            "AddLevel": va_method_signatures("AddLevel"),
        },
        "wall_style_first_api": wall_modern_shape["verified"],
        "door_point_api": door_modern_shape["verified"],
        "window_point_api": window_modern_shape["verified"],
        "slab_curve_api": slab_curve_shape["verified"],
        "space_curve_api": space_curve_shape["verified"],
        "door_style_rectangular_api": door_style_shape["verified"],
        "window_style_rectangular_api": window_style_shape["verified"],
        "slab_style_create_api": all(
            shape["verified"]
            for shape in slab_style_contract_shapes.values()),
        "space_style_create_api": all(
            shape["verified"]
            for shape in space_style_contract_shapes.values()),
        "style_creation_shape_contracts": {
            "slab": slab_style_contract_shapes,
            "space": space_style_contract_shapes,
        },
        "opening_size_profile_api": opening_size_profile_shape["verified"],
        "level_building_api": level_modern_shape["verified"],
        "door_direct_dimension_override": (
            methods["SetDoorWidth"] and methods["SetDoorHeight"]),
        "door_direct_dimension_readback": (
            methods["GetDoorWidth"] and methods["GetDoorHeight"]),
        "opening_profile_readback": methods["GetOpeningProfile"],
        "opening_profile_override": methods["SetOpeningProfile"],
        "opening_style_size_profiles": methods["AddOpeningStyleSizeProfile"],
        "ifc_export_api": (
            "VisualARQ.Script" if methods["ExportIFC"]
            else "RhinoDoc.WriteFile"),
        "api_shape_detection": {
            "source": "loaded VisualARQ.Script .NET reflection",
            "risk": (
                "Shapes describe the assembly loaded in this Rhino process; "
                "re-run va_status after every VisualARQ update"),
        },
    },
    "wall_styles": safe(lambda: len(va.GetAllWallStyleIds() or [])),
    "door_styles": safe(lambda: len(va.GetAllDoorStyleIds() or [])),
    "window_styles": safe(lambda: len(va.GetAllWindowStyleIds() or [])),
    "slab_styles": safe(lambda: len(va.GetAllSlabStyleIds() or [])),
    "space_styles": safe(lambda: len(va.GetAllSpaceStyleIds() or [])),
    "levels": safe(count_levels),
    "buildings": safe(lambda: len(va.GetAllBuildingIds() or [])),
}
"""
        result = run_va(rhino, status_body)
        if result.get("runner_failure") == "missing_result_marker":
            result = run_va(rhino, status_body)
            result["bootstrap_retry_attempted"] = True
            result["bootstrap_retry_reason"] = "missing_result_marker"
        if va_unavailable(result):
            # Status is a *query*: not-installed is an answer, not an error.
            return json.dumps(ok(
                message="VisualARQ not available",
                data={"available": False, "hint": _UNAVAILABLE_HINT},
            ))
        if result.get("status") == "error":
            return _respond(result, "")
        return json.dumps(ok(
            message=f"VisualARQ available — {result.get('wall_styles')} wall / "
                    f"{result.get('door_styles')} door / "
                    f"{result.get('window_styles')} window / "
                    f"{result.get('slab_styles')} slab / "
                    f"{result.get('space_styles')} space styles, "
                    f"{result.get('levels')} levels",
            data=result,
        ))
    except Exception as e:
        logger.error(f"Error checking VisualARQ status: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_styles(ctx: Context, kind: str = "wall") -> str:
    """List wall, door, window, slab, or space VisualARQ styles.

    Returns:
        {"success": true, "data": {"kind": "door",
            "styles": [{"id": "...", "name": "Door 80x210"}, ...]}}
    """
    if kind not in ("wall", "door", "window", "slab", "space"):
        return json.dumps(from_exception(
            ValueError(
                "kind must be 'wall', 'door', 'window', 'slab' or 'space'"),
            code=ErrorCode.INVALID_PARAMS))
    try:
        rhino = get_rhino_connection()
        result = run_va(rhino, _STYLE_SCRIPT_HELPERS + r"""
kind = params["kind"]
styles = [va_style_snapshot(style_id) for style_id in va_style_ids(kind)]
styles = [style for style in styles if style is not None]
styles.sort(key=lambda style: (va_text_key(style["name"]), style["id"]))
name_groups = {}
for style in styles:
    key = va_text_key(style["name"])
    if key not in name_groups:
        name_groups[key] = []
    name_groups[key].append(style)
ambiguous_names = []
for key in sorted(name_groups.keys()):
    group = name_groups[key]
    if len(group) > 1:
        ambiguous_names.append({
            "name": group[0]["name"],
            "ids": [style["id"] for style in group],
        })
result = {
    "status": "success", "kind": kind,
    "styles": styles, "count": len(styles),
    "ambiguous_names": ambiguous_names,
    "readback_complete": all(
        style.get("readback_complete", True) for style in styles),
    "incomplete_style_ids": [
        style["id"] for style in styles
        if style.get("readback_complete", True) is not True
    ],
}
""", {"kind": kind})
        return _respond(
            result,
            f"{len(result.get('styles', []))} {kind} style(s)",
        )
    except Exception as e:
        logger.error(f"Error listing VisualARQ styles: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_get_style(
    ctx: Context,
    style_id: str,
    expected_kind: Optional[str] = None,
) -> str:
    """Read one VisualARQ style by canonical GUID.

    Wall and Slab styles include their measured layer structure. Door/window
    styles include size-profile identities; Space styles include identity and
    current product count. ``expected_kind`` turns a mismatch into an error.
    """
    try:
        _require_guid(style_id, "style_id")
        if expected_kind is not None and expected_kind not in {
            "wall", "door", "window", "slab", "space",
        }:
            raise ValueError(
                "expected_kind must be 'wall', 'door', 'window', 'slab', "
                "or 'space'")
        rhino = get_rhino_connection()
        result = run_va(rhino, _STYLE_SCRIPT_HELPERS + r"""
style_id = Guid(params["style_id"])
style = va_style_snapshot(style_id)
if style is None:
    result = {
        "status": "error", "code": "INVALID_ID",
        "message": "VisualARQ style not found: " + params["style_id"],
    }
elif params.get("expected_kind") is not None and \
        style["kind"] != params["expected_kind"]:
    result = {
        "status": "error", "code": "INVALID_ID",
        "message": "Style kind mismatch",
        "expected_kind": params["expected_kind"],
        "actual_kind": style["kind"], "style": style,
    }
elif style.get("readback_complete", True) is not True:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": "VisualARQ style readback is incomplete",
        "style": style,
    }
else:
    result = {"status": "success", "style": style}
""", {"style_id": style_id, "expected_kind": expected_kind})
        return _respond(result, f"VisualARQ style {style_id}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error reading VisualARQ style: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


def _va_create_opening_style(
    ctx: Context,
    name: str,
    *,
    opening_kind: Literal["door", "window"],
) -> str:
    """Create one verified rectangular Door/Window Style."""

    try:
        _require_name(name, "name")
        requested_name = name.strip()
        rhino = get_rhino_connection()
        opening_style_script = r"""
requested_name = params["name"]
mutation_shapes = {
    "AddDoorStyle": va_exact_method_shape(
        "AddDoorStyle", ["System.String", "System.Guid"], "System.Guid"),
    "GetRectangularProfileTemplate": va_exact_method_shape(
        "GetRectangularProfileTemplate", [], "System.Guid"),
    "GetProfileTemplates": va_exact_method_shape(
        "GetProfileTemplates", [], "System.Guid[]"),
    "IsOpeningStyle": va_exact_method_shape(
        "IsOpeningStyle", ["System.Guid"], "System.Boolean"),
    "IsDoorStyle": va_exact_method_shape(
        "IsDoorStyle", ["System.Guid"], "System.Boolean"),
    "GetStyleName": va_exact_method_shape(
        "GetStyleName", ["System.Guid"], "System.String"),
    "GetProductsByStyle": va_exact_method_shape(
        "GetProductsByStyle", ["System.Guid", "System.Boolean"],
        "System.Guid[]"),
    "DeleteStyle": va_exact_method_shape(
        "DeleteStyle", ["System.Guid"], "System.Boolean"),
}
failed_mutation_shapes = sorted(
    method_name for method_name in mutation_shapes
    if mutation_shapes[method_name]["verified"] is not True)
profile_shape_contract = va_opening_profile_shape_contract()
if failed_mutation_shapes or profile_shape_contract["pass"] is not True:
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "message": (
            "VisualARQ door-style API has no unique supported CLR shape"),
        "failed_mutation_shapes": failed_mutation_shapes,
        "mutation_shapes": mutation_shapes,
        "profile_shape_contract": profile_shape_contract,
    }
else:
    global_before = va_global_style_inventory()
    profiles_before = va_opening_profile_inventory()
    if global_before["read_complete"] is not True or \
            profiles_before["read_complete"] is not True:
        result = {
            "status": "error", "code": "VERIFICATION_FAILED",
            "message": (
                "Global VisualARQ style/profile baseline is incomplete; "
                "door style creation was refused before mutation"),
            "global_inventory_before": global_before,
            "profile_inventory_before": profiles_before,
        }
    else:
        duplicate_style_ids = sorted(
            entry["id"] for entry in global_before["styles"]
            if entry["inventory_method"] == "GetAllDoorStyleIds" and
            va_text_key(entry["name"]) == va_text_key(requested_name))
        if duplicate_style_ids:
            result = {
                "status": "error", "code": "ALREADY_EXISTS",
                "message": "A door style with this name already exists",
                "name": requested_name,
                "style_ids": duplicate_style_ids,
            }
        else:
            template_id = Guid.Empty
            template_evidence = None
            try:
                template_id = va.GetRectangularProfileTemplate()
                template_catalog = list(va.GetProfileTemplates() or [])
                template_evidence = {
                    "id": str(template_id)
                        if template_id != Guid.Empty else None,
                    "name": va_text(va.GetProfileName(template_id))
                        if template_id != Guid.Empty else None,
                    "in_catalog": template_id in template_catalog,
                    "is_profile": bool(va.IsProfile(template_id))
                        if template_id != Guid.Empty else False,
                    "is_profile_template": bool(
                        va.IsProfileTemplate(template_id))
                        if template_id != Guid.Empty else False,
                    "rectangular": bool(va.IsRectangularProfile(template_id))
                        if template_id != Guid.Empty else False,
                }
            except Exception as template_error:
                template_evidence = {
                    "id": None, "error": va_text(template_error)}
            template_verified = template_id != Guid.Empty and \
                template_evidence.get("in_catalog") is True and \
                template_evidence.get("is_profile") is True and \
                template_evidence.get("is_profile_template") is True and \
                template_evidence.get("rectangular") is True
            if not template_verified:
                result = {
                    "status": "error", "code": "VERIFICATION_FAILED",
                    "message": (
                        "The canonical rectangular VisualARQ profile "
                        "template could not be verified"),
                    "template": template_evidence,
                }
            else:
                created_id = Guid.Empty
                ownership_verified = False
                try:
                    baseline_guid_union = set(
                        global_before["all_style_ids"] +
                        global_before["all_component_ids"] +
                        profiles_before["all_profile_ids"])
                    created_id = va.AddDoorStyle(
                        requested_name, template_id)
                    if created_id is None or created_id == Guid.Empty:
                        raise Exception("AddDoorStyle returned an empty Guid")
                    if str(created_id) in baseline_guid_union:
                        raise Exception(
                            "AddDoorStyle returned a pre-existing Guid")
                    global_after = va_global_style_inventory()
                    profiles_after = va_opening_profile_inventory()
                    if global_after["read_complete"] is not True or \
                            profiles_after["read_complete"] is not True:
                        raise Exception(
                            "post-creation style/profile inventory is incomplete")

                    added_style_ids = sorted(
                        set(global_after["all_style_ids"]) -
                        set(global_before["all_style_ids"]))
                    removed_style_ids = sorted(
                        set(global_before["all_style_ids"]) -
                        set(global_after["all_style_ids"]))
                    added_component_ids = sorted(
                        set(global_after["all_component_ids"]) -
                        set(global_before["all_component_ids"]))
                    removed_component_ids = sorted(
                        set(global_before["all_component_ids"]) -
                        set(global_after["all_component_ids"]))
                    added_profile_ids = sorted(
                        set(profiles_after["all_profile_ids"]) -
                        set(profiles_before["all_profile_ids"]))
                    removed_profile_ids = sorted(
                        set(profiles_before["all_profile_ids"]) -
                        set(profiles_after["all_profile_ids"]))
                    before_styles_by_key = dict(
                        (entry["key"], entry)
                        for entry in global_before["styles"])
                    after_styles_by_key = dict(
                        (entry["key"], entry)
                        for entry in global_after["styles"])
                    existing_styles_unchanged = all(
                        after_styles_by_key.get(key) == entry
                        for key, entry in before_styles_by_key.items())
                    before_profiles_by_key = dict(
                        (entry["key"], entry)
                        for entry in profiles_before["styles"])
                    after_profiles_by_key = dict(
                        (entry["key"], entry)
                        for entry in profiles_after["styles"])
                    existing_profile_styles_unchanged = all(
                        after_profiles_by_key.get(key) == entry
                        for key, entry in before_profiles_by_key.items())
                    added_profile_style_keys = sorted(
                        set(after_profiles_by_key) -
                        set(before_profiles_by_key))
                    expected_profile_style_key = "door|" + str(created_id)
                    new_components_owned = all(
                        global_after["component_owners"].get(component_id) ==
                        str(created_id)
                        for component_id in added_component_ids)
                    new_profiles_owned = all(
                        profiles_after["profile_owners"].get(profile_id) ==
                        str(created_id)
                        for profile_id in added_profile_ids)
                    ownership_verified = \
                        added_style_ids == [str(created_id)] and \
                        not removed_style_ids and \
                        global_after["style_owners"].get(str(created_id)) == \
                        "GetAllDoorStyleIds" and \
                        existing_styles_unchanged and \
                        not removed_component_ids and \
                        new_components_owned and \
                        existing_profile_styles_unchanged and \
                        not removed_profile_ids and \
                        new_profiles_owned and \
                        added_profile_style_keys == [
                            expected_profile_style_key]
                    if not ownership_verified:
                        raise Exception(
                            "AddDoorStyle global style/profile delta is not "
                            "isolated")

                    actual = va_style_snapshot(created_id)
                    actual_template = actual.get("profile_template") \
                        if actual is not None else None
                    products = list(
                        va.GetProductsByStyle(created_id, False) or [])
                    verification_checks = {
                        "style_snapshot_complete": actual is not None and
                            actual.get("readback_complete") is True,
                        "kind_door": actual is not None and
                            actual.get("kind") == "door",
                        "name_matches": actual is not None and
                            actual.get("name") == requested_name,
                        "is_opening_style": bool(
                            va.IsOpeningStyle(created_id)),
                        "is_door_style": bool(va.IsDoorStyle(created_id)),
                        "template_matches": actual_template is not None and
                            actual_template.get("id") == str(template_id),
                        "template_rectangular": actual_template is not None and
                            actual_template.get("rectangular") is True,
                        "product_count_zero": not products,
                        "ownership_and_delta": ownership_verified,
                    }
                    if not all(verification_checks.values()):
                        raise Exception(
                            "Created door style failed persistent readback")
                    result = {
                        "status": "success",
                        "style_id": str(created_id),
                        "requested": {
                            "name": requested_name,
                            "profile_template": "rectangular",
                        },
                        "actual": actual,
                        "template": template_evidence,
                        "automatic_component_ids": added_component_ids,
                        "automatic_profile_ids": added_profile_ids,
                        "verification": {
                            "pass": True,
                            "checks": verification_checks,
                            "source": "VisualARQ.Script persistent readback",
                        },
                        "global_inventory_before": global_before,
                        "global_inventory_after": global_after,
                        "profile_inventory_before": profiles_before,
                        "profile_inventory_after": profiles_after,
                    }
                except Exception as creation_error:
                    global_failure = None
                    profiles_failure = None
                    cleanup_attempted = False
                    cleanup_delete_result = None
                    cleanup_delete_error = None
                    cleanup_refused_reason = None
                    try:
                        global_failure = va_global_style_inventory()
                        profiles_failure = va_opening_profile_inventory()
                        returned_text = str(created_id) \
                            if created_id != Guid.Empty else None
                        if global_failure["read_complete"] is True and \
                                profiles_failure["read_complete"] is True and \
                                returned_text is not None and \
                                returned_text not in baseline_guid_union:
                            added_ids = sorted(
                                set(global_failure["all_style_ids"]) -
                                set(global_before["all_style_ids"]))
                            removed_ids = sorted(
                                set(global_before["all_style_ids"]) -
                                set(global_failure["all_style_ids"]))
                            returned_entries = [
                                entry for entry in global_failure["styles"]
                                if entry["id"] == returned_text and
                                entry["inventory_method"] ==
                                "GetAllDoorStyleIds" and
                                entry["name"] == requested_name]
                            ownership_verified = \
                                added_ids == [returned_text] and \
                                not removed_ids and len(returned_entries) == 1
                    except Exception as ownership_error:
                        cleanup_refused_reason = \
                            "ownership probe failed: " + \
                            va_text(ownership_error)
                    if ownership_verified:
                        try:
                            product_ids = list(
                                va.GetProductsByStyle(created_id, False) or [])
                            if product_ids:
                                cleanup_refused_reason = \
                                    "created style is already in use"
                            else:
                                cleanup_attempted = True
                                cleanup_delete_result = bool(
                                    va.DeleteStyle(created_id))
                        except Exception as cleanup_error:
                            cleanup_delete_error = va_text(cleanup_error)
                    elif cleanup_refused_reason is None:
                        cleanup_refused_reason = \
                            "returned Guid ownership was not proven"
                    global_cleanup = va_global_style_inventory()
                    profiles_cleanup = va_opening_profile_inventory()
                    cleanup_verified = \
                        global_cleanup == global_before and \
                        profiles_cleanup == profiles_before
                    result = {
                        "status": "error",
                        "code": "RHINO_ERROR" if cleanup_verified else
                            "PARTIAL_MUTATION",
                        "message": (
                            "Door style creation failed: " +
                            va_text(creation_error)),
                        "created_style_id": str(created_id)
                            if created_id != Guid.Empty else None,
                        "ownership_verified": ownership_verified,
                        "cleanup_attempted": cleanup_attempted,
                        "cleanup_delete_result": cleanup_delete_result,
                        "cleanup_delete_error": cleanup_delete_error,
                        "cleanup_refused_reason": cleanup_refused_reason,
                        "cleanup_verified": cleanup_verified,
                        "global_inventory_before": global_before,
                        "global_inventory_after_failure": global_failure,
                        "global_inventory_after_cleanup": global_cleanup,
                        "profile_inventory_before": profiles_before,
                        "profile_inventory_after_failure": profiles_failure,
                        "profile_inventory_after_cleanup": profiles_cleanup,
                        "residual_style_ids": sorted(
                            set(global_cleanup.get("all_style_ids", [])) -
                            set(global_before["all_style_ids"])),
                        "residual_component_ids": sorted(
                            set(global_cleanup.get("all_component_ids", [])) -
                            set(global_before["all_component_ids"])),
                        "residual_profile_ids": sorted(
                            set(profiles_cleanup.get("all_profile_ids", [])) -
                            set(profiles_before["all_profile_ids"])),
                    }
"""
        opening_style_script = _specialize_door_runtime_script(
            opening_style_script,
            opening_kind,
            required_tokens=(
                "AddDoorStyle",
                "IsDoorStyle",
                "GetAllDoorStyleIds",
                '"door|"',
            ),
            contract="Opening Style creation",
        )
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + opening_style_script,
            {"name": requested_name},
        )
        return _respond(
            result,
            f"VisualARQ {opening_kind} style '{requested_name}' created",
        )
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(
            "Error creating VisualARQ %s style: %s", opening_kind, e)
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_door_style(ctx: Context, name: str) -> str:
    """Create a rectangular VisualARQ Door Style and verify its identity.

    This creates only the document-resident style. Add named dimensions with
    :func:`va_add_rectangular_opening_size_profile`; VisualARQ may itself add
    default components or profiles, which are returned rather than hidden.
    """
    return _va_create_opening_style(ctx, name, opening_kind="door")


@mcp.tool()
def va_create_window_style(ctx: Context, name: str) -> str:
    """Create a rectangular VisualARQ Window Style and verify its identity.

    Uses the exact ``AddWindowStyle(String, Guid)`` rectangular-template
    overload. Automatic components/profiles are reported as owned deltas, and
    failure cleanup is attempted only after exact ownership is proven.
    """
    return _va_create_opening_style(ctx, name, opening_kind="window")


@mcp.tool()
def va_add_rectangular_opening_size_profile(
    ctx: Context,
    style_id: str,
    name: str,
    width: float,
    height: float,
) -> str:
    """Add a named rectangular size profile to a door or window style.

    The style must already use VisualARQ's canonical rectangular template.
    Width and height are document units and are always read back from the
    created profile; requested values are never reported as actual values.
    """
    try:
        _require_guid(style_id, "style_id")
        _require_name(name, "name")
        _require_positive(width, "width")
        _require_positive(height, "height")
        canonical_style_id = str(UUID(style_id.strip().strip("{}")))
        requested_name = name.strip()
        requested_width = float(width)
        requested_height = float(height)
        rhino = get_rhino_connection()
        result = run_va(rhino, _STYLE_SCRIPT_HELPERS + r"""
import scriptcontext as sc
style_id = Guid(params["style_id"])
requested_name = params["name"]
requested_width = float(params["width"])
requested_height = float(params["height"])
mutation_shapes = {
    "AddOpeningStyleSizeProfile": va_exact_method_shape(
        "AddOpeningStyleSizeProfile", ["System.Guid", "System.String"],
        "System.Guid"),
    "FindOpeningStyleSizeProfile": va_exact_method_shape(
        "FindOpeningStyleSizeProfile", ["System.Guid", "System.String"],
        "System.Guid"),
    "SetRectangularProfileSize": va_exact_method_shape(
        "SetRectangularProfileSize",
        ["System.Guid", "VisualARQ.Script+RectangularProfileSize"],
        "System.Boolean"),
    "GetRectangularProfileTemplate": va_exact_method_shape(
        "GetRectangularProfileTemplate", [], "System.Guid"),
    "FindOpeningsBySizeProfile": va_exact_method_shape(
        "FindOpeningsBySizeProfile", ["System.Guid"], "System.Guid[]"),
    "DeleteProfile": va_exact_method_shape(
        "DeleteProfile", ["System.Guid"], "System.Boolean"),
}
failed_mutation_shapes = sorted(
    method_name for method_name in mutation_shapes
    if mutation_shapes[method_name]["verified"] is not True)
profile_shape_contract = va_opening_profile_shape_contract()
constructor_contract = va_rectangular_profile_size_constructor_contract()
if failed_mutation_shapes or profile_shape_contract["pass"] is not True or \
        constructor_contract["pass"] is not True:
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "message": (
            "VisualARQ rectangular opening-profile API has no unique "
            "supported CLR shape"),
        "failed_mutation_shapes": failed_mutation_shapes,
        "mutation_shapes": mutation_shapes,
        "profile_shape_contract": profile_shape_contract,
        "constructor_contract": constructor_contract,
    }
else:
    actual_kind = va_style_kind(style_id)
    if actual_kind not in ["door", "window"]:
        result = {
            "status": "error", "code": "INVALID_ID",
            "message": "Style GUID is not a door or window style",
            "style_id": str(style_id), "actual_kind": actual_kind,
        }
    else:
        global_before = va_global_style_inventory()
        profiles_before = va_opening_profile_inventory()
        style_before = va_style_snapshot(style_id)
        if global_before["read_complete"] is not True or \
                profiles_before["read_complete"] is not True or \
                style_before is None or \
                style_before.get("readback_complete") is not True:
            result = {
                "status": "error", "code": "VERIFICATION_FAILED",
                "message": (
                    "Style/profile baseline is incomplete; size-profile "
                    "creation was refused before mutation"),
                "style": style_before,
                "global_inventory_before": global_before,
                "profile_inventory_before": profiles_before,
            }
        else:
            rectangular_template_id = va.GetRectangularProfileTemplate()
            style_template = style_before.get("profile_template")
            template_verified = \
                rectangular_template_id != Guid.Empty and \
                style_template is not None and \
                style_template.get("readback_complete") is True and \
                style_template.get("id") == str(rectangular_template_id) and \
                style_template.get("rectangular") is True
            target_entry_before = next(
                (entry for entry in profiles_before["styles"]
                 if entry["style_id"] == str(style_id)), None)
            duplicate_profile_ids = []
            if target_entry_before is not None:
                duplicate_profile_ids = sorted(
                    profile["id"] for profile in
                    target_entry_before["profiles"]
                    if va_text_key(profile["name"]) ==
                    va_text_key(requested_name))
            if not template_verified:
                result = {
                    "status": "error", "code": "UNSUPPORTED_OPERATION",
                    "message": (
                        "The opening style does not use the canonical "
                        "rectangular profile template"),
                    "style": style_before,
                    "rectangular_template_id": str(
                        rectangular_template_id)
                        if rectangular_template_id != Guid.Empty else None,
                }
            elif target_entry_before is None:
                result = {
                    "status": "error", "code": "VERIFICATION_FAILED",
                    "message": "Target style is absent from profile baseline",
                    "style": style_before,
                    "profile_inventory_before": profiles_before,
                }
            elif duplicate_profile_ids:
                result = {
                    "status": "error", "code": "ALREADY_EXISTS",
                    "message": (
                        "An opening size profile with this name already exists"),
                    "style_id": str(style_id),
                    "name": requested_name,
                    "profile_ids": duplicate_profile_ids,
                }
            else:
                requested_size = None
                try:
                    requested_size = va.RectangularProfileSize(
                        requested_width, requested_height)
                    if va_valid_double(requested_size.Width) != \
                            requested_width or \
                            va_valid_double(requested_size.Height) != \
                            requested_height:
                        raise Exception(
                            "RectangularProfileSize constructor changed values")
                except Exception as size_error:
                    result = {
                        "status": "error", "code": "VERIFICATION_FAILED",
                        "message": (
                            "RectangularProfileSize could not be constructed "
                            "before mutation"),
                        "error": va_text(size_error),
                        "constructor_contract": constructor_contract,
                    }
                if requested_size is not None and result is None:
                    created_id = Guid.Empty
                    ownership_verified = False
                    try:
                        baseline_guid_union = set(
                            global_before["all_style_ids"] +
                            global_before["all_component_ids"] +
                            profiles_before["all_profile_ids"])
                        created_id = va.AddOpeningStyleSizeProfile(
                            style_id, requested_name)
                        if created_id is None or created_id == Guid.Empty:
                            raise Exception(
                                "AddOpeningStyleSizeProfile returned an empty Guid")
                        if str(created_id) in baseline_guid_union:
                            raise Exception(
                                "AddOpeningStyleSizeProfile returned a "
                                "pre-existing Guid")

                        global_after_add = va_global_style_inventory()
                        profiles_after_add = va_opening_profile_inventory()
                        if global_after_add["read_complete"] is not True or \
                                profiles_after_add["read_complete"] is not True:
                            raise Exception(
                                "post-add style/profile inventory is incomplete")
                        added_style_ids = sorted(
                            set(global_after_add["all_style_ids"]) -
                            set(global_before["all_style_ids"]))
                        removed_style_ids = sorted(
                            set(global_before["all_style_ids"]) -
                            set(global_after_add["all_style_ids"]))
                        added_component_ids = sorted(
                            set(global_after_add["all_component_ids"]) -
                            set(global_before["all_component_ids"]))
                        removed_component_ids = sorted(
                            set(global_before["all_component_ids"]) -
                            set(global_after_add["all_component_ids"]))
                        added_profile_ids = sorted(
                            set(profiles_after_add["all_profile_ids"]) -
                            set(profiles_before["all_profile_ids"]))
                        removed_profile_ids = sorted(
                            set(profiles_before["all_profile_ids"]) -
                            set(profiles_after_add["all_profile_ids"]))

                        global_before_map = dict(
                            (entry["key"], entry)
                            for entry in global_before["styles"])
                        global_after_map = dict(
                            (entry["key"], entry)
                            for entry in global_after_add["styles"])
                        target_global_key = \
                            ("GetAllDoorStyleIds" if actual_kind == "door"
                             else "GetAllWindowStyleIds") + "|" + str(style_id)
                        unrelated_global_unchanged = all(
                            global_after_map.get(key) == entry
                            for key, entry in global_before_map.items()
                            if key != target_global_key)
                        target_global_before = global_before_map.get(
                            target_global_key)
                        target_global_after = global_after_map.get(
                            target_global_key)
                        target_global_shape_unchanged = \
                            target_global_before is not None and \
                            target_global_after is not None and \
                            dict((key, value) for key, value in
                                 target_global_before.items()
                                 if key != "component_ids") == \
                            dict((key, value) for key, value in
                                 target_global_after.items()
                                 if key != "component_ids")
                        optional_component_delta_valid = \
                            added_component_ids in [[], [str(created_id)]] and \
                            all(global_after_add[
                                "component_owners"].get(component_id) ==
                                str(style_id)
                                for component_id in added_component_ids)

                        profiles_before_map = dict(
                            (entry["key"], entry)
                            for entry in profiles_before["styles"])
                        profiles_after_map = dict(
                            (entry["key"], entry)
                            for entry in profiles_after_add["styles"])
                        target_profile_key = actual_kind + "|" + str(style_id)
                        unrelated_profiles_unchanged = all(
                            profiles_after_map.get(key) == entry
                            for key, entry in profiles_before_map.items()
                            if key != target_profile_key)
                        target_after_add = profiles_after_map.get(
                            target_profile_key)
                        target_profile_delta_exact = \
                            target_after_add is not None and \
                            target_after_add["profile_ids"] == \
                            target_entry_before["profile_ids"] + [
                                str(created_id)] and \
                            target_after_add["profiles"][:-1] == \
                            target_entry_before["profiles"] and \
                            target_after_add["profiles"][-1]["id"] == \
                            str(created_id)
                        ownership_verified = \
                            not added_style_ids and not removed_style_ids and \
                            not removed_component_ids and \
                            optional_component_delta_valid and \
                            unrelated_global_unchanged and \
                            target_global_shape_unchanged and \
                            added_profile_ids == [str(created_id)] and \
                            not removed_profile_ids and \
                            profiles_after_add["profile_owners"].get(
                                str(created_id)) == str(style_id) and \
                            unrelated_profiles_unchanged and \
                            target_profile_delta_exact
                        if not ownership_verified:
                            raise Exception(
                                "AddOpeningStyleSizeProfile global delta/owner "
                                "is not isolated")

                        setter_result = bool(va.SetRectangularProfileSize(
                            created_id, requested_size))
                        global_final = va_global_style_inventory()
                        profiles_final = va_opening_profile_inventory()
                        if global_final["read_complete"] is not True or \
                                profiles_final["read_complete"] is not True:
                            raise Exception(
                                "final style/profile inventory is incomplete")
                        if global_final != global_after_add:
                            raise Exception(
                                "size setter changed the global style inventory")
                        actual = None
                        for entry in profiles_final["styles"]:
                            for profile in entry["profiles"]:
                                if profile["id"] == str(created_id):
                                    actual = profile
                        found_id = va.FindOpeningStyleSizeProfile(
                            style_id, requested_name)
                        openings = list(
                            va.FindOpeningsBySizeProfile(created_id) or [])
                        tolerance = float(sc.doc.ModelAbsoluteTolerance)
                        actual_dimensions = actual.get("dimensions") \
                            if actual is not None else None
                        verification_checks = {
                            "ownership_and_delta": ownership_verified,
                            "profile_snapshot_complete": actual is not None and
                                actual.get("readback_complete") is True,
                            "name_matches": actual is not None and
                                actual.get("name") == requested_name,
                            "owner_matches": actual is not None and
                                actual.get("style_id") == str(style_id) and
                                actual.get("owner_matches") is True,
                            "membership_verified": actual is not None and
                                actual.get("membership_verified") is True,
                            "rectangular": actual is not None and
                                actual.get("rectangular") is True,
                            "width_matches": actual_dimensions is not None and
                                abs(actual_dimensions["width"] -
                                    requested_width) <= tolerance,
                            "height_matches": actual_dimensions is not None and
                                abs(actual_dimensions["height"] -
                                    requested_height) <= tolerance,
                            "find_matches": found_id == created_id,
                            "unused_after_creation": not openings,
                        }
                        if not all(verification_checks.values()):
                            raise Exception(
                                "Created opening size profile failed readback")
                        warnings = []
                        if setter_result is not True:
                            warnings.append(
                                "SetRectangularProfileSize returned false, but "
                                "the requested dimensions persisted")
                        result = {
                            "status": "success",
                            "profile_id": str(created_id),
                            "style_id": str(style_id),
                            "style_kind": actual_kind,
                            "requested": {
                                "name": requested_name,
                                "width": requested_width,
                                "height": requested_height,
                            },
                            "actual": actual,
                            "setter_result": setter_result,
                            "warnings": warnings,
                            "verification": {
                                "pass": True,
                                "tolerance": tolerance,
                                "checks": verification_checks,
                                "source": (
                                    "VisualARQ.Script persistent readback"),
                            },
                            "global_inventory_before": global_before,
                            "global_inventory_after": global_final,
                            "profile_inventory_before": profiles_before,
                            "profile_inventory_after": profiles_final,
                        }
                    except Exception as creation_error:
                        global_failure = None
                        profiles_failure = None
                        cleanup_attempted = False
                        cleanup_delete_result = None
                        cleanup_delete_error = None
                        cleanup_refused_reason = None
                        in_use_opening_ids = None
                        try:
                            global_failure = va_global_style_inventory()
                            profiles_failure = va_opening_profile_inventory()
                            returned_text = str(created_id) \
                                if created_id != Guid.Empty else None
                            if returned_text is not None and \
                                    returned_text not in baseline_guid_union and \
                                    profiles_failure["read_complete"] is True:
                                added_profiles = sorted(
                                    set(profiles_failure["all_profile_ids"]) -
                                    set(profiles_before["all_profile_ids"]))
                                removed_profiles = sorted(
                                    set(profiles_before["all_profile_ids"]) -
                                    set(profiles_failure["all_profile_ids"]))
                                ownership_verified = \
                                    added_profiles == [returned_text] and \
                                    not removed_profiles and \
                                    profiles_failure["profile_owners"].get(
                                        returned_text) == str(style_id)
                        except Exception as ownership_error:
                            cleanup_refused_reason = \
                                "ownership probe failed: " + \
                                va_text(ownership_error)
                        if ownership_verified:
                            try:
                                in_use_opening_ids = [
                                    str(value) for value in
                                    list(va.FindOpeningsBySizeProfile(
                                        created_id) or [])]
                                if in_use_opening_ids:
                                    cleanup_refused_reason = \
                                        "created profile is already in use"
                                else:
                                    cleanup_attempted = True
                                    cleanup_delete_result = bool(
                                        va.DeleteProfile(created_id))
                            except Exception as cleanup_error:
                                cleanup_delete_error = va_text(cleanup_error)
                        elif cleanup_refused_reason is None:
                            cleanup_refused_reason = \
                                "returned Guid ownership was not proven"
                        global_cleanup = va_global_style_inventory()
                        profiles_cleanup = va_opening_profile_inventory()
                        cleanup_verified = \
                            global_cleanup == global_before and \
                            profiles_cleanup == profiles_before
                        result = {
                            "status": "error",
                            "code": "RHINO_ERROR" if cleanup_verified else
                                "PARTIAL_MUTATION",
                            "message": (
                                "Opening size-profile creation failed: " +
                                va_text(creation_error)),
                            "created_profile_id": str(created_id)
                                if created_id != Guid.Empty else None,
                            "ownership_verified": ownership_verified,
                            "cleanup_attempted": cleanup_attempted,
                            "cleanup_delete_result": cleanup_delete_result,
                            "cleanup_delete_error": cleanup_delete_error,
                            "cleanup_refused_reason": cleanup_refused_reason,
                            "in_use_opening_ids": in_use_opening_ids,
                            "cleanup_verified": cleanup_verified,
                            "global_inventory_before": global_before,
                            "global_inventory_after_failure": global_failure,
                            "global_inventory_after_cleanup": global_cleanup,
                            "profile_inventory_before": profiles_before,
                            "profile_inventory_after_failure": profiles_failure,
                            "profile_inventory_after_cleanup": profiles_cleanup,
                            "residual_profile_ids": sorted(
                                set(profiles_cleanup.get(
                                    "all_profile_ids", [])) -
                                set(profiles_before["all_profile_ids"])),
                        }
""", {
            "style_id": canonical_style_id,
            "name": requested_name,
            "width": requested_width,
            "height": requested_height,
        })
        return _respond(
            result,
            f"Rectangular VisualARQ opening size profile '{requested_name}' "
            "created",
        )
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error creating VisualARQ opening size profile: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_wall_style(
    ctx: Context,
    name: str,
    layers: List[Dict[str, Any]],
    height: Optional[float] = None,
) -> str:
    """Create and independently read back a layered VisualARQ wall style.

    Each layer accepts ``name``, positive ``thickness``, ``type``
    (``normal``/``core``), and boolean ``wrapping_ends`` /
    ``wrapping_openings``. VisualARQ 3.7.2 exposes top/bottom offsets only as
    wall-instance overrides and exposes no layer-function setter; requesting
    those fields fails before any style is created.
    """
    try:
        _require_name(name, "name")
        normalized_layers = _normalize_wall_layers(layers)
        if height is not None:
            _require_positive(height, "height")
        requested_name = name.strip()
        rhino = get_rhino_connection()
        result = run_va(rhino, _STYLE_SCRIPT_HELPERS + r"""
import scriptcontext as sc
requested_name = params["name"]
required_methods = [
    "AddWallStyle", "AddWallLayer", "SetWallLayerType",
    "SetWallLayerWrapping", "GetWallLayerThickness",
    "GetWallLayerType", "GetWallLayerWrapping",
    "GetSubStyleComponents", "IsWallLayer",
    "GetStyleComponentName", "GetParentStyleComponent",
    "GetStyleName", "GetProductsByStyle", "GetWallStyleHeight",
    "DeleteStyle",
]
if params.get("height") is not None:
    required_methods.extend(["SetWallStyleHeight", "GetWallStyleHeight"])
missing_methods = [
    method_name for method_name in required_methods
    if not va_method_available(method_name)
]
if missing_methods:
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "message": "VisualARQ wall-style API is incomplete",
        "missing_methods": missing_methods,
    }
else:
    global_inventory_before = va_global_style_inventory()
    wall_style_ids_before = list(va_style_ids("wall"))
    duplicates = []
    for existing_id in wall_style_ids_before:
        if va_text_key(va.GetStyleName(existing_id)) == \
                va_text_key(requested_name):
            duplicates.append(str(existing_id))
    if global_inventory_before["read_complete"] is not True:
        result = {
            "status": "error", "code": "VERIFICATION_FAILED",
            "message": (
                "Global VisualARQ style/component inventory is incomplete; "
                "wall-style creation was refused before mutation"),
            "inventory": global_inventory_before,
        }
    elif duplicates:
        result = {
            "status": "error", "code": "ALREADY_EXISTS",
            "message": "Wall style name already exists: " + requested_name,
            "candidates": duplicates,
        }
    else:
        created_id = Guid.Empty
        style_ownership_verified = False
        created_layer_ids = []
        try:
            created_id = va.AddWallStyle(requested_name)
            if created_id == Guid.Empty:
                raise Exception("AddWallStyle returned empty Guid")
            global_inventory_after_style = va_global_style_inventory()
            if global_inventory_after_style["read_complete"] is not True:
                raise Exception(
                    "global style inventory is unreadable after AddWallStyle")
            before_style_ids = set(
                global_inventory_before["all_style_ids"])
            after_style_ids = set(
                global_inventory_after_style["all_style_ids"])
            added_style_ids = sorted(after_style_ids - before_style_ids)
            removed_style_ids = sorted(before_style_ids - after_style_ids)
            if added_style_ids != [str(created_id)] or removed_style_ids or \
                    global_inventory_after_style["style_owners"].get(
                        str(created_id)) != "GetAllWallStyleIds" or \
                    str(created_id) in \
                        global_inventory_before["all_component_ids"] or \
                    va_text(va.GetStyleName(created_id)) != requested_name:
                raise Exception(
                    "AddWallStyle global inventory delta/identity mismatch")
            style_ownership_verified = True
            if params.get("height") is not None:
                set_height = va.SetWallStyleHeight(
                    created_id, params["height"])
                if set_height is False:
                    raise Exception("SetWallStyleHeight returned false")
            for requested_layer in params["layers"]:
                global_layer_inventory_before = \
                    va_global_style_inventory()
                if global_layer_inventory_before["read_complete"] is not True:
                    raise Exception(
                        "global component inventory is unreadable before " +
                        "AddWallLayer")
                layer_inventory_before = va_wall_layer_ids(created_id)
                if not layer_inventory_before["read_complete"]:
                    raise Exception(
                        "wall layer inventory is unreadable before AddWallLayer")
                layer_id = va.AddWallLayer(
                    created_id,
                    requested_layer["name"],
                    requested_layer["thickness"])
                if layer_id == Guid.Empty:
                    raise Exception(
                        "AddWallLayer returned empty Guid for " +
                        requested_layer["name"])
                layer_inventory_after = va_wall_layer_ids(created_id)
                if not layer_inventory_after["read_complete"]:
                    raise Exception(
                        "wall layer inventory is unreadable after AddWallLayer")
                global_layer_inventory_after = va_global_style_inventory()
                if global_layer_inventory_after["read_complete"] is not True:
                    raise Exception(
                        "global component inventory is unreadable after " +
                        "AddWallLayer")
                layer_ids_before_text = set(
                    str(value) for value in layer_inventory_before["ids"])
                added_layer_ids = [
                    value for value in layer_inventory_after["ids"]
                    if str(value) not in layer_ids_before_text]
                global_components_before = set(
                    global_layer_inventory_before["all_component_ids"])
                global_components_after = set(
                    global_layer_inventory_after["all_component_ids"])
                added_global_components = sorted(
                    global_components_after - global_components_before)
                removed_global_components = sorted(
                    global_components_before - global_components_after)
                global_style_ids_unchanged = \
                    global_layer_inventory_after["all_style_ids"] == \
                    global_layer_inventory_before["all_style_ids"]
                parent_id = va.GetParentStyleComponent(layer_id)
                if added_layer_ids != [layer_id] or \
                        added_global_components != [str(layer_id)] or \
                        removed_global_components or \
                        not global_style_ids_unchanged or \
                        str(layer_id) in \
                            global_layer_inventory_before["all_style_ids"] or \
                        global_layer_inventory_after[
                            "component_owners"].get(str(layer_id)) != \
                            str(created_id) or parent_id != created_id:
                    raise Exception(
                        "AddWallLayer global inventory delta/parent mismatch")
                created_layer_ids.append(layer_id)
                layer_type = va.WallLayerType.Core \
                    if requested_layer["type"] == "core" \
                    else va.WallLayerType.Normal
                set_type = va.SetWallLayerType(layer_id, layer_type)
                if set_type is False:
                    raise Exception(
                        "SetWallLayerType returned false for " +
                        requested_layer["name"])
                wrapping = getattr(va.WallLayerWrapping, "None")
                if requested_layer["wrapping_ends"]:
                    wrapping = wrapping | va.WallLayerWrapping.Ends
                if requested_layer["wrapping_openings"]:
                    wrapping = wrapping | va.WallLayerWrapping.Openings
                set_wrapping = va.SetWallLayerWrapping(layer_id, wrapping)
                if set_wrapping is False:
                    raise Exception(
                        "SetWallLayerWrapping returned false for " +
                        requested_layer["name"])

            global_inventory_final = va_global_style_inventory()
            if global_inventory_final["read_complete"] is not True:
                raise Exception("final global style inventory is incomplete")
            baseline_style_ids = set(
                global_inventory_before["all_style_ids"])
            final_style_ids = set(global_inventory_final["all_style_ids"])
            baseline_component_ids = set(
                global_inventory_before["all_component_ids"])
            final_component_ids = set(
                global_inventory_final["all_component_ids"])
            baseline_entries = dict(
                (entry["key"], entry)
                for entry in global_inventory_before["styles"])
            final_entries = dict(
                (entry["key"], entry)
                for entry in global_inventory_final["styles"])
            baseline_styles_unchanged = all(
                final_entries.get(key) == entry
                for key, entry in baseline_entries.items())
            if sorted(final_style_ids - baseline_style_ids) != \
                    [str(created_id)] or \
                    baseline_style_ids - final_style_ids or \
                    sorted(final_component_ids - baseline_component_ids) != \
                        sorted(str(value) for value in created_layer_ids) or \
                    baseline_component_ids - final_component_ids or \
                    not baseline_styles_unchanged:
                raise Exception(
                    "final global style/component delta is not isolated")

            actual = va_style_snapshot(created_id)
            tolerance = float(sc.doc.ModelAbsoluteTolerance)
            if actual is None or actual["name"] != requested_name:
                raise Exception("wall style identity readback mismatch")
            if actual.get("product_count_read_complete") is not True or \
                    actual.get("product_count") != 0:
                raise Exception(
                    "new wall style unused-state readback is incomplete")
            if actual.get("readback_complete") is not True:
                raise Exception("wall style readback is incomplete")
            if actual["layer_count"] != len(params["layers"]):
                raise Exception("wall style readback has the wrong layer count")
            for index in range(len(params["layers"])):
                requested_layer = params["layers"][index]
                actual_layer = actual["layers"][index]
                if actual_layer["name"] != requested_layer["name"]:
                    raise Exception("wall layer name readback mismatch")
                if actual_layer["thickness"] is None or \
                        abs(actual_layer["thickness"] - \
                            requested_layer["thickness"]) > tolerance:
                    raise Exception("wall layer thickness readback mismatch")
                if actual_layer["type"] != requested_layer["type"]:
                    raise Exception("wall layer type readback mismatch")
                if actual_layer["wrapping"]["ends"] != \
                        requested_layer["wrapping_ends"] or \
                        actual_layer["wrapping"]["openings"] != \
                        requested_layer["wrapping_openings"]:
                    raise Exception("wall layer wrapping readback mismatch")
            if params.get("height") is not None and \
                    (actual["height"] is None or \
                     abs(actual["height"] - params["height"]) > tolerance):
                raise Exception("wall style height readback mismatch")
            requested_total = sum(
                layer["thickness"] for layer in params["layers"])
            if actual["total_layer_thickness"] is None or \
                    abs(actual["total_layer_thickness"] - \
                        requested_total) > tolerance:
                raise Exception("wall style total thickness readback mismatch")
            result = {
                "status": "success", "style_id": str(created_id),
                "requested": {
                    "name": requested_name, "height": params.get("height"),
                    "layers": params["layers"],
                    "total_layer_thickness": requested_total,
                    "layer_order": "inside_to_outside",
                },
                "actual": actual,
                "verification": {
                    "pass": True,
                    "tolerance": tolerance,
                    "source": (
                        "VisualARQ.Script readback plus global reflected "
                        "style/component inventory delta"),
                    "global_ownership_verified": True,
                },
            }
        except Exception as creation_error:
            cleanup_attempts = []
            cleanup_target_id = created_id
            inferred_created_style_id = None
            ownership_verified = style_ownership_verified
            inventory_before_text = sorted(
                str(style_id) for style_id in wall_style_ids_before)
            inventory_after_failure = None
            global_inventory_after_failure = None
            inventory_read_error = None
            new_style_ids = []
            try:
                inventory_after_failure = list(va_style_ids("wall"))
                global_inventory_after_failure = \
                    va_global_style_inventory()
                if global_inventory_after_failure["read_complete"] is not True:
                    raise Exception(
                        "global inventory is incomplete after creation failure")
                before_set = set(inventory_before_text)
                new_style_ids = [
                    style_id for style_id in inventory_after_failure
                    if str(style_id) not in before_set
                ]
                global_before_ids = set(
                    global_inventory_before["all_style_ids"])
                global_after_ids = set(
                    global_inventory_after_failure["all_style_ids"])
                global_new_style_ids = sorted(
                    global_after_ids - global_before_ids)
                global_removed_style_ids = sorted(
                    global_before_ids - global_after_ids)
                if not ownership_verified and len(new_style_ids) == 1 and \
                        global_new_style_ids == [str(new_style_ids[0])] and \
                        not global_removed_style_ids and \
                        global_inventory_after_failure[
                            "style_owners"].get(str(new_style_ids[0])) == \
                            "GetAllWallStyleIds":
                    inferred_id = new_style_ids[0]
                    inferred_name = va_text(va.GetStyleName(inferred_id))
                    returned_matches = created_id != Guid.Empty and \
                        created_id == inferred_id
                    if inferred_name == requested_name and returned_matches:
                        cleanup_target_id = inferred_id
                        inferred_created_style_id = str(inferred_id)
                        ownership_verified = True
            except Exception as inventory_error:
                inventory_read_error = va_text(inventory_error)
            if cleanup_target_id != Guid.Empty and ownership_verified:
                try:
                    cleanup_attempts.append({
                        "operation": "DeleteStyle",
                        "id": str(cleanup_target_id),
                        "result": bool(va.DeleteStyle(cleanup_target_id)),
                    })
                except Exception as cleanup_error:
                    cleanup_attempts.append({
                        "operation": "DeleteStyle",
                        "error": va_text(cleanup_error),
                    })
                initial_presence = va_style_presence(cleanup_target_id)
                if initial_presence is not False and \
                        va_method_available("DeleteStyleComponent"):
                    for layer_id in reversed(created_layer_ids):
                        try:
                            cleanup_parent_id = \
                                va.GetParentStyleComponent(layer_id)
                            if cleanup_parent_id == cleanup_target_id:
                                cleanup_attempts.append({
                                    "operation": "DeleteStyleComponent",
                                    "id": str(layer_id),
                                    "parent_verified": True,
                                    "result": bool(
                                        va.DeleteStyleComponent(layer_id)),
                                })
                            else:
                                cleanup_attempts.append({
                                    "operation": "DeleteStyleComponent",
                                    "id": str(layer_id),
                                    "parent_verified": False,
                                    "actual_parent_id": str(cleanup_parent_id),
                                    "refused": True,
                                })
                        except Exception as cleanup_error:
                            cleanup_attempts.append({
                                "operation": "DeleteStyleComponent",
                                "id": str(layer_id),
                                "error": va_text(cleanup_error),
                            })
                    try:
                        cleanup_attempts.append({
                            "operation": "DeleteStyleRetry",
                            "id": str(cleanup_target_id),
                            "result": bool(va.DeleteStyle(cleanup_target_id)),
                        })
                    except Exception as cleanup_error:
                        cleanup_attempts.append({
                            "operation": "DeleteStyleRetry",
                            "error": va_text(cleanup_error),
                        })
            cleanup_presence = None
            if cleanup_target_id != Guid.Empty:
                cleanup_presence = va_style_presence(cleanup_target_id)
            inventory_after_cleanup = None
            global_inventory_after_cleanup = None
            inventory_restored = False
            try:
                inventory_after_cleanup = list(va_style_ids("wall"))
                global_inventory_after_cleanup = \
                    va_global_style_inventory()
                inventory_restored = \
                    global_inventory_after_cleanup["read_complete"] is True and \
                    global_inventory_after_cleanup == global_inventory_before
            except Exception as cleanup_inventory_error:
                inventory_read_error = (
                    (inventory_read_error + "; ")
                    if inventory_read_error else "") + \
                    "cleanup: " + va_text(cleanup_inventory_error)
            cleanup_still_exists = cleanup_presence is True
            cleanup_verified = inventory_restored
            leaked_layer_ids = []
            component_presence = {}
            for layer_id in created_layer_ids:
                presence = va_style_component_presence(
                    layer_id,
                    cleanup_target_id \
                        if cleanup_target_id != Guid.Empty else None)
                component_presence[str(layer_id)] = presence
                if presence is not False:
                    leaked_layer_ids.append(str(layer_id))
            cleanup_verified = cleanup_verified and not leaked_layer_ids
            residual_style_ids = []
            residual_component_ids = []
            if global_inventory_after_cleanup is not None:
                residual_style_ids = sorted(
                    set(global_inventory_after_cleanup["all_style_ids"]) -
                    set(global_inventory_before["all_style_ids"]))
                residual_component_ids = sorted(
                    set(global_inventory_after_cleanup["all_component_ids"]) -
                    set(global_inventory_before["all_component_ids"]))
            leaked_ids = sorted(set(
                list(residual_style_ids) + list(residual_component_ids) +
                list(leaked_layer_ids)))
            result = {
                "status": "error",
                "code": "RHINO_ERROR" if cleanup_verified \
                    else "PARTIAL_MUTATION",
                "message": (
                    "Wall style creation failed: " + va_text(creation_error)),
                "created_style_id": str(created_id) \
                    if created_id != Guid.Empty else None,
                "inferred_created_style_id": inferred_created_style_id,
                "ownership_verified": ownership_verified,
                "created_layer_ids": [
                    str(layer_id) for layer_id in created_layer_ids],
                "cleanup_attempts": cleanup_attempts,
                "cleanup_presence": cleanup_presence,
                "cleanup_verified": cleanup_verified,
                "inventory_before": inventory_before_text,
                "inventory_after_failure": [
                    str(style_id) for style_id in inventory_after_failure
                ] if inventory_after_failure is not None else None,
                "inventory_after_cleanup": [
                    str(style_id) for style_id in inventory_after_cleanup
                ] if inventory_after_cleanup is not None else None,
                "global_inventory_before": global_inventory_before,
                "global_inventory_after_failure": \
                    global_inventory_after_failure,
                "global_inventory_after_cleanup": \
                    global_inventory_after_cleanup,
                "inventory_restored": inventory_restored,
                "inventory_read_error": inventory_read_error,
                "cleanup_still_exists": cleanup_still_exists,
                "component_presence": component_presence,
                "residual_style_ids": residual_style_ids,
                "residual_component_ids": residual_component_ids,
                "leaked_ids": leaked_ids,
            }
""", {
            "name": requested_name,
            "layers": normalized_layers,
            "height": float(height) if height is not None else None,
        })
        return _respond(
            result,
            f"Wall style '{requested_name}' created and read back",
        )
    except NotImplementedError as e:
        return json.dumps(from_exception(
            e, code=ErrorCode.UNSUPPORTED_OPERATION,
        ))
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error creating VisualARQ wall style: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


def _va_create_slab_or_space_style(
    ctx: Context,
    name: str,
    *,
    kind: Literal["slab", "space"],
    layers: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Run the shared verified Slab/Space Style creation vertical."""

    try:
        _require_name(name, "name")
        normalized_layers = _normalize_slab_layers(layers) \
            if kind == "slab" else None
        requested_name = name.strip()
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _STYLE_CREATION_BODY,
            {
                "kind": kind,
                "name": requested_name,
                "layers": normalized_layers,
            },
        )
        return _respond(
            result,
            f"VisualARQ {kind} style '{requested_name}' created and verified",
        )
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error("Error creating VisualARQ %s style: %s", kind, e)
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_slab_style(
    ctx: Context,
    name: str,
    layers: List[Dict[str, Any]],
) -> str:
    """Create and independently verify one layered VisualARQ Slab Style.

    Each layer requires a name and positive thickness in document units;
    ``type`` is ``normal`` (default) or ``core``. The operation fails closed
    unless the loaded VisualARQ CLR signatures and the complete global style
    inventory are proven before mutation. Success requires exact layer,
    product-count and global additive-delta readback.

    Failed creation removes only a uniquely proven command-owned style. On
    VisualARQ 3.7.2 the last Slab Style may be undeletable; any non-restored
    baseline is therefore reported truthfully as ``PARTIAL_MUTATION``.
    """
    return _va_create_slab_or_space_style(
        ctx, name, kind="slab", layers=layers)


@mcp.tool()
def va_create_space_style(ctx: Context, name: str) -> str:
    """Create and independently verify one VisualARQ Space Style.

    The name must be unique among Space Styles. The tool proves the exact CLR
    shape, a complete global style/component baseline, zero products and the
    exact additive inventory delta. Rollback is attempted only for a uniquely
    proven new style; uncertain or residual state returns ``PARTIAL_MUTATION``.
    """
    return _va_create_slab_or_space_style(ctx, name, kind="space")


@mcp.tool()
def va_rename_style(ctx: Context, style_id: str, new_name: str) -> str:
    """Rename a VisualARQ style by GUID and verify the actual name."""
    try:
        _require_guid(style_id, "style_id")
        _require_name(new_name, "new_name")
        canonical_name = new_name.strip()
        rhino = get_rhino_connection()
        result = run_va(rhino, _STYLE_SCRIPT_HELPERS + r"""
style_id = Guid(params["style_id"])
before = va_style_snapshot(style_id)
global_before = va_global_style_inventory()
if before is None:
    result = {
        "status": "error", "code": "INVALID_ID",
        "message": "VisualARQ style not found: " + params["style_id"],
    }
elif global_before.get("read_complete") is not True:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": (
            "Global VisualARQ style inventory is incomplete; rename was "
            "refused before mutation"),
        "style": before,
        "global_inventory_before": global_before,
    }
elif before.get("name") is None or \
        before.get("readback_complete", True) is not True:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": "Style name readback is incomplete; rename was refused",
        "style": before,
    }
else:
    expected_after = dict(before)
    expected_after["name"] = params["new_name"]
    duplicate_ids = []
    target_inventory_method = global_before["style_owners"].get(
        str(style_id))
    for entry in global_before["styles"]:
        if entry["id"] != str(style_id) and \
                entry["inventory_method"] == target_inventory_method and \
                va_text_key(entry["name"]) == \
                va_text_key(params["new_name"]):
            duplicate_ids.append(entry["id"])
    if not va_method_available("RenameStyle"):
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "message": "RenameStyle is not available",
        }
    elif duplicate_ids:
        result = {
            "status": "error", "code": "ALREADY_EXISTS",
            "message": "Style name already exists: " + params["new_name"],
            "candidates": duplicate_ids,
        }
    elif before["name"] == params["new_name"]:
        result = {
            "status": "success", "changed": False,
            "before": before, "actual": before,
            "global_inventory_before": global_before,
            "global_inventory_after": global_before,
        }
    else:
        mutation_result = None
        mutation_error = None
        try:
            mutation_result = bool(
                va.RenameStyle(style_id, params["new_name"]))
        except Exception as rename_error:
            mutation_error = va_text(rename_error)
        actual = None
        readback_error = None
        try:
            actual = va_style_snapshot(style_id)
        except Exception as actual_error:
            readback_error = va_text(actual_error)
        global_actual = va_global_style_inventory()
        global_contract = va_global_style_rename_contract(
            global_before, global_actual, style_id, params["new_name"])
        if actual == expected_after and global_contract["pass"]:
            warnings = []
            if mutation_result is False or mutation_error is not None:
                warnings.append(
                    "Rename return value disagreed with persistent readback")
            result = {
                "status": "success", "changed": True,
                "before": before, "actual": actual,
                "mutation_result": mutation_result,
                "mutation_error": mutation_error,
                "warnings": warnings,
                "global_inventory_before": global_before,
                "global_inventory_after": global_actual,
                "global_verification": global_contract,
            }
        else:
            rollback_result = None
            rollback_error = None
            rollback_actual = actual
            rollback_global = global_actual
            if actual is None or actual["name"] != before["name"]:
                try:
                    rollback_result = bool(
                        va.RenameStyle(style_id, before["name"]))
                except Exception as rollback_exception:
                    rollback_error = va_text(rollback_exception)
                try:
                    rollback_actual = va_style_snapshot(style_id)
                except Exception as rollback_readback_error:
                    rollback_error = (
                        (rollback_error + "; ") if rollback_error else "") + \
                        "readback: " + va_text(rollback_readback_error)
            rollback_global = va_global_style_inventory()
            rollback_verified = rollback_actual == before and \
                rollback_global == global_before
            presence = style_id in [
                Guid(value) for value in
                rollback_global.get("all_style_ids", [])] \
                if rollback_global.get("read_complete") is True else None
            result = {
                "status": "error",
                "code": "RHINO_ERROR" if rollback_verified \
                    else "PARTIAL_MUTATION",
                "message": "Style rename did not persist as requested",
                "before": before, "actual": actual,
                "mutation_result": mutation_result,
                "mutation_error": mutation_error,
                "readback_error": readback_error,
                "rollback_result": rollback_result,
                "rollback_error": rollback_error,
                "rollback_actual": rollback_actual,
                "rollback_verified": rollback_verified,
                "presence": presence,
                "global_inventory_before": global_before,
                "global_inventory_after": global_actual,
                "global_verification": global_contract,
                "rollback_global_inventory": rollback_global,
            }
""", {"style_id": style_id, "new_name": canonical_name})
        return _respond(result, f"VisualARQ style renamed to '{canonical_name}'")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error renaming VisualARQ style: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_delete_style(ctx: Context, style_id: str, confirm: bool = False) -> str:
    """Delete an unused VisualARQ style by GUID after explicit confirmation.

    Styles with products are rejected. RhinoClaw never cascades object deletion
    from this tool.
    """
    try:
        _require_guid(style_id, "style_id")
        if confirm is not True:
            raise ValueError("confirm=true is required to delete a style")
        rhino = get_rhino_connection()
        result = run_va(rhino, _STYLE_SCRIPT_HELPERS + r"""
style_id = Guid(params["style_id"])
before = va_style_snapshot(style_id)
global_before = va_global_style_inventory()
if before is None:
    result = {
        "status": "error", "code": "INVALID_ID",
        "message": "VisualARQ style not found: " + params["style_id"],
    }
elif global_before.get("read_complete") is not True:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": (
            "Global VisualARQ style inventory is incomplete; deletion was "
            "refused before mutation"),
        "style": before,
        "global_inventory_before": global_before,
    }
elif before.get("readback_complete", True) is not True:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": "Style readback is incomplete; deletion was refused",
        "style": before,
    }
elif not va_method_available("GetProductsByStyle") or \
        not va_method_available("GetProductStyle") or \
        not va_method_available("IsProduct"):
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "message": "Cannot prove that the style is unused",
    }
elif not va_method_available("DeleteStyle"):
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "message": "DeleteStyle is not available",
    }
else:
    import scriptcontext as sc
    api_product_ids = list(va.GetProductsByStyle(style_id, False) or [])
    scanned_product_ids = []
    scan_errors = []
    scan_error_count = 0
    for obj in sc.doc.Objects:
        try:
            if not va.IsProduct(obj.Id):
                continue
            if va.GetProductStyle(obj.Id) == style_id:
                scanned_product_ids.append(obj.Id)
        except Exception as scan_error:
            scan_error_count += 1
            if len(scan_errors) < 100:
                scan_errors.append({
                    "object_id": str(obj.Id),
                    "error": va_text(scan_error),
                })
    api_product_text = sorted(str(value) for value in api_product_ids)
    scanned_product_text = sorted(
        str(value) for value in scanned_product_ids)
    product_ids = sorted(set(api_product_text + scanned_product_text))
    if scan_error_count > 0:
        result = {
            "status": "error", "code": "VERIFICATION_FAILED",
            "message": "Cannot prove that the style is unused",
            "style": before,
            "api_product_ids": api_product_text,
            "scanned_product_ids": scanned_product_text,
            "product_sources_agree": \
                api_product_text == scanned_product_text,
            "scan_error_count": scan_error_count,
            "scan_errors": scan_errors,
            "scan_errors_truncated": scan_error_count > len(scan_errors),
        }
    elif product_ids:
        result = {
            "status": "error", "code": "RESOURCE_IN_USE",
            "message": "Style is used by document products",
            "product_ids": product_ids,
            "product_count": len(product_ids), "style": before,
            "api_product_ids": api_product_text,
            "scanned_product_ids": scanned_product_text,
            "product_sources_agree": \
                api_product_text == scanned_product_text,
        }
    else:
        delete_result = None
        delete_error = None
        try:
            delete_result = bool(va.DeleteStyle(style_id))
        except Exception as mutation_error:
            delete_error = va_text(mutation_error)
        global_after = va_global_style_inventory()
        global_contract = va_global_style_delete_contract(
            global_before, global_after, style_id)
        presence = str(style_id) in global_after.get("all_style_ids", []) \
            if global_after.get("read_complete") is True else None
        component_presence = {}
        residual_component_ids = []
        target_component_ids = global_contract["target_component_ids"]
        for component_id in target_component_ids:
            child_presence = component_id in \
                global_after.get("all_component_ids", []) \
                if global_after.get("read_complete") is True else None
            component_presence[component_id] = child_presence
            if child_presence is not False:
                residual_component_ids.append(component_id)
        components_absent = not residual_component_ids
        if presence is True:
            after = va_style_snapshot(style_id)
            state_unchanged = after == before and \
                global_after == global_before
            result = {
                "status": "error",
                "code": "RHINO_ERROR" if state_unchanged \
                    else "PARTIAL_MUTATION",
                "message": "DeleteStyle was not persistent",
                "delete_result": delete_result, "delete_error": delete_error,
                "presence": presence,
                "component_presence": component_presence,
                "residual_component_ids": residual_component_ids,
                "style": before, "after": after,
                "state_unchanged": state_unchanged,
                "global_inventory_before": global_before,
                "global_inventory_after": global_after,
                "global_verification": global_contract,
            }
        elif presence is False and components_absent and \
                global_contract["pass"]:
            warnings = []
            if delete_result is False or delete_error is not None:
                warnings.append(
                    "Delete return value disagreed with persistent inventory")
            result = {
                "status": "success", "deleted": True,
                "delete_result": delete_result, "delete_error": delete_error,
                "style": before, "warnings": warnings,
                "api_product_ids": api_product_text,
                "scanned_product_ids": scanned_product_text,
                "product_sources_agree": True,
                "component_presence": component_presence,
                "residual_component_ids": [],
                "global_inventory_before": global_before,
                "global_inventory_after": global_after,
                "global_verification": global_contract,
            }
        elif presence is False:
            result = {
                "status": "error", "code": "PARTIAL_MUTATION",
                "message": (
                    "Style was removed but its exact global style/component "
                    "delta could not be proven"),
                "deleted": True,
                "delete_result": delete_result, "delete_error": delete_error,
                "presence": presence,
                "style": before,
                "component_presence": component_presence,
                "residual_component_ids": residual_component_ids,
                "global_inventory_before": global_before,
                "global_inventory_after": global_after,
                "global_verification": global_contract,
            }
        else:
            result = {
                "status": "error", "code": "PARTIAL_MUTATION",
                "message": "Style deletion could not be verified from inventory",
                "delete_result": delete_result, "delete_error": delete_error,
                "presence": presence,
                "component_presence": component_presence,
                "residual_component_ids": residual_component_ids,
                "style": before,
                "global_inventory_before": global_before,
                "global_inventory_after": global_after,
                "global_verification": global_contract,
            }
""", {"style_id": style_id})
        return _respond(result, f"VisualARQ style {style_id} deleted")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error deleting VisualARQ style: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_objects(
    ctx: Context,
    kind: VisualArqObjectKind = "wall",
    limit: int = 200,
) -> str:
    """List document-resident VisualARQ products with measured metadata.

    ``kind`` defaults to ``wall`` for an inexpensive focused query. Use
    ``all`` deliberately to classify every VisualARQ product. Results include
    canonical object/style IDs, geometry validity/BBox and lightweight
    kind-specific readback. Expensive volume and wall-layer detail are omitted;
    call ``va_get_object`` for the full measured snapshot. ``matched_count``
    remains truthful when the returned list is truncated by ``limit``.
    """
    try:
        if kind not in _VA_OBJECT_KINDS:
            raise ValueError(
                "kind must be one of: " + ", ".join(sorted(_VA_OBJECT_KINDS))
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError("limit must be an integer between 1 and 5000")
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _OBJECT_SCRIPT_HELPERS + r"""
import scriptcontext as sc
requested_kind = params["kind"]
matched_count = 0
objects = []
scan_errors = []
scan_error_count = 0
style_cache = {}
for obj in sc.doc.Objects:
    if requested_kind == "all":
        # Avoid all classifiers for plain Rhino objects in large documents.
        identity_probe = va_visualarq_identity_probe(obj.Id)
        if identity_probe["match"] is None:
            scan_error_count += 1
            if len(scan_errors) < 100:
                scan_errors.append({
                    "object_id": str(obj.Id),
                    "stage": "identity",
                    "errors": identity_probe["errors"],
                })
            continue
        if identity_probe["match"] is False:
            continue
    else:
        match_probe = va_matches_kind(obj.Id, requested_kind)
        if match_probe["match"] is None:
            scan_error_count += 1
            if len(scan_errors) < 100:
                scan_errors.append({
                    "object_id": str(obj.Id), "stage": "kind_filter",
                    "method": match_probe.get("method"),
                    "error": match_probe.get("error"),
                })
            continue
        if match_probe["match"] is False:
            continue
    classification_probe = va_object_classification_probe(obj.Id)
    classifications = classification_probe["classifications"]
    if requested_kind != "all" and requested_kind not in classifications:
        scan_error_count += 1
        if len(scan_errors) < 100:
            scan_errors.append({
                "object_id": str(obj.Id),
                "stage": "classification_consistency",
                "errors": classification_probe["errors"],
            })
        continue
    if va_primary_kind(classifications) is None:
        scan_error_count += 1
        if len(scan_errors) < 100:
            scan_errors.append({
                "object_id": str(obj.Id), "stage": "primary_kind",
                "classifications": classifications,
                "errors": classification_probe["errors"],
            })
        continue
    if not classification_probe["complete"]:
        scan_error_count += 1
        if len(scan_errors) < 100:
            scan_errors.append({
                "object_id": str(obj.Id), "stage": "classification",
                "errors": classification_probe["errors"],
            })
    matched_count += 1
    if len(objects) < params["limit"]:
        snapshot = va_product_snapshot(
            obj, classification_probe, False, False, style_cache)
        if snapshot is not None:
            objects.append(snapshot)
            if snapshot.get("readback_complete") is not True:
                scan_error_count += 1
                if len(scan_errors) < 100:
                    scan_errors.append({
                        "object_id": str(obj.Id),
                        "stage": "product_readback",
                        "errors": snapshot.get("readback_errors", []),
                    })
result = {
    "status": "success", "kind": requested_kind,
    "objects": objects, "matched_count": matched_count,
    "returned_count": len(objects),
    "truncated": matched_count > len(objects),
    "scan_complete": scan_error_count == 0,
    "scan_error_count": scan_error_count,
    "scan_errors": scan_errors,
    "scan_errors_truncated": scan_error_count > len(scan_errors),
}
""",
            {"kind": kind, "limit": limit},
        )
        return _respond(
            result,
            f"{result.get('matched_count', 0)} VisualARQ {kind} object(s)",
        )
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error listing VisualARQ objects: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_get_object(
    ctx: Context,
    object_id: str,
    expected_kind: Optional[str] = None,
) -> str:
    """Read one VisualARQ product by canonical Rhino object GUID."""
    try:
        _require_guid(object_id, "object_id")
        if expected_kind is not None and expected_kind not in _VA_OBJECT_KINDS - {"all"}:
            raise ValueError(
                "expected_kind must be one of: "
                + ", ".join(sorted(_VA_OBJECT_KINDS - {"all"}))
            )
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _OBJECT_SCRIPT_HELPERS + r"""
import scriptcontext as sc
object_id = Guid(params["object_id"])
obj = sc.doc.Objects.FindId(object_id)
if obj is None:
    result = {
        "status": "error", "code": "INVALID_ID",
        "message": "Rhino object not found: " + params["object_id"],
    }
else:
    classification_probe = va_object_classification_probe(object_id)
    classifications = classification_probe["classifications"]
    actual_kind = va_primary_kind(classifications)
    if actual_kind is None:
        if classification_probe["errors"]:
            result = {
                "status": "error", "code": "VERIFICATION_FAILED",
                "message": "VisualARQ object classification failed",
                "object_id": params["object_id"],
                "classification_errors": classification_probe["errors"],
            }
        else:
            result = {
                "status": "error", "code": "INVALID_ID",
                "message": "Object is not a supported VisualARQ product",
                "object_id": params["object_id"],
            }
    elif params.get("expected_kind") is not None and \
            params["expected_kind"] not in classifications:
        expected_kind_errors = [
            error for error in classification_probe["errors"]
            if error.get("kind") == params["expected_kind"]
        ]
        if expected_kind_errors:
            result = {
                "status": "error", "code": "VERIFICATION_FAILED",
                "message": "Expected VisualARQ kind could not be classified",
                "expected_kind": params["expected_kind"],
                "actual_kind": actual_kind,
                "classifications": classifications,
                "classification_errors": expected_kind_errors,
            }
        else:
            result = {
                "status": "error", "code": "INVALID_ID",
                "message": "VisualARQ object kind mismatch",
                "expected_kind": params["expected_kind"],
                "actual_kind": actual_kind,
                "classifications": classifications,
            }
    else:
        snapshot = va_product_snapshot(obj, classification_probe)
        if snapshot is None or snapshot.get("readback_complete") is not True:
            result = {
                "status": "error", "code": "VERIFICATION_FAILED",
                "message": "VisualARQ object readback is incomplete",
                "object": snapshot,
                "object_id": params["object_id"],
                "readback_errors": snapshot.get("readback_errors", [])
                    if snapshot is not None else [],
            }
        else:
            result = {"status": "success", "object": snapshot}
""",
            {"object_id": object_id, "expected_kind": expected_kind},
        )
        return _respond(result, f"VisualARQ object {object_id}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error reading VisualARQ object: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_slab(
    ctx: Context,
    style: str,
    boundary: List[List[float]],
    alignment: SlabAlignment = "top",
) -> str:
    """Create and independently verify one native VisualARQ Slab.

    Parameters:
    - style: Slab style GUID (preferred) or an unambiguous exact name.
    - boundary: Horizontal polygon as ``[[x, y, z], ...]``. The closing
      point is optional; RhinoClaw validates simplicity and closes it.
    - alignment: ``top``, ``center`` or ``bottom`` relative to the boundary.

    The operation validates the installed CLR signature before mutation and
    judges the fresh Slab through its semantic contour, alignment, thickness,
    style and runtime generation. A failed judge removes only the exact
    command-owned generation; any uncertain residual is reported as
    ``PARTIAL_MUTATION`` instead of being deleted speculatively.
    """
    try:
        _require_name(style, "style")
        normalized_boundary = _normalize_planar_boundary(boundary)
        if alignment not in ("top", "center", "bottom"):
            raise ValueError("alignment must be 'top', 'center' or 'bottom'")
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS
            + _OBJECT_SCRIPT_HELPERS
            + _PLANAR_PRODUCT_CREATION_BODY,
            {
                "kind": "slab",
                "style": style.strip(),
                "boundary": normalized_boundary,
                "alignment": alignment,
                "height": None,
                "label_point": None,
            },
        )
        return _respond(result, f"VisualARQ Slab {result.get('object_id')}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error creating VisualARQ Slab: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_space(
    ctx: Context,
    style: str,
    boundary: List[List[float]],
    height: float,
    label_point: List[float],
) -> str:
    """Create and independently verify one native VisualARQ Space.

    Parameters:
    - style: Space style GUID (preferred) or an unambiguous exact name.
    - boundary: Horizontal polygon as ``[[x, y, z], ...]``. Its Z value is
      the requested Space elevation; the closing point is optional.
    - height: Positive Space height in document units.
    - label_point: ``[x, y, z]`` strictly inside the boundary, at the same Z.

    The judge re-reads the semantic Space curve, area, perimeter, elevation,
    height, label, style and runtime generation. Failed verification uses the
    same exact-generation cleanup policy as ``va_create_slab``.
    """
    try:
        _require_name(style, "style")
        normalized_boundary = _normalize_planar_boundary(boundary)
        _require_positive(height, "height")
        _require_label_inside_boundary(label_point, normalized_boundary)
        normalized_label = [float(value) for value in label_point]
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS
            + _OBJECT_SCRIPT_HELPERS
            + _PLANAR_PRODUCT_CREATION_BODY,
            {
                "kind": "space",
                "style": style.strip(),
                "boundary": normalized_boundary,
                "alignment": None,
                "height": float(height),
                "label_point": normalized_label,
            },
        )
        return _respond(result, f"VisualARQ Space {result.get('object_id')}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error creating VisualARQ Space: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_wall(
    ctx: Context,
    style: str,
    start: List[float],
    end: List[float],
    height: float,
) -> str:
    """Create a VisualARQ wall (a real BIM element, not a box).

    Parameters:
    - style: Wall style GUID (preferred) or an unambiguous exact name.
    - start / end: [x, y, z] of the wall axis at its base.
    - height: Wall height in document units.

    The response separates requested/applied values from a fresh object/style,
    path, thickness, BBox and independent solid-definition volume readback. A
    failed creation judge deletes the new wall and returns
    `VERIFICATION_FAILED` rather than leaving dubious BIM.

    Doors/windows are inserted into the wall afterwards via
    `va_create_door` with this `wall_id`.
    """
    try:
        _require_name(style, "style")
        _require_point3(start, "start")
        _require_point3(end, "end")
        _require_positive(height, "height")
        if all(float(a) == float(b) for a, b in zip(start, end)):
            raise ValueError("wall axis is degenerate: start and end must differ")
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _OBJECT_SCRIPT_HELPERS + r"""
import scriptcontext as sc
style_id, style_error = va_resolve_style(params["style"], "wall")
if style_error is not None:
    result = style_error
else:
    wall_modern_shape = va_exact_method_shape("AddWall", [
        "System.Guid", "Rhino.Geometry.Point3d", "Rhino.Geometry.Point3d"])
    wall_legacy_shape = va_exact_method_shape("AddWall", [
        "Rhino.Geometry.Point3d", "Rhino.Geometry.Point3d",
        "System.Double", "System.Guid"])
    wall_add_api = "modern" if wall_modern_shape["verified"] else (
        "legacy" if wall_legacy_shape["verified"] else None)
    required_methods = [
        "AddWall", "GetProductStyle", "IsWall", "GetWallHeight",
        "GetWallThickness", "GetWallPathCurve", "GetStyleName",
        "GetWallLayerThickness", "GetWallLayerType",
        "GetWallLayerWrapping", "GetStyleComponentName",
        "GetWallStyleHeight", "GetProductsByStyle",
    ]
    if wall_add_api == "modern":
        required_methods.append("SetWallHeight")
    missing_methods = [
        method_name for method_name in required_methods
        if not va_method_available(method_name)
    ]
    if not va_method_available("GetWallLayers") and not (
            va_method_available("GetSubStyleComponents") and
            va_method_available("IsWallLayer")):
        missing_methods.append(
            "GetWallLayers OR GetSubStyleComponents+IsWallLayer")
    style_actual = va_style_snapshot(style_id) if not missing_methods else None
    tolerance = float(sc.doc.ModelAbsoluteTolerance)
    start = params["start"]
    end = params["end"]
    start_point = rg.Point3d(start[0], start[1], start[2])
    end_point = rg.Point3d(end[0], end[1], end[2])
    axis_length = start_point.DistanceTo(end_point)
    if wall_add_api is None:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": "wall_add_signature_unverified",
            "message": (
                "VisualARQ AddWall has no unique supported CLR signature; "
                "no wall was created"),
            "modern_shape": wall_modern_shape,
            "legacy_shape": wall_legacy_shape,
        }
    elif missing_methods:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": "wall_contract_api_incomplete",
            "message": "VisualARQ wall API cannot satisfy verified creation",
            "missing_methods": missing_methods,
        }
    elif style_actual is None:
        result = {
            "status": "error", "code": "INVALID_ID",
            "message": "Resolved wall style could not be read back",
            "style_id": str(style_id),
        }
    elif style_actual.get("readback_complete", True) is not True:
        result = {
            "status": "error", "code": "VERIFICATION_FAILED",
            "reason": "wall_style_layer_inventory_unverified",
            "message": "Wall style layer inventory could not be verified",
            "style": style_actual,
        }
    elif style_actual.get("layer_count") is None or \
            style_actual.get("layer_count") < 1 or \
            style_actual.get("total_layer_thickness") is None or \
            style_actual["total_layer_thickness"] <= tolerance:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": "wall_style_has_no_measurable_layers",
            "message": (
                "Wall style needs at least one positive-thickness layer "
                "for verified creation"),
            "style": style_actual,
        }
    elif axis_length <= tolerance:
        result = {
            "status": "error", "code": "INVALID_PARAMS",
            "message": "Wall axis must be longer than document tolerance",
            "axis_length": axis_length, "tolerance": tolerance,
        }
    else:
        def cleanup_exact_wall(object_id, expected_serial):
            cleanup_obj = sc.doc.Objects.FindId(object_id)
            actual_serial = int(cleanup_obj.RuntimeSerialNumber) \
                if cleanup_obj is not None else None
            serial_matches = cleanup_obj is None or (
                expected_serial is not None and
                actual_serial == expected_serial)
            deleted = False
            if cleanup_obj is not None and serial_matches:
                deleted = bool(sc.doc.Objects.Delete(object_id, True))
            object_exists = sc.doc.Objects.FindId(object_id) is not None
            is_wall = None
            try:
                is_wall = bool(va.IsWall(object_id))
            except Exception:
                pass
            return {
                "deleted": deleted, "object_exists": object_exists,
                "expected_runtime_serial_number": expected_serial,
                "actual_runtime_serial_number": actual_serial,
                "runtime_serial_matches": serial_matches,
                "replacement_detected": serial_matches is False,
                "is_wall_diagnostic": is_wall,
                "cleanup_verified": object_exists is False and \
                    serial_matches is not False and is_wall is False,
            }

        next_runtime_serial_before = int(
            Rhino.DocObjects.RhinoObject.NextRuntimeSerialNumber)
        object_ids_before = set(str(obj.Id) for obj in sc.doc.Objects)

        def new_wall_candidates():
            candidates = []
            errors = []
            active_generations = []
            try:
                recent = sc.doc.Objects.AllObjectsSince(
                    max(next_runtime_serial_before - 1, 0)) or []
                for recent_obj in recent:
                    current_obj = sc.doc.Objects.FindId(recent_obj.Id)
                    if current_obj is None or int(
                            current_obj.RuntimeSerialNumber) != int(
                                recent_obj.RuntimeSerialNumber):
                        continue
                    active_generations.append({
                        "id": str(current_obj.Id),
                        "runtime_serial_number": int(
                            current_obj.RuntimeSerialNumber),
                        "object_type": str(current_obj.GetType().FullName),
                    })
                    try:
                        if va.IsWall(current_obj.Id):
                            candidate_style_id = va.GetProductStyle(
                                current_obj.Id)
                            if candidate_style_id == style_id:
                                candidates.append({
                                    "id": str(current_obj.Id),
                                    "runtime_serial_number": int(
                                        current_obj.RuntimeSerialNumber),
                                    "style_id": str(candidate_style_id),
                                })
                    except Exception as candidate_error:
                        errors.append({
                            "id": str(current_obj.Id),
                            "error": va_text(candidate_error),
                        })
            except Exception as scan_error:
                errors.append({"stage": "AllObjectsSince",
                               "error": va_text(scan_error)})
            return candidates, errors, active_generations

        wall_id = Guid.Empty
        created_runtime_serial = None
        final_runtime_serial = None
        returned_guid_was_preexisting = False
        try:
            if wall_add_api == "modern":
                wall_id = va.AddWall(style_id, start_point, end_point)
            else:
                wall_id = va.AddWall(
                    start_point, end_point, params["height"], style_id)
            if wall_id == Guid.Empty:
                raise Exception("AddWall returned empty Guid")
            returned_guid_was_preexisting = \
                str(wall_id) in object_ids_before
            if returned_guid_was_preexisting:
                raise Exception("AddWall returned a pre-existing object Guid")

            initial_obj = sc.doc.Objects.FindId(wall_id)
            if initial_obj is None:
                raise Exception("Created wall is not readable in the document")
            candidate_runtime_serial = int(initial_obj.RuntimeSerialNumber)
            if candidate_runtime_serial < next_runtime_serial_before:
                raise Exception(
                    "AddWall returned a pre-existing object generation")
            created_runtime_serial = candidate_runtime_serial
            if wall_add_api == "modern":
                set_height = va.SetWallHeight(wall_id, params["height"])
                if set_height is False:
                    raise Exception("SetWallHeight returned false")
            final_obj = sc.doc.Objects.FindId(wall_id)
            if final_obj is None:
                raise Exception("Created wall disappeared after mutation")
            final_runtime_serial = int(final_obj.RuntimeSerialNumber)
            if final_runtime_serial != created_runtime_serial:
                raise Exception("Created wall was replaced during mutation")

            obj = final_obj
            classification_probe = va_object_classification_probe(wall_id)
            classifications = classification_probe["classifications"]
            actual = va_product_snapshot(obj, classification_probe) \
                if obj is not None else None
            post_snapshot_obj = sc.doc.Objects.FindId(wall_id)
            final_runtime_serial = int(
                post_snapshot_obj.RuntimeSerialNumber) \
                if post_snapshot_obj is not None else None
            geometry = actual.get("geometry") \
                if actual is not None else None
            quantity = actual.get("quantity") \
                if actual is not None else None
            direct_volume = geometry.get("volume") \
                if geometry is not None else None
            definition_volume = quantity.get("volume") \
                if quantity is not None and \
                    quantity.get("volume_verified") is True else None
            if direct_volume is not None:
                volume = direct_volume
                volume_source = "object_geometry"
            elif definition_volume is not None:
                volume = definition_volume
                volume_source = quantity.get("source")
            else:
                volume = None
                volume_source = None
            creation_checks = {
                "object_readable": actual is not None,
                "readback_complete": actual is not None and \
                    actual.get("readback_complete") is True,
                "runtime_serial_stable": actual is not None and \
                    actual.get("runtime_serial_number") == \
                        created_runtime_serial and \
                    final_runtime_serial == created_runtime_serial,
                "classified_as_wall": "wall" in classifications,
                "style_matches": actual is not None and \
                    actual.get("style_id") == str(style_id),
                "height_matches": actual is not None and \
                    actual.get("height") is not None and \
                    abs(actual["height"] - params["height"]) <= tolerance,
                "path_start_matches": actual is not None and \
                    actual.get("path") is not None and \
                    rg.Point3d(*actual["path"]["start"]).DistanceTo(
                        start_point) <= tolerance,
                "path_end_matches": actual is not None and \
                    actual.get("path") is not None and \
                    rg.Point3d(*actual["path"]["end"]).DistanceTo(
                        end_point) <= tolerance,
                "path_length_matches": actual is not None and \
                    actual.get("path") is not None and \
                    abs(actual["path"]["length"] - axis_length) <= tolerance,
                "geometry_valid": geometry is not None and \
                    geometry.get("is_valid") is True,
                "bbox_nondegenerate": geometry is not None and \
                    geometry.get("bbox_valid") is True and \
                    geometry.get("bbox_diagonal") is not None and \
                    geometry["bbox_diagonal"] > tolerance,
                "thickness_matches_style": actual is not None and \
                    actual.get("thickness") is not None and \
                    abs(actual["thickness"] - \
                        style_actual["total_layer_thickness"]) <= tolerance,
            }
            quantity_checks = {
                "volume_available": volume is not None,
                "volume_positive": volume is not None and \
                    volume > tolerance * tolerance * tolerance,
            }
            creation_pass = all(creation_checks.values())
            quantity_verification_pass = all(quantity_checks.values())
            verification = {
                "pass": creation_pass and quantity_verification_pass,
                "creation_pass": creation_pass,
                "quantity_verification_pass": quantity_verification_pass,
                "creation_checks": creation_checks,
                "quantity_checks": quantity_checks,
                "tolerance": tolerance,
                "volume_verified": volume is not None,
                "volume": volume,
                "volume_source": volume_source,
                "source": "VisualARQ.Script and Rhino document readback",
            }
            if not creation_pass:
                cleanup = cleanup_exact_wall(
                    wall_id, created_runtime_serial)
                residual_candidates, residual_errors, \
                    residual_generations = new_wall_candidates()
                cleanup_verified = cleanup["cleanup_verified"] and \
                    not residual_generations and not residual_errors
                result = {
                    "status": "error",
                    "code": "VERIFICATION_FAILED" if cleanup_verified \
                        else "PARTIAL_MUTATION",
                    "message": "Wall readback verification failed",
                    "wall_id": str(wall_id), "style": style_actual,
                    "actual": actual, "verification": verification,
                    "cleanup_deleted": cleanup["deleted"],
                    "cleanup_object_exists": cleanup["object_exists"],
                    "cleanup_is_wall": cleanup["is_wall_diagnostic"],
                    "cleanup_verified": cleanup_verified,
                    "residual_new_generations": residual_generations,
                    "residual_scan_errors": residual_errors,
                    "cleanup_runtime_serial_matches": \
                        cleanup["runtime_serial_matches"],
                    "replacement_detected": \
                        cleanup["replacement_detected"],
                    "created_runtime_serial_number": \
                        created_runtime_serial,
                    "cleanup_actual_runtime_serial_number": \
                        cleanup["actual_runtime_serial_number"],
                }
            else:
                warnings = []
                if not quantity_verification_pass:
                    warnings.append(
                        "Independent positive volume is not verified; "
                        "verify through instance-definition solids or IFC "
                        "before quantity use")
                result = {
                    "status": "success", "wall_id": str(wall_id),
                    "creation_runtime_serial_floor": \
                        next_runtime_serial_before,
                    "owned_runtime_serial_number": created_runtime_serial,
                    "runtime_generation_history": [created_runtime_serial],
                    "style": style_actual,
                    "requested_height": params["height"],
                    "applied_height": params["height"],
                    "actual_height": actual["height"],
                    "height_source": actual.get("height_source"),
                    "actual": actual, "verification": verification,
                    "warnings": warnings,
                }
        except Exception as creation_error:
            cleanup_deleted = None
            cleanup_object_exists = None
            cleanup_is_wall = None
            cleanup_runtime_serial_matches = None
            cleanup_replacement_detected = False
            recovered_wall_id = None
            recovered_runtime_serial = None
            candidate_errors = []
            cleanup_verified = False
            cleanup_target_id = wall_id
            cleanup_target_serial = created_runtime_serial
            cleanup_refused_reason = None
            candidates, candidate_errors, active_generations = \
                new_wall_candidates()
            if cleanup_target_id == Guid.Empty and len(candidates) == 1 and \
                    not candidate_errors:
                recovered_wall_id = candidates[0]["id"]
                recovered_runtime_serial = \
                    candidates[0]["runtime_serial_number"]
                cleanup_refused_reason = (
                    "AddWall returned an empty Guid; a style-matching recent "
                    "wall is diagnostic evidence, not causal ownership")
            elif cleanup_target_id != Guid.Empty and \
                    cleanup_target_serial is None and \
                    not returned_guid_was_preexisting:
                matching_candidates = [
                    candidate for candidate in candidates
                    if candidate["id"] == str(cleanup_target_id)]
                if len(matching_candidates) == 1 and not candidate_errors:
                    cleanup_target_serial = \
                        matching_candidates[0]["runtime_serial_number"]
            elif returned_guid_was_preexisting:
                cleanup_refused_reason = \
                    "returned_guid_existed_before_addwall"
            if cleanup_target_id != Guid.Empty and \
                    cleanup_target_serial is not None:
                try:
                    cleanup = cleanup_exact_wall(
                        cleanup_target_id, cleanup_target_serial)
                    cleanup_deleted = cleanup["deleted"]
                    cleanup_object_exists = cleanup["object_exists"]
                    cleanup_is_wall = cleanup["is_wall_diagnostic"]
                    cleanup_verified = cleanup["cleanup_verified"]
                    cleanup_runtime_serial_matches = \
                        cleanup["runtime_serial_matches"]
                    cleanup_replacement_detected = \
                        cleanup["replacement_detected"]
                except Exception as cleanup_error:
                    cleanup_deleted = False
                    cleanup_verified = False
                    candidate_errors.append({
                        "stage": "cleanup", "error": va_text(cleanup_error)})
            elif cleanup_target_id == Guid.Empty and \
                    not active_generations and not candidate_errors:
                # The serial-bounded active-object scan proves that AddWall did
                # not leave a document-resident wall despite the empty return.
                cleanup_object_exists = False
                try:
                    cleanup_is_wall = bool(va.IsWall(Guid.Empty))
                except Exception as cleanup_error:
                    candidate_errors.append({
                        "stage": "cleanup_empty_guid_is_wall",
                        "error": va_text(cleanup_error),
                    })
                cleanup_verified = cleanup_is_wall is False
            residual_candidates, residual_errors, residual_generations = \
                new_wall_candidates()
            if residual_generations or residual_errors:
                cleanup_verified = False
            result = {
                "status": "error",
                "code": "RHINO_ERROR" if cleanup_verified \
                    else "PARTIAL_MUTATION",
                "message": "Wall creation failed: " + va_text(creation_error),
                "wall_id": str(wall_id) if wall_id != Guid.Empty else None,
                "creation_runtime_serial_floor": \
                    next_runtime_serial_before,
                "recovered_wall_id": recovered_wall_id,
                "recovered_runtime_serial_number": recovered_runtime_serial,
                "new_wall_candidates": candidates,
                "new_active_generations": active_generations,
                "candidate_scan_errors": candidate_errors,
                "residual_new_generations": residual_generations,
                "residual_scan_errors": residual_errors,
                "cleanup_deleted": cleanup_deleted,
                "cleanup_object_exists": cleanup_object_exists,
                "cleanup_is_wall": cleanup_is_wall,
                "cleanup_verified": cleanup_verified,
                "created_runtime_serial_number": created_runtime_serial,
                "final_runtime_serial_number": final_runtime_serial,
                "cleanup_runtime_serial_matches": \
                    cleanup_runtime_serial_matches,
                "replacement_detected": cleanup_replacement_detected,
                "returned_guid_was_preexisting": \
                    returned_guid_was_preexisting,
                "cleanup_refused_reason": cleanup_refused_reason,
            }
""",
            {"style": style.strip(), "start": start, "end": end, "height": height},
        )
        result = _refresh_wall_quantity(
            rhino, result, start, end, height,
        )
        return _respond(result, f"Wall created: {result.get('wall_id')}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error creating VisualARQ wall: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


def _specialize_door_runtime_script(
    script: str,
    opening_kind: Literal["door", "window"],
    *,
    required_tokens: tuple[str, ...],
    contract: str,
) -> str:
    """Lexically specialize one audited Door runtime program for Window."""
    if opening_kind == "door":
        return script
    if opening_kind != "window":
        raise ValueError("opening_kind must be 'door' or 'window'")
    missing = [token for token in required_tokens if token not in script]
    if missing:
        raise RuntimeError(
            f"{contract} template drifted; missing Door tokens: "
            + ", ".join(missing)
        )
    specialized = script.replace("Door", "Window").replace("door", "window")
    missing_window_tokens = [
        token.replace("Door", "Window").replace("door", "window")
        for token in required_tokens
        if token.replace("Door", "Window").replace("door", "window")
        not in specialized
    ]
    if missing_window_tokens:
        raise RuntimeError(
            f"{contract} Window specialization is incomplete: "
            + ", ".join(missing_window_tokens)
        )
    return specialized


def _specialize_opening_creation_script(
    script: str,
    opening_kind: Literal["door", "window"],
) -> str:
    """Reuse one audited opening vertical for Door and Window.

    The Rhino-side program is authored once with ``door`` identifiers. Window
    specialization is lexical and happens before transport; regression tests
    compile both generated programs and require the exact Add/Is/style tokens.
    The shared script owns operational profile/host/delta/cleanup mechanics,
    while the public wrappers own the object-kind policy and user contract.
    """
    return _specialize_door_runtime_script(
        script,
        opening_kind,
        required_tokens=("AddDoor", "IsDoor", '"door_id"'),
        contract="Opening creation",
    )


def _is_async_opening_materialization(
    result: Dict[str, Any],
    opening_kind: Literal["door", "window"],
) -> bool:
    """Recognize VA's deferred Rhino-object materialization exactly."""
    return (
        result.get("status") == "error"
        and result.get("code") == ErrorCode.PARTIAL_MUTATION
        and result.get("reason")
        == f"{opening_kind}_materialization_pending_after_add"
        and result.get("mutation_started") is True
        and result.get("returned_guid_was_preexisting") is False
        and result.get(
            f"add{opening_kind}_returned_empty_guid") is False
        and result.get("materialization_pending") is True
        and isinstance(result.get("api_return_id"), str)
        and bool(result.get("api_return_id"))
        and result.get("created_runtime_serial_number") is None
    )


def _refresh_async_opening_creation(
    rhino: Any,
    result: Dict[str, Any],
    *,
    opening_kind: Literal["door", "window"],
    style: str,
    point: Optional[List[float]],
    rotation: float,
    wall_id: Optional[str],
    width: Optional[float],
    height: Optional[float],
    max_attempts: int = 4,
) -> Dict[str, Any]:
    """Resolve a deferred VA opening after control returns to Rhino's UI.

    VisualARQ 3.7 can return an internal/transient GUID from ``AddDoor`` or
    ``AddWindow`` while the actual Rhino InstanceObject is published only
    after the executing command releases the UI thread.  The follow-up is
    serial-floor bounded and accepts exactly one object matching kind, style,
    host, profile and placement.  It never deletes across commands.
    """
    if not _is_async_opening_materialization(result, opening_kind):
        return result

    id_key = f"{opening_kind}_id"
    api_return_id = result.get("api_return_id")
    serial_floor = result.get("creation_runtime_serial_floor")
    style_id = result.get("resolved_style_id")
    selected_profile_id = result.get("selected_profile_id")
    preadd_object_ids = result.get("preadd_object_ids")
    expected_profile_ids = [
        item.get("id") for item in result.get("style_profiles_before", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    host_baselines: Dict[str, Any] = {}
    for item in result.get("host_cleanup_results", []):
        if not isinstance(item, dict):
            continue
        baseline = item.get("baseline")
        baseline_id = item.get("wall_id")
        if (
            isinstance(baseline_id, str)
            and isinstance(baseline, dict)
            and baseline.get("readback_complete") is True
            and baseline.get("id") == baseline_id
        ):
            host_baselines[baseline_id] = baseline

    preconditions = {
        "serial_floor": (
            isinstance(serial_floor, int)
            and not isinstance(serial_floor, bool)
            and serial_floor > 0
        ),
        "style_id": isinstance(style_id, str) and bool(style_id),
        "point": (
            isinstance(point, list)
            and len(point) == 3
            and all(_finite_float(value) is not None for value in point)
        ),
        "spatial_host_baseline_complete": (
            result.get("spatial_host_baseline_complete") is True
        ),
        "host_baselines": bool(host_baselines),
        "profile_inventory": bool(expected_profile_ids),
        "preadd_object_inventory": isinstance(preadd_object_ids, list),
    }
    if not all(preconditions.values()):
        result.update({
            "status": "error",
            "code": ErrorCode.PARTIAL_MUTATION,
            "message": (
                f"{opening_kind.title()} materialized asynchronously, but "
                "its cross-command ownership baseline is incomplete"),
            "async_materialization": {
                "attempted": False,
                "api_return_id": api_return_id,
                "preconditions": preconditions,
                "materialization_attribution_verified": False,
                "exact_generation_verified": False,
                "cleanup_ownership_verified": False,
                "cross_command_cleanup_authorized": False,
            },
            "cleanup_deleted": False,
            "cleanup_verified": False,
            "cleanup_refused_reason": "cross_command_cleanup_is_forbidden",
        })
        return result

    readback_body = r"""
import math
import scriptcontext as sc
kind = params["kind"]
kind_method = "IsDoor" if kind == "door" else "IsWindow"
expected_style_id = Guid(params["style_id"])
serial_floor = int(params["serial_floor"])
host_baselines = params["host_baselines"]
preadd_object_ids = set(params.get("preadd_object_ids") or [])
expected_host_id = params.get("wall_id")
expected_profile_ids = list(params.get("expected_profile_ids") or [])
selected_profile_text = params.get("selected_profile_id")
selected_profile_id = Guid(selected_profile_text) \
    if selected_profile_text else Guid.Empty
active_generations = []
candidate_generations = []
unexpected_generations = []
scan_errors = []
seen_generations = set()
current_object_ids = sorted(str(obj.Id) for obj in sc.doc.Objects)
removed_object_ids = sorted(preadd_object_ids - set(current_object_ids))
added_object_ids = sorted(set(current_object_ids) - preadd_object_ids)
try:
    recent_objects = list(sc.doc.Objects.AllObjectsSince(
        max(serial_floor - 1, 0)) or [])
except Exception as error:
    recent_objects = []
    scan_errors.append({
        "stage": "AllObjectsSince", "error": va_text(error)})
for recent_obj in recent_objects:
    current_obj = sc.doc.Objects.FindId(recent_obj.Id)
    if current_obj is None or int(current_obj.RuntimeSerialNumber) != int(
            recent_obj.RuntimeSerialNumber):
        continue
    current_serial = int(current_obj.RuntimeSerialNumber)
    if current_serial < serial_floor:
        continue
    generation_key = str(current_obj.Id) + "|" + str(current_serial)
    if generation_key in seen_generations:
        continue
    seen_generations.add(generation_key)
    entry = {
        "id": str(current_obj.Id),
        "runtime_serial_number": current_serial,
        "object_type": str(current_obj.GetType().FullName),
        "role": None,
    }
    if entry["id"] not in current_object_ids:
        # AllObjectsSince also reports fresh instance-definition leaves.
        # They are covered by the active-object delta and the canonical
        # opening/host definition fingerprints below, but are not independent
        # document-resident mutations or opening candidates.
        entry["role"] = "nonactive_instance_definition_generation"
        active_generations.append(entry)
        continue
    if entry["id"] in host_baselines:
        try:
            if bool(va.IsWall(current_obj.Id)):
                entry["role"] = "baseline_host_regeneration"
                active_generations.append(entry)
                continue
        except Exception as error:
            scan_errors.append({
                "id": entry["id"], "stage": "host_classification",
                "error": va_text(error),
            })
            active_generations.append(entry)
            continue
    if entry["id"] in preadd_object_ids:
        entry["role"] = "unexpected_preadd_object_regeneration"
        unexpected_generations.append(entry)
        active_generations.append(entry)
        continue
    kind_probe = va_matches_kind(current_obj.Id, kind)
    if kind_probe.get("match") is None:
        scan_errors.append({
            "id": entry["id"], "stage": "kind_classification",
            "method": kind_probe.get("method"),
            "error": kind_probe.get("error"),
        })
    elif kind_probe.get("match") is True:
        try:
            candidate_style_id = va.GetProductStyle(current_obj.Id)
            entry["style_id"] = str(candidate_style_id) \
                if candidate_style_id is not None and \
                    candidate_style_id != Guid.Empty else None
            if candidate_style_id == expected_style_id:
                entry["role"] = "opening_candidate"
                candidate_generations.append(entry)
            else:
                entry["role"] = "unexpected_opening_style"
                unexpected_generations.append(entry)
        except Exception as error:
            entry["role"] = "unreadable_opening_style"
            scan_errors.append({
                "id": entry["id"], "stage": "style",
                "error": va_text(error),
            })
    else:
        entry["role"] = "unexpected_active_generation"
        unexpected_generations.append(entry)
    active_generations.append(entry)

candidate_ids = sorted(
    item["id"] for item in candidate_generations)
nonactive_generation_ids = sorted(
    item["id"] for item in active_generations
    if item.get("role") ==
        "nonactive_instance_definition_generation")
active_object_delta_matches = not removed_object_ids and (
    added_object_ids == candidate_ids)
if scan_errors or unexpected_generations or \
        len(candidate_generations) > 1 or not active_object_delta_matches:
    result = {
        "status": "error", "code": "PARTIAL_MUTATION",
        "message": (
            "Deferred " + kind +
            " materialization is not an isolated runtime-generation delta"),
        "reason": "async_opening_generation_delta_unverified",
        "active_generations": active_generations,
        "candidate_generations": candidate_generations,
        "unexpected_generations": unexpected_generations,
        "scan_errors": scan_errors,
        "preadd_object_ids": sorted(preadd_object_ids),
        "current_object_ids": current_object_ids,
        "added_object_ids": added_object_ids,
        "removed_object_ids": removed_object_ids,
        "active_object_delta_matches": active_object_delta_matches,
        "cross_command_cleanup_authorized": False,
    }
elif not candidate_generations:
    result = {
        "status": "pending",
        "reason": "async_opening_object_not_published_yet",
        "active_generations": active_generations,
        "candidate_generations": [],
        "preadd_object_ids": sorted(preadd_object_ids),
        "current_object_ids": current_object_ids,
        "added_object_ids": added_object_ids,
        "removed_object_ids": removed_object_ids,
        "active_object_delta_matches": active_object_delta_matches,
        "cross_command_cleanup_authorized": False,
    }
else:
    candidate = candidate_generations[0]
    object_id = Guid(candidate["id"])
    obj = sc.doc.Objects.FindId(object_id)
    actual_profile_id = va.GetOpeningProfile(object_id)
    if selected_profile_id != Guid.Empty and \
            actual_profile_id != selected_profile_id:
        result = {
            "status": "error", "code": "PARTIAL_MUTATION",
            "message": (
                "Deferred " + kind +
                " did not retain the selected Size Profile"),
            "reason": "async_opening_profile_update_not_persistent",
            "actual_profile_id": str(actual_profile_id)
                if actual_profile_id is not None and
                    actual_profile_id != Guid.Empty else None,
            "selected_profile_id": selected_profile_text,
            "candidate_generations": candidate_generations,
            "active_generations": active_generations,
            "cross_command_cleanup_authorized": False,
        }
    else:
        classification_probe = va_object_classification_probe(object_id)
        product_snapshot = va_product_snapshot(
            obj, classification_probe, False, True)
        materialized_definition = \
            va_instance_definition_volume_snapshot(obj)
        actual_style_id = va.GetProductStyle(object_id)
        style_component_ids = []
        style_component_inventory_error = None
        try:
            style_component_ids = sorted(
                str(value) for value in list(
                    va.GetSubStyleComponents(expected_style_id) or []))
            if len(style_component_ids) != len(set(style_component_ids)):
                raise Exception("duplicate opening style component Guid")
            if str(Guid.Empty) in style_component_ids:
                raise Exception("empty opening style component Guid")
        except Exception as error:
            style_component_inventory_error = va_text(error)
        visible_geometry_expected = bool(style_component_ids) \
            if style_component_inventory_error is None else None
        opening_position = va.GetOpeningPosition(object_id)
        opening_rotation_radians = va_valid_double(
            va.GetOpeningRotation(object_id))
        opening_host_id = va.GetOpeningHost(object_id)
        opening_host_text = str(opening_host_id) \
            if opening_host_id is not None and \
                opening_host_id != Guid.Empty else None
        host_readbacks = [{
            "source": "GetOpeningHost", "id": opening_host_text,
            "error": None,
        }]
        valid_host_ids = [opening_host_text] \
            if opening_host_text is not None else []
        legacy_host_methods = ["GetDoorHostId", "GetDoorWallId"] \
            if kind == "door" else [
                "GetWindowHostId", "GetWindowWallId"]
        for host_method in legacy_host_methods:
            if not va_method_available(host_method):
                continue
            try:
                legacy_id = getattr(va, host_method)(object_id)
                legacy_text = str(legacy_id) \
                    if legacy_id is not None and \
                        legacy_id != Guid.Empty else None
                host_readbacks.append({
                    "source": host_method, "id": legacy_text,
                    "error": None,
                })
                if legacy_text is not None:
                    valid_host_ids.append(legacy_text)
            except Exception as error:
                host_readbacks.append({
                    "source": host_method, "id": None,
                    "error": va_text(error),
                })
        unique_host_ids = sorted(set(valid_host_ids))
        tolerance = float(sc.doc.ModelAbsoluteTolerance)
        host_state_results = []
        changed_host_ids = []
        host_states_after = {}
        for baseline_id in sorted(host_baselines):
            baseline_state = host_baselines[baseline_id]
            current_host_obj = sc.doc.Objects.FindId(Guid(baseline_id))
            current_host_state = None
            current_host_error = None
            try:
                if current_host_obj is None or not bool(
                        va.IsWall(current_host_obj.Id)):
                    raise Exception(
                        "baselined spatial host is absent or not a wall")
                current_host_state = va_opening_host_wall_state(
                    current_host_obj)
            except Exception as error:
                current_host_error = va_text(error)
            host_states_after[baseline_id] = current_host_state
            semantics_match = va_opening_host_wall_semantics_match(
                baseline_state, current_host_state, tolerance)
            fingerprint_matches = \
                va_instance_definition_fingerprints_match(
                    baseline_state.get("definition_fingerprint"),
                    current_host_state.get("definition_fingerprint")
                        if current_host_state is not None else None)
            exact_state_matches = semantics_match and fingerprint_matches
            definition_changed = semantics_match and not fingerprint_matches
            if definition_changed:
                changed_host_ids.append(baseline_id)
            host_state_results.append({
                "wall_id": baseline_id,
                "baseline": baseline_state,
                "actual": current_host_state,
                "semantics_match": semantics_match,
                "definition_fingerprint_matches": fingerprint_matches,
                "definition_changed": definition_changed,
                "exact_state_matches": exact_state_matches,
                "error": current_host_error,
            })
        host_before = host_baselines.get(opening_host_text) \
            if opening_host_text is not None else None
        host_after = host_states_after.get(opening_host_text) \
            if opening_host_text is not None else None
        known_definition_generation_ids = set()
        materialized_fingerprint = materialized_definition.get(
            "definition_fingerprint")
        if materialized_fingerprint is not None:
            for diagnostic in materialized_fingerprint.get(
                    "diagnostic_leaves", []):
                leaf_id = diagnostic.get("leaf_id")
                if leaf_id is not None:
                    known_definition_generation_ids.add(leaf_id)
        for current_host_state in host_states_after.values():
            if current_host_state is None:
                continue
            host_fingerprint = current_host_state.get(
                "definition_fingerprint")
            if host_fingerprint is None:
                continue
            for diagnostic in host_fingerprint.get(
                    "diagnostic_leaves", []):
                leaf_id = diagnostic.get("leaf_id")
                if leaf_id is not None:
                    known_definition_generation_ids.add(leaf_id)
        unattributed_nonactive_generation_ids = sorted(
            set(nonactive_generation_ids) -
            known_definition_generation_ids)
        host_semantics_stable = va_opening_host_wall_semantics_match(
            host_before, host_after, tolerance)
        host_definition_changed = host_before is not None and \
            host_after is not None and \
            host_before.get("definition_fingerprint") is not None and \
            host_after.get("definition_fingerprint") is not None and not \
            va_instance_definition_fingerprints_match(
                host_before.get("definition_fingerprint"),
                host_after.get("definition_fingerprint"))
        host_cut_volume_delta = None
        if host_before is not None and host_before.get("volume") is not None \
                and host_after is not None and \
                host_after.get("volume") is not None:
            host_cut_volume_delta = \
                host_before["volume"] - host_after["volume"]
        profile_snapshot = va_opening_profile_snapshot(
            expected_style_id, actual_profile_id) \
            if actual_profile_id is not None and \
                actual_profile_id != Guid.Empty else None
        actual_dimensions = dict(profile_snapshot["dimensions"]) \
            if profile_snapshot is not None and \
                profile_snapshot.get("dimensions") is not None else {}
        current_profile_ids = [
            str(value) for value in list(
                va.GetOpeningStyleSizeProfiles(expected_style_id) or [])]
        expected_point = rg.Point3d(
            params["point"][0], params["point"][1], params["point"][2])
        requested_rotation = float(params.get("rotation") or 0.0) % 360.0
        actual_rotation = math.degrees(opening_rotation_radians) % 360.0 \
            if opening_rotation_radians is not None else None
        rotation_delta = abs(
            (actual_rotation - requested_rotation + 180.0) % 360.0 - 180.0
        ) if actual_rotation is not None else None
        geometry = product_snapshot.get("geometry") \
            if product_snapshot is not None else None
        requested_width = params.get("width")
        requested_height = params.get("height")
        materialized_leaf_count = materialized_fingerprint.get("leaf_count") \
            if materialized_fingerprint is not None else None
        bbox_nondegenerate = geometry is not None and \
            geometry.get("bbox_valid") is True and \
            geometry.get("bbox_diagonal") is not None and \
            geometry["bbox_diagonal"] > tolerance
        componentless_definition_empty = \
            visible_geometry_expected is False and \
            materialized_leaf_count == 0
        checks = {
            "isolated_runtime_generation_delta":
                len(candidate_generations) == 1 and
                not unexpected_generations and not scan_errors,
            "active_object_delta_matches": active_object_delta_matches,
            "runtime_serial_bounded":
                int(obj.RuntimeSerialNumber) >= serial_floor,
            "classification_complete": classification_probe["complete"],
            "classified_as_kind": kind in
                classification_probe["classifications"],
            "product_readback_complete": product_snapshot is not None and
                product_snapshot.get("readback_complete") is True,
            "materialized_definition_fingerprint_complete":
                visible_geometry_expected is False or (
                    materialized_fingerprint is not None and
                    materialized_fingerprint.get("complete") is True),
            "componentless_style_definition_empty":
                visible_geometry_expected is not False or
                componentless_definition_empty,
            "nonactive_generation_attribution_verified":
                not unattributed_nonactive_generation_ids,
            "style_matches": actual_style_id == expected_style_id,
            "style_component_inventory_complete":
                style_component_inventory_error is None,
            "geometry_valid": geometry is not None and
                geometry.get("is_valid") is True,
            "bbox_nondegenerate_when_visible_geometry_expected":
                visible_geometry_expected is False or bbox_nondegenerate,
            "profile_readback_complete": profile_snapshot is not None and
                profile_snapshot.get("readback_complete") is True,
            "profile_in_style_inventory":
                str(actual_profile_id) in current_profile_ids,
            "profile_matches_selected": selected_profile_id == Guid.Empty or
                actual_profile_id == selected_profile_id,
            "profile_matches_product_readback": product_snapshot is not None
                and product_snapshot.get("profile_id") ==
                    str(actual_profile_id),
            "style_profile_inventory_unchanged":
                current_profile_ids == expected_profile_ids,
            "opening_position_matches": opening_position is not None and
                opening_position.DistanceTo(expected_point) <= tolerance,
            "rotation_matches": rotation_delta is not None and
                rotation_delta <= 1e-4,
            "host_nonempty": opening_host_text is not None,
            "host_in_preadd_baseline": opening_host_text in host_baselines,
            "host_sources_agree": len(unique_host_ids) == 1,
            "host_matches_expected": expected_host_id is None or
                opening_host_text == expected_host_id,
            "host_readback_complete": host_after is not None and
                host_after.get("readback_complete") is True,
            "all_spatial_host_states_readable":
                len(host_state_results) == len(host_baselines) and all(
                    item["actual"] is not None and
                    item["actual"].get("readback_complete") is True and
                    item["error"] is None for item in host_state_results),
            "only_authoritative_host_definition_changed":
                changed_host_ids == [opening_host_text],
            "other_spatial_hosts_unchanged": all(
                item["wall_id"] == opening_host_text or
                item["exact_state_matches"] is True
                for item in host_state_results),
            "host_semantics_stable": host_semantics_stable,
            "host_definition_changed": host_definition_changed,
            "host_cut_independently_verified":
                host_semantics_stable and host_definition_changed,
            "width_matches": requested_width is None or
                actual_dimensions.get("width") is not None and abs(
                    actual_dimensions["width"] - requested_width
                ) <= tolerance,
            "height_matches": requested_height is None or
                actual_dimensions.get("height") is not None and abs(
                    actual_dimensions["height"] - requested_height
                ) <= tolerance,
        }
        verification_pass = all(checks.values())
        result = {
            "status": "success" if verification_pass else "error",
            "code": None if verification_pass else "PARTIAL_MUTATION",
            "message": None if verification_pass else (
                "Deferred " + kind +
                " failed final ownership/readback verification"),
            "reason": None if verification_pass else
                "async_opening_final_verification_failed",
            "api_return_id": params.get("api_return_id"),
            "style": params["style"],
            "style_id": str(expected_style_id),
            "actual_style_id": str(actual_style_id),
            "style_component_ids": style_component_ids,
            "style_component_inventory_error":
                style_component_inventory_error,
            "visible_geometry_expected": visible_geometry_expected,
            "requested_point": params["point"],
            "requested_rotation_degrees": params.get("rotation"),
            "wall_id": expected_host_id,
            "host": {
                "id": opening_host_text,
                "source": "GetOpeningHost"
                    if opening_host_text is not None else None,
                "readbacks": host_readbacks,
                "unique_valid_ids": unique_host_ids,
                "sources_agree": len(unique_host_ids) == 1,
                "in_preadd_baseline": opening_host_text in host_baselines,
            },
            "product": product_snapshot,
            "materialized_definition": materialized_definition,
            "geometry_expectation": {
                "visible_geometry_expected": visible_geometry_expected,
                "style_component_count": len(style_component_ids),
                "bbox_nondegenerate": bbox_nondegenerate,
                "materialized_definition_leaf_count":
                    materialized_leaf_count,
                "componentless_definition_empty":
                    componentless_definition_empty,
            },
            "profile_id": str(actual_profile_id)
                if actual_profile_id is not None and
                    actual_profile_id != Guid.Empty else None,
            "selected_profile_id": selected_profile_text,
            "profile": profile_snapshot,
            "style_profiles_before": params["style_profiles_before"],
            "host_wall_before": host_before,
            "host_wall_after": host_after,
            "host_state_results": host_state_results,
            "changed_host_ids": changed_host_ids,
            "host_semantics_stable": host_semantics_stable,
            "host_definition_changed": host_definition_changed,
            "host_cut_volume_delta": host_cut_volume_delta,
            "placement_verification": {
                "expected_point": params["point"],
                "opening_position": va_point(opening_position)
                    if opening_position is not None else None,
                "point_matches": checks["opening_position_matches"],
                "requested_rotation_degrees": requested_rotation,
                "actual_rotation_degrees": actual_rotation,
                "rotation_delta_degrees": rotation_delta,
                "rotation_matches": checks["rotation_matches"],
            },
            "requested_dimensions": {
                "width": requested_width, "height": requested_height},
            "applied_dimensions": actual_dimensions,
            "actual_dimensions": actual_dimensions,
            "dimension_sources": {
                "width": "GetRectangularProfileSize",
                "height": "GetRectangularProfileSize",
            } if actual_dimensions else {},
            "verification": {
                "pass": verification_pass,
                "creation_checks": checks,
                "tolerance": tolerance,
                "source": (
                    "serial-bounded deferred VisualARQ materialization plus "
                    "Rhino document readback"),
            },
            "runtime_serial_number": int(obj.RuntimeSerialNumber),
            "active_generations": active_generations,
            "candidate_generations": candidate_generations,
            "unexpected_generations": unexpected_generations,
            "scan_errors": scan_errors,
            "nonactive_generation_ids": nonactive_generation_ids,
            "known_definition_generation_ids": sorted(
                known_definition_generation_ids),
            "unattributed_nonactive_generation_ids":
                unattributed_nonactive_generation_ids,
            "preadd_object_ids": sorted(preadd_object_ids),
            "current_object_ids": current_object_ids,
            "added_object_ids": added_object_ids,
            "removed_object_ids": removed_object_ids,
            "active_object_delta_matches": active_object_delta_matches,
            "cross_command_cleanup_authorized": False,
        }
        result["warnings"] = [
            "Opening style has no sub-style components; its semantic BIM "
            "opening and host cut are verified, but no standalone visible "
            "opening geometry is expected"
        ] if visible_geometry_expected is False else []
        result[kind + "_id"] = str(object_id)
"""

    attempts: List[Dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        try:
            refreshed = run_va(
                rhino,
                _STYLE_SCRIPT_HELPERS + _OBJECT_SCRIPT_HELPERS
                + _OPENING_HOST_SCRIPT_HELPERS + readback_body,
                {
                    "kind": opening_kind,
                    "style": style,
                    "style_id": style_id,
                    "serial_floor": serial_floor,
                    "point": point,
                    "rotation": rotation,
                    "wall_id": wall_id,
                    "width": width,
                    "height": height,
                    "selected_profile_id": selected_profile_id,
                    "expected_profile_ids": expected_profile_ids,
                    "style_profiles_before": result.get(
                        "style_profiles_before", []),
                    "host_baselines": host_baselines,
                    "preadd_object_ids": preadd_object_ids,
                    "api_return_id": api_return_id,
                },
            )
        except Exception as exc:
            attempts.append({
                "attempt": attempt,
                "status": "transport_error",
                "error": str(exc),
            })
            continue

        attempt_record = {
            "attempt": attempt,
            "status": refreshed.get("status"),
            "reason": refreshed.get("reason"),
            "candidate_count": len(
                refreshed.get("candidate_generations", [])),
        }
        attempts.append(attempt_record)
        if refreshed.get("status") == "pending":
            continue
        if (
            refreshed.get("status") == "error"
            and refreshed.get("reason") in {
                "async_opening_final_verification_failed",
                "async_opening_profile_update_not_persistent",
            }
            and attempt < max_attempts
        ):
            continue
        if refreshed.get("status") == "success":
            actual_id = refreshed.get(id_key)
            refreshed["async_materialization"] = {
                "attempted": True,
                "complete": True,
                "attempt_count": attempt,
                "attempts": attempts,
                "api_return_id": api_return_id,
                "actual_object_id": actual_id,
                "object_id_changed": actual_id != api_return_id,
                "serial_floor": serial_floor,
                "materialization_attribution_verified": True,
                "exact_generation_verified": True,
                "cleanup_ownership_verified": False,
                "attribution_method": (
                    "unique_active_object_delta_plus_full_contract"),
                "cross_command_cleanup_authorized": False,
            }
            return refreshed

        refreshed["async_materialization"] = {
            "attempted": True,
            "complete": False,
            "attempt_count": attempt,
            "attempts": attempts,
            "api_return_id": api_return_id,
            "serial_floor": serial_floor,
            "materialization_attribution_verified": False,
            "exact_generation_verified": False,
            "cleanup_ownership_verified": False,
            "cross_command_cleanup_authorized": False,
        }
        refreshed.update({
            "cleanup_deleted": False,
            "cleanup_verified": False,
            "cleanup_refused_reason": "cross_command_cleanup_is_forbidden",
        })
        return refreshed

    result.update({
        "status": "error",
        "code": ErrorCode.PARTIAL_MUTATION,
        "message": (
            f"{opening_kind.title()} was accepted by VisualARQ, but its "
            "Rhino object did not become uniquely verifiable after bounded "
            "cross-command readback"),
        "async_materialization": {
            "attempted": True,
            "complete": False,
            "attempt_count": max_attempts,
            "attempts": attempts,
            "api_return_id": api_return_id,
            "serial_floor": serial_floor,
            "materialization_attribution_verified": False,
            "exact_generation_verified": False,
            "cleanup_ownership_verified": False,
            "cross_command_cleanup_authorized": False,
        },
        "cleanup_deleted": False,
        "cleanup_verified": False,
        "cleanup_refused_reason": "cross_command_cleanup_is_forbidden",
    })
    return result


def _va_create_opening(
    ctx: Context,
    style: str,
    point: Optional[List[float]] = None,
    rotation: float = 0.0,
    wall_id: Optional[str] = None,
    position: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    *,
    opening_kind: Literal["door", "window"],
) -> str:
    """Shared verified VisualARQ Door/Window insertion implementation.

    Two placement modes — pass whichever the situation gives you:
    - `point` [x, y, z] **on a wall axis** (+ optional `rotation` in
      degrees): VisualARQ hosts the opening into that wall automatically.
      This is the native mode of current VA versions.
    - `wall_id` + `position` (distance along the wall axis): legacy VA
      API; on current versions the tool converts is not possible — prefer
      `point`.

    Parameters:
    - style: Opening style name for the requested object kind.
    - width / height: Optional overrides; omit to keep the style's values.

    Returns:
        The kind-specific payload contains ``door_id`` or ``window_id`` plus
        independently read style, placement, profile, host and cut evidence.
    """
    try:
        _require_name(style, "style")
        if point is None and (wall_id is None or position is None):
            raise ValueError(
                "pass either point=[x,y,z] (on a wall axis) or "
                "wall_id + position")
        if point is not None and position is not None:
            raise ValueError(
                "point and position are mutually exclusive placement modes")
        if point is not None:
            _require_point3(point, "point")
        if wall_id is not None:
            _require_guid(wall_id, "wall_id")
            wall_id = str(UUID(wall_id.strip().strip("{}")))
        if position is not None:
            _require_finite_number(position, "position")
            if position < 0:
                raise ValueError("position must be non-negative")
        _require_finite_number(rotation, "rotation")
        if width is not None:
            _require_positive(width, "width")
        if height is not None:
            _require_positive(height, "height")
        rhino = get_rhino_connection()
        opening_script = r"""
import math
import scriptcontext as sc
style_id, style_error = va_resolve_style(params["style"], "door")
if style_error is not None:
    result = style_error
else:
    requested_width = params.get("width")
    requested_height = params.get("height")
    dimensions_requested = requested_width is not None or \
        requested_height is not None
    door_modern_shape = va_exact_method_shape("AddDoor", [
        "System.Guid", "Rhino.Geometry.Point3d", "System.Double"])
    point_placement_api = door_modern_shape["verified"]
    opening_position_shape = va_exact_method_shape(
        "GetOpeningPosition", ["System.Guid"], "Rhino.Geometry.Point3d")
    opening_rotation_shape = va_exact_method_shape(
        "GetOpeningRotation", ["System.Guid"], "System.Double")
    opening_profile_shape = va_exact_method_shape(
        "GetOpeningProfile", ["System.Guid"], "System.Guid")
    opening_host_shape = va_exact_method_shape(
        "GetOpeningHost", ["System.Guid"], "System.Guid")
    style_profiles_shape = va_exact_method_shape(
        "GetOpeningStyleSizeProfiles", ["System.Guid"], "System.Guid[]")
    profile_membership_shape = va_exact_method_shape(
        "IsOpeningStyleSizeProfile",
        ["System.Guid", "System.Guid"], "System.Boolean")
    profile_owner_shape = va_exact_method_shape(
        "GetOpeningStyleFromSizeProfile",
        ["System.Guid"], "System.Guid")
    set_profile_shape = va_exact_method_shape(
        "SetOpeningProfile",
        ["System.Guid", "System.Guid"], "System.Boolean")
    rectangular_classifier_shape = va_exact_method_shape(
        "IsRectangularProfile", ["System.Guid"], "System.Boolean")
    rectangular_size_shape = va_exact_method_shape(
        "GetRectangularProfileSize", ["System.Guid"],
        "VisualARQ.Script+RectangularProfileSize")
    opening_readback_shapes = {
        "GetOpeningPosition": opening_position_shape,
        "GetOpeningRotation": opening_rotation_shape,
        "GetOpeningProfile": opening_profile_shape,
        "GetOpeningHost": opening_host_shape,
        "GetOpeningStyleSizeProfiles": style_profiles_shape,
        "IsOpeningStyleSizeProfile": profile_membership_shape,
        "GetOpeningStyleFromSizeProfile": profile_owner_shape,
        "SetOpeningProfile": set_profile_shape,
    }
    opening_readback_verified = all(
        shape["verified"] for shape in opening_readback_shapes.values())
    required_methods = [
        "AddDoor", "GetProductStyle", "IsDoor", "IsWall",
        "GetOpeningPosition", "GetOpeningRotation",
        "GetOpeningProfile", "GetOpeningHost",
        "GetOpeningStyleSizeProfiles", "IsOpeningStyleSizeProfile",
        "GetOpeningStyleFromSizeProfile", "SetOpeningProfile",
        "GetWallHeight", "GetWallThickness", "GetWallPathCurve",
    ]
    missing_methods = [
        method_name for method_name in required_methods
        if not va_method_available(method_name)
    ]
    host_methods = [
        method_name for method_name in
        ["GetOpeningHost", "GetDoorHostId", "GetDoorWallId"]
        if va_method_available(method_name)
    ]
    if not host_methods:
        missing_methods.append(
            "GetOpeningHost OR GetDoorHostId OR GetDoorWallId")
    if dimensions_requested and (
            not rectangular_classifier_shape["verified"] or
            not rectangular_size_shape["verified"]):
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": "door_size_profile_readback_unsupported",
            "message": (
                "Requested door dimensions require an existing rectangular "
                "Opening Size Profile with exact size readback"),
            "requested_dimensions": {
                "width": requested_width, "height": requested_height},
            "rectangular_classifier_shape":
                rectangular_classifier_shape,
            "rectangular_size_shape": rectangular_size_shape,
        }
    elif missing_methods:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "message": "VisualARQ door API cannot satisfy verified creation",
            "missing_methods": missing_methods,
        }
    elif not opening_readback_verified:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": "door_readback_signature_unverified",
            "message": (
                "VisualARQ opening position/rotation/profile/host getters "
                "do not have unique supported CLR signatures"),
            "readback_shapes": opening_readback_shapes,
        }
    elif not point_placement_api:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "reason": "door_add_signature_unverified",
            "message": (
                "VisualARQ AddDoor has no unique supported point-placement "
                "CLR signature; no door was created. Legacy wall-position "
                "semantics are deliberately unsupported."),
            "modern_shape": door_modern_shape,
        }
    elif point_placement_api and not params.get("point"):
        result = {
            "status": "error", "code": "INVALID_PARAMS",
            "message": (
                "This VisualARQ version places doors by 3D point - "
                "pass point=[x,y,z] on the wall axis"),
        }
    else:
        def door_instance_placement(obj):
            placement = {
                "readback_complete": False,
                "source": "Rhino InstanceXform",
                "point": None,
                "rotation_degrees": None,
                "error": None,
            }
            try:
                xform = obj.InstanceXform
                origin = xform * rg.Point3d.Origin
                x_axis = xform * rg.Vector3d.XAxis
                planar_length = math.sqrt(
                    x_axis.X * x_axis.X + x_axis.Y * x_axis.Y)
                if not origin.IsValid or planar_length <= 1e-12:
                    raise Exception(
                        "InstanceXform has invalid origin or planar X axis")
                angle = math.degrees(math.atan2(x_axis.Y, x_axis.X))
                if angle < 0.0:
                    angle += 360.0
                placement.update({
                    "readback_complete": True,
                    "point": [origin.X, origin.Y, origin.Z],
                    "rotation_degrees": angle,
                })
            except Exception as placement_error:
                placement["error"] = va_text(placement_error)
            return placement

        style_profile_ids_before = []
        style_profile_inventory_error = None
        try:
            style_profile_ids_before = list(
                va.GetOpeningStyleSizeProfiles(style_id) or [])
            style_profile_texts = [
                str(profile_id) for profile_id in style_profile_ids_before]
            if not style_profile_ids_before:
                raise Exception("door style has no Size Profiles")
            if len(style_profile_texts) != len(set(style_profile_texts)):
                raise Exception(
                    "door style Size Profile inventory has duplicate Guids")
            if any(profile_id == Guid.Empty
                   for profile_id in style_profile_ids_before):
                raise Exception(
                    "door style Size Profile inventory has an empty Guid")
        except Exception as error:
            style_profile_inventory_error = va_text(error)
        profile_snapshots_before = [
            va_opening_profile_snapshot(style_id, profile_id)
            for profile_id in style_profile_ids_before]
        selected_profile_id = Guid.Empty
        matching_profile_ids = []
        if dimensions_requested and style_profile_inventory_error is None:
            tolerance = float(sc.doc.ModelAbsoluteTolerance)
            for profile_snapshot in profile_snapshots_before:
                profile_dimensions = profile_snapshot.get("dimensions")
                if profile_snapshot.get("readback_complete") is not True or \
                        profile_snapshot.get("rectangular") is not True or \
                        profile_dimensions is None:
                    continue
                width_matches = requested_width is None or abs(
                    profile_dimensions["width"] - requested_width
                ) <= tolerance
                height_matches = requested_height is None or abs(
                    profile_dimensions["height"] - requested_height
                ) <= tolerance
                if width_matches and height_matches:
                    matching_profile_ids.append(
                        Guid(profile_snapshot["id"]))
            if len(matching_profile_ids) == 1:
                selected_profile_id = matching_profile_ids[0]

        next_runtime_serial_before = int(
            Rhino.DocObjects.RhinoObject.NextRuntimeSerialNumber)
        object_ids_before = set(str(obj.Id) for obj in sc.doc.Objects)

        def door_host_wall_state(wall_obj):
            errors = []
            geometry_crc = None
            bbox_values = None
            style_text = None
            height_value = None
            thickness_value = None
            path_values = None
            outer_attributes = None
            try:
                geometry = wall_obj.Geometry
                geometry_crc = int(geometry.DataCRC(System.UInt32(0)))
                bbox = geometry.GetBoundingBox(True)
                if not bbox.IsValid:
                    raise Exception("host wall bounding box is invalid")
                bbox_values = {
                    "min": [bbox.Min.X, bbox.Min.Y, bbox.Min.Z],
                    "max": [bbox.Max.X, bbox.Max.Y, bbox.Max.Z],
                }
            except Exception as error:
                errors.append({
                    "stage": "geometry_state", "error": va_text(error)})
            try:
                outer_attributes = va_object_attributes_fingerprint(
                    wall_obj.Attributes)
            except Exception as error:
                errors.append({
                    "stage": "outer_attributes", "error": va_text(error)})
            try:
                candidate_style_id = va.GetProductStyle(wall_obj.Id)
                if candidate_style_id is None or \
                        candidate_style_id == Guid.Empty:
                    raise Exception("host wall style Guid is empty")
                style_text = str(candidate_style_id)
            except Exception as error:
                errors.append({
                    "stage": "style", "error": va_text(error)})
            try:
                height_value = va_valid_double(
                    va.GetWallHeight(wall_obj.Id))
                thickness_value = va_valid_double(
                    va.GetWallThickness(wall_obj.Id))
                if height_value is None or thickness_value is None:
                    raise Exception(
                        "host height or thickness is invalid/unset")
            except Exception as error:
                errors.append({
                    "stage": "wall_dimensions", "error": va_text(error)})
            try:
                path = va.GetWallPathCurve(wall_obj.Id)
                if path is None or not path.IsValid:
                    raise Exception("host wall path is invalid")
                path_values = {
                    "start": va_point(path.PointAtStart),
                    "end": va_point(path.PointAtEnd),
                    "length": float(path.GetLength()),
                    "type": str(path.GetType().FullName),
                }
            except Exception as error:
                errors.append({
                    "stage": "wall_path", "error": va_text(error)})
            quantity = va_instance_definition_volume_snapshot(wall_obj)
            definition_fingerprint = quantity.get("definition_fingerprint")
            if definition_fingerprint is None or \
                    definition_fingerprint.get("complete") is not True:
                errors.append({
                    "stage": "definition_fingerprint",
                    "error": (
                        "host wall instance-definition fingerprint is "
                        "incomplete"),
                    "fingerprint_errors": definition_fingerprint.get(
                        "errors") if definition_fingerprint is not None
                        else None,
                })
            if quantity.get("measurement_complete") is not True or \
                    quantity.get("volume_verified") is not True or \
                    quantity.get("volume") is None:
                errors.append({
                    "stage": "host_volume",
                    "error": "host wall solid volume is not verified",
                    "quantity_errors": quantity.get("errors"),
                })
            return {
                "id": str(wall_obj.Id),
                "runtime_serial_number": int(
                    wall_obj.RuntimeSerialNumber),
                "geometry_crc": geometry_crc,
                "outer_attributes": outer_attributes,
                "bbox": bbox_values,
                "style_id": style_text,
                "height": height_value,
                "thickness": thickness_value,
                "path": path_values,
                "volume": quantity.get("volume"),
                "volume_source": quantity.get("source"),
                "quantity": quantity,
                "definition_fingerprint": definition_fingerprint,
                "readback_complete": not errors,
                "readback_errors": errors,
            }

        def door_host_wall_semantics_match(
                before_state, after_state, tolerance):
            if before_state is None or after_state is None or \
                    before_state.get("readback_complete") is not True or \
                    after_state.get("readback_complete") is not True:
                return False
            if before_state.get("id") != after_state.get("id") or \
                    before_state.get("style_id") != \
                        after_state.get("style_id") or \
                    before_state.get("outer_attributes") != \
                        after_state.get("outer_attributes"):
                return False
            for field in ["height", "thickness"]:
                if before_state.get(field) is None or \
                        after_state.get(field) is None or abs(
                            before_state[field] - after_state[field]
                        ) > tolerance:
                    return False
            before_path = before_state.get("path")
            after_path = after_state.get("path")
            if before_path is None or after_path is None or \
                    before_path.get("type") != after_path.get("type") or \
                    abs(before_path["length"] - after_path["length"]) > \
                        tolerance:
                return False
            for key in ["start", "end"]:
                if rg.Point3d(*before_path[key]).DistanceTo(
                        rg.Point3d(*after_path[key])) > tolerance:
                    return False
            before_bbox = before_state.get("bbox")
            after_bbox = after_state.get("bbox")
            if before_bbox is None or after_bbox is None:
                return False
            for key in ["min", "max"]:
                if rg.Point3d(*before_bbox[key]).DistanceTo(
                        rg.Point3d(*after_bbox[key])) > tolerance:
                    return False
            return True

        def door_host_wall_state_matches(before_state, after_state, tolerance):
            return door_host_wall_semantics_match(
                before_state, after_state, tolerance) and \
                va_instance_definition_fingerprints_match(
                    before_state.get("definition_fingerprint"),
                    after_state.get("definition_fingerprint"))

        # Keep one operational implementation for the initial command and
        # the bounded cross-command materialization readback.
        door_host_wall_state = va_opening_host_wall_state
        door_host_wall_semantics_match = \
            va_opening_host_wall_semantics_match
        door_host_wall_state_matches = \
            va_opening_host_wall_state_matches

        wall_states_before = {}
        wall_inventory_errors = []
        candidate_wall_objects = []
        spatial_wall_probes = []
        active_wall_ids = []
        requested_wall_id = Guid(params["wall_id"]) \
            if params.get("wall_id") is not None else Guid.Empty
        placement_point = rg.Point3d(
            params["point"][0], params["point"][1], params["point"][2])

        def door_wall_spatial_probe(wall_obj, point, tolerance):
            probe = {
                "wall_id": str(wall_obj.Id),
                "complete": False,
                "candidate": False,
                "bbox_contains": None,
                "planar_bbox_contains": None,
                "vertical_within_host": None,
                "path_distance": None,
                "path_distance_semantics": "planar_xy",
                "planar_path_distance": None,
                "vertical_offset_from_path": None,
                "maximum_path_distance": None,
                "error": None,
            }
            try:
                geometry = wall_obj.Geometry
                bbox = geometry.GetBoundingBox(True) \
                    if geometry is not None else rg.BoundingBox.Empty
                if not bbox.IsValid:
                    raise Exception("wall bounding box is invalid")
                planar_bbox_contains = \
                    bbox.Min.X - tolerance <= point.X <= \
                        bbox.Max.X + tolerance and \
                    bbox.Min.Y - tolerance <= point.Y <= \
                        bbox.Max.Y + tolerance
                vertical_within_host = \
                    bbox.Min.Z - tolerance <= point.Z <= \
                        bbox.Max.Z + tolerance
                bbox_contains = bool(
                    planar_bbox_contains and vertical_within_host)
                path = va.GetWallPathCurve(wall_obj.Id)
                if path is None or not path.IsValid:
                    raise Exception("wall path is invalid")
                closest_result = path.ClosestPoint(point)
                if closest_result is None or len(closest_result) != 2 or \
                        not bool(closest_result[0]):
                    raise Exception("wall path closest-point query failed")
                closest_point = path.PointAt(float(closest_result[1]))
                # Opening elevations are measured from the wall baseline.
                # Host proximity therefore uses the document XY projection;
                # a 3-D distance would reject every elevated window.
                delta_x = float(closest_point.X - point.X)
                delta_y = float(closest_point.Y - point.Y)
                planar_path_distance = float(
                    (delta_x * delta_x + delta_y * delta_y) ** 0.5)
                vertical_offset_from_path = float(
                    point.Z - closest_point.Z)
                thickness = va_valid_double(
                    va.GetWallThickness(wall_obj.Id))
                if thickness is None or thickness <= 0.0:
                    raise Exception("wall thickness is invalid or unset")
                maximum_path_distance = max(
                    thickness * 0.5, tolerance) + tolerance
                probe.update({
                    "complete": True,
                    "candidate": bool(
                        bbox_contains and
                        planar_path_distance <= maximum_path_distance),
                    "bbox_contains": bool(bbox_contains),
                    "planar_bbox_contains": bool(planar_bbox_contains),
                    "vertical_within_host": bool(vertical_within_host),
                    # Keep the legacy field while making its meaning exact.
                    "path_distance": planar_path_distance,
                    "planar_path_distance": planar_path_distance,
                    "vertical_offset_from_path": vertical_offset_from_path,
                    "maximum_path_distance": maximum_path_distance,
                })
            except Exception as error:
                probe["error"] = va_text(error)
            return probe

        spatial_tolerance = float(sc.doc.ModelAbsoluteTolerance)
        # `wall_id` is not an AddDoor argument. Always scan every active wall
        # so overlapping spatial candidates all have a pre-mutation baseline.
        for candidate_obj in sc.doc.Objects:
            try:
                if not va.IsWall(candidate_obj.Id):
                    continue
                active_wall_ids.append(str(candidate_obj.Id))
                probe = door_wall_spatial_probe(
                    candidate_obj, placement_point, spatial_tolerance)
                spatial_wall_probes.append(probe)
                if probe["complete"] is not True:
                    wall_inventory_errors.append({
                        "object_id": str(candidate_obj.Id),
                        "stage": "spatial_probe",
                        "error": probe["error"],
                    })
                elif probe["candidate"] is True:
                    candidate_wall_objects.append(candidate_obj)
            except Exception as error:
                wall_inventory_errors.append({
                    "object_id": str(candidate_obj.Id),
                    "stage": "wall_classification",
                    "error": va_text(error),
                })
        for candidate_obj in candidate_wall_objects:
            state = door_host_wall_state(candidate_obj)
            wall_states_before[state["id"]] = state
        spatial_candidate_ids = sorted(wall_states_before)
        requested_wall_valid = requested_wall_id == Guid.Empty or \
            str(requested_wall_id) in active_wall_ids
        requested_wall_contains_point = requested_wall_id == Guid.Empty or \
            str(requested_wall_id) in spatial_candidate_ids
        spatial_host_scan_complete = not wall_inventory_errors
        spatial_host_baseline_complete = \
            spatial_host_scan_complete and bool(wall_states_before) and all(
                state.get("readback_complete") is True
                for state in wall_states_before.values())

        def new_door_candidates():
            candidates = []
            errors = []
            active_generations = []
            try:
                recent = sc.doc.Objects.AllObjectsSince(
                    max(next_runtime_serial_before - 1, 0)) or []
                for recent_obj in recent:
                    current_obj = sc.doc.Objects.FindId(recent_obj.Id)
                    if current_obj is None or int(
                            current_obj.RuntimeSerialNumber) != int(
                                recent_obj.RuntimeSerialNumber):
                        continue
                    active_generations.append({
                        "id": str(current_obj.Id),
                        "runtime_serial_number": int(
                            current_obj.RuntimeSerialNumber),
                        "object_type": str(current_obj.GetType().FullName),
                    })
                    try:
                        if va.IsDoor(current_obj.Id):
                            candidate_style_id = va.GetProductStyle(
                                current_obj.Id)
                            if candidate_style_id == style_id:
                                candidates.append({
                                    "id": str(current_obj.Id),
                                    "runtime_serial_number": int(
                                        current_obj.RuntimeSerialNumber),
                                    "style_id": str(candidate_style_id),
                                })
                    except Exception as candidate_error:
                        errors.append({
                            "id": str(current_obj.Id),
                            "error": va_text(candidate_error),
                        })
            except Exception as scan_error:
                errors.append({
                    "stage": "AllObjectsSince", "error": va_text(scan_error)})
            return candidates, errors, active_generations

        door_id = Guid.Empty
        adddoor_returned_empty_guid = False
        created_runtime_serial = None
        final_runtime_serial = None
        returned_guid_was_preexisting = False
        creation_checks = None
        actual_dimensions = {}
        dimension_sources = {}
        host = None
        host_state_before = None
        host_state_after = None
        host_cut_volume_delta = None
        product_snapshot = None
        actual_style_id = Guid.Empty
        actual_profile_snapshot = None
        profile_set_result = None
        creation_failure_code = None
        creation_failure_reason = None
        mutation_started = False
        materialization_pending = False
        opening_host_text = None
        opening_host_in_preadd_baseline = None
        try:
            if style_profile_inventory_error is not None or any(
                    snapshot.get("readback_complete") is not True
                    for snapshot in profile_snapshots_before):
                creation_failure_code = "VERIFICATION_FAILED"
                creation_failure_reason = \
                    "door_style_profile_inventory_unverified"
                raise Exception(
                    style_profile_inventory_error or
                    "door style Size Profile readback is incomplete")
            if dimensions_requested and len(matching_profile_ids) == 0:
                creation_failure_code = "INVALID_PARAMS"
                creation_failure_reason = \
                    "matching_door_size_profile_not_found"
                raise Exception(
                    "No existing rectangular door Size Profile matches the "
                    "requested dimensions")
            if dimensions_requested and len(matching_profile_ids) > 1:
                creation_failure_code = "AMBIGUOUS_REFERENCE"
                creation_failure_reason = \
                    "matching_door_size_profile_ambiguous"
                raise Exception(
                    "Multiple door Size Profiles match the requested "
                    "dimensions")
            if requested_wall_id != Guid.Empty and not requested_wall_valid:
                creation_failure_code = "INVALID_ID"
                creation_failure_reason = "requested_wall_invalid"
                raise Exception(
                    "Requested wall does not exist or is not a wall")
            if requested_wall_id != Guid.Empty and \
                    not requested_wall_contains_point:
                creation_failure_code = "INVALID_PARAMS"
                creation_failure_reason = \
                    "requested_wall_does_not_contain_point"
                raise Exception(
                    "Requested wall is not a complete spatial host candidate "
                    "for the placement point")
            if wall_inventory_errors or not spatial_host_scan_complete:
                creation_failure_code = "VERIFICATION_FAILED"
                creation_failure_reason = \
                    "candidate_host_wall_inventory_unverified"
                raise Exception(
                    "Candidate host-wall inventory has readback errors")
            if not wall_states_before:
                creation_failure_code = "INVALID_PARAMS"
                creation_failure_reason = "no_candidate_host_wall"
                raise Exception(
                    "No host-wall bounding box contains the requested point")
            if not spatial_host_baseline_complete or any(
                    state.get("readback_complete") is not True
                    for state in wall_states_before.values()):
                creation_failure_code = "VERIFICATION_FAILED"
                creation_failure_reason = \
                    "candidate_host_wall_state_unverified"
                raise Exception(
                    "Candidate host-wall state is not completely readable")
            p = params["point"]
            mutation_started = True
            returned_door_id = va.AddDoor(
                style_id,
                rg.Point3d(p[0], p[1], p[2]),
                math.radians(params.get("rotation") or 0.0))
            if returned_door_id is None or returned_door_id == Guid.Empty:
                door_id = Guid.Empty
                adddoor_returned_empty_guid = True
                creation_failure_reason = \
                    "adddoor_returned_empty_guid_ownership_unprovable"
                raise Exception("AddDoor returned empty Guid")
            door_id = returned_door_id
            returned_guid_was_preexisting = \
                str(door_id) in object_ids_before
            if returned_guid_was_preexisting:
                raise Exception("AddDoor returned a pre-existing object Guid")
            initial_obj = sc.doc.Objects.FindId(door_id)
            if initial_obj is None:
                materialization_pending = True
                creation_failure_reason = \
                    "door_materialization_pending_after_add"
                raise Exception("Created door is not readable in the document")
            candidate_runtime_serial = int(initial_obj.RuntimeSerialNumber)
            if candidate_runtime_serial < next_runtime_serial_before:
                raise Exception(
                    "AddDoor returned a pre-existing object generation")
            created_runtime_serial = candidate_runtime_serial

            applied_dimensions = {}
            if selected_profile_id != Guid.Empty:
                profile_set_result = bool(
                    va.SetOpeningProfile(door_id, selected_profile_id))
                selected_profile_snapshot = next(
                    snapshot for snapshot in profile_snapshots_before
                    if snapshot["id"] == str(selected_profile_id))
                applied_dimensions = dict(
                    selected_profile_snapshot["dimensions"])

            # Setters may replace a VisualARQ-backed Rhino object. Refetch and
            # prove that the same object generation survived before readback.
            final_obj = sc.doc.Objects.FindId(door_id)
            if final_obj is None:
                raise Exception("Created door disappeared after mutation")
            final_runtime_serial = int(final_obj.RuntimeSerialNumber)
            if final_runtime_serial != created_runtime_serial:
                raise Exception(
                    "Created door was replaced during profile mutation")

            classification_probe = va_object_classification_probe(door_id)
            product_snapshot = va_product_snapshot(
                final_obj, classification_probe, False, True)
            actual_style_id = va.GetProductStyle(door_id)
            opening_position = va.GetOpeningPosition(door_id)
            opening_rotation_radians = va_valid_double(
                va.GetOpeningRotation(door_id))
            opening_profile_id = va.GetOpeningProfile(door_id)
            opening_host_id = va.GetOpeningHost(door_id)
            opening_host_text = str(opening_host_id) \
                if opening_host_id is not None and \
                    opening_host_id != Guid.Empty else None
            opening_host_in_preadd_baseline = \
                opening_host_text is not None and \
                spatial_host_baseline_complete and \
                opening_host_text in wall_states_before and \
                wall_states_before[opening_host_text].get(
                    "readback_complete") is True
            actual_profile_snapshot = va_opening_profile_snapshot(
                style_id, opening_profile_id) \
                if opening_profile_id is not None and \
                    opening_profile_id != Guid.Empty else None
            if actual_profile_snapshot is not None and \
                    actual_profile_snapshot.get("dimensions") is not None:
                actual_dimensions = dict(
                    actual_profile_snapshot["dimensions"])
                dimension_sources = {
                    "width": "GetRectangularProfileSize",
                    "height": "GetRectangularProfileSize",
                }

            host_readbacks = [{
                "source": "GetOpeningHost", "id": opening_host_text,
                "error": None,
            }]
            valid_host_ids = [opening_host_id] \
                if opening_host_text is not None else []
            for host_method in host_methods:
                if host_method == "GetOpeningHost":
                    continue
                try:
                    candidate_host_id = getattr(va, host_method)(door_id)
                    candidate_text = str(candidate_host_id) \
                        if candidate_host_id is not None and \
                            candidate_host_id != Guid.Empty else None
                    host_readbacks.append({
                        "source": host_method, "id": candidate_text,
                        "error": None,
                    })
                    if candidate_host_id is not None and \
                            candidate_host_id != Guid.Empty:
                        valid_host_ids.append(candidate_host_id)
                except Exception as host_error:
                    host_readbacks.append({
                        "source": host_method, "id": None,
                        "error": va_text(host_error),
                    })
            unique_host_texts = sorted(set(
                str(candidate_id) for candidate_id in valid_host_ids))
            # GetOpeningHost is authoritative. Legacy getters are consistency
            # diagnostics and can never select a different cleanup target.
            host_id = opening_host_id \
                if opening_host_text is not None else Guid.Empty
            matching_sources = [
                item["source"] for item in host_readbacks
                if item["id"] is not None and
                item["id"] in unique_host_texts
            ]
            host = {
                "id": str(host_id) if host_id != Guid.Empty else None,
                "source": "GetOpeningHost"
                    if opening_host_text is not None else None,
                "sources": matching_sources,
                "readbacks": host_readbacks,
                "unique_valid_ids": unique_host_texts,
                "sources_agree": len(unique_host_texts) == 1,
                "in_preadd_baseline": opening_host_in_preadd_baseline,
            }
            host_object = sc.doc.Objects.FindId(host_id) \
                if host_id != Guid.Empty else None
            host_classified_as_wall = host_object is not None and \
                bool(va.IsWall(host_id))
            host_state_before = wall_states_before.get(str(host_id)) \
                if host_id != Guid.Empty else None
            host_state_after = door_host_wall_state(host_object) \
                if host_classified_as_wall else None
            tolerance = float(sc.doc.ModelAbsoluteTolerance)
            host_semantics_stable = door_host_wall_semantics_match(
                host_state_before, host_state_after, tolerance)
            host_definition_changed = \
                host_state_before is not None and \
                host_state_after is not None and \
                host_state_before.get("definition_fingerprint") is not None and \
                host_state_after.get("definition_fingerprint") is not None and \
                host_state_before["definition_fingerprint"].get(
                    "complete") is True and \
                host_state_after["definition_fingerprint"].get(
                    "complete") is True and not \
                va_instance_definition_fingerprints_match(
                    host_state_before["definition_fingerprint"],
                    host_state_after["definition_fingerprint"])
            if host_state_before is not None and \
                    host_state_before.get("volume") is not None and \
                    host_state_after is not None and \
                    host_state_after.get("volume") is not None:
                host_cut_volume_delta = \
                    host_state_before["volume"] - host_state_after["volume"]
            placement = door_instance_placement(final_obj)
            expected_point = rg.Point3d(
                params["point"][0], params["point"][1], params["point"][2])
            opening_position_matches = opening_position is not None and \
                opening_position.IsValid and \
                opening_position.DistanceTo(expected_point) <= tolerance
            instance_point_matches = \
                placement["readback_complete"] and \
                rg.Point3d(*placement["point"]).DistanceTo(
                    expected_point) <= tolerance
            requested_rotation_degrees = float(
                params.get("rotation") or 0.0) % 360.0
            actual_rotation_degrees = math.degrees(
                opening_rotation_radians) % 360.0 \
                if opening_rotation_radians is not None else None
            rotation_delta_degrees = None
            if actual_rotation_degrees is not None:
                rotation_delta_degrees = abs(
                    (actual_rotation_degrees - requested_rotation_degrees +
                     180.0) % 360.0 - 180.0)
            rotation_matches = rotation_delta_degrees is not None and \
                rotation_delta_degrees <= 1e-4
            instance_rotation_degrees = placement.get("rotation_degrees")
            instance_rotation_delta_degrees = None
            if instance_rotation_degrees is not None:
                instance_rotation_delta_degrees = abs(
                    (instance_rotation_degrees - requested_rotation_degrees +
                     180.0) % 360.0 - 180.0)
            width_matches = requested_width is None or (
                actual_dimensions.get("width") is not None and
                abs(actual_dimensions["width"] - requested_width) <= tolerance)
            height_matches = requested_height is None or (
                actual_dimensions.get("height") is not None and
                abs(actual_dimensions["height"] - requested_height) <= tolerance)
            expected_host_id = Guid.Empty
            if params.get("wall_id") is not None:
                expected_host_id = Guid(params["wall_id"])
            host_matches = host_id != Guid.Empty and (
                expected_host_id == Guid.Empty or host_id == expected_host_id)
            profile_id = str(opening_profile_id) \
                if opening_profile_id is not None and \
                    opening_profile_id != Guid.Empty else None
            style_profile_inventory_after_error = None
            style_profile_ids_after = []
            try:
                style_profile_ids_after = list(
                    va.GetOpeningStyleSizeProfiles(style_id) or [])
            except Exception as error:
                style_profile_inventory_after_error = va_text(error)
            style_profile_inventory_unchanged = \
                style_profile_inventory_after_error is None and \
                [str(value) for value in style_profile_ids_after] == \
                [str(value) for value in style_profile_ids_before]
            profile_in_style_inventory = opening_profile_id in \
                style_profile_ids_before \
                if opening_profile_id is not None else False
            profile_matches_selected = selected_profile_id == Guid.Empty or \
                opening_profile_id == selected_profile_id
            profile_set_persisted = selected_profile_id == Guid.Empty or \
                opening_profile_id == selected_profile_id
            geometry = product_snapshot.get("geometry") \
                if product_snapshot is not None else None
            host_cut_verified = \
                host_semantics_stable and host_definition_changed
            post_readback_obj = sc.doc.Objects.FindId(door_id)
            final_runtime_serial = int(
                post_readback_obj.RuntimeSerialNumber) \
                if post_readback_obj is not None else None
            creation_checks = {
                "object_readable": post_readback_obj is not None,
                "runtime_serial_stable": (
                    final_runtime_serial == created_runtime_serial),
                "classified_as_door": bool(va.IsDoor(door_id)),
                "product_readback_complete": product_snapshot is not None and \
                    product_snapshot.get("readback_complete") is True,
                "style_matches": actual_style_id == style_id,
                "geometry_valid": geometry is not None and \
                    geometry.get("is_valid") is True,
                "bbox_nondegenerate": geometry is not None and \
                    geometry.get("bbox_valid") is True and \
                    geometry.get("bbox_diagonal") is not None and \
                    geometry["bbox_diagonal"] > tolerance,
                "profile_readable": profile_id is not None,
                "profile_readback_complete":
                    actual_profile_snapshot is not None and \
                    actual_profile_snapshot.get(
                        "readback_complete") is True,
                "profile_in_style_inventory": profile_in_style_inventory,
                "profile_matches_selected": profile_matches_selected,
                "profile_set_persisted": profile_set_persisted,
                "style_profile_inventory_unchanged":
                    style_profile_inventory_unchanged,
                "profile_matches_product_readback":
                    product_snapshot is not None and \
                    product_snapshot.get("profile_id") == profile_id,
                "spatial_host_baseline_complete":
                    spatial_host_baseline_complete,
                "opening_host_nonempty": opening_host_text is not None,
                "opening_host_in_preadd_baseline":
                    opening_host_in_preadd_baseline is True,
                "host_readable": host["id"] is not None,
                "host_sources_agree": len(unique_host_texts) == 1,
                "host_matches_exact_getter":
                    opening_host_id == host_id and host_id != Guid.Empty,
                "host_matches_expected": host_matches,
                "host_object_exists": host_object is not None,
                "host_classified_as_wall": host_classified_as_wall,
                "host_baseline_readable": host_state_before is not None and \
                    host_state_before.get("readback_complete") is True and \
                    not wall_inventory_errors,
                "host_after_readable": host_state_after is not None and \
                    host_state_after.get("readback_complete") is True,
                "host_definition_changed": host_definition_changed,
                "host_cut_independently_verified": host_cut_verified,
                "opening_position_matches": opening_position_matches,
                "rotation_matches": rotation_matches,
                "width_matches": width_matches,
                "height_matches": height_matches,
            }
            if not all(creation_checks.values()):
                failed_checks = [
                    name for name, passed in creation_checks.items()
                    if not passed
                ]
                creation_failure_code = "VERIFICATION_FAILED"
                creation_failure_reason = "door_readback_verification_failed"
                raise Exception(
                    "Door readback verification failed: " +
                    ", ".join(failed_checks))
            result = {
                "status": "success", "door_id": str(door_id),
                "style": params["style"], "style_id": str(style_id),
                "actual_style_id": str(actual_style_id),
                "requested_point": params.get("point"),
                "requested_rotation_degrees": params.get("rotation"),
                "requested_position": params.get("position"),
                "wall_id": params.get("wall_id"), "host": host,
                "product": product_snapshot,
                "profile_id": profile_id,
                "selected_profile_id": str(selected_profile_id) \
                    if selected_profile_id != Guid.Empty else None,
                "profile_set_result": profile_set_result,
                "profile": actual_profile_snapshot,
                "style_profiles_before": profile_snapshots_before,
                "style_profile_inventory_after_error":
                    style_profile_inventory_after_error,
                "host_wall_before": host_state_before,
                "host_wall_after": host_state_after,
                "spatial_host_scan_complete": spatial_host_scan_complete,
                "spatial_host_baseline_complete":
                    spatial_host_baseline_complete,
                "spatial_candidate_ids": spatial_candidate_ids,
                "spatial_wall_probes": spatial_wall_probes,
                "opening_host_in_preadd_baseline":
                    opening_host_in_preadd_baseline,
                "host_semantics_stable": host_semantics_stable,
                "host_definition_changed": host_definition_changed,
                "host_cut_volume_delta": host_cut_volume_delta,
                "actual_placement": placement,
                "placement_verification": {
                    "expected_point": [
                        expected_point.X, expected_point.Y, expected_point.Z],
                    "opening_position": [
                        opening_position.X, opening_position.Y,
                        opening_position.Z],
                    "point_matches": opening_position_matches,
                    "instance_point_matches": instance_point_matches,
                    "rotation_applicable": True,
                    "requested_rotation_degrees":
                        requested_rotation_degrees,
                    "actual_rotation_degrees": actual_rotation_degrees,
                    "rotation_delta_degrees": rotation_delta_degrees,
                    "rotation_matches": rotation_matches,
                    "instance_rotation_degrees":
                        instance_rotation_degrees,
                    "instance_rotation_delta_degrees":
                        instance_rotation_delta_degrees,
                },
                "requested_dimensions": {
                    "width": requested_width, "height": requested_height},
                "applied_dimensions": applied_dimensions,
                "actual_dimensions": actual_dimensions,
                "dimension_sources": dimension_sources,
                "verification": {
                    "pass": True, "creation_checks": creation_checks,
                    "tolerance": tolerance,
                    "source": "VisualARQ.Script and Rhino document readback",
                },
                "runtime_serial_number": final_runtime_serial,
            }
        except Exception as creation_error:
            cleanup_deleted = None
            cleanup_object_exists = None
            cleanup_is_door = None
            cleanup_actual_runtime_serial = None
            cleanup_runtime_serial_matches = None
            cleanup_replacement_detected = False
            recovered_door_id = None
            recovered_runtime_serial = None
            cleanup_host_id = opening_host_text
            cleanup_host_was_in_preadd_baseline = \
                opening_host_in_preadd_baseline is True
            if cleanup_host_id is None and door_id != Guid.Empty and \
                    not returned_guid_was_preexisting:
                try:
                    candidate_host_id = va.GetOpeningHost(door_id)
                    cleanup_host_id = str(candidate_host_id) \
                        if candidate_host_id is not None and \
                            candidate_host_id != Guid.Empty else None
                    cleanup_host_was_in_preadd_baseline = \
                        cleanup_host_id is not None and \
                        spatial_host_baseline_complete and \
                        cleanup_host_id in wall_states_before and \
                        wall_states_before[cleanup_host_id].get(
                            "readback_complete") is True
                except Exception:
                    pass
            cleanup_host_baseline = wall_states_before.get(cleanup_host_id) \
                if cleanup_host_id is not None else None
            cleanup_host_state = None
            host_cleanup_verified = None
            candidates, candidate_errors, active_generations = \
                new_door_candidates()
            cleanup_target_id = door_id
            cleanup_target_serial = created_runtime_serial
            cleanup_refused_reason = None
            if materialization_pending:
                cleanup_target_id = Guid.Empty
                cleanup_refused_reason = \
                    "deferred_materialization_requires_read_only_followup"
            elif adddoor_returned_empty_guid:
                if len(candidates) == 1 and not candidate_errors:
                    recovered_door_id = candidates[0]["id"]
                    recovered_runtime_serial = \
                        candidates[0]["runtime_serial_number"]
                cleanup_refused_reason = \
                    "adddoor_returned_empty_guid_ownership_unprovable"
            elif cleanup_target_id != Guid.Empty and \
                    cleanup_target_serial is None and \
                    not returned_guid_was_preexisting:
                matching_candidates = [
                    candidate for candidate in candidates
                    if candidate["id"] == str(cleanup_target_id)]
                if len(matching_candidates) == 1 and not candidate_errors:
                    cleanup_target_serial = \
                        matching_candidates[0]["runtime_serial_number"]
            elif returned_guid_was_preexisting:
                cleanup_refused_reason = \
                    "returned_guid_existed_before_adddoor"
            cleanup_verified = False
            if cleanup_target_id != Guid.Empty and \
                    cleanup_target_serial is not None:
                try:
                    cleanup_obj = sc.doc.Objects.FindId(cleanup_target_id)
                    cleanup_actual_runtime_serial = int(
                        cleanup_obj.RuntimeSerialNumber) \
                        if cleanup_obj is not None else None
                    cleanup_runtime_serial_matches = cleanup_obj is None or (
                        cleanup_target_serial is not None and
                        cleanup_actual_runtime_serial == cleanup_target_serial)
                    cleanup_replacement_detected = \
                        cleanup_runtime_serial_matches is False
                    if cleanup_obj is not None and \
                            cleanup_runtime_serial_matches:
                        cleanup_deleted = bool(
                            sc.doc.Objects.Delete(cleanup_target_id, True))
                    else:
                        cleanup_deleted = False
                    cleanup_object_exists = \
                        sc.doc.Objects.FindId(cleanup_target_id) is not None
                except Exception:
                    cleanup_deleted = False
                    cleanup_verified = False
                try:
                    cleanup_is_door = bool(va.IsDoor(cleanup_target_id))
                except Exception:
                    pass
                cleanup_verified = cleanup_object_exists is False and \
                    cleanup_runtime_serial_matches is not False and \
                    cleanup_is_door is False
            residual_candidates, residual_errors, residual_generations = \
                new_door_candidates()
            if residual_generations or residual_errors:
                cleanup_verified = False
            host_cleanup_results = []
            if mutation_started:
                cleanup_tolerance = float(sc.doc.ModelAbsoluteTolerance)
                for baseline_id in sorted(wall_states_before):
                    baseline_state = wall_states_before[baseline_id]
                    current_state = None
                    state_error = None
                    state_matches = False
                    try:
                        current_obj = sc.doc.Objects.FindId(Guid(baseline_id))
                        if current_obj is None or \
                                not va.IsWall(current_obj.Id):
                            raise Exception(
                                "candidate host wall disappeared or was "
                                "reclassified")
                        current_state = door_host_wall_state(current_obj)
                        state_matches = door_host_wall_state_matches(
                            baseline_state, current_state, cleanup_tolerance)
                    except Exception as error:
                        state_error = va_text(error)
                    host_cleanup_results.append({
                        "wall_id": baseline_id,
                        "baseline": baseline_state,
                        "actual": current_state,
                        "state_matches": state_matches,
                        "error": state_error,
                    })
                host_cleanup_verified = bool(host_cleanup_results) and all(
                    item["state_matches"] for item in host_cleanup_results) and \
                    spatial_host_baseline_complete and \
                    cleanup_host_was_in_preadd_baseline
            else:
                # Preflight failed before AddDoor; no host mutation was called.
                host_cleanup_verified = True
                cleanup_verified = True
            cleanup_verified = cleanup_verified and \
                host_cleanup_verified is True and \
                not adddoor_returned_empty_guid
            if cleanup_host_id is not None:
                matching_host_result = next(
                    (item for item in host_cleanup_results
                     if item["wall_id"] == cleanup_host_id), None)
                cleanup_host_baseline = matching_host_result["baseline"] \
                    if matching_host_result is not None else \
                        cleanup_host_baseline
                cleanup_host_state = matching_host_result["actual"] \
                    if matching_host_result is not None else None
            result = {
                "status": "error",
                "code": (creation_failure_code or "RHINO_ERROR") \
                    if cleanup_verified else "PARTIAL_MUTATION",
                "message": "Door creation failed: " + va_text(creation_error),
                "door_id": None if materialization_pending else (
                    str(door_id) if door_id != Guid.Empty else None),
                "api_return_id": str(door_id) \
                    if door_id != Guid.Empty else None,
                "resolved_style_id": str(style_id),
                "creation_runtime_serial_floor": \
                    next_runtime_serial_before,
                "preadd_object_ids": sorted(object_ids_before),
                "recovered_door_id": recovered_door_id,
                "recovered_runtime_serial_number": recovered_runtime_serial,
                "new_door_candidates": candidates,
                "new_active_generations": active_generations,
                "candidate_scan_errors": candidate_errors,
                "residual_new_generations": residual_generations,
                "residual_scan_errors": residual_errors,
                "cleanup_deleted": cleanup_deleted,
                "cleanup_object_exists": cleanup_object_exists,
                "cleanup_is_door": cleanup_is_door,
                "cleanup_verified": cleanup_verified,
                "created_runtime_serial_number": created_runtime_serial,
                "final_runtime_serial_number": final_runtime_serial,
                "cleanup_actual_runtime_serial_number": \
                    cleanup_actual_runtime_serial,
                "cleanup_runtime_serial_matches": \
                    cleanup_runtime_serial_matches,
                "replacement_detected": cleanup_replacement_detected,
                "cleanup_host_id": cleanup_host_id,
                "cleanup_host_was_in_preadd_baseline":
                    cleanup_host_was_in_preadd_baseline,
                "cleanup_host_baseline": cleanup_host_baseline,
                "cleanup_host_state": cleanup_host_state,
                "host_cleanup_verified": host_cleanup_verified,
                "host_cleanup_results": host_cleanup_results,
                "mutation_started": mutation_started,
                "materialization_pending": materialization_pending,
                "returned_guid_was_preexisting": \
                    returned_guid_was_preexisting,
                "adddoor_returned_empty_guid":
                    adddoor_returned_empty_guid,
                "spatial_host_scan_complete": spatial_host_scan_complete,
                "spatial_host_baseline_complete":
                    spatial_host_baseline_complete,
                "spatial_candidate_ids": spatial_candidate_ids,
                "spatial_wall_probes": spatial_wall_probes,
                "cleanup_refused_reason": cleanup_refused_reason,
                "reason": creation_failure_reason,
                "verification": {
                    "pass": False,
                    "creation_checks": creation_checks,
                } if creation_checks is not None else None,
                "actual_style_id": str(actual_style_id) \
                    if actual_style_id != Guid.Empty else None,
                "actual_dimensions": actual_dimensions,
                "dimension_sources": dimension_sources,
                "requested_dimensions": {
                    "width": requested_width, "height": requested_height},
                "style_profiles_before": profile_snapshots_before,
                "matching_profile_ids": [
                    str(value) for value in matching_profile_ids],
                "selected_profile_id": str(selected_profile_id) \
                    if selected_profile_id != Guid.Empty else None,
                "host": host,
            }
"""
        opening_script = _specialize_opening_creation_script(
            opening_script, opening_kind)
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _OBJECT_SCRIPT_HELPERS +
            _OPENING_HOST_SCRIPT_HELPERS + opening_script,
            {"style": style, "point": point, "rotation": rotation,
            "wall_id": wall_id, "position": position,
            "width": width, "height": height})
        result = _refresh_async_opening_creation(
            rhino,
            result,
            opening_kind=opening_kind,
            style=style,
            point=point,
            rotation=rotation,
            wall_id=wall_id,
            width=width,
            height=height,
        )
        id_key = f"{opening_kind}_id"
        return _respond(
            result,
            f"{opening_kind.title()} created: {result.get(id_key)}",
        )
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error("Error creating VisualARQ %s: %s", opening_kind, e)
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_door(
    ctx: Context,
    style: str,
    point: Optional[List[float]] = None,
    rotation: float = 0.0,
    wall_id: Optional[str] = None,
    position: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
) -> str:
    """Insert and independently verify a hosted VisualARQ BIM Door.

    Use ``point`` on a wall axis; ``wall_id`` is an optional hard host
    assertion. Optional width/height must resolve to exactly one existing
    rectangular Size Profile owned by the selected Door Style.
    """
    return _va_create_opening(
        ctx,
        style,
        point,
        rotation,
        wall_id,
        position,
        width,
        height,
        opening_kind="door",
    )


@mcp.tool()
def va_create_window(
    ctx: Context,
    style: str,
    point: Optional[List[float]] = None,
    rotation: float = 0.0,
    wall_id: Optional[str] = None,
    position: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
) -> str:
    """Insert and independently verify a hosted VisualARQ BIM Window.

    The Window follows the same fail-closed profile, spatial-host baseline,
    host-cut and ownership-only cleanup contract as ``va_create_door``. The
    installed VisualARQ runtime must expose the exact point-placement
    ``AddWindow(Guid, Point3d, Double)`` overload and typed readback methods.
    """
    return _va_create_opening(
        ctx,
        style,
        point,
        rotation,
        wall_id,
        position,
        width,
        height,
        opening_kind="window",
    )


@mcp.tool()
def va_list_buildings(ctx: Context) -> str:
    """List the verified VisualARQ Building -> Level hierarchy.

    Ownership comes from every building's ``GetBuildingLevelIds`` inventory;
    direct owner getters are optional cross-checks. Orphans, duplicate owners,
    stale classifications, invalid elevations, or incomplete inventories fail
    closed with ``VERIFICATION_FAILED`` and the partial hierarchy evidence.
    """
    try:
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _HIERARCHY_SCRIPT_HELPERS + r"""
hierarchy = va_hierarchy_snapshot()
if hierarchy["verification"]["pass"]:
    result = {
        "status": "success",
        "buildings": hierarchy["buildings"],
        "building_count": len(hierarchy["buildings"]),
        "level_count": len(hierarchy["levels"]),
        "verification": hierarchy["verification"],
    }
else:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": "VisualARQ building/level hierarchy is not verifiable",
        "hierarchy": hierarchy,
    }
""",
        )
        return _respond(
            result, f"{len(result.get('buildings', []))} building(s)")
    except Exception as e:
        logger.error(f"Error listing VisualARQ buildings: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_levels(
    ctx: Context,
    building_id: Optional[str] = None,
) -> str:
    """List independently verified VisualARQ levels and their owner Building.

    ``building_id`` optionally filters the result *after* the complete document
    hierarchy has passed. Every level includes the owner ID/name/elevation,
    optional cut elevation, membership evidence, and getter cross-checks.

    Returns:
        {"success": true, "data": {"levels":
            [{"id": "...", "name": "EG", "elevation": 0.0,
              "owner_building_id": "...", "owner_verified": true}, ...]}}
    """
    try:
        canonical_building_id = None
        if building_id is not None:
            _require_guid(building_id, "building_id")
            canonical_building_id = str(
                UUID(building_id.strip().strip("{}")))
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _HIERARCHY_SCRIPT_HELPERS + r"""
hierarchy = va_hierarchy_snapshot()
if not hierarchy["verification"]["pass"]:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": "VisualARQ building/level hierarchy is not verifiable",
        "hierarchy": hierarchy,
    }
else:
    requested_building_id = params.get("building_id")
    building_ids = set(
        building["id"] for building in hierarchy["buildings"])
    if requested_building_id is not None and \
            requested_building_id not in building_ids:
        result = {
            "status": "error", "code": "INVALID_ID",
            "message": "VisualARQ building not found: " +
                requested_building_id,
            "building_id": requested_building_id,
        }
    else:
        levels = [
            level for level in hierarchy["levels"]
            if requested_building_id is None or
                level["owner_building_id"] == requested_building_id
        ]
        result = {
            "status": "success", "levels": levels,
            "level_count": len(levels),
            "building_id": requested_building_id,
            "buildings": hierarchy["buildings"],
            "verification": hierarchy["verification"],
        }
""",
            {"building_id": canonical_building_id},
        )
        return _respond(result, f"{len(result.get('levels', []))} level(s)")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error listing VisualARQ levels: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_add_building(
    ctx: Context,
    name: str,
    elevation: float = 0.0,
) -> str:
    """Create one VisualARQ Building with an exact verified hierarchy delta.

    The baseline hierarchy must already be fully readable. Success requires one
    new Building, no implicit Level, matching name/elevation/classification, and
    no mutation of pre-existing hierarchy state. A failed owned creation is
    rolled back only when exact ownership is proven.
    """
    try:
        _require_name(name, "name")
        _require_finite_number(elevation, "elevation")
        canonical_name = name.strip()
        canonical_elevation = float(elevation)
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _HIERARCHY_SCRIPT_HELPERS + r"""
import scriptcontext as sc

add_shape = va_exact_method_shape(
    "AddBuilding", ["System.String", "System.Double"])
delete_shape = va_exact_method_shape(
    "DeleteBuilding", ["System.Guid"], "System.Boolean")
before = va_hierarchy_snapshot()
if not add_shape["verified"] or not delete_shape["verified"]:
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "reason": "building_mutation_signature_unverified",
        "message": (
            "VisualARQ Building factory/delete signatures are not uniquely "
            "verified; no Building was created"),
        "add_shape": add_shape, "delete_shape": delete_shape,
    }
elif not before["verification"]["pass"]:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": "Baseline Building/Level hierarchy is not verifiable",
        "hierarchy": before,
    }
else:
    building_id = Guid.Empty
    after = None
    delta = None
    checks = None
    try:
        building_id = va.AddBuilding(params["name"], params["elevation"])
        if building_id == Guid.Empty:
            raise Exception("AddBuilding returned empty Guid")
        before_ids = set(
            building["id"] for building in before["buildings"]) | set(
                level["id"] for level in before["levels"])
        if str(building_id) in before_ids:
            raise Exception(
                "AddBuilding returned a pre-existing hierarchy Guid")
        after = va_hierarchy_snapshot()
        delta = va_hierarchy_diff(before, after)
        actual = next(
            (building for building in after["buildings"]
             if building["id"] == str(building_id)), None)
        tolerance = float(sc.doc.ModelAbsoluteTolerance)
        checks = {
            "hierarchy_verified": after["verification"]["pass"],
            "exact_building_delta": \
                delta["added_building_ids"] == [str(building_id)],
            "no_existing_building_removed": \
                not delta["removed_building_ids"],
            "no_existing_building_changed": \
                not delta["changed_building_ids"],
            "no_level_delta": not delta["added_level_ids"] and \
                not delta["removed_level_ids"] and \
                not delta["changed_level_ids"],
            "no_membership_delta": \
                not delta["added_membership_edges"] and \
                not delta["removed_membership_edges"],
            "building_readable": actual is not None,
            "building_readback_complete": actual is not None and \
                actual["readback_complete"],
            "classified_as_building": actual is not None and \
                actual["classified_as_building"],
            "name_matches": actual is not None and \
                actual["name"] == params["name"],
            "elevation_matches": actual is not None and \
                actual["elevation"] is not None and abs(
                    actual["elevation"] - params["elevation"]) <= tolerance,
        }
        if not all(checks.values()):
            raise Exception(
                "Building readback verification failed: " + ", ".join(
                    key for key, value in checks.items() if not value))
        result = {
            "status": "success", "building_id": str(building_id),
            "requested": {
                "name": params["name"], "elevation": params["elevation"]},
            "actual": actual,
            "hierarchy_delta": delta,
            "verification": {
                "pass": True, "creation_checks": checks,
                "tolerance": tolerance,
                "source": "VisualARQ hierarchy inventory and getter readback",
                "inventory_scope":
                    after["verification"]["inventory_scope"],
                "orphan_check_available":
                    after["verification"]["orphan_check_available"],
            },
        }
    except Exception as creation_error:
        if after is None:
            after = va_hierarchy_snapshot()
        if delta is None:
            delta = va_hierarchy_diff(before, after) \
                if after["verification"]["pass"] else None
        returned_id = str(building_id) \
            if building_id != Guid.Empty else None
        owned = returned_id is not None and delta is not None and \
            delta["added_building_ids"] == [returned_id] and \
            not delta["removed_building_ids"] and \
            not delta["changed_building_ids"] and \
            not delta["added_level_ids"] and \
            not delta["removed_level_ids"] and \
            not delta["changed_level_ids"] and \
            not delta["added_membership_edges"] and \
            not delta["removed_membership_edges"]
        cleanup_delete_result = None
        cleanup_delete_error = None
        if owned:
            try:
                cleanup_delete_result = bool(va.DeleteBuilding(building_id))
            except Exception as cleanup_error:
                cleanup_delete_error = va_text(cleanup_error)
        cleanup_after = va_hierarchy_snapshot()
        cleanup_delta = va_hierarchy_diff(before, cleanup_after) \
            if cleanup_after["verification"]["pass"] else None
        cleanup_classified_as_building = None
        if returned_id is not None:
            try:
                cleanup_classified_as_building = bool(
                    va.IsBuilding(building_id))
            except Exception:
                pass
        cleanup_verified = cleanup_delta is not None and \
            not cleanup_delta["mutation_detected"] and \
            cleanup_classified_as_building is False
        result = {
            "status": "error",
            "code": "RHINO_ERROR" if cleanup_verified \
                else "PARTIAL_MUTATION",
            "message": "Building creation failed: " + va_text(creation_error),
            "building_id": returned_id,
            "owned_building": owned,
            "creation_checks": checks,
            "hierarchy_delta": delta,
            "cleanup_delete_result": cleanup_delete_result,
            "cleanup_delete_error": cleanup_delete_error,
            "cleanup_hierarchy_delta": cleanup_delta,
            "cleanup_classified_as_building":
                cleanup_classified_as_building,
            "cleanup_verified": cleanup_verified,
        }
""",
            {"name": canonical_name, "elevation": canonical_elevation},
        )
        return _respond(
            result, f"VisualARQ Building created: {result.get('building_id')}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error creating VisualARQ Building: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_add_level(
    ctx: Context,
    name: str,
    elevation: float,
    building_id: str,
) -> str:
    """Add one Level to one explicit VisualARQ Building and verify ownership.

    The complete Building -> Level hierarchy must pass before mutation.
    building_id is mandatory; RhinoClaw never selects a sole Building and
    never creates a hidden default Building. Success requires exactly one new
    Level GUID and exactly one new membership edge to the requested Building.
    """
    try:
        _require_name(name, "name")
        _require_finite_number(elevation, "elevation")
        _require_guid(building_id, "building_id")
        canonical_name = name.strip()
        canonical_elevation = float(elevation)
        canonical_building_id = str(
            UUID(building_id.strip().strip("{}"))
        )
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _STYLE_SCRIPT_HELPERS + _HIERARCHY_SCRIPT_HELPERS + r"""
import scriptcontext as sc

add_shape = va_exact_method_shape(
    "AddLevel", ["System.Guid", "System.String", "System.Double"])
delete_shape = va_exact_method_shape(
    "DeleteLevel", ["System.Guid"], "System.Boolean")
before = va_hierarchy_snapshot()
requested_building_id = params["building_id"]
before_building_ids = set(
    building["id"] for building in before["buildings"])
if not add_shape["verified"] or not delete_shape["verified"]:
    result = {
        "status": "error", "code": "UNSUPPORTED_OPERATION",
        "reason": "level_mutation_signature_unverified",
        "message": (
            "VisualARQ Level factory/delete signatures are not uniquely "
            "verified; no Level was created"),
        "add_shape": add_shape, "delete_shape": delete_shape,
    }
elif not before["verification"]["pass"]:
    result = {
        "status": "error", "code": "VERIFICATION_FAILED",
        "message": "Baseline Building/Level hierarchy is not verifiable",
        "hierarchy": before,
    }
elif requested_building_id not in before_building_ids:
    result = {
        "status": "error", "code": "INVALID_ID",
        "message": "VisualARQ Building not found: " + requested_building_id,
        "building_id": requested_building_id,
    }
else:
    level_id = Guid.Empty
    after = None
    delta = None
    checks = None
    try:
        level_id = va.AddLevel(
            Guid(requested_building_id),
            params["name"],
            params["elevation"])
        if level_id == Guid.Empty:
            raise Exception("AddLevel returned empty Guid")
        before_hierarchy_ids = set(
            level["id"] for level in before["levels"]) | set(
                building["id"] for building in before["buildings"])
        if str(level_id) in before_hierarchy_ids:
            raise Exception(
                "AddLevel returned a Guid already present in the observed "
                "hierarchy inventory")

        after = va_hierarchy_snapshot()
        delta = va_hierarchy_diff(before, after)
        actual = next(
            (level for level in after["levels"]
             if level["id"] == str(level_id)), None)
        expected_edge = {
            "building_id": requested_building_id,
            "level_id": str(level_id),
        }
        tolerance = float(sc.doc.ModelAbsoluteTolerance)
        checks = {
            "hierarchy_verified": after["verification"]["pass"],
            "not_preexisting_in_observed_inventory":
                str(level_id) not in before_hierarchy_ids,
            "exact_level_delta":
                delta["added_level_ids"] == [str(level_id)],
            "no_building_delta":
                not delta["added_building_ids"] and
                not delta["removed_building_ids"] and
                not delta["changed_building_ids"],
            "no_existing_level_removed":
                not delta["removed_level_ids"],
            "no_existing_level_changed":
                not delta["changed_level_ids"],
            "exact_membership_delta":
                delta["added_membership_edges"] == [expected_edge],
            "no_membership_removed":
                not delta["removed_membership_edges"],
            "level_readable": actual is not None,
            "level_readback_complete": actual is not None and
                actual["readback_complete"],
            "classified_as_level": actual is not None and
                actual["classified_as_level"],
            "owner_verified": actual is not None and
                actual["owner_verified"],
            "owner_matches": actual is not None and
                actual["owner_building_id"] == requested_building_id,
            "name_matches": actual is not None and
                actual["name"] == params["name"],
            "elevation_matches": actual is not None and
                actual["elevation"] is not None and abs(
                    actual["elevation"] - params["elevation"]) <= tolerance,
        }
        if not all(checks.values()):
            raise Exception(
                "Level readback verification failed: " + ", ".join(
                    key for key, value in checks.items() if not value))
        result = {
            "status": "success", "level_id": str(level_id),
            "requested": {
                "name": params["name"],
                "elevation": params["elevation"],
                "building_id": requested_building_id,
            },
            "actual": actual,
            "hierarchy_delta": delta,
            "verification": {
                "pass": True,
                "creation_checks": checks,
                "tolerance": tolerance,
                "source": "VisualARQ hierarchy inventory and getter readback",
                "inventory_scope":
                    after["verification"]["inventory_scope"],
                "guid_freshness_scope":
                    after["verification"]["inventory_scope"],
                "global_guid_freshness_verified":
                    after["verification"]["inventory_scope"] == "global",
                "orphan_check_available":
                    after["verification"]["orphan_check_available"],
            },
        }
    except Exception as creation_error:
        if after is None:
            after = va_hierarchy_snapshot()
        if delta is None:
            delta = va_hierarchy_diff(before, after) \
                if after["verification"]["pass"] else None
        returned_id = str(level_id) if level_id != Guid.Empty else None
        expected_edge = {
            "building_id": requested_building_id,
            "level_id": returned_id,
        } if returned_id is not None else None
        before_hierarchy_ids = set(
            level["id"] for level in before["levels"]) | set(
                building["id"] for building in before["buildings"])
        owned = returned_id is not None and delta is not None and \
            returned_id not in before_hierarchy_ids and \
            delta["added_level_ids"] == [returned_id] and \
            not delta["added_building_ids"] and \
            not delta["removed_building_ids"] and \
            not delta["changed_building_ids"] and \
            not delta["removed_level_ids"] and \
            not delta["changed_level_ids"] and \
            delta["added_membership_edges"] == [expected_edge] and \
            not delta["removed_membership_edges"]
        cleanup_delete_result = None
        cleanup_delete_error = None
        cleanup_delete_refused_reason = None
        cleanup_delete_authorized = owned and \
            before["verification"]["inventory_scope"] == "global"
        if cleanup_delete_authorized:
            try:
                cleanup_delete_result = bool(va.DeleteLevel(level_id))
            except Exception as cleanup_error:
                cleanup_delete_error = va_text(cleanup_error)
        elif owned:
            cleanup_delete_refused_reason = (
                "reachable-only baseline cannot exclude a pre-existing "
                "orphan Level Guid; automatic DeleteLevel was refused")
        cleanup_after = va_hierarchy_snapshot()
        cleanup_delta = va_hierarchy_diff(before, cleanup_after) \
            if cleanup_after["verification"]["pass"] else None
        cleanup_classified_as_level = None
        if returned_id is not None:
            try:
                cleanup_classified_as_level = bool(va.IsLevel(level_id))
            except Exception:
                pass
        cleanup_verified = cleanup_delete_authorized and \
            cleanup_delta is not None and \
            not cleanup_delta["mutation_detected"] and \
            cleanup_classified_as_level is False
        result = {
            "status": "error",
            "code": "RHINO_ERROR" if cleanup_verified
                else "PARTIAL_MUTATION",
            "message": "Level creation failed: " + va_text(creation_error),
            "level_id": returned_id,
            "owned_level": owned,
            "creation_checks": checks,
            "hierarchy_delta": delta,
            "cleanup_delete_result": cleanup_delete_result,
            "cleanup_delete_error": cleanup_delete_error,
            "cleanup_delete_authorized": cleanup_delete_authorized,
            "cleanup_delete_refused_reason":
                cleanup_delete_refused_reason,
            "cleanup_hierarchy_delta": cleanup_delta,
            "cleanup_classified_as_level": cleanup_classified_as_level,
            "cleanup_verified": cleanup_verified,
        }
""",
            {
                "name": canonical_name,
                "elevation": canonical_elevation,
                "building_id": canonical_building_id,
            },
        )
        return _respond(
            result, f"VisualARQ Level created: {result.get('level_id')}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error creating VisualARQ Level: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))

@mcp.tool()
def va_ifc_export(
    ctx: Context,
    path: str,
    version: IfcSchema = "IFC4",
    require_wall_material_layers: bool = False,
) -> str:
    """Export the document to IFC via VisualARQ — the BIM deliverable.

    Parameters:
    - path: Output `.ifc` path, visible to the WINDOWS Rhino process
      (e.g. `C:/Users/<you>/Desktop/model.ifc`).
    - version: "IFC4" (default) or "IFC2x3". Only honored by the legacy
      `va.ExportIFC` API; on current VisualARQ the schema comes from the
      saved exporter settings (the V3 engine writes IFC2x3).

    Returns the requested schema separately from the schema parsed from
    the written IFC header. The latter is the authoritative value.

    Set ``require_wall_material_layers=true`` for a strict layered-wall BIM
    gate. The staged IFC must then contain at least one IfcWall and every wall
    must resolve, directly or via IfcWallType, through
    IfcRelAssociatesMaterial to IfcMaterialLayerSet(Usage).

    VisualARQ elements (walls, doors, windows, slabs, levels) export as
    typed IFC entities (IfcWall, IfcDoor, ...); plain Rhino geometry
    exports as proxies.

    FIRST-RUN GOTCHA: the VisualARQ IFC exporter pops a **modal options
    dialog** on its first use in an installation — it blocks this tool
    (timeout) AND every later save until someone clicks it away in the
    Rhino UI. Have the user tick *"Always use these settings. Do not show
    this dialog again"* once (settings adjustable any time via the
    `IfcExportOptionsDialog` command); afterwards exports run headless.
    """
    try:
        _require_name(path, "path")
        canonical_path = path.strip()
        if not canonical_path.lower().endswith(".ifc"):
            raise ValueError("path must end with .ifc")
        if version not in ("IFC4", "IFC2x3"):
            raise ValueError("version must be 'IFC4' or 'IFC2x3'")
        if not isinstance(require_wall_material_layers, bool):
            raise ValueError("require_wall_material_layers must be a boolean")
        rhino = get_rhino_connection()
        result = run_va(rhino, _IFC_VALIDATION_SCRIPT_HELPERS + r"""
target_path = Path.GetFullPath(params["path"])
directory = Path.GetDirectoryName(target_path)
stem = Path.GetFileNameWithoutExtension(target_path)
transaction_id = Guid.NewGuid().ToString("N")
temp_path = Path.Combine(
    directory,
    "." + stem + ".rhinoclaw-" + transaction_id + ".ifc")
backup_path = Path.Combine(
    directory,
    "." + stem + ".rhinoclaw-backup-" + transaction_id + ".ifc")
recovery_path = Path.Combine(
    directory,
    "." + stem + ".rhinoclaw-recovery-" + transaction_id + ".ifc")
target_before = None
target_prepublication = None
target_existed_before = None
exporter = None
publication_mode = None
publication_attempted = False
publication_completed = False
staged_validation = None
staged_hash = None
published_validation = None
published_evidence = None
backup_evidence = None
rollback_attempted = False
rollback_verified = False
rollback_refused_reason = None
try:
    if File.Exists(temp_path) or File.Exists(backup_path) or \
            File.Exists(recovery_path):
        raise Exception("Unique IFC transaction path already exists")
    target_before = va_file_evidence(target_path)
    if target_before["read_complete"] is not True:
        raise Exception("IFC target baseline could not be read")
    target_existed_before = target_before["exists"]

    # Export only to a new sibling artifact. An old target can therefore
    # never masquerade as output from this call.
    if hasattr(va, "ExportIFC"):
        export_success = va.ExportIFC(temp_path, params["version"])
        exporter = "va.ExportIFC"
    else:
        opts = Rhino.FileIO.FileWriteOptions()
        opts.SuppressDialogBoxes = True
        opts.WriteSelectedObjectsOnly = False
        export_success = sc.doc.WriteFile(temp_path, opts)
        exporter = "doc.WriteFile (VisualARQ IFC plugin, dialogs suppressed)"
    if not export_success:
        raise Exception("IFC export returned false")

    staged_validation = validate_ifc(
        temp_path, params["require_wall_material_layers"])
    if not staged_validation["valid"]:
        raise Exception(
            "IFC exporter returned success but staged output validation failed")
    staged_hash = file_sha256(temp_path)

    # Compare-and-swap: never publish over a target that changed while the
    # exporter was producing/validating the staged artifact.
    target_prepublication = va_file_evidence(target_path)
    if not va_same_file_state(target_before, target_prepublication):
        raise Exception(
            "IFC target changed during export; publication was refused")
    publication_attempted = True
    if target_existed_before:
        File.Replace(temp_path, target_path, backup_path)
        publication_mode = "replace"
    else:
        File.Move(temp_path, target_path)
        publication_mode = "move"
    publication_completed = True

    published_validation = validate_ifc(
        target_path, params["require_wall_material_layers"])
    published_evidence = va_file_evidence(target_path)
    published_hash = published_evidence["sha256"] \
        if published_evidence["read_complete"] is True and \
            published_evidence["exists"] is True else None
    if target_existed_before:
        backup_evidence = va_file_evidence(backup_path)
        if backup_evidence["read_complete"] is not True or \
                backup_evidence["exists"] is not True or \
                backup_evidence["sha256"] != \
                    target_prepublication["sha256"]:
            raise Exception(
                "IFC replacement backup does not match displaced target")
    published = published_validation["valid"] and \
        published_evidence["read_complete"] is True and \
        published_hash == staged_hash and not File.Exists(temp_path)
    if not published:
        raise Exception("Published IFC does not match the staged artifact")

    actual_schema = published_validation["actual_schema"]
    requested_key = params["version"].upper().replace("X", "")
    actual_key = actual_schema.upper().replace("X", "")
    schema_request_honored = actual_key == requested_key
    warnings = []
    if not schema_request_honored:
        warnings.append(
            "Requested schema " + params["version"] +
            " was not honored; exporter wrote " + actual_schema)
    if published_validation["wall_count"] > 0 and not \
            published_validation["wall_material_layer_association_pass"]:
        warnings.append(
            "One or more IFC walls have no verified material-layer-set "
            "association")
    backup_cleanup_error = None
    if target_existed_before and File.Exists(backup_path):
        try:
            File.Delete(backup_path)
        except Exception as cleanup_error:
            backup_cleanup_error = va_text(cleanup_error)
    backup_cleanup_evidence = va_file_evidence(backup_path)
    backup_cleanup_verified = \
        backup_cleanup_evidence["read_complete"] is True and \
        backup_cleanup_evidence["exists"] is False
    if not backup_cleanup_verified:
        warnings.append(
            "Verified IFC publication succeeded, but its displaced-target "
            "backup could not be removed")
    result = {
        "status": "success", "path": params["path"],
        "target_path": target_path,
        "requested_schema": params["version"],
        "actual_schema": actual_schema,
        "schema_request_honored": schema_request_honored,
        "warnings": warnings,
        "file_exists": published_validation["file_exists"],
        "file_size": published_validation["file_size"],
        "max_validation_bytes":
            published_validation["max_validation_bytes"],
        "file_size_within_limit":
            published_validation["file_size_within_limit"],
        "header_valid": published_validation["header_valid"],
        "schema_valid": published_validation["schema_valid"],
        "header_entity_names":
            published_validation["header_entity_names"],
        "header_errors": published_validation["header_errors"],
        "supported_schemas": published_validation["supported_schemas"],
        "complete_step_structure":
            published_validation["complete_step_structure"],
        "data_instance_count": published_validation["data_instance_count"],
        "duplicate_entity_ids":
            published_validation["duplicate_entity_ids"],
        "unrecognized_data_statements":
            published_validation["unrecognized_data_statements"],
        "invalid_entity_statements":
            published_validation["invalid_entity_statements"],
        "dangling_reference_ids":
            published_validation["dangling_reference_ids"],
        "invalid_semantic_entity_ids":
            published_validation["invalid_semantic_entity_ids"],
        "invalid_semantic_reasons":
            published_validation["invalid_semantic_reasons"],
        "entity_counts": published_validation["entity_counts"],
        "project_count": published_validation["project_count"],
        "valid_project_count": published_validation["valid_project_count"],
        "wall_count": published_validation["wall_count"],
        "material_layer_set_count":
            published_validation["material_layer_set_count"],
        "valid_material_layer_set_count": published_validation[
            "valid_material_layer_set_count"],
        "material_layer_set_usage_count":
            published_validation["material_layer_set_usage_count"],
        "valid_material_layer_set_usage_count": published_validation[
            "valid_material_layer_set_usage_count"],
        "material_layer_count":
            published_validation["material_layer_count"],
        "material_association_count":
            published_validation["material_association_count"],
        "walls_with_material_layer_association": published_validation[
            "walls_with_material_layer_association"],
        "unassociated_wall_ids":
            published_validation["unassociated_wall_ids"],
        "ambiguous_material_wall_ids":
            published_validation["ambiguous_material_wall_ids"],
        "ambiguous_wall_type_ids":
            published_validation["ambiguous_wall_type_ids"],
        "invalid_wall_type_target_ids":
            published_validation["invalid_wall_type_target_ids"],
        "wall_material_layer_association_pass": published_validation[
            "wall_material_layer_association_pass"],
        "wall_material_layers_required":
            params["require_wall_material_layers"],
        "exporter": exporter,
        "fresh_artifact_verified": True,
        "staged_artifact_validated": True,
        "published": True,
        "publication_mode": publication_mode,
        "publication_attempted": publication_attempted,
        "publication_completed": publication_completed,
        "target_before": target_before,
        "target_prepublication": target_prepublication,
        "published_evidence": published_evidence,
        "backup_path": backup_path if target_existed_before else None,
        "backup_cleanup_error": backup_cleanup_error,
        "backup_cleanup_verified": backup_cleanup_verified,
        "residual_backup_path": backup_path
            if not backup_cleanup_verified else None,
        "sha256": published_hash,
    }
except Exception as export_error:
    rollback_error = None
    recovery_cleanup_error = None
    temp_cleanup_error = None
    target_after_error = va_file_evidence(target_path)
    staged_was_published = None
    if staged_hash is None:
        staged_was_published = False
    elif target_after_error["read_complete"] is True:
        staged_was_published = target_after_error["exists"] is True and \
            target_after_error["sha256"] == staged_hash

    target_preserved = va_same_file_state(
        target_before, target_after_error) \
        if target_before is not None else None
    target_after_rollback = target_after_error
    recovery_evidence = va_file_evidence(recovery_path)
    if staged_was_published is True:
        if target_existed_before:
            backup_evidence = va_file_evidence(backup_path)
            trusted_backup = \
                backup_evidence["read_complete"] is True and \
                backup_evidence["exists"] is True and \
                target_prepublication is not None and \
                target_prepublication.get("read_complete") is True and \
                backup_evidence["sha256"] == \
                    target_prepublication["sha256"]
            if trusted_backup and recovery_evidence["read_complete"] is True \
                    and recovery_evidence["exists"] is False:
                rollback_attempted = True
                try:
                    File.Replace(backup_path, target_path, recovery_path)
                except Exception as rollback_exception:
                    rollback_error = va_text(rollback_exception)
                target_after_rollback = va_file_evidence(target_path)
                recovery_evidence = va_file_evidence(recovery_path)
                rollback_verified = va_same_file_state(
                    target_before, target_after_rollback) and \
                    recovery_evidence["read_complete"] is True and \
                    recovery_evidence["exists"] is True and \
                    recovery_evidence["sha256"] == staged_hash
            else:
                rollback_refused_reason = (
                    "Displaced-target backup was absent, unreadable, or did "
                    "not match the prepublication target")
        else:
            if recovery_evidence["read_complete"] is True and \
                    recovery_evidence["exists"] is False:
                rollback_attempted = True
                try:
                    File.Move(target_path, recovery_path)
                except Exception as rollback_exception:
                    rollback_error = va_text(rollback_exception)
                target_after_rollback = va_file_evidence(target_path)
                recovery_evidence = va_file_evidence(recovery_path)
                rollback_verified = va_same_file_state(
                    target_before, target_after_rollback) and \
                    recovery_evidence["read_complete"] is True and \
                    recovery_evidence["exists"] is True and \
                    recovery_evidence["sha256"] == staged_hash
            else:
                rollback_refused_reason = (
                    "Unique recovery path was not proven absent")
    elif publication_completed:
        rollback_refused_reason = (
            "Published target no longer matches the staged artifact; "
            "rollback was refused to avoid clobbering a third-party change")

    if rollback_verified:
        target_preserved = True
        if recovery_evidence["exists"] is True:
            try:
                File.Delete(recovery_path)
            except Exception as cleanup_error:
                recovery_cleanup_error = va_text(cleanup_error)
        recovery_evidence = va_file_evidence(recovery_path)

    temp_evidence = va_file_evidence(temp_path)
    if temp_evidence["read_complete"] is True and \
            temp_evidence["exists"] is True:
        try:
            File.Delete(temp_path)
        except Exception as cleanup_error:
            temp_cleanup_error = va_text(cleanup_error)
    temp_evidence = va_file_evidence(temp_path)
    temp_cleanup_verified = temp_evidence["read_complete"] is True and \
        temp_evidence["exists"] is False
    backup_final_evidence = va_file_evidence(backup_path)
    recovery_final_evidence = va_file_evidence(recovery_path)
    publication_may_have_mutated = publication_completed or \
        staged_was_published is True or (
            publication_attempted and target_existed_before is True and
            backup_final_evidence["exists"] is True)
    partial_mutation = publication_may_have_mutated and \
        target_preserved is not True
    result = {
        "status": "error",
        "code": "PARTIAL_MUTATION" if partial_mutation else "RHINO_ERROR",
        "message": "IFC export failed: " + va_text(export_error),
        "path": params["path"], "target_path": target_path,
        "exporter": exporter,
        "staging_path": temp_path,
        "backup_path": backup_path,
        "recovery_path": recovery_path,
        "staged_validation": staged_validation,
        "staged_artifact_validated": staged_validation is not None and
            staged_validation.get("valid") is True,
        "staged_sha256": staged_hash,
        "target_before": target_before,
        "target_prepublication": target_prepublication,
        "target_after_error": target_after_error,
        "target_after_rollback": target_after_rollback,
        "publication_attempted": publication_attempted,
        "publication_completed": publication_completed,
        "publication_mode": publication_mode,
        "staged_was_published": staged_was_published,
        "target_preserved": target_preserved,
        "rollback_attempted": rollback_attempted,
        "rollback_verified": rollback_verified,
        "rollback_error": rollback_error,
        "rollback_refused_reason": rollback_refused_reason,
        "backup_evidence": backup_final_evidence,
        "recovery_evidence": recovery_final_evidence,
        "recovery_cleanup_error": recovery_cleanup_error,
        "temp_cleanup_error": temp_cleanup_error,
        "temp_cleanup_verified": temp_cleanup_verified,
        "temp_evidence": temp_evidence,
        "retry_safe": not partial_mutation and
            temp_cleanup_verified and
            recovery_final_evidence["exists"] is False and
            backup_final_evidence["exists"] is False,
    }
""", {
            "path": canonical_path,
            "version": version,
            "require_wall_material_layers": require_wall_material_layers,
        })
        success_message = f"IFC exported: {canonical_path}"
        if result.get("status") == "success":
            actual_schema = result.get("actual_schema")
            requested_schema = result.get("requested_schema")
            success_message += f"; actual schema {actual_schema}"
            if result.get("schema_request_honored") is False:
                success_message += (
                    f" (requested {requested_schema}; request not honored)"
                )
        return _respond(result, success_message)
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error exporting IFC: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_ifc_import(ctx: Context, path: str) -> str:
    """Validate and import an IFC file through the exact VisualARQ API.

    Parameters:
    - path: `.ifc` path visible to the WINDOWS Rhino process.

    The source is parsed before mutation. RhinoClaw then compares Rhino-object
    generations, every reflected VisualARQ style inventory, and the complete
    building/level hierarchy before and after `ImportIFC(String)`. The generic
    Rhino document importer is deliberately not used: it cannot prove that the
    result is VisualARQ BIM. A failed or unverifiable call never triggers
    automatic deletion; when a mutation is detected the response recommends
    Rhino Undo.
    """
    try:
        _require_name(path, "path")
        canonical_path = path.strip()
        if not canonical_path.lower().endswith(".ifc"):
            raise ValueError("path must end with .ifc")
        rhino = get_rhino_connection()
        result = run_va(
            rhino,
            _IFC_VALIDATION_SCRIPT_HELPERS +
            _STYLE_SCRIPT_HELPERS +
            _HIERARCHY_SCRIPT_HELPERS +
            _IFC_IMPORT_SCRIPT_HELPERS + r"""
source_path = Path.GetFullPath(params["path"])
if not File.Exists(source_path):
    result = {
        "status": "error", "code": "INVALID_PARAMS",
        "message": "IFC source file does not exist: " + source_path,
        "path": source_path,
        "mutation_attempted": False,
    }
else:
    import_shape = va_exact_method_shape(
        "ImportIFC", ["System.String"], "System.Boolean")
    if not import_shape["verified"]:
        result = {
            "status": "error", "code": "UNSUPPORTED_OPERATION",
            "message": (
                "VisualARQ ImportIFC(String) -> Boolean is unavailable or "
                "ambiguous; generic Rhino import was refused"),
            "path": source_path,
            "import_shape": import_shape,
            "mutation_attempted": False,
        }
    else:
        directory = Path.GetDirectoryName(source_path)
        stem = Path.GetFileNameWithoutExtension(source_path)
        staging_path = Path.Combine(
            directory,
            "." + stem + ".rhinoclaw-import-" +
            Guid.NewGuid().ToString("N") + ".ifc")
        source_guard = None
        stage_guard = None
        source_guard_close_error = None
        stage_guard_close_error = None
        staging_cleanup_error = None
        source_hash = None
        staged_hash = None
        source_copy_verified = False
        source_validation = None
        before = None
        after = None
        delta = None
        post_snapshot_error = None
        delta_error = None
        import_returned = None
        import_error = None
        mutation_attempted = False
        try:
            if File.Exists(staging_path):
                raise Exception("Unique IFC import staging path already exists")
            # The source handle denies writers and deletion while the copy and
            # both hashes are made. The retained stage handle likewise denies
            # mutation through validation and ImportIFC(String).
            source_guard = File.Open(
                source_path, FileMode.Open, FileAccess.Read, FileShare.Read)
            File.Copy(source_path, staging_path, False)
            stage_guard = File.Open(
                staging_path, FileMode.Open, FileAccess.Read, FileShare.Read)
            source_hash = file_sha256(source_path)
            staged_hash = file_sha256(staging_path)
            source_copy_verified = source_hash == staged_hash
            if not source_copy_verified:
                raise Exception("IFC staging copy hash does not match source")
            source_validation = validate_ifc(staging_path, False)
            source_validation["validated_path"] = staging_path
            if not source_validation["valid"]:
                result = {
                    "status": "error", "code": "INVALID_PARAMS",
                    "message": (
                        "IFC source failed RhinoClaw's targeted STEP/header/"
                        "core and layered-wall validation"),
                    "path": source_path,
                    "staging_path": staging_path,
                    "source_sha256": source_hash,
                    "staged_sha256": staged_hash,
                    "source_copy_verified": source_copy_verified,
                    "source_validation": source_validation,
                    "mutation_attempted": False,
                }
            else:
                try:
                    source_guard.Close()
                    source_guard = None
                except Exception as close_error:
                    source_guard_close_error = va_text(close_error)
                    raise
                before = va_ifc_import_snapshot()
                if before["read_complete"] is not True:
                    result = {
                        "status": "error", "code": "VERIFICATION_FAILED",
                        "message": (
                            "Document inventory is incomplete; IFC import "
                            "was refused before mutation"),
                        "reason": "inventory_baseline_incomplete",
                        "path": source_path,
                        "staging_path": staging_path,
                        "source_sha256": source_hash,
                        "staged_sha256": staged_hash,
                        "source_copy_verified": source_copy_verified,
                        "source_validation": source_validation,
                        "before": before,
                        "mutation_attempted": False,
                    }
                else:
                    mutation_attempted = True
                    try:
                        import_returned = bool(va.ImportIFC(staging_path))
                    except Exception as error:
                        import_error = va_text(error)
                    try:
                        after = va_ifc_import_snapshot()
                    except Exception as snapshot_error:
                        post_snapshot_error = va_text(snapshot_error)
                    if after is not None and \
                            after.get("read_complete") is True:
                        try:
                            delta = va_ifc_import_delta(before, after)
                        except Exception as after_delta_error:
                            delta_error = va_text(after_delta_error)
                    mutation_detected = delta["mutation_detected"] \
                        if delta is not None else None
                    common = {
                        "path": source_path,
                        "staging_path": staging_path,
                        "source_sha256": source_hash,
                        "staged_sha256": staged_hash,
                        "source_copy_verified": source_copy_verified,
                        "source_validation": source_validation,
                        "import_shape": import_shape,
                        "imported_path": staging_path,
                        "import_returned": import_returned,
                        "import_error": import_error,
                        "before": before,
                        "after": after,
                        "post_snapshot_error": post_snapshot_error,
                        "delta": delta,
                        "delta_error": delta_error,
                        "mutation_attempted": True,
                        "mutation_detected": mutation_detected,
                        "automatic_cleanup_attempted": False,
                        "undo_recommended": mutation_detected is not False,
                    }
                    if import_returned is True and import_error is None and \
                            delta is not None and \
                            delta["mutation_detected"] and \
                            delta["additive"] and \
                            delta["verified_visualarq_addition"]:
                        common.update({
                            "status": "success",
                            "verification": {
                                "pass": True,
                                "source": (
                                    "locked staged IFC plus exact covered "
                                    "object/style/hierarchy inventory fields"),
                                "coverage": before.get("coverage"),
                                "additive": True,
                            },
                        })
                        result = common
                    elif delta is None:
                        common.update({
                            "status": "error", "code": "PARTIAL_MUTATION",
                            "message": (
                                "IFC import returned without a complete "
                                "post-mutation inventory/delta; use Rhino Undo "
                                "and inspect the document"),
                        })
                        result = common
                    elif not delta["mutation_detected"]:
                        common.update({
                            "status": "error",
                            "code": "VERIFICATION_FAILED"
                            if import_returned is True and import_error is None
                            else "RHINO_ERROR",
                            "message": (
                                "ImportIFC reported success but produced no "
                                "verified covered-state delta"
                                if import_returned is True and
                                    import_error is None
                                else "ImportIFC failed without changing the "
                                    "covered document state"),
                            "undo_recommended": False,
                        })
                        result = common
                    else:
                        common.update({
                            "status": "error", "code": "PARTIAL_MUTATION",
                            "message": (
                                "IFC import changed the covered document state "
                                "but the delta was not a verified additive "
                                "VisualARQ mutation; use Rhino Undo"),
                        })
                        result = common
        except Exception as staging_error:
            if result is None:
                result = {
                    "status": "error",
                    "code": "PARTIAL_MUTATION" if mutation_attempted
                        else "RHINO_ERROR",
                    "message": "IFC import transaction failed: " +
                        va_text(staging_error),
                    "path": source_path,
                    "staging_path": staging_path,
                    "source_sha256": source_hash,
                    "staged_sha256": staged_hash,
                    "source_copy_verified": source_copy_verified,
                    "source_validation": source_validation,
                    "before": before,
                    "after": after,
                    "delta": delta,
                    "mutation_attempted": mutation_attempted,
                    "mutation_detected": None
                        if mutation_attempted else False,
                    "automatic_cleanup_attempted": False,
                    "undo_recommended": mutation_attempted,
                }
        finally:
            if source_guard is not None:
                try:
                    source_guard.Close()
                except Exception as close_error:
                    source_guard_close_error = va_text(close_error)
            if stage_guard is not None:
                try:
                    stage_guard.Close()
                except Exception as close_error:
                    stage_guard_close_error = va_text(close_error)
            if File.Exists(staging_path):
                try:
                    File.Delete(staging_path)
                except Exception as cleanup_error:
                    staging_cleanup_error = va_text(cleanup_error)
            staging_cleanup_verified = not File.Exists(staging_path)
            result["source_guard_close_error"] = source_guard_close_error
            result["stage_guard_close_error"] = stage_guard_close_error
            result["staging_cleanup_error"] = staging_cleanup_error
            result["staging_cleanup_verified"] = staging_cleanup_verified
            result["residual_staging_path"] = staging_path \
                if not staging_cleanup_verified else None
            if not staging_cleanup_verified or \
                    stage_guard_close_error is not None:
                result["retry_safe"] = False
                if result.get("status") == "success":
                    warnings = list(result.get("warnings") or [])
                    warnings.append(
                        "Verified import succeeded, but its staging artifact "
                        "could not be fully released/removed")
                    result["warnings"] = warnings
""",
            {"path": canonical_path},
        )
        return _respond(result, f"IFC imported: {canonical_path}")
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error importing IFC: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
