"""Regression contracts for localized and layout-aware viewport resolution."""

from pathlib import Path

import pytest

from rhinoclaw.utils.image_storage import validate_image_dimensions
from rhinoclaw.utils.errors import RhinoCommandError
from rhinoclaw.utils.viewports import (
    require_verified_viewport_mutation,
    resolved_viewport_label,
    viewport_params,
)


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_FUNCTIONS = ROOT / "rhinoclaw_plugin" / "Functions"


def test_viewport_params_omits_unspecified_or_blank_name():
    assert viewport_params({"width": 640}, None) == {"width": 640}
    assert viewport_params({"width": 640}, "  ") == {"width": 640}


def test_viewport_params_preserves_explicit_name_without_mutating_input():
    original = {"width": 640}

    result = viewport_params(original, "  Page 1::Detail 01  ")

    assert result == {"width": 640, "viewport_name": "Page 1::Detail 01"}
    assert original == {"width": 640}


def test_resolved_viewport_label_prefers_plugin_ground_truth():
    assert resolved_viewport_label({"viewport": "Perspektive"}, None) == "Perspektive"
    assert resolved_viewport_label({}, "Top") == "Top"
    assert resolved_viewport_label({}, None) == "ActiveView"


def test_verified_viewport_mutation_requires_inner_status_and_readback():
    verified = {
        "status": "success",
        "verification": {"pass": True},
    }
    assert require_verified_viewport_mutation(verified) is verified

    with pytest.raises(RhinoCommandError) as missing:
        require_verified_viewport_mutation({"status": "success"})
    assert missing.value.error_code == "VERIFICATION_FAILED"

    with pytest.raises(RhinoCommandError) as failed:
        require_verified_viewport_mutation({
            "status": "error",
            "code": "PARTIAL_MUTATION",
            "message": "restore unproven",
        })
    assert failed.value.error_code == "PARTIAL_MUTATION"


def test_all_native_viewport_consumers_use_one_shared_resolver():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    consumer_source = "\n".join(
        (PLUGIN_FUNCTIONS / name).read_text(encoding="utf-8")
        for name in ("ViewportOperations.cs", "RenderOperations.cs")
    )

    assert utils_source.count("ResolvedViewport resolveViewport(") == 1
    assert 'normalizedRequest == "activeview"' in utils_source
    assert "ActiveViewport" in utils_source
    assert "RhinoPageView" in utils_source
    assert "GetDetailViews" in utils_source
    assert "StringComparison.OrdinalIgnoreCase" in utils_source
    assert '"standard_projection"' in utils_source
    assert "Layout::Detail" in utils_source

    assert consumer_source.count(
        'resolveViewport(doc, parameters["viewport_name"])'
    ) == 7
    assert "ResolveViewport(" not in consumer_source
    assert '"resolve_viewport"' not in (
        ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs"
    ).read_text(encoding="utf-8")
    assert '?? "Perspective"' not in consumer_source
    assert "MainViewport.Name ==" not in consumer_source
    assert "viewport.SetProjection(projection, null, true)" in consumer_source
    assert "DefinedViewportProjection.Top" in consumer_source
    assert "DefinedViewportProjection.TwoPointPerspective" in consumer_source
    assert "KeyboardRotate(leftRight, angleRadians)" in consumer_source
    assert "execute_rhinoscript_python_code" not in (
        ROOT
        / "rhinoclaw_server"
        / "src"
        / "rhinoclaw"
        / "tools"
        / "orbit_camera.py"
    ).read_text(encoding="utf-8")
    assert consumer_source.count("capture_scope = captureScope") == 4
    assert "using var bitmap = target.HostView.CaptureToBitmap" in consumer_source


