"""Regression tests for VisualARQ's exceptional beam-style inventory API."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT / "scripts" / "rhinoclaw_client"
CLIENT_PATH = CLIENT_DIR / "visualarq.py"


class _DotNetText(str):
    def Trim(self):
        return self.strip()


class _Guid:
    Empty = "EMPTY"


class _BindingFlags:
    Public = 1
    Static = 2
    DeclaredOnly = 4


class _Reflection:
    BindingFlags = _BindingFlags


class _System:
    Reflection = _Reflection


class _ReflectedMethod:
    def __init__(self, name):
        self.Name = name
        self.IsGenericMethod = False
        self.ContainsGenericParameters = False

    @staticmethod
    def GetParameters():
        return []


class _ReflectedType:
    def __init__(self, names):
        self._methods = [_ReflectedMethod(name) for name in names]

    def GetMethods(self, _flags):
        return self._methods


class _Assembly:
    def __init__(self, names):
        self._types = [_ReflectedType(names)]

    def GetTypes(self):
        return self._types


class _FakeVa:
    def __init__(self):
        self.calls = {"GetAllBeamStyle": 0, "GetAllBeamStyleIds": 0}

    def GetAllBeamStyle(self):
        self.calls["GetAllBeamStyle"] += 1
        return ["beam-canonical"]

    def GetAllBeamStyleIds(self):
        self.calls["GetAllBeamStyleIds"] += 1
        return ["beam-legacy"]

    @staticmethod
    def GetAllWallStyleIds():
        return []

    @staticmethod
    def GetStyleName(style_id):
        return _DotNetText("Canonical Beam" if style_id == "beam-canonical"
                           else "Legacy Beam")

    @staticmethod
    def GetSubStyleComponents(_style_id):
        return []


def _global_inventory_runtime(shape_results, reflected_names):
    from rhinoclaw.tools.visualarq import _STYLE_SCRIPT_HELPERS

    start = _STYLE_SCRIPT_HELPERS.index("def va_global_style_inventory():")
    end = _STYLE_SCRIPT_HELPERS.index(
        "def va_global_style_rename_contract(", start
    )
    source = _STYLE_SCRIPT_HELPERS[start:end]
    shape_calls = []

    def exact_method_shape(name, parameter_types, return_type):
        shape_calls.append((name, parameter_types, return_type))
        verified = shape_results.get(name, False)
        return {
            "verified": verified,
            "match_count": 1 if verified else 0,
        }

    fake_va = _FakeVa()
    namespace = {
        "Guid": _Guid,
        "System": _System,
        "va": fake_va,
        "va_assembly": _Assembly(reflected_names),
        "va_exact_method_shape": exact_method_shape,
        "va_method_available": lambda name: name in {
            "GetStyleName",
            "GetSubStyleComponents",
        },
        "va_text": lambda value: _DotNetText(str(value)),
    }
    exec(compile(source, "<va_global_style_inventory>", "exec"), namespace)
    return namespace["va_global_style_inventory"](), fake_va, shape_calls


def _load_tcp_visualarq_client():
    sys.path.insert(0, str(CLIENT_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "rhinoclaw_tcp_visualarq_client",
            CLIENT_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(CLIENT_DIR))


TCP_VISUALARQ_CLIENT = _load_tcp_visualarq_client()


def test_global_inventory_includes_exact_canonical_beam_inventory():
    result, fake_va, shape_calls = _global_inventory_runtime(
        {"GetAllBeamStyle": True},
        ["GetAllBeamStyle"],
    )

    assert result["read_complete"] is True
    assert result["beam_inventory_method"] == "GetAllBeamStyle"
    assert result["inventory_methods"] == ["GetAllBeamStyle"]
    assert result["inventory_counts"] == {"GetAllBeamStyle": 1}
    assert result["style_owners"] == {
        "beam-canonical": "GetAllBeamStyle",
    }
    assert fake_va.calls == {
        "GetAllBeamStyle": 1,
        "GetAllBeamStyleIds": 0,
    }
    assert ("GetAllBeamStyle", [], "System.Guid[]") in shape_calls


def test_global_inventory_rejects_legacy_beam_alias_and_fails_closed():
    result, fake_va, _shape_calls = _global_inventory_runtime(
        {"GetAllBeamStyleIds": True},
        ["GetAllBeamStyleIds"],
    )

    assert result["read_complete"] is False
    assert result["beam_inventory_method"] is None
    assert result["inventory_methods"] == []
    assert any(
        error.get("method") == "GetAllBeamStyle"
        for error in result["readback_errors"]
    )
    assert fake_va.calls == {
        "GetAllBeamStyle": 0,
        "GetAllBeamStyleIds": 0,
    }


def test_global_inventory_fails_closed_without_exact_beam_shape():
    result, fake_va, _shape_calls = _global_inventory_runtime(
        {},
        ["GetAllWallStyleIds", "GetAllBeamStyle"],
    )

    assert result["read_complete"] is False
    assert result["beam_inventory_method"] is None
    assert result["inventory_methods"] == ["GetAllWallStyleIds"]
    assert any(
        error.get("stage") == "inventory_discovery"
        and error.get("method") == "GetAllBeamStyle"
        for error in result["readback_errors"]
    )
    assert fake_va.calls == {
        "GetAllBeamStyle": 0,
        "GetAllBeamStyleIds": 0,
    }


def _capture_client_script(call):
    client = MagicMock()
    client.send_command.return_value = {"status": "error"}
    with patch.object(TCP_VISUALARQ_CLIENT, "RhinoClient") as client_type:
        client_type.return_value.__enter__.return_value = client
        call()
    return client.send_command.call_args[0][1]["code"]


def _assert_client_beam_inventory_fallback(code):
    compile(code, "<tcp_visualarq_client>", "exec")
    canonical_check = code.index('hasattr(va, "GetAllBeamStyle")')
    canonical_call = code.index("return va.GetAllBeamStyle()")
    legacy_check = code.index('hasattr(va, "GetAllBeamStyleIds")')
    legacy_call = code.index("return va.GetAllBeamStyleIds()")
    assert canonical_check < canonical_call < legacy_check < legacy_call
    assert "beam_style_ids = _get_all_beam_style_ids(va)" in code
    assert "beam_style_ids = va.GetAllBeamStyleIds()" not in code


def test_tcp_get_info_prefers_real_beam_inventory_with_legacy_fallback():
    code = _capture_client_script(TCP_VISUALARQ_CLIENT.get_info)

    _assert_client_beam_inventory_fallback(code)


def test_tcp_create_beam_prefers_real_beam_inventory_with_legacy_fallback():
    code = _capture_client_script(
        lambda: TCP_VISUALARQ_CLIENT.create_beam(
            "Beam A",
            [0, 0, 0],
            [1000, 0, 0],
        )
    )

    _assert_client_beam_inventory_fallback(code)
