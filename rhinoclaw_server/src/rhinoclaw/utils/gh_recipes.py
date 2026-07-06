"""Composition recipes — named, catalog-grounded GH graph templates (G4/2.3).

Each recipe instantiates a small SDK-native component graph (no script
components → solves headless) from numeric params, plus the MEASURABLE
expectation that the G3 loop (`build_gh_interactive`) verifies after the
bake. The expectation is computed from the same params — so "verified"
means re-measured geometry matched the recipe's own contract, never that
the bake merely returned success.

GUIDs come from the introspected component catalog
(`static/gh_components.json`); the lint stage re-verifies every GUID on
each instantiation, so catalog drift after a Rhino/plugin update fails
loudly instead of baking garbage.

Pure Python, no Rhino — the registry must stay deterministic and
unit-testable (the plugin-side primitive recipes box/sphere/cylinder/cone
stay in C#; these compositions live here because they are authored
through the verified loop, not a plugin rebuild).
"""
from typing import Any, Callable, Dict, List, Tuple

# Catalog ground truth (Rhino 8.31 catalog, re-linted on every build):
GUID_CENTER_BOX = "28061aae-04fb-4cb5-ac45-16f3b66bc0a4"   # in B,X,Y,Z → out B
GUID_RECTANGLE = "d93100b6-d50b-40b2-831a-814659dc38e3"    # in P,X,Y,R → out R,L
GUID_EXTRUDE = "962034e9-cc27-4394-afc4-5c16e3447cf9"      # in B,D → out E
GUID_UNIT_X = "79f9fbb3-8f1d-4d9a-88a9-f7961b1012cd"       # in F → out V
GUID_UNIT_Z = "9103c240-a6a9-4223-9b42-dbd19bf38e2b"       # in F → out V
GUID_SOLID_DIFFERENCE = "fab11c30-2d9c-4d15-ab3c-2289f1ae5c21"  # in A,B → out R
GUID_LINEAR_ARRAY = "e87db220-a0a0-4d67-a405-f97fd14b2d7a"  # in G,D,N → out G,X
GUID_ORIENT = "378d0690-9da0-4dd1-ab16-1d15246e7c22"       # in G,A,B → out G,X
GUID_XY_PLANE = "17b7152b-d30d-4d50-b9ef-c9fe25576fc2"     # in O → out P
GUID_XZ_PLANE = "8cc3a196-f6a0-49ea-9ed9-0cb343a3ae64"     # in O → out P

Spec = Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]


def _sliders(values: Dict[str, float], maximum: float = 100000.0) -> List[Dict[str, Any]]:
    return [{"type": "slider", "name": name, "default": value,
             "min": 0, "max": maximum} for name, value in values.items()]


def _center_box(name: str, x: str, y: str, z: str) -> Spec:
    """Center Box wired to half-extent sliders (X/Y/Z are HALF-extents —
    the live iteration-2 lesson baked into the registry)."""
    comp = {"type": "sdk_component", "name": name, "guid": GUID_CENTER_BOX}
    wires = [{"from": x, "to": name, "to_input": "X"},
             {"from": y, "to": name, "to_input": "Y"},
             {"from": z, "to": name, "to_input": "Z"}]
    return [comp], wires


def _rect_extrude(p: Dict[str, float]) -> Spec:
    """Rectangle (number→domain coerces to [0,size]) extruded along Z."""
    x, y, h = p["x"], p["y"], p["height"]
    components = _sliders({"X": x, "Y": y, "H": h}) + [
        {"type": "sdk_component", "name": "Rect", "guid": GUID_RECTANGLE},
        {"type": "sdk_component", "name": "Dir", "guid": GUID_UNIT_Z},
        {"type": "sdk_component", "name": "Ext", "guid": GUID_EXTRUDE},
    ]
    wires = [
        {"from": "X", "to": "Rect", "to_input": "X"},
        {"from": "Y", "to": "Rect", "to_input": "Y"},
        {"from": "H", "to": "Dir", "to_input": "F"},
        {"from": "Rect", "from_output": "R", "to": "Ext", "to_input": "B"},
        {"from": "Dir", "from_output": "V", "to": "Ext", "to_input": "D"},
    ]
    return components, wires


def _rect_extrude_expect(p: Dict[str, float]) -> Dict[str, Any]:
    return {"min_count": 1,
            "bbox_min": [0, 0, 0],
            "bbox_max": [p["x"], p["y"], p["height"]],
            "dims_mm": [p["x"], p["y"], p["height"]]}


def _box_difference(p: Dict[str, float]) -> Spec:
    """Outer box minus a through-cut inner box (closed solids on both
    sides — the GH Cylinder outputs an UNCAPPED surface, which Solid
    Difference rejects; box-minus-box is the reliable native CSG)."""
    x, y, z, c = p["x"], p["y"], p["z"], p["cut"]
    box_a, wires_a = _center_box("BoxA", "X", "Y", "Z")
    box_b, wires_b = _center_box("BoxB", "C", "C", "Z2")
    components = (_sliders({"X": x, "Y": y, "Z": z, "C": c, "Z2": z * 2})
                  + box_a + box_b + [
        {"type": "sdk_component", "name": "Diff",
         "guid": GUID_SOLID_DIFFERENCE},
    ])
    wires = wires_a + wires_b + [
        {"from": "BoxA", "from_output": "B", "to": "Diff", "to_input": "A"},
        {"from": "BoxB", "from_output": "B", "to": "Diff", "to_input": "B"},
    ]
    return components, wires


