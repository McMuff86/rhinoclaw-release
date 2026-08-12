"""Focused contracts for verified Slab/Space Style creation."""

import ast
import json
from unittest.mock import MagicMock, patch


PATCH = "rhinoclaw.tools.visualarq.get_rhino_connection"
PRINT = "Script successfully executed! Print output: "


def _rhino(va_result):
    rhino = MagicMock()
    rhino.send_command.return_value = (
        PRINT + "RESULT:" + json.dumps(va_result)
    )
    return rhino


def _params_from_code(code):
    marker = "params_reader = JsonTextReader(System.IO.StringReader("
    line = next(line for line in code.splitlines() if marker in line)
    literal = line.split(marker, 1)[1].rsplit("))", 1)[0]
    return json.loads(ast.literal_eval(literal))


def test_slab_layers_normalize_and_invalid_requests_never_reach_rhino():
    from rhinoclaw.tools.visualarq import (
        _normalize_slab_layers,
        va_create_slab_style,
    )

    assert _normalize_slab_layers([
        {"name": " Finish ", "thickness": 20},
        {"name": "Structure", "thickness": 220, "type": "CORE"},
    ]) == [
        {"name": "Finish", "thickness": 20.0, "type": "normal"},
        {"name": "Structure", "thickness": 220.0, "type": "core"},
    ]

    invalid_layers = (
        [],
        [{"name": "", "thickness": 10}],
        [{"name": "A", "thickness": 0}],
        [{"name": "A", "thickness": 10, "type": "insulation"}],
        [
            {"name": "A", "thickness": 10},
            {"name": "a", "thickness": 20},
        ],
        [{"name": "A", "thickness": 10, "unexpected": True}],
    )
    with patch(PATCH) as connection:
        results = [
            json.loads(va_create_slab_style(MagicMock(), "Test", layers))
            for layers in invalid_layers
        ]

    assert all(result["success"] is False for result in results)
    assert all(result["code"] == "INVALID_PARAMS" for result in results)
    connection.assert_not_called()