def test_all_viewport_results_expose_one_shared_resolved_identity_contract():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    consumer_source = "\n".join(
        (PLUGIN_FUNCTIONS / name).read_text(encoding="utf-8")
        for name in ("ViewportOperations.cs", "RenderOperations.cs")
    )

    assert utils_source.count("JObject withResolvedViewport(") == 1
    helper = utils_source[
        utils_source.index("JObject withResolvedViewport("):
        utils_source.index("ArgumentException ambiguousViewportError(")
    ]
    for field in (
        "viewport",
        "viewport_id",
        "detail_object_id",
        "requested_viewport",
        "viewport_kind",
        "viewport_resolution",
        "fallback_used",
    ):
        assert f'result["{field}"]' in helper

    # Nine success branches plus the verified navigation-failure branch use
    # the same identity contract. No consumer owns a one-off GUID response.
    assert consumer_source.count("return withResolvedViewport(target,") == 9
    assert utils_source.count("return withResolvedViewport(target,") == 1
    assert "viewport_id = target.ViewportId" not in consumer_source
    assert "detail_object_id = target.DetailObjectId" not in consumer_source


def test_navigation_consumers_reject_page_main_and_locked_detail():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    consumer_source = "\n".join(
        (PLUGIN_FUNCTIONS / name).read_text(encoding="utf-8")
        for name in ("ViewportOperations.cs", "RenderOperations.cs")
    )

    assert consumer_source.count("ensureViewportCanNavigate(target,") == 5
    assert 'target.Kind == "page"' in utils_source
    assert "target.IsProjectionLocked" in utils_source
    assert "DetailGeometry?.IsProjectionLocked" in utils_source


def test_set_view_and_camera_report_measured_state_and_verified_rollback():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    view_source = (PLUGIN_FUNCTIONS / "ViewportOperations.cs").read_text(
        encoding="utf-8"
    )
    camera_source = (PLUGIN_FUNCTIONS / "RenderOperations.cs").read_text(
        encoding="utf-8"
    )

    assert "ViewportNavigationState" in utils_source
    assert "viewportNavigationReadback" in utils_source
    assert "PopViewProjection()" in utils_source
    assert 'ErrorCode.PARTIAL_MUTATION' in utils_source
    assert '"covered_state_restored"' in utils_source

    assert "requested_view_type" in view_source
    assert "actualViewType" in view_source
    assert "standardViewportMatches(" in view_source
    assert "view_type = viewType" not in view_source
    assert 'restoreConstructionPlane: true' in view_source

    assert "requested_camera_location" in camera_source
    assert 'actual["camera_location"]' in camera_source
    assert "camera_location = new[] { cameraLocation" not in camera_source
    assert "viewportProjectionKindMatches(" in camera_source
    assert 'restoreConstructionPlane: false' in camera_source


def test_detail_mutations_commit_and_resolver_rejects_ambiguity():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    consumer_source = "\n".join(
        (PLUGIN_FUNCTIONS / name).read_text(encoding="utf-8")
        for name in ("ViewportOperations.cs", "RenderOperations.cs")
    )

    assert "DetailViewObject DetailObject" in utils_source
    assert "DetailObject.CommitViewportChanges()" in utils_source
    assert "detail.Id == requestedId" in utils_source
    assert '"detail_object_id"' in utils_source
    assert "ambiguousViewportError" in utils_source
    assert "exactNameMatches.Count > 1" in utils_source
    assert "mainMatches.Count == 1" not in utils_source
    assert "detailMatches.Count == 1" not in utils_source
    assert "qualifiedMatches.Count > 1" in utils_source
    assert "non-empty layout name before '::'" in utils_source
    assert "non-empty detail name after '::'" in utils_source
    assert consumer_source.count("target.CommitDetailViewportChanges();") == 7
    assert 'render_view cannot apply one display mode to layout page' in consumer_source


def test_shared_image_budget_accepts_8k_uhd_and_rejects_each_limit():
    validate_image_dimensions(7680, 4320)

    with pytest.raises(ValueError, match="16384 pixels per dimension"):
        validate_image_dimensions(16_385, 1)
    with pytest.raises(ValueError, match="33177600-pixel budget"):
        validate_image_dimensions(8192, 4096)


