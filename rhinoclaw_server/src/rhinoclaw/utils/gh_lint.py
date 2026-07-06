"""Static lint for build_gh_definition specs — fail BEFORE the round-trip.

Validates a component/wire spec against the introspected component
catalog (ground truth) and the known builder rules, so an agent learns
about hallucinated GUIDs, misspelled ports, and unbindable script outputs
in milliseconds instead of after an author→solve→bake round-trip.

Pure Python, no Rhino. Reused by `validate_gh_definition` (tool) and the
future interactive author loop (NEXT-LEVEL 5.3).
"""
import re
from typing import Any, Dict, List, Optional

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

KNOWN_TYPES = {
    "slider", "toggle", "panel",
    "python3_script", "script",
    "sdk_component", "sdk",
    "custom_preview", "preview",
    "colour_swatch", "color_swatch", "colour", "color",
}
_SCRIPT_TYPES = {"python3_script", "script"}
_SDK_TYPES = {"sdk_component", "sdk"}
_PREVIEW_TYPES = {"custom_preview", "preview"}
# Builder-builtin wire targets that are not in the catalog.
_PREVIEW_INPUTS = ["Geometry", "Material"]

REQUIRED_FIELDS = {
    "slider": ("name",),
    "toggle": ("name",),
    "panel": ("name",),
    "python3_script": ("name", "code"),
    "script": ("name", "code"),
    "sdk_component": ("guid",),
    "sdk": ("guid",),
}


