"""Source contracts for loaded-definition parameter and solve conformance."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = (
    ROOT / "rhinoclaw_plugin" / "Functions" /
    "GrasshopperApiOperations.cs"
)
BUILDER_SOURCE = (
    ROOT / "rhinoclaw_plugin" / "Functions" /
    "GrasshopperDefinitionBuilder.cs"
)
SERVER_SOURCE = ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs"


def test_loaded_parameters_have_one_canonical_identity_record():
    source = API_SOURCE.read_text(encoding="utf-8")
    load_start = source.index("public JObject LoadGrasshopperDefinition")
    set_start = source.index("public JObject SetGrasshopperParameter")
    load_source = source[load_start:set_start]

    assert "if (obj is GH_NumberSlider slider)" in load_source
    assert "else if (obj is GH_Panel panel)" in load_source
    assert "else if (obj is GH_BooleanToggle toggle)" in load_source
    assert 'parameter_identity = "parameter_instance_id"' in load_source
    assert '["parameter_instance_id"] = slider.InstanceGuid.ToString()' in (
        load_source
    )
    assert '["settable_by_instance_id"] = true' in load_source


def test_archive_load_hydrates_persistent_rhino_curve_references():
    source = API_SOURCE.read_text(encoding="utf-8")
    load_start = source.index("public JObject LoadGrasshopperDefinition")
    set_start = source.index("public JObject SetGrasshopperParameter")
    load_source = source[load_start:set_start]

    assert "ResolvePersistentRhinoCurveReferences(ghDoc)" in load_source
    assert 'curve_reference_resolution = curveReferenceResolution' in load_source
    assert "ghDoc.Objects.OfType<Param_Curve>()" in source
    assert "curveParameter.PersistentData.Branches" in source
    assert "curve.LoadGeometry(rhinoDoc)" in source
    assert '["all_resolved"] = resolved == found' in source


def test_atomic_parameter_batch_preflights_before_first_mutation():
    source = API_SOURCE.read_text(encoding="utf-8")
    start = source.index("public JObject SetGrasshopperParameters")
    end = source.index("public JObject GetGrasshopperOutputs", start)
    batch = source[start:end]

    assert "PrepareGhAtomicParameterAssignment(" in batch
    assert batch.index('if (issues.Count > 0)') < batch.index(
        "ApplyGhAtomicParameterValue(")
    assert '["status"] = "preflight_failed"' in batch
    assert '["mutation_attempted"] = false' in batch
    assert "parameter_instance_id did not resolve to exactly one object" in batch
    assert "NumberSlider value" in source and "is outside" in source


def test_atomic_parameter_batch_reads_back_and_reverse_rolls_back():
    source = API_SOURCE.read_text(encoding="utf-8")
    start = source.index("public JObject SetGrasshopperParameters")
    end = source.index("public JObject GetGrasshopperOutputs", start)
    batch = source[start:end]

    assert "SnapshotGhAtomicParameter(assignment.Target)" in batch
    assert '["readback_match"] = readbackMatch' in batch
    assert "applied.AsEnumerable().Reverse()" in batch
    assert "RestoreGhAtomicParameter(" in batch
    assert '["status"] = "failed_after_mutation"' in batch
    assert '["complete"] = rollbackComplete' in batch


def test_loaded_solve_uses_shared_exact_cycle_and_complete_messages():
    api = API_SOURCE.read_text(encoding="utf-8")
    builder = BUILDER_SOURCE.read_text(encoding="utf-8")
    start = api.index("public JObject SolveGrasshopper")
    end = api.index("public JObject BakeGrasshopper", start)
    solve = api[start:end]

    assert "SolveGrasshopperDefinitionOnce(\n            ghDoc, expireAll, false)" in solve
    assert '["runtime_messages"] = solve.RuntimeMessages' in solve
    assert '["remarks"] = solve.Remarks' in solve
    assert '["solution"] = solve.Diagnostics' in solve
    assert "doc.NewSolution(expireAllObjects, GH_SolutionMode.Silent)" in builder
    assert "doc.SolutionStart -= solutionStartHandler" in builder
    assert "doc.SolutionEnd -= solutionEndHandler" in builder
    assert 'AppendGrasshopperRuntimeMessages(\n                runtimeMessages' in builder


def test_new_atomic_tool_is_dispatchable_and_advertised():
    server = SERVER_SOURCE.read_text(encoding="utf-8")
    assert '"set_grasshopper_parameters"' in server
    assert (
        '["set_grasshopper_parameters"] = '
        "this.handler.SetGrasshopperParameters"
    ) in server
