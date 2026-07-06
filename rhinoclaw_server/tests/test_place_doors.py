"""Tests for the place_doors vertical (NEXT-LEVEL-PLAN 1.3).

Three layers:
- the pure shared core (`utils/door_batch.py`) — no mocks needed,
- the player runner (`utils/gh_player.py`) against a scripted fake plugin,
- the MCP tool (`tools/place_doors.py`) — response contract.
"""
import json
from unittest.mock import MagicMock, patch

PRINT = "Script successfully executed! Print output: "


# --- Layer 1: shared door-batch core (pure) ---

def test_normalize_maps_floorplan_vocabulary():
    from rhinoclaw.utils.door_batch import normalize_door_item

    item = {"id": "RT01", "pt": [1, 2, 3], "rotation": 90,
            "lichtbreite": 900, "wall_axis": "x", "Custom": 7}
    out = normalize_door_item(item)

    assert out == {"Point": [1, 2, 3], "Rotation": 90,
                   "Lichtbreite": 900, "WallAxis": "x", "Custom": 7}
    assert "id" not in out


def test_batch_auto_groups_under_id_and_echoes_judge_metadata():
    from rhinoclaw.utils.door_batch import run_doors_batch

    seen = []

    def runner(definition, params):
        seen.append(dict(params))
        return {"status": "success", "objects_created": 2,
                "created_guids": ["g1", "g2"], "rotation_applied": 90,
                "group": params.get("Group"), "layer": None,
                "baked_bbox": [[0, 0, 0], [1, 1, 1]]}

    batch = run_doors_batch(
        "C:/door.gh",
        [{"id": "RT01", "pt": [0, 0, 0], "rotation": 90,
          "lichtbreite": 900, "wall_axis": "y"}],
        runner=runner,
    )

    # WallAxis is judge metadata: never sent to the player, echoed in the result.
    assert "WallAxis" not in seen[0]
    assert seen[0]["Group"] == "RT01"  # auto_group default
    door = batch["doors"][0]
    assert door["wall_axis"] == "y"
    assert door["width_requested"] == 900
    assert door["baked_bbox"] == [[0, 0, 0], [1, 1, 1]]
    assert door["object_ids"] == ["g1", "g2"]
    assert batch["status"] == "success"
    assert batch["succeeded"] == 1


def test_batch_continue_on_error_keeps_going():
    from rhinoclaw.utils.door_batch import run_doors_batch

    def runner(definition, params):
        if params.get("Point") == [0, 0, 0]:
            raise RuntimeError("player exploded")
        return {"status": "success", "objects_created": 1,
                "created_guids": ["g"], "bbox": [[0, 0, 0], [1, 1, 1]]}

    batch = run_doors_batch(
        "C:/door.gh",
        [{"id": "A", "pt": [0, 0, 0]}, {"id": "B", "pt": [5, 0, 0]}],
        runner=runner,
    )

    assert batch["status"] == "partial"
    assert batch["total"] == 2
    assert batch["succeeded"] == 1
    assert batch["doors"][0] == {"id": "A", "status": "error",
                                 "message": "player exploded"}
    # legacy `bbox` falls through to baked_bbox
    assert batch["doors"][1]["baked_bbox"] == [[0, 0, 0], [1, 1, 1]]


def test_batch_aborts_without_continue_on_error():
    from rhinoclaw.utils.door_batch import run_doors_batch

    def runner(definition, params):
        raise RuntimeError("boom")

    batch = run_doors_batch(
        "C:/door.gh", [{"id": "A"}], runner=runner, continue_on_error=False,
    )
    assert batch["status"] == "error"
    assert "boom" in batch["message"]


def test_batch_rejects_empty_items():
    from rhinoclaw.utils.door_batch import run_doors_batch

    batch = run_doors_batch("C:/door.gh", [], runner=lambda f, p: {})
    assert batch["status"] == "error"


# --- Layer 2: the player runner against a scripted fake plugin ---