def test_native_capture_and_render_share_overflow_safe_image_budget():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    consumer_source = "\n".join(
        (PLUGIN_FUNCTIONS / name).read_text(encoding="utf-8")
        for name in ("ViewportOperations.cs", "RenderOperations.cs")
    )
    capture_source = (
        ROOT
        / "rhinoclaw_server"
        / "src"
        / "rhinoclaw"
        / "tools"
        / "capture_viewport.py"
    ).read_text(encoding="utf-8")
    render_source = (
        ROOT
        / "rhinoclaw_server"
        / "src"
        / "rhinoclaw"
        / "tools"
        / "render_view.py"
    ).read_text(encoding="utf-8")

    assert utils_source.count("void validateImageDimensions(") == 1
    assert "private const int MaxImageDimension = 16384;" in utils_source
    assert "private const long MaxImagePixels = 33177600L;" in utils_source
    assert "checked((long)width * (long)height)" in utils_source
    assert consumer_source.count("validateImageDimensions(") == 2
    assert capture_source.count("validate_image_dimensions(width, height)") == 1
    assert render_source.count("validate_image_dimensions(width, height)") == 1


def test_native_image_dimensions_require_json_integer_tokens():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    consumer_source = "\n".join(
        (PLUGIN_FUNCTIONS / name).read_text(encoding="utf-8")
        for name in ("ViewportOperations.cs", "RenderOperations.cs")
    )

    assert utils_source.count("int? readImageDimension(") == 1
    assert "token.Type != JTokenType.Integer" in utils_source
    assert "must be a JSON integer" in utils_source
    assert consumer_source.count('readImageDimension(parameters, "width")') == 2
    assert consumer_source.count('readImageDimension(parameters, "height")') == 2


def test_plugin_classifies_viewport_validation_and_ambiguity_errors():
    error_source = (
        ROOT / "rhinoclaw_plugin" / "ErrorCode.cs"
    ).read_text(encoding="utf-8")
    server_source = (
        ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs"
    ).read_text(encoding="utf-8")

    ambiguity_check = error_source.index('message.Contains("ambiguous")')
    argument_check = error_source.index("ex is ArgumentException")

    assert (
        'public const string AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE";'
        in error_source
    )
    for code in (
        "UNSUPPORTED_OPERATION",
        "ALREADY_EXISTS",
        "RESOURCE_IN_USE",
        "PRECONDITION_FAILED",
        "VERIFICATION_FAILED",
        "PARTIAL_MUTATION",
    ):
        assert f'public const string {code} = "{code}";' in error_source
    assert ambiguity_check < argument_check
    assert "return INVALID_PARAMS;" in error_source[argument_check:]
    assert '["error_code"] = ErrorCode.FromException(e, cmdType)' in server_source


def test_native_image_writes_validate_the_windows_host_boundary():
    utils_source = (PLUGIN_FUNCTIONS / "_utils.cs").read_text(encoding="utf-8")
    consumer_source = "\n".join(
        (PLUGIN_FUNCTIONS / name).read_text(encoding="utf-8")
        for name in ("ViewportOperations.cs", "RenderOperations.cs")
    )

    assert utils_source.count("void validateRhinoHostImagePath(") == 1
    assert 'normalized.StartsWith(@"\\\\?\\"' in utils_source
    assert 'normalized.StartsWith(@"\\\\.\\"' in utils_source
    assert "ReservedWindowsDeviceNames.Contains(baseName)" in utils_source
    assert "Path.GetPathRoot(filename)" in utils_source
    assert "if (isUncRoot && relative.Length > 0 &&" in utils_source
    assert "relative = relative.Substring(1);" in utils_source
    assert consumer_source.count("validateRhinoHostImagePath(filename);") == 2
    assert consumer_source.count('save_location = "rhino_host"') == 2
    assert consumer_source.count("bytes_written = fileInfo.Length") == 2