def _catalog_index(catalog: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not catalog:
        return {}
    return {c["guid"].lower(): c for c in catalog.get("components", [])
            if c.get("guid")}


def _port_names(ports: List[Dict[str, str]]) -> List[str]:
    names = []
    for p in ports or []:
        names.extend([p.get("n") or "", p.get("nn") or ""])
    return [n for n in names if n]


def _script_outputs(component: Dict[str, Any]) -> List[str]:
    return ["a", "out"] + list(component.get("extra_outputs") or [])


def lint_definition(
    components: List[Dict[str, Any]],
    wires: Optional[List[Dict[str, Any]]] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Lint a builder spec. Returns {valid, errors, warnings}."""
    errors: List[str] = []
    warnings: List[str] = []
    wires = wires or []
    guid_index = _catalog_index(catalog)

    if not isinstance(components, list) or not components:
        return {"valid": False, "warnings": [],
                "errors": ["components must be a non-empty list"]}

    by_name: Dict[str, Dict[str, Any]] = {}
    for i, comp in enumerate(components):
        label = comp.get("name") or comp.get("guid") or f"#{i}"
        ctype = (comp.get("type") or "").lower()
        if ctype not in KNOWN_TYPES:
            errors.append(
                f"component '{label}': unknown type '{comp.get('type')}' — "
                f"known: {sorted(KNOWN_TYPES)}")
            continue
        for field in REQUIRED_FIELDS.get(ctype, ()):
            if not comp.get(field):
                errors.append(
                    f"component '{label}' ({ctype}): missing required "
                    f"field '{field}'")

        name = comp.get("name")
        if name:
            if name in by_name:
                errors.append(
                    f"duplicate component name '{name}' — wires address "
                    "components by name, duplicates are ambiguous")
            by_name[name] = comp

        if ctype in _SDK_TYPES and comp.get("guid"):
            guid = str(comp["guid"]).lower()
            entry = guid_index.get(guid)
            if guid_index and entry is None:
                errors.append(
                    f"component '{label}': GUID {comp['guid']} not in the "
                    "component catalog — look it up with find_gh_component "
                    "instead of guessing")
            elif entry is not None:
                comp["_catalog"] = entry
                if entry.get("obsolete"):
                    warnings.append(
                        f"component '{label}': '{entry.get('name')}' is "
                        "flagged OBSOLETE — prefer the current version")

        if ctype in _SCRIPT_TYPES:
            for out in comp.get("extra_outputs") or []:
                if "RH_OUT" in str(out):
                    errors.append(
                        f"script '{label}': output '{out}' — RH_OUT names "
                        "can never bind to a script variable; keep outputs "
                        "plain identifiers, put RH_OUT:<Name> on a group")
                elif not _IDENTIFIER_RE.match(str(out)):
                    errors.append(
                        f"script '{label}': output '{out}' is not a valid "
                        "Python identifier — the assignment will not bind")
            for inp in comp.get("inputs") or []:
                if not _IDENTIFIER_RE.match(str(inp)):
                    errors.append(
                        f"script '{label}': input '{inp}' is not a valid "
                        "Python identifier")

        if ctype == "slider":
            default = comp.get("default")
            lo, hi = comp.get("min"), comp.get("max")
            if default is not None and lo is not None and hi is not None \
                    and not (lo <= default <= hi):
                warnings.append(
                    f"slider '{label}': default {default} outside "
                    f"[{lo}, {hi}]")

    # --- wires ---
    def resolve_inputs(comp: Dict[str, Any]):
        """(known input names | None, port count | None) of a wire target."""
        ctype = (comp.get("type") or "").lower()
        if ctype in _SCRIPT_TYPES:
            inputs = list(comp.get("inputs") or [])
            return inputs, len(inputs)
        if ctype in _PREVIEW_TYPES:
            return list(_PREVIEW_INPUTS), len(_PREVIEW_INPUTS)
        if ctype in _SDK_TYPES:
            entry = comp.get("_catalog")
            if entry is None:
                return None, None
            ports = entry.get("in") or []
            return _port_names(ports), len(ports)
        return [], 0  # slider/toggle/panel/swatch have no inputs

    def resolve_outputs(comp: Dict[str, Any]) -> Optional[List[str]]:
        ctype = (comp.get("type") or "").lower()
        if ctype in _SCRIPT_TYPES:
            return _script_outputs(comp)
        if ctype in _SDK_TYPES:
            entry = comp.get("_catalog")
            return _port_names(entry.get("out")) if entry else None
        return None  # sliders etc. emit their single value

    for i, wire in enumerate(wires):
        src_name = wire.get("from")
        dst_name = wire.get("to")
        label = f"wire #{i} ({src_name!r} → {dst_name!r})"
        src = by_name.get(src_name)
        dst = by_name.get(dst_name)
        if src is None:
            errors.append(f"{label}: source component '{src_name}' does "
                          "not exist")
        if dst is None:
            errors.append(f"{label}: target component '{dst_name}' does "
                          "not exist")
        if src is None or dst is None:
            continue

        to_input = wire.get("to_input")
        known_inputs, port_count = resolve_inputs(dst)
        if known_inputs is not None:
            if port_count == 0:
                errors.append(
                    f"{label}: target '{dst_name}' "
                    f"({dst.get('type')}) accepts no wire inputs")
            elif isinstance(to_input, int):
                if not (0 <= to_input < port_count):
                    errors.append(
                        f"{label}: input index {to_input} out of range — "
                        f"target has {port_count} input(s): {known_inputs}")
            elif to_input is not None and str(to_input) not in known_inputs:
                errors.append(
                    f"{label}: target has no input '{to_input}' — known: "
                    f"{known_inputs}")

        from_output = wire.get("from_output")
        if from_output is not None and not isinstance(from_output, int):
            known_outputs = resolve_outputs(src)
            if known_outputs is not None and str(from_output) not in known_outputs:
                errors.append(
                    f"{label}: source has no output '{from_output}' — "
                    f"known: {known_outputs}")

    # --- headless reality check ---
    if any((c.get("type") or "").lower() in _SCRIPT_TYPES
           for c in components):
        warnings.append(
            "definition contains script components — these do NOT solve in "
            "headless GH on Rhino 8 (build_and_bake_gh will bake nothing): "
            "use build_and_bake_recipe / native components, or run via the "
            "Grasshopper editor / Compute Platform")

    return {"valid": not errors, "errors": errors, "warnings": warnings}