class FakeRhino:
    """Scripted plugin connection: dispatches send_command by content."""

    def __init__(self, prompts, before_ids, after_ids, bboxes,
                 file_exists=True):
        self.prompts = iter(prompts)
        self.ids = iter([before_ids, after_ids])
        self.bboxes = bboxes
        self.file_exists = file_exists
        self.sent_inputs = []
        self.rotated = []
        self.grouped = []
        self.layered = []

    def send_command(self, command, params=None, timeout=None):
        params = params or {}
        if command == "load_grasshopper_definition":
            return {"definition_id": "d1", "parameters": [
                {"nickname": "Lichtbreite", "type": "Number", "value": 800},
            ]}
        if command == "unload_grasshopper_definition":
            return {}
        if command == "get_command_history":
            return {"command_prompt": next(self.prompts, "Command")}
        if command == "get_objects_info":
            return {"count": len(params["ids"]), "results": [
                {"geometry_details": {"bounding_box": b}} for b in self.bboxes
            ]}
        if command == "execute_rhinoscript_python_code":
            code = params["code"]
            if "os.path.exists" in code:
                return PRINT + ("1" if self.file_exists else "0")
            if "rs.AllObjects()" in code:
                return PRINT + ",".join(next(self.ids))
            if "GrasshopperPlayer" in code:
                return PRINT
            if "RotateObjects" in code:
                self.rotated.append(code)
                return PRINT + "OK"
            if "AddObjectsToGroup" in code:
                self.grouped.append(code)
                return PRINT + "RT01"
            if "ObjectLayer" in code:
                self.layered.append(code)
                return PRINT + "2"
            if "SendKeystrokes" in code:
                self.sent_inputs.append(code)
                return PRINT
        raise AssertionError(f"unexpected command {command}")


def test_runner_diffs_guids_postprocesses_and_reads_real_bbox():
    from rhinoclaw.utils.gh_player import run_player_for_door

    rhino = FakeRhino(
        prompts=["Lichtbreite <800>", "Get Point ( Undo )", "Command"],
        before_ids=["old-1"],
        after_ids=["old-1", "new-1", "new-2"],
        bboxes=[{"min": [0, 0, 0], "max": [1000, 100, 2100]},
                {"min": [-50, -50, 0], "max": [900, 80, 2000]}],
    )

    result = run_player_for_door(
        rhino,
        "C:/door.gh",
        {"Point": [1000, 500, 0], "Lichtbreite": 900,
         "Rotation": 90, "Group": "RT01", "Layer": "Doors"},
        sleep=lambda s: None,
    )

    assert result["status"] == "success"
    assert result["created_guids"] == ["new-1", "new-2"]
    assert result["objects_created"] == 2
    # post-processing ran: layer first, then rotation around the placement
    # point, then grouping
    assert result["layer"] == "Doors"
    assert result["rotation_applied"] == 90
    assert "(1000.0, 500.0, 0.0)" in rhino.rotated[0]
    assert result["group"] == "RT01"
    # baked_bbox is the union of get_objects_info boxes — real geometry
    assert result["baked_bbox"] == [[-50, -50, 0], [1000, 100, 2100]]
    # the prompt loop fed our custom width and the point
    fed = " ".join(rhino.sent_inputs)
    assert "900" in fed
    assert "1000,500,0" in fed.replace(" ", "")


def test_runner_no_new_objects_reports_no_geometry():
    from rhinoclaw.utils.gh_player import run_player_for_door

    rhino = FakeRhino(
        prompts=["Lichtbreite <800>", "Command"],
        before_ids=["old-1"],
        after_ids=["old-1"],
        bboxes=[],
    )
    result = run_player_for_door(rhino, "C:/door.gh", {"Lichtbreite": 900},
                                 sleep=lambda s: None)

    # 'no_geometry', not a hollow 'success' — the batch counts it as failed.
    assert result["status"] == "no_geometry"
    assert result["objects_created"] == 0
    assert result["baked_bbox"] is None
    assert result["rotation_applied"] == 0.0


def test_runner_fails_fast_when_rhino_cannot_see_the_definition():
    import pytest

    from rhinoclaw.utils.door_batch import run_doors_batch
    from rhinoclaw.utils.gh_player import run_player_for_door

    rhino = FakeRhino(prompts=[], before_ids=[], after_ids=[], bboxes=[],
                      file_exists=False)

    # Runner level: immediate FileNotFoundError, no player run, no timeout.
    with pytest.raises(FileNotFoundError, match="visible to the WINDOWS"):
        run_player_for_door(rhino, "C:/missing/door.gh", {"Lichtbreite": 900},
                            sleep=lambda s: None)
    assert rhino.sent_inputs == []  # the player was never started

    # Batch level: surfaces as a per-door error entry with the message.
    rhino2 = FakeRhino(prompts=[], before_ids=[], after_ids=[], bboxes=[],
                       file_exists=False)
    batch = run_doors_batch(
        "C:/missing/door.gh", [{"id": "RT01", "pt": [0, 0, 0]}],
        runner=lambda f, p: run_player_for_door(rhino2, f, p,
                                                sleep=lambda s: None),
    )
    assert batch["status"] == "partial"
    assert batch["doors"][0]["status"] == "error"
    assert "not found by Rhino" in batch["doors"][0]["message"]


