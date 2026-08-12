"""Shared runner for VisualARQ script execution (NEXT-LEVEL-PLAN 4.1).

VisualARQ has no public .NET SDK on NuGet; its scripting surface is the
`VisualARQ.Script` assembly inside Rhino. Every VA tool ships a small
IronPython-2.7 body that runs in-process; this module wraps it with:
- parameter injection via JSON (no string-format escaping),
- VisualARQ availability detection → graceful degradation,
- RESULT-line parsing back to a dict.

Port of the proven `scripts/rhinoclaw_client/visualarq.py` mechanics.
"""
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("rhinoclaw.visualarq")

_PRINT_PREFIX = "Script successfully executed! Print output: "

# Loading VisualARQ.Script can initialize the plug-in and abort the first
# IronPython scope before it reaches its final print. Keep that one-time host
# side effect out of the actual operation body: a lost load probe is safe to
# ignore, while blindly retrying a body could duplicate a mutation.
_LOAD_PROBE = """import clr
try:
    clr.AddReference("VisualARQ.Script")
    print("VA_LOAD_PROBE:ready")
except Exception as e:
    print("VA_LOAD_PROBE:unavailable:" + str(e))
"""

# The body runs with `va` (VisualARQ.Script), `params` (injected dict),
# `Guid`, `rg` (Rhino.Geometry) in scope and must assign `result`.
_TEMPLATE = """import clr
import json
import System
params = {{}}
result = None
def _va_serialize(value):
    return json.dumps(value)
try:
    clr.AddReference("Newtonsoft.Json")
    import System
    from Newtonsoft.Json import (
        JsonConvert, JsonSerializerSettings,
        JsonTextReader, StringEscapeHandling)
    from Newtonsoft.Json.Linq import JArray, JObject, JToken, JTokenType, JValue
    def _va_json_value(token):
        if isinstance(token, JObject):
            return dict((str(prop.Name), _va_json_value(prop.First))
                        for prop in token)
        if isinstance(token, JArray):
            return [_va_json_value(child) for child in token]
        if token.Type == JTokenType.Null:
            return None
        text = token.ToString()
        if token.Type == JTokenType.Integer:
            return int(text)
        if token.Type == JTokenType.Float:
            return float(text)
        if token.Type == JTokenType.Boolean:
            return text.ToUpperInvariant() == "TRUE"
        if token.Type == JTokenType.String:
            return text
        raise Exception("Unsupported JSON token type")
    params_reader = JsonTextReader(System.IO.StringReader({params_json!r}))
    try:
        params_token = JToken.ReadFrom(params_reader)
        params = _va_json_value(params_token)
    finally:
        params_reader.Close()
    _va_json_settings = JsonSerializerSettings()
    _va_json_settings.StringEscapeHandling = \
        StringEscapeHandling.EscapeNonAscii
    def _va_to_jtoken(value):
        if value is None:
            return JValue.CreateNull()
        if isinstance(value, dict):
            converted = JObject()
            for key, child in value.items():
                converted[str(key)] = _va_to_jtoken(child)
            return converted
        if isinstance(value, (list, tuple)):
            converted = JArray()
            for child in value:
                converted.Add(_va_to_jtoken(child))
            return converted
        if isinstance(value, bool):
            return JValue(value)
        # IronPython 2 uses ``long`` for values outside Int32. Passing those
        # through Convert.ToString changed both JSON type and, under a localized
        # .NET culture, precision. Preserve the full integral domain explicitly.
        if isinstance(value, (int, long)):
            integer = long(value)
            if integer < -9223372036854775808 or \
                    integer > 18446744073709551615:
                raise Exception("Integer is outside the JSON UInt64 range")
            if integer <= 9223372036854775807:
                return JValue(System.Int64(integer))
            return JValue(System.UInt64(integer))
        if isinstance(value, float):
            return JValue(value)
        try:
            if value.GetType() == System.String:
                return JValue(value)
        except Exception:
            pass
        return JValue(System.Convert.ToString(value))
    def _va_serialize(value):
        return JsonConvert.SerializeObject(
            _va_to_jtoken(value), _va_json_settings)
except Exception as e:
    result = {{"status": "error",
              "message": "VisualARQ parameter decoding failed: " +
                  System.Convert.ToString(e)}}
if result is None:
    try:
        va_assembly = clr.AddReference("VisualARQ.Script")
        import VisualARQ.Script as va
        # IronPython 2 returns None from clr.AddReference in Rhino 8 even
        # though the assembly was loaded successfully. Resolve the actual
        # runtime assembly for installed-version reporting.
        if va_assembly is None:
            for loaded_assembly in System.AppDomain.CurrentDomain.GetAssemblies():
                if str(loaded_assembly.GetName().Name) == "VisualARQ.Script":
                    va_assembly = loaded_assembly
                    break
    except Exception as e:
        result = {{"available": False, "status": "unavailable",
                  "message": "VisualARQ not available: " +
                      System.Convert.ToString(e)}}
if result is None:
    try:
        from System import Guid
        import Rhino
        import Rhino.Geometry as rg
        def va_text(value):
            if value is None:
                return None
            try:
                if value.GetType() == System.String:
                    return value
            except Exception:
                pass
            return System.Convert.ToString(value)
        def va_text_key(value):
            text = va_text(value)
            return text.ToUpperInvariant() if text is not None else None
        def va_method_available(name):
            return hasattr(va, name)
        _va_signature_cache = {{}}
        def va_method_signatures(name):
            # Complete public method shapes from the loaded .NET assembly.
            # Mutation dispatch must match CLR types, never parameter names.
            if name in _va_signature_cache:
                return _va_signature_cache[name]
            signatures = []
            if va_assembly is not None:
                method_flags = System.Reflection.BindingFlags.Public | \
                    System.Reflection.BindingFlags.Static | \
                    System.Reflection.BindingFlags.DeclaredOnly
                for reflected_type in va_assembly.GetTypes():
                    for method in reflected_type.GetMethods(method_flags):
                        if method.Name == name:
                            parameters = []
                            for parameter in method.GetParameters():
                                parameters.append({{
                                    "name": str(parameter.Name),
                                    "type": str(parameter.ParameterType.FullName),
                                    "by_reference": bool(
                                        parameter.ParameterType.IsByRef),
                                    "is_optional": bool(parameter.IsOptional),
                                }})
                            signatures.append({{
                                "declaring_type": str(
                                    method.DeclaringType.FullName),
                                "return_type": str(method.ReturnType.FullName),
                                "is_public": bool(method.IsPublic),
                                "is_static": bool(method.IsStatic),
                                "is_generic_method": bool(
                                    method.IsGenericMethod),
                                "contains_generic_parameters": bool(
                                    method.ContainsGenericParameters),
                                "parameters": parameters,
                            }})
            _va_signature_cache[name] = signatures
            return signatures
        def va_method_parameter_sets(name):
            # Backward-compatible diagnostics; never use names for dispatch.
            return [
                [parameter["name"] for parameter in signature["parameters"]]
                for signature in va_method_signatures(name)
            ]
        def va_method_has_parameter(name, parameter_name):
            for parameter_names in va_method_parameter_sets(name):
                if parameter_name in parameter_names:
                    return True
            return False
        def va_exact_method_shape(
                name, parameter_types, return_type="System.Guid"):
            matching = []
            signatures = va_method_signatures(name)
            for signature in signatures:
                parameters = signature["parameters"]
                if signature["declaring_type"] != "VisualARQ.Script" or \
                        signature["return_type"] != return_type or \
                        not signature["is_public"] or \
                        not signature["is_static"] or \
                        signature["is_generic_method"] or \
                        signature["contains_generic_parameters"] or \
                        len(parameters) != len(parameter_types):
                    continue
                if any(parameter["by_reference"] or parameter["is_optional"]
                       for parameter in parameters):
                    continue
                if [parameter["type"] for parameter in parameters] == \
                        list(parameter_types):
                    matching.append(signature)
            return {{
                "verified": len(matching) == 1,
                "match_count": len(matching),
                "parameter_types": list(parameter_types),
                "return_type": return_type,
                "matching_signatures": matching,
                "reflected_signatures": signatures,
            }}
{body}
    except Exception as e:
        result = {{"status": "error", "message": "VisualARQ error: " +
                  System.Convert.ToString(e)}}
print("RESULT:" + System.Convert.ToString(_va_serialize(result)))
"""