def test_create_slab_style_has_exact_preflight_delta_and_cleanup_contract():
    from rhinoclaw.tools.visualarq import va_create_slab_style

    style_id = "11111111-1111-1111-1111-111111111111"
    layer_id = "22222222-2222-2222-2222-222222222222"
    rhino = _rhino({
        "status": "success",
        "style_id": style_id,
        "requested": {
            "name": "RC_Slab",
            "layers": [
                {"name": "Structure", "thickness": 220.0, "type": "core"},
            ],
            "total_layer_thickness": 220.0,
        },
        "actual": {
            "id": style_id,
            "kind": "slab",
            "name": "RC_Slab",
            "product_count": 0,
            "layers": [{
                "id": layer_id,
                "name": "Structure",
                "thickness": 220.0,
                "type": "core",
            }],
        },
        "created_layer_ids": [layer_id],
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_create_slab_style(
            MagicMock(),
            "  RC_Slab  ",
            [{"name": " Structure ", "thickness": 220, "type": "CORE"}],
        ))

    assert response["success"] is True
    assert response["data"]["style_id"] == style_id
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_slab_style>", "exec")
    params = _params_from_code(code)
    assert params == {
        "kind": "slab",
        "name": "RC_Slab",
        "layers": [
            {"name": "Structure", "thickness": 220.0, "type": "core"},
        ],
    }

    for exact_shape in (
        '["AddSlabStyle", ["System.String", "System.Guid"],',
        '["AddSlabLayer", ["System.Guid", "System.String", "System.Double"],',
        '["SetSlabLayerType", [',
        '"VisualARQ.Script+SlabLayerType"],',
        '["DeleteStyle", ["System.Guid"], "System.Boolean"]',
        '["DeleteStyleComponent", ["System.Guid"], "System.Boolean"]',
    ):
        assert exact_shape in code
    failed_shapes = code.index("if failed_shapes:")
    baseline = code.index("global_before = va_global_style_inventory()")
    add_style = code.index("created_id = va.AddSlabStyle(")
    assert failed_shapes < baseline < add_style
    assert 'global_before["read_complete"] is not True' in code
    assert 'va_text_key(entry["name"]) == va_text_key(requested_name)' in code
    assert "style_add_contract = va_global_style_create_contract(" in code
    assert "final_delta_contract = va_global_style_create_contract(" in code
    assert 'actual.get("product_count") == 0' in code
    assert '"layer_ids_and_order_exact"' in code
    assert '"total_thickness_exact"' in code
    assert '"global_additive_delta_exact"' in code

    first_delete = code.index('"operation": "DeleteStyle",', add_style)
    component_delete = code.index(
        '"DeleteStyleComponent",', first_delete)
    retry_delete = code.index('"operation": "DeleteStyleRetry",', first_delete)
    assert first_delete < component_delete < retry_delete
    assert '"component_owners"].get(' in code
    assert "va.GetParentStyleComponent(" in code
    assert "global_cleanup == global_before" in code
    assert '"PARTIAL_MUTATION"' in code


def test_create_space_style_specializes_shared_verified_vertical():
    from rhinoclaw.tools.visualarq import va_create_space_style

    style_id = "33333333-3333-3333-3333-333333333333"
    rhino = _rhino({
        "status": "success",
        "style_id": style_id,
        "requested": {"name": "RC_Space", "layers": None},
        "actual": {
            "id": style_id,
            "kind": "space",
            "name": "RC_Space",
            "product_count": 0,
        },
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_create_space_style(
            MagicMock(), "  RC_Space  "))

    assert response["success"] is True
    assert response["data"]["actual"]["kind"] == "space"
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_space_style>", "exec")
    assert _params_from_code(code) == {
        "kind": "space", "name": "RC_Space", "layers": None,
    }
    assert '["AddSpaceStyle", ["System.String"], "System.Guid"]' in code
    assert '["IsSpaceStyle", ["System.Guid"], "System.Boolean"]' in code
    assert 'created_id = va.AddSpaceStyle(requested_name)' in code
    assert 'inventory_method = "GetAllSlabStyleIds" if kind == "slab"' in code
    assert 'else "GetAllSpaceStyleIds"' in code
    assert 'global_cleanup == global_before' in code


def test_partial_mutation_from_failed_style_cleanup_is_preserved():
    from rhinoclaw.tools.visualarq import va_create_slab_style

    style_id = "44444444-4444-4444-4444-444444444444"
    rhino = _rhino({
        "status": "error",
        "code": "PARTIAL_MUTATION",
        "message": "Slab style creation failed: rollback incomplete",
        "created_style_id": style_id,
        "ownership_verified": True,
        "cleanup_attempts": [
            {"operation": "DeleteStyle", "result": False},
            {"operation": "DeleteStyleComponent", "result": True},
            {"operation": "DeleteStyleRetry", "result": False},
        ],
        "cleanup_verified": False,
        "residual_style_ids": [style_id],
    })
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_create_slab_style(
            MagicMock(), "Only Slab", [
                {"name": "Core", "thickness": 200, "type": "core"},
            ]))

    assert response["success"] is False
    assert response["code"] == "PARTIAL_MUTATION"
    assert response["data"]["cleanup_verified"] is False
    assert response["data"]["residual_style_ids"] == [style_id]


def test_status_and_package_exports_advertise_style_creation():
    import rhinoclaw
    from rhinoclaw.tools.visualarq import va_status

    for name in ("va_create_slab_style", "va_create_space_style"):
        assert callable(getattr(rhinoclaw, name))

    rhino = _rhino({
        "available": True,
        "capabilities": {
            "slab_style_create_api": True,
            "space_style_create_api": True,
        },
        "wall_styles": 0,
        "door_styles": 0,
        "window_styles": 0,
        "slab_styles": 0,
        "space_styles": 0,
        "levels": 0,
    })
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_status(MagicMock()))

    assert response["success"] is True
    status_code = rhino.send_command.call_args[0][1]["code"]
    compile(status_code, "<va_status>", "exec")
    for method_name in (
        "AddSlabStyle",
        "AddSlabLayer",
        "SetSlabLayerType",
        "AddSpaceStyle",
        "IsSlabStyle",
        "IsSpaceStyle",
    ):
        assert f'"{method_name}"' in status_code
    assert '"slab_style_create_api"' in status_code
    assert '"space_style_create_api"' in status_code
    assert '"style_creation_shape_contracts"' in status_code
    assert '"GetAllBeamStyle": va_exact_method_shape(' in status_code