def _box_difference_expect(p: Dict[str, float]) -> Dict[str, Any]:
    x, y, z = p["x"], p["y"], p["z"]
    return {"min_count": 1,
            "bbox_min": [-x, -y, -z], "bbox_max": [x, y, z],
            "dims_mm": [2 * x, 2 * y, 2 * z]}


def _box_array(p: Dict[str, float]) -> Spec:
    """Center Box arrayed N× along X."""
    x, y, z, step, n = p["x"], p["y"], p["z"], p["step"], int(p["count"])
    box, box_wires = _center_box("Box", "X", "Y", "Z")
    components = (_sliders({"X": x, "Y": y, "Z": z, "S": step})
                  + [{"type": "slider", "name": "N", "default": n,
                      "min": 1, "max": 1000, "decimals": 0}]
                  + box + [
        {"type": "sdk_component", "name": "Dir", "guid": GUID_UNIT_X},
        {"type": "sdk_component", "name": "Arr", "guid": GUID_LINEAR_ARRAY},
    ])
    wires = box_wires + [
        {"from": "S", "to": "Dir", "to_input": "F"},
        {"from": "Box", "from_output": "B", "to": "Arr", "to_input": "G"},
        {"from": "Dir", "from_output": "V", "to": "Arr", "to_input": "D"},
        {"from": "N", "to": "Arr", "to_input": "N"},
    ]
    return components, wires


def _box_array_expect(p: Dict[str, float]) -> Dict[str, Any]:
    x, y, z, step, n = p["x"], p["y"], p["z"], p["step"], int(p["count"])
    return {"min_count": n,
            "bbox_min": [-x, -y, -z],
            "bbox_max": [x + (n - 1) * step, y, z],
            "dims_mm": [2 * x + (n - 1) * step, 2 * y, 2 * z]}


def _box_orient(p: Dict[str, float]) -> Spec:
    """Center Box oriented WorldXY → WorldXZ — the measurable proof is the
    axis swap: the box's Y half-extent must land on world Z."""
    box, box_wires = _center_box("Box", "X", "Y", "Z")
    components = (_sliders({"X": p["x"], "Y": p["y"], "Z": p["z"]})
                  + box + [
        {"type": "sdk_component", "name": "From", "guid": GUID_XY_PLANE},
        {"type": "sdk_component", "name": "To", "guid": GUID_XZ_PLANE},
        {"type": "sdk_component", "name": "Ori", "guid": GUID_ORIENT},
    ])
    wires = box_wires + [
        {"from": "Box", "from_output": "B", "to": "Ori", "to_input": "G"},
        {"from": "From", "from_output": "P", "to": "Ori", "to_input": "A"},
        {"from": "To", "from_output": "P", "to": "Ori", "to_input": "B"},
    ]
    return components, wires


def _box_orient_expect(p: Dict[str, float]) -> Dict[str, Any]:
    x, y, z = p["x"], p["y"], p["z"]
    # XY→XZ: local X stays world X, local Y → world Z, normal → -Y.
    return {"min_count": 1, "dims_mm": [2 * x, 2 * z, 2 * y]}


class CompositionRecipe:
    def __init__(self, name: str, description: str,
                 defaults: Dict[str, float],
                 build: Callable[[Dict[str, float]], Spec],
                 expect: Callable[[Dict[str, float]], Dict[str, Any]]):
        self.name = name
        self.description = description
        self.defaults = defaults
        self._build = build
        self._expect = expect

    def instantiate(self, params: Dict[str, float] = None) -> Dict[str, Any]:
        """Merged params → {components, wires, expect, params}."""
        merged = dict(self.defaults)
        for key, value in (params or {}).items():
            if key not in self.defaults:
                raise ValueError(
                    f"recipe '{self.name}' has no param '{key}' — "
                    f"available: {sorted(self.defaults)}")
            merged[key] = value
        components, wires = self._build(merged)
        return {"components": components, "wires": wires,
                "expect": self._expect(merged), "params": merged}


COMPOSITION_RECIPES: Dict[str, CompositionRecipe] = {r.name: r for r in [
    CompositionRecipe(
        "rect_extrude",
        "Rectangle x×y extruded to height — the rectangle→extrude spine",
        {"x": 400.0, "y": 200.0, "height": 100.0},
        _rect_extrude, _rect_extrude_expect),
    CompositionRecipe(
        "box_difference",
        "Box (half-extents x,y,z) minus a square through-cut of half-width "
        "cut — native solid CSG",
        {"x": 200.0, "y": 100.0, "z": 50.0, "cut": 40.0},
        _box_difference, _box_difference_expect),
    CompositionRecipe(
        "box_array",
        "Box (half-extents) arrayed count× along X at step spacing",
        {"x": 50.0, "y": 50.0, "z": 50.0, "step": 150.0, "count": 4},
        _box_array, _box_array_expect),
    CompositionRecipe(
        "box_orient",
        "Box oriented WorldXY→WorldXZ — verified by the measured axis swap",
        {"x": 200.0, "y": 100.0, "z": 50.0},
        _box_orient, _box_orient_expect),
]}


def list_compositions() -> Dict[str, Any]:
    return {name: {"params": recipe.defaults,
                   "description": recipe.description,
                   "kind": "composition"}
            for name, recipe in COMPOSITION_RECIPES.items()}