def test_parse_prompt_variants():
    from rhinoclaw.utils.gh_player import parse_prompt

    assert parse_prompt("Lichthoehe <2100>") == ("Lichthoehe", "2100")
    assert parse_prompt("RahmenbreiteL <120> ( Undo )") == ("RahmenbreiteL", "120")
    assert parse_prompt("Get Point ( Undo )") == ("Point", None)
    assert parse_prompt("Bandseite:") == ("Bandseite", None)


def test_union_bbox_handles_missing_boxes():
    from rhinoclaw.utils.gh_player import union_bbox

    assert union_bbox({"results": []}) is None
    assert union_bbox({"results": [
        {"geometry_details": {"bounding_box": {"min": [0, 0, 0], "max": [1, 1, 1]}}},
        {"geometry_details": {}},
        {"geometry_details": {"bounding_box": {"min": [-1, 0, 0], "max": [2, 0.5, 3]}}},
    ]}) == [[-1, 0, 0], [2, 1, 3]]


# --- Layer 3: the MCP tool response contract ---

def _patched_tool(run_result):
    mock_runner = MagicMock(return_value=run_result)
    return (
        patch("rhinoclaw.tools.place_doors.get_rhino_connection",
              return_value=MagicMock()),
        patch("rhinoclaw.tools.place_doors.run_player_for_door", mock_runner),
        mock_runner,
    )


def test_tool_returns_plan_contract_fields():
    from rhinoclaw.tools.place_doors import place_doors

    conn_patch, runner_patch, mock_runner = _patched_tool({
        "status": "success", "objects_created": 3,
        "created_guids": ["a", "b", "c"], "rotation_applied": 180,
        "group": "RT07", "layer": "Doors",
        "baked_bbox": [[0, 0, 0], [900, 100, 2100]],
    })
    with conn_patch, runner_patch:
        result = place_doors(
            MagicMock(),
            "C:/proj/Rahmentuer_UD5.gh",
            [{"id": "RT07", "pt": [0, 0, 0], "rotation": 180,
              "lichtbreite": 900, "wall_axis": "x"}],
            defaults={"lichthoehe": 2100},
        )

    data = json.loads(result)
    assert data["success"] is True
    [door] = data["data"]["doors"]
    for key in ("id", "status", "object_ids", "baked_bbox", "rotation_applied",
                "point", "width_requested", "wall_axis", "group", "layer"):
        assert key in door, f"missing contract key {key}"
    assert door["object_ids"] == ["a", "b", "c"]
    assert door["baked_bbox"] == [[0, 0, 0], [900, 100, 2100]]
    assert door["wall_axis"] == "x"
    assert door["width_requested"] == 900
    # defaults were merged into the player params
    sent_params = mock_runner.call_args[0][2]
    assert sent_params["Lichthoehe"] == 2100
    assert "WallAxis" not in sent_params
    assert "1/1" in data["message"]


def test_tool_rejects_bad_definition_and_empty_items():
    from rhinoclaw.tools.place_doors import place_doors

    data = json.loads(place_doors(MagicMock(), "C:/door.txt", [{"id": "A"}]))
    assert data["success"] is False

    data = json.loads(place_doors(MagicMock(), "C:/door.gh", []))
    assert data["success"] is False


def test_tool_partial_batch_passes_through():
    from rhinoclaw.tools.place_doors import place_doors

    results = iter([
        RuntimeError("door 1 failed"),
        {"status": "success", "objects_created": 1, "created_guids": ["g"],
         "baked_bbox": [[0, 0, 0], [1, 1, 1]]},
    ])

    def runner(rhino, definition, params, timeout):
        value = next(results)
        if isinstance(value, Exception):
            raise value
        return value

    with patch("rhinoclaw.tools.place_doors.get_rhino_connection",
               return_value=MagicMock()), \
         patch("rhinoclaw.tools.place_doors.run_player_for_door", runner):
        result = place_doors(
            MagicMock(), "C:/door.gh",
            [{"id": "A"}, {"id": "B", "lichtbreite": 800}],
        )

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["status"] == "partial"
    assert data["data"]["doors"][0]["status"] == "error"
    assert data["data"]["doors"][1]["object_count"] == 1
