"""Source contracts for safe Grasshopper authoring and one-solve baking.

These tests pin mechanics that cannot be exercised without a loaded Rhino +
Grasshopper runtime: author-only never solves, build-and-bake solves exactly
once and consumes that same document, and .gh publication never writes
directly to the requested target.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
BUILDER = (
    ROOT / "rhinoclaw_plugin" / "Functions" / "GrasshopperDefinitionBuilder.cs"
)
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


def _source() -> str:
    return BUILDER.read_text(encoding="utf-8")


def _slice(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end, source.index(start))]


def test_author_only_skips_solve_while_build_and_bake_solves_exactly_once():
    source = _source()
    public_build = _slice(
        source,
        "public JObject BuildGrasshopperDefinition(",
        "private GrasshopperBuildSession CreateGrasshopperDefinitionSession(",
    )
    author = _slice(
        source,
        "private GrasshopperBuildSession CreateGrasshopperDefinitionSession(",
        "private static GrasshopperSolveResult GrasshopperSolveNotRequested(",
    )
    no_solve = _slice(
        source,
        "private static GrasshopperSolveResult GrasshopperSolveNotRequested(",
        "private static GrasshopperSolveResult SolveGrasshopperDefinitionOnce(",
    )
    solve = _slice(
        source,
        "private static GrasshopperSolveResult SolveGrasshopperDefinitionOnce(",
        "private static int AppendGrasshopperRuntimeMessages(",
    )
    bake = _slice(
        source,
        "public JObject BuildAndBakeGrasshopperDefinition(",
        "private static Guid BakeGoo(",
    )

    # Both public paths converge on one helper with explicit solve policy.
    assert source.count(".NewSolution(") == 1
    assert "solveRequested: false" in public_build
    assert "}\n        return buildResult;" in public_build
    assert "solveRequested: true" in bake
    assert "? SolveGrasshopperDefinitionOnce(doc)" in author
    assert ": GrasshopperSolveNotRequested(doc)" in author
    assert "SolveGrasshopperDefinitionOnce(doc)" in author
    assert author.index("WireComponents(objectMap, wire)") < author.index(
        "SolveGrasshopperDefinitionOnce(doc)"
    )
    assert author.index("SolveGrasshopperDefinitionOnce(doc)") < author.index(
        "PublishGrasshopperDefinitionAtomically(doc, filePath)"
    )
    assert author.index(
        "PublishGrasshopperDefinitionAtomically(doc, filePath)"
    ) < author.index("doc.Enabled = false")
    assert '["document_frozen_after_publication"] = true' in author
    assert '["requested"] = false' in no_solve
    assert '["solve_count"] = 0' in no_solve
    assert '["runtime_messages_collected"] = false' in no_solve
    assert "doc.NewSolution(true, GH_SolutionMode.Silent)" in solve
    assert "doc.SolutionStart +=" in solve
    assert "doc.SolutionEnd +=" in solve
    assert "solutionStartCount != 1 || solutionEndCount != 1" in solve
    assert '["requested"] = true' in solve
    assert '["solve_count"] = 1' in solve
    assert '["runtime_messages_collected"] = true' in solve
    assert '["duration_ms"] = doc.SolutionSpan.TotalMilliseconds' in solve

    assert "CreateGrasshopperDefinitionSession(" in bake
    assert "GH_Document ghDoc = buildSession.Document" in bake
    assert "ReadFromFile" not in bake
    assert "ExtractObject" not in bake
    assert "NewSolution" not in bake
    assert '["build_result"] = buildResult' in bake


def test_runtime_message_contract_is_complete_and_keeps_legacy_errors():
    source = _source()
    solve = _slice(
        source,
        "private static GrasshopperSolveResult SolveGrasshopperDefinitionOnce(",
        "private static int AppendGrasshopperRuntimeMessages(",
    )
    collect = _slice(
        source,
        "private static int AppendGrasshopperRuntimeMessages(",
        "private static JObject PublishGrasshopperDefinitionAtomically(",
    )
    author = _slice(
        source,
        "private GrasshopperBuildSession CreateGrasshopperDefinitionSession(",
        "private static GrasshopperSolveResult GrasshopperSolveNotRequested(",
    )

    # Query each level independently: RuntimeMessageLevel only reports the worst
    # level and would otherwise hide warnings/remarks when an error also exists.
    assert "GH_RuntimeMessageLevel.Remark" in solve
    assert "GH_RuntimeMessageLevel.Warning" in solve
    assert "GH_RuntimeMessageLevel.Error" in solve
    assert "RuntimeMessageLevel ==" not in source

    for field in (
        '["component"]',
        '["component_name"]',
        '["component_id"]',
        '["component_type"]',
        '["level"]',
        '["message"]',
    ):
        assert field in collect

    assert '["runtime_message_counts"]' in solve
    assert '["runtime_messages"] = solveResult.RuntimeMessages' in author
    # Existing clients still receive their historical error-only shape/status.
    assert '["errors"] = solveResult.Errors' in author
    assert '"success_with_errors"' in author
    assert "if (level == GH_RuntimeMessageLevel.Error)" in collect


def test_definition_publication_is_same_directory_atomic_and_cleans_staging():
    source = _source()
    publish = _slice(
        source,
        "private static JObject PublishGrasshopperDefinitionAtomically(",
        "#region Component Creators",
    )

    assert "string targetPath = Path.GetFullPath(filePath)" in publish
    assert "string targetDirectory = Path.GetDirectoryName(targetPath)" in publish
    assert "Path.Combine(\n            targetDirectory," in publish
    assert 'Guid.NewGuid():N}.stage.gh"' in publish

    append = publish.index('if (!archive.AppendObject(doc, "Definition"))')
    stage_write = publish.index("archive.WriteToFile(stagingPath")
    replace = publish.index("File.Replace(stagingPath, targetPath, null)")
    move = publish.index("File.Move(stagingPath, targetPath)")
    cleanup = publish.index("File.Delete(stagingPath)")
    assert append < stage_write < replace
    assert stage_write < move
    assert "WriteToFile(filePath" not in source
    assert "WriteToFile(targetPath" not in source
    assert "finally" in publish
    assert cleanup > stage_write

    for evidence in (
        '["published"] = true',
        '["atomic"] = true',
        '["same_directory"] = true',
        '["direct_target_write"] = false',
        '["compare_and_swap"] = false',
        '["foreign_target_change_detection"] = false',
        '["target_preexisted"] = targetPreexisted',
        '["staging_file_cleaned"] = stagingFileCleaned',
    ):
        assert evidence in publish

    assert "published=false; direct_target_write=false" in publish
    assert "staging_file_cleaned={cleanupDetail}" in publish
    assert "this is not compare-and-swap" in publish
    assert "File.Replace would then overwrite that newer version" in publish


def test_build_session_owns_document_server_cleanup_on_all_paths():
    source = _source()
    session = _slice(
        source,
        "private sealed class GrasshopperBuildSession",
        "private sealed class GrasshopperSolveResult",
    )
    cleanup = _slice(
        source,
        "private static JObject CleanupGrasshopperBuildDocument(",
        "public JObject BuildGrasshopperDefinition(",
    )
    author = _slice(
        source,
        "private GrasshopperBuildSession CreateGrasshopperDefinitionSession(",
        "private static GrasshopperSolveResult GrasshopperSolveNotRequested(",
    )
    bake = _slice(
        source,
        "public JObject BuildAndBakeGrasshopperDefinition(",
        "private static Guid BakeGoo(",
    )

    assert "CleanupGrasshopperBuildDocument(" in session
    assert 'BuildResult["session_cleanup"]' in session
    assert "cleanup diagnostic must not turn a completed mutating bake" in session

    remove = cleanup.index("documentServer.RemoveDocument(document)")
    readback = cleanup.index(
        "documentAbsentFromServer = !documentServer.Contains(document)"
    )
    dispose = cleanup.index("document.Dispose()")
    assert remove < readback < dispose
    assert "if (containsCheckCompleted && documentAbsentFromServer)" in cleanup
    assert '["document_removed"] = documentAbsentFromServer' in cleanup
    assert '["document_absent_from_server"] = documentAbsentFromServer' in cleanup
    assert '["complete"] = documentAbsentFromServer && documentDisposed' in cleanup

    assert "if (documentAdded)" in author
    assert "CleanupGrasshopperBuildDocument(docServer, doc)" in author

    # Both build_errors and success/no_geometry are created only after Dispose
    # has appended session_cleanup to buildResult.
    disposed_comment = bake.index(
        "The using block has disposed the session and appended independently"
    )
    assert "return JObject.FromObject" not in bake
    assert disposed_comment < bake.rindex("if (hasBuildErrors)")
    assert disposed_comment < bake.index('return new JObject', disposed_comment)
    assert bake.count('["build_result"] = buildResult') == 2


def test_author_only_wrapper_preserves_no_solve_and_publication_evidence():
    from rhinoclaw.tools.build_gh_definition import build_gh_definition

    response = {
        "file_path": "C:/test/safe.gh",
        "object_count": 1,
        "errors": [],
        "runtime_messages": [],
        "solution": {
            "requested": False,
            "solve_count": 0,
            "solution_end_count": 0,
        },
        "publication": {
            "published": True,
            "atomic": True,
            "staging_file_cleaned": True,
        },
        "catalog_verification": CATALOG_OK,
        "status": "success",
    }
    connection = MagicMock()
    connection.send_command.return_value = response

    with patch(
        "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
        return_value=connection,
    ):
        result = build_gh_definition(
            MagicMock(),
            "C:/test/safe.gh",
            [{"type": "slider", "name": "Width", "default": 10}],
        )

    data = json.loads(result)["data"]
    assert data["solution"]["requested"] is False
    assert data["solution"]["solve_count"] == 0
    assert data["runtime_messages"] == []
    assert data["publication"]["atomic"] is True
    assert data["publication"]["staging_file_cleaned"] is True


def test_build_and_bake_wrapper_preserves_identical_build_solve_evidence():
    from rhinoclaw.tools.build_and_bake_gh import build_and_bake_gh

    response = {
        "file_path": "C:/test/safe.gh",
        "layer": "GH_Bake",
        "baked_count": 1,
        "baked_ids": ["b0655a04-fc48-4081-98cf-f980c9b7fcca"],
        "status": "success",
        "catalog_verification": CATALOG_OK,
        "build_result": {
            "solution": {"requested": True, "solve_count": 1},
            "runtime_messages": [],
            "publication": {"published": True, "atomic": True},
            "session_cleanup": {
                "complete": True,
                "document_absent_from_server": True,
            },
        },
    }
    connection = MagicMock()
    connection.send_command.return_value = response

    with patch(
        "rhinoclaw.tools.build_and_bake_gh.get_rhino_connection",
        return_value=connection,
    ):
        result = build_and_bake_gh(
            MagicMock(),
            "C:/test/safe.gh",
            [{"type": "slider", "name": "Width", "default": 10}],
        )

    build_result = json.loads(result)["data"]["build_result"]
    assert build_result["solution"]["requested"] is True
    assert build_result["solution"]["solve_count"] == 1
    assert build_result["publication"]["atomic"] is True
    assert build_result["session_cleanup"]["complete"] is True
