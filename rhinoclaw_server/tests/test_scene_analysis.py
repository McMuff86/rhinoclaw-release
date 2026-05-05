"""Tests for the scene-analysis MCP tools (find_nearby / is_inside /
get_relationships / scene_summary)."""
import json
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
#  find_nearby
# ---------------------------------------------------------------------------

class TestFindNearby:
    @patch("rhinoclaw.tools.find_nearby.get_rhino_connection")
    def test_basic_call(self, mock_get_conn):
        from rhinoclaw.tools.find_nearby import find_nearby
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 2,
            "search_point": [0.0, 0.0, 0.0],
            "search_radius": 5.0,
            "distance_metric": "bbox_center",
            "results": [
                {"id": "g1", "name": "BoxA", "layer": "Default", "type": "Brep", "distance": 1.5},
                {"id": "g2", "name": "BoxB", "layer": "Default", "type": "Brep", "distance": 4.7},
            ],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = find_nearby(ctx, point=[0, 0, 0], radius=5.0)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["count"] == 2
        mock_rhino.send_command.assert_called_once_with(
            "find_nearby",
            {"point": [0, 0, 0], "radius": 5.0, "by": "center", "limit": 100},
        )

    def test_invalid_point(self):
        from rhinoclaw.tools.find_nearby import find_nearby
        ctx = MagicMock()
        result = find_nearby(ctx, point=[0, 0], radius=5.0)
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_invalid_radius(self):
        from rhinoclaw.tools.find_nearby import find_nearby
        ctx = MagicMock()
        result = find_nearby(ctx, point=[0, 0, 0], radius=0)
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    @patch("rhinoclaw.tools.find_nearby.get_rhino_connection")
    def test_with_layer_filter(self, mock_get_conn):
        from rhinoclaw.tools.find_nearby import find_nearby
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 0, "results": [], "search_point": [1, 2, 3],
            "search_radius": 2.0, "distance_metric": "closest_point_on_bbox",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        find_nearby(ctx, point=[1, 2, 3], radius=2.0, by="closest", layer="Walls", limit=10)

        mock_rhino.send_command.assert_called_once_with(
            "find_nearby",
            {"point": [1, 2, 3], "radius": 2.0, "by": "closest", "limit": 10, "layer": "Walls"},
        )


# ---------------------------------------------------------------------------
#  is_inside
# ---------------------------------------------------------------------------

class TestIsInside:
    @patch("rhinoclaw.tools.is_inside.get_rhino_connection")
    def test_inside_brep_volume(self, mock_get_conn):
        from rhinoclaw.tools.is_inside import is_inside
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "is_inside": True,
            "method": "brep_point_in_volume",
            "object_id": "abc",
            "container_id": "xyz",
            "strictly_inside": True,
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = is_inside(ctx, object_id="abc", container_id="xyz")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["is_inside"] is True
        assert "inside" in parsed["message"]

    @patch("rhinoclaw.tools.is_inside.get_rhino_connection")
    def test_bbox_reject(self, mock_get_conn):
        from rhinoclaw.tools.is_inside import is_inside
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "is_inside": False,
            "method": "bbox_reject",
            "object_id": "abc",
            "container_id": "xyz",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = is_inside(ctx, object_id="abc", container_id="xyz", strictly_inside=False)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["is_inside"] is False
        assert "outside" in parsed["message"]

    def test_missing_ids(self):
        from rhinoclaw.tools.is_inside import is_inside
        ctx = MagicMock()
        result = is_inside(ctx, object_id="", container_id="xyz")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
#  get_relationships
# ---------------------------------------------------------------------------

class TestGetRelationships:
    @patch("rhinoclaw.tools.get_relationships.get_rhino_connection")
    def test_buckets_returned(self, mock_get_conn):
        from rhinoclaw.tools.get_relationships import get_relationships
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "object_id": "target",
            "touch_tolerance": 0.01,
            "touching":    [{"id": "t1", "name": "Touch1", "layer": "L", "type": "Brep"}],
            "overlapping": [{"id": "o1", "name": "Over1",  "layer": "L", "type": "Brep"}],
            "aligned": {
                "x_min": [{"id": "a1", "name": "A1", "layer": "L", "type": "Brep"}],
                "x_max": [], "y_min": [], "y_max": [], "z_min": [], "z_max": [],
            },
            "counts": {"touching": 1, "overlapping": 1, "aligned_total": 1},
            "limit": 50,
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = get_relationships(ctx, object_id="target")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["counts"]["touching"] == 1
        assert "1 touching" in parsed["message"]
        assert "1 overlapping" in parsed["message"]

    def test_missing_object_id(self):
        from rhinoclaw.tools.get_relationships import get_relationships
        ctx = MagicMock()
        result = get_relationships(ctx, object_id="")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
#  scene_summary
# ---------------------------------------------------------------------------

class TestSceneSummary:
    @patch("rhinoclaw.tools.scene_summary.get_rhino_connection")
    def test_summary_with_layers_and_types(self, mock_get_conn):
        from rhinoclaw.tools.scene_summary import scene_summary
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "object_count": 47,
            "doc_bbox": {
                "min": [0, 0, 0], "max": [10, 10, 5],
                "size": [10, 10, 5], "center": [5, 5, 2.5],
            },
            "types":  {"Brep": 30, "Curve": 12, "Mesh": 5},
            "layers": {
                "Default": {"count": 25, "bbox": {"min": [0,0,0], "max": [5,5,5],
                                                  "size":[5,5,5], "center":[2.5,2.5,2.5]}},
                "Walls":   {"count": 22, "bbox": {"min": [5,5,0], "max": [10,10,5],
                                                  "size":[5,5,5], "center":[7.5,7.5,2.5]}},
            },
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = scene_summary(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["object_count"] == 47
        assert parsed["data"]["types"]["Brep"] == 30
        assert "47 object" in parsed["message"]
        mock_rhino.send_command.assert_called_once_with(
            "scene_summary", {"include_layers": True, "include_types": True},
        )

    @patch("rhinoclaw.tools.scene_summary.get_rhino_connection")
    def test_summary_minimal(self, mock_get_conn):
        from rhinoclaw.tools.scene_summary import scene_summary
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "object_count": 0, "doc_bbox": None,
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        scene_summary(ctx, include_layers=False, include_types=False)
        mock_rhino.send_command.assert_called_once_with(
            "scene_summary", {"include_layers": False, "include_types": False},
        )

    @patch("rhinoclaw.tools.scene_summary.get_rhino_connection")
    def test_error_propagates(self, mock_get_conn):
        from rhinoclaw.tools.scene_summary import scene_summary
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("No active document.")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = scene_summary(ctx)
        parsed = json.loads(result)
        assert parsed["success"] is False