def build_va_script(body: str, params: Optional[Dict[str, Any]] = None) -> str:
    """Wrap an IronPython body (sets `result`) with the VA prelude."""
    indented = "\n".join(
        "        " + line if line.strip() else line
        for line in body.strip("\n").splitlines()
    )
    return _TEMPLATE.format(
        params_json=json.dumps(params or {}),
        body=indented,
    )


def warm_va(rhino) -> None:
    """Load VisualARQ with an idempotent probe before the read-only status body.

    The cold load can terminate this probe without output. That is acceptable:
    callers must still execute their real body exactly once and inspect its
    structured result.
    """
    rhino.send_command(
        "execute_rhinoscript_python_code", {"code": _LOAD_PROBE})


def run_va(rhino, body: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a VA script body in Rhino exactly once and parse its result."""
    code = build_va_script(body, params)
    raw = rhino.send_command("execute_rhinoscript_python_code", {"code": code})

    if isinstance(raw, dict) and raw.get("success") is False:
        return {
            "status": "error",
            "code": "SCRIPT_ERROR",
            "runner_failure": "script_execution_failed",
            "message": str(raw.get("message") or "VisualARQ script failed"),
        }

    text = raw if isinstance(raw, str) else ""
    if isinstance(raw, dict):
        nested = (
            raw.get("output") or raw.get("result") or raw.get("message", "")
        )
        text = nested if isinstance(nested, str) else str(nested or "")
    if text.startswith(_PRINT_PREFIX):
        text = text[len(_PRINT_PREFIX):]

    if "RESULT:" not in text:
        return {
            "status": "error",
            "code": "SCRIPT_ERROR",
            "runner_failure": "missing_result_marker",
            "message": f"No RESULT line in VA script output: {text[:200]}",
        }
    payload = text.split("RESULT:", 1)[1].strip().splitlines()[0]
    return json.loads(payload)


def va_unavailable(result: Dict[str, Any]) -> bool:
    """True when the script reported VisualARQ as not loaded."""
    return result.get("available") is False
