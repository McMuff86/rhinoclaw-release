"""Tests for the build_and_bake_gh tool — the one-shot author→solve→bake path."""
import json
from unittest.mock import MagicMock, patch

SLIDER = {"type": "slider", "name": "Radius", "default": 5}
SCRIPT = {"type": "python3_script", "name": "Sph", "code": "a = Radius", "inputs": ["Radius"]}
WIRE = {"from": "Radius", "to": "Sph", "to_input": "Radius"}
CATALOG_OK = {
    "pass": True,
    "schema_version": 1,
    "global_match": True,
    "scope": "full_catalog",
    "authoring_search_complete": True,
    "evidence": {
        "contract": {
            "schema_version": 1,
            "component_count": 2534,
            "proxy_guid_sha256": "a" * 64,
            "component_contract_sha256": "b" * 64,
        },
        "runtime": {"proxy_count": 2534, "proxy_guid_sha256": "a" * 64},
        "used_component_count": 0,
        "used_components": [],
    },
}


def _verified(result):
    return {**result, "catalog_verification": CATALOG_OK}


class TestBuildAndBakeGh:
    def test_success_returns_baked_ids(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified({
            "file_path": "C:/test/sph.gh",
            "layer": "Spheres",
            "baked_count": 2,
            "baked_ids": ["guid-1", "guid-2"],
            "status": "success",
        })
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = build_and_bake_gh(
                MagicMock(), "C:/test/sph.gh", [SLIDER, SCRIPT], [WIRE], layer="Spheres"
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["baked_count"] == 2
        assert data["data"]["baked_ids"] == ["guid-1", "guid-2"]
        cmd, params = mock_rhino.send_command.call_args[0]
        assert cmd == "build_and_bake_gh"
        assert params["layer"] == "Spheres"
        assert params["wires"] == [WIRE]

    def test_no_geometry_status_passes_through(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified({
            "file_path": "C:/test/sph.gh",
            "layer": "GH_Bake",
            "baked_count": 0,
            "baked_ids": [],
            "status": "no_geometry",
        })
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = build_and_bake_gh(MagicMock(), "C:/test/sph.gh", [SCRIPT])

        data = json.loads(result)
        # Transport success, but the agent can see nothing actually baked.
        assert data["success"] is True
        assert data["data"]["status"] == "no_geometry"
        assert data["data"]["baked_count"] == 0
        assert "no_geometry" in data["message"]

    def test_material_forwarded_when_given(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified(
            {"status": "success", "baked_count": 1}
        )
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
            return_value=mock_rhino,
        ):
            build_and_bake_gh(
                MagicMock(), "C:/test/sph.gh", [SLIDER], material="Glass"
            )

        _, params = mock_rhino.send_command.call_args[0]
        assert params["material"] == "Glass"
        assert params["layer"] == "GH_Bake"  # default

    def test_bake_output_defaults_to_a(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified(
            {"status": "success", "baked_count": 1}
        )
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
            return_value=mock_rhino,
        ):
            build_and_bake_gh(MagicMock(), "C:/test/sph.gh", [SLIDER])

        _, params = mock_rhino.send_command.call_args[0]
        assert params["bake_output"] == "a"

    def test_bake_output_forwarded(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified(
            {"status": "success", "baked_count": 1}
        )
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
            return_value=mock_rhino,
        ):
            # native Center Box bakes its "B" output, not "a"
            build_and_bake_gh(MagicMock(), "C:/test/box.gh", [SLIDER], bake_output="B")

        _, params = mock_rhino.send_command.call_args[0]
        assert params["bake_output"] == "B"

    def test_material_omitted_when_none(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified(
            {"status": "success", "baked_count": 1}
        )
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
            return_value=mock_rhino,
        ):
            build_and_bake_gh(MagicMock(), "C:/test/sph.gh", [SLIDER])

        _, params = mock_rhino.send_command.call_args[0]
        assert "material" not in params

    def test_old_plugin_success_without_verification_fails_closed(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "status": "success",
            "baked_count": 1,
            "baked_ids": ["11111111-1111-4111-8111-111111111111"],
        }
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = build_and_bake_gh(
                MagicMock(), "C:/test/old.gh", [SLIDER]
            )

        data = json.loads(result)
        assert data["success"] is False
        assert data["code"] == "VERIFICATION_FAILED"
        assert data["data"]["catalog_verification"] is None
        assert data["data"]["mutation_scope"] == "unknown_old_plugin_response"

    def test_empty_path_fails(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        data = json.loads(build_and_bake_gh(MagicMock(), "", [SLIDER]))
        assert data["success"] is False
        assert "file_path is required" in data["message"]

    def test_wrong_extension_fails(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        data = json.loads(build_and_bake_gh(MagicMock(), "C:/test/sph.3dm", [SLIDER]))
        assert data["success"] is False
        assert ".gh" in data["message"]

    def test_empty_components_fails(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        data = json.loads(build_and_bake_gh(MagicMock(), "C:/test/sph.gh", []))
        assert data["success"] is False
        assert "components" in data["message"]

    def test_unknown_sdk_guid_fails_before_mutating_roundtrip(self):
        from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

        unknown = {
            "type": "sdk_component",
            "name": "Unknown",
            "guid": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        }
        with patch(
            "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
        ) as connection:
            data = json.loads(build_and_bake_gh(
                MagicMock(), "C:/test/unsafe.gh", [unknown]))

        assert data["success"] is False
        assert data["code"] == "INVALID_PARAMS"
        assert data["data"]["lint"]["valid"] is False
        assert any("not in the component catalog" in value
                   for value in data["data"]["lint"]["errors"])
        connection.assert_not_called()
