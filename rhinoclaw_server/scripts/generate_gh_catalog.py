#!/usr/bin/env python3
"""Regenerate ``static/gh_components.json`` from a live scratch Rhino.

Run from ``rhinoclaw_server/`` on Windows or WSL only after opening an
isolated Rhino document:

    RHINOCLAW_HOST=<host> uv run python scripts/generate_gh_catalog.py

The generator is intentionally resumable. Some third-party ObjectProxies hang
inside ``CreateInstance``; the Rhino-side marker identifies the exact proxy,
the next retry records it as ``ports_skipped``, and generation continues. The
finished catalog is published atomically only when its JSONL has exactly the
live proxy count and no duplicate GUIDs.

Use ``--reset`` to remove only this generator's JSONL/marker files before a
fresh scratch run. Never run the instantiation sweep in a productive Rhino.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import platform
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, Iterable, List, Tuple

from rhinoclaw.server import get_rhino_connection
from rhinoclaw.utils.gh_catalog import catalog_contract



def _is_wsl() -> bool:
    """Return whether this Python process is running inside WSL."""
    return (
        os.name == "posix"
        and (
            bool(os.environ.get("WSL_INTEROP"))
            or "microsoft" in platform.release().lower()
        )
    )


def _default_work_dir() -> Path:
    """Choose scratch storage that the connected Rhino process can read."""
    if _is_wsl():
        return Path("/mnt/c/Temp/rhinoclaw-gh-catalog")
    return Path(tempfile.gettempdir()) / "rhinoclaw-gh-catalog"


DEFAULT_WORK_DIR = _default_work_dir()
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "rhinoclaw"
    / "static"
    / "gh_components.json"
)

_PROBE_CODE = r"""
import Grasshopper
import Rhino
import hashlib
import json

def proxy_identity(proxy):
    runtime_guid = str(proxy.Guid).lower()
    try:
        if proxy.GetType().FullName == 'Grasshopper.Kernel.GH_UserObjectProxy':
            library_guid = str(proxy.LibraryGuid).lower()
            if library_guid and library_guid != '00000000-0000-0000-0000-000000000000':
                return library_guid
    except BaseException:
        pass
    return runtime_guid

proxy_guids = sorted(
    proxy_identity(proxy)
    for proxy in Grasshopper.Instances.ComponentServer.ObjectProxies)
print('CATALOG_META:' + json.dumps({
    'proxy_count': len(proxy_guids),
    'proxy_guid_sha256': hashlib.sha256(
        '\n'.join(proxy_guids).encode('utf-8')).hexdigest(),
    'rhino_version': str(Rhino.RhinoApp.Version),
}, sort_keys=True))
"""

_CHUNK_CODE = r"""
import codecs
import clr
import Grasshopper
import hashlib
import json
clr.AddReference('Newtonsoft.Json')
clr.AddReference('System')
from Newtonsoft.Json import JsonConvert
from System.Diagnostics import FileVersionInfo

server = Grasshopper.Instances.ComponentServer
proxies = list(server.ObjectProxies)
start = __START__
expected_proxy_hash = __EXPECTED_PROXY_HASH__

def proxy_identity(proxy):
    runtime_guid = str(proxy.Guid).lower()
    try:
        if proxy.GetType().FullName == 'Grasshopper.Kernel.GH_UserObjectProxy':
            library_guid = str(proxy.LibraryGuid).lower()
            if library_guid and library_guid != '00000000-0000-0000-0000-000000000000':
                return library_guid
    except BaseException:
        pass
    return runtime_guid

def proxy_guid_hash(items):
    guids = sorted(proxy_identity(proxy) for proxy in items)
    return hashlib.sha256('\n'.join(guids).encode('utf-8')).hexdigest()

initial_proxy_hash = proxy_guid_hash(proxies)
catalog_changed = initial_proxy_hash != expected_proxy_hash
end = start if catalog_changed else min(start + __CHUNK__, len(proxies))
skip = set(__SKIP__)
out_path = __OUT__
marker_path = __MARKER__
errors = 0
assembly_cache = {}

def ports(plist):
    result = []
    for param in plist:
        try:
            result.append({
                'n': param.Name,
                'nn': param.NickName,
                't': param.TypeName,
                'access': str(param.Access).lower(),
                'optional': bool(param.Optional),
                'runtime_type': param.GetType().FullName,
            })
        except BaseException:
            result.append({'n': '?', 'nn': '?', 't': '?'})
    return result

def text_attr(source, name, default=''):
    try:
        value = getattr(source, name)
        return value if value is not None else default
    except BaseException:
        return default

def guid_attr(source, name):
    try:
        return str(getattr(source, name)).lower()
    except BaseException:
        return ''

def instance_metadata(instance):
    runtime_type = instance.GetType()
    assembly = runtime_type.Assembly
    assembly_name = assembly.GetName()
    location = ''
    try:
        location = assembly.Location or ''
    except BaseException:
        pass
    cache_key = location or str(assembly.FullName)
    if cache_key not in assembly_cache:
        metadata = {
            'name': str(assembly_name.Name),
            'version': str(assembly_name.Version),
            'location': location,
        }
        if location:
            try:
                version_info = FileVersionInfo.GetVersionInfo(location)
                metadata['file_version'] = version_info.FileVersion or ''
                metadata['product_version'] = version_info.ProductVersion or ''
            except BaseException:
                pass
        assembly_cache[cache_key] = metadata
    return {
        'runtime_type': runtime_type.FullName,
        'assembly': assembly_cache[cache_key],
    }

out_file = codecs.open(out_path, 'a', encoding='utf-8')
marker_file = codecs.open(marker_path, 'w', encoding='utf-8')
try:
    index = start
    for proxy in proxies[start:end]:
        guid_text = ''
        entry = {'proxy_index': index}
        try:
            runtime_guid = str(proxy.Guid).lower()
            guid_text = proxy_identity(proxy)
            entry['guid'] = guid_text
            entry['proxy_type'] = proxy.GetType().FullName
            if runtime_guid != guid_text:
                entry['runtime_guid'] = runtime_guid
                entry['guid_source'] = 'library_guid'
        except BaseException as exc:
            entry['guid'] = ''
            entry['proxy_error'] = (
                'Guid read raised ' + type(exc).__name__)
            errors += 1

        try:
            desc = proxy.Desc
            entry.update({
                'name': text_attr(desc, 'Name', guid_text),
                'nick': text_attr(desc, 'NickName'),
                'cat': text_attr(desc, 'Category'),
                'sub': text_attr(desc, 'SubCategory'),
                'desc': text_attr(desc, 'Description')[:140],
            })
        except BaseException as exc:
            entry.update({
                'name': guid_text,
                'nick': '',
                'cat': '',
                'sub': '',
                'desc': '',
                'descriptor_error': (
                    'Desc read raised ' + type(exc).__name__),
            })
            errors += 1

        try:
            if bool(proxy.Obsolete):
                entry['obsolete'] = True
        except BaseException as exc:
            entry['obsolete_read_error'] = type(exc).__name__
            errors += 1

        entry['library_guid'] = guid_attr(proxy, 'LibraryGuid')
        entry['location'] = text_attr(proxy, 'Location')
        entry['exposure'] = str(text_attr(proxy, 'Exposure')).lower()

        if not guid_text:
            entry['instantiate_error'] = 'proxy Guid unavailable'
        elif guid_text in skip:
            entry['ports_skipped'] = 'instantiation hangs'
        else:
            marker_file.seek(0)
            marker_file.truncate()
            # Keep the crash marker ASCII-only. Third-party display names can
            # contain values that IronPython cannot coerce through its default
            # byte encoding; index + GUID are sufficient for safe resumption.
            marker_file.write(str(index) + '|' + guid_text)
            marker_file.flush()
            try:
                instance = proxy.CreateInstance()
                if instance is None:
                    entry['instantiate_error'] = (
                        'CreateInstance returned null')
                    errors += 1
                else:
                    entry['instantiated'] = True
                    try:
                        entry.update(instance_metadata(instance))
                        if hasattr(instance, 'Params'):
                            entry['in'] = ports(instance.Params.Input)
                            entry['out'] = ports(instance.Params.Output)
                        elif hasattr(instance, 'TypeName'):
                            entry['param_type'] = instance.TypeName
                    finally:
                        try:
                            instance.Dispose()
                        except BaseException:
                            pass
            except BaseException as exc:
                entry['instantiate_error'] = (
                    'CreateInstance raised ' + type(exc).__name__)
                errors += 1

        # IronPython's stdlib json decoder assumes UTF-8 for byte strings, but
        # several plug-ins expose cp1252 text (for example a superscript 2).
        # Newtonsoft serializes the CLR/Python dictionary without corrupting
        # those names. Exactly one line per proxy remains the resumability
        # invariant; a serialization failure keeps an ASCII diagnostic row.
        try:
            encoded = JsonConvert.SerializeObject(entry)
        except BaseException as exc:
            encoded = JsonConvert.SerializeObject({
                'guid': guid_text,
                'name': guid_text,
                'nick': '',
                'cat': '',
                'sub': '',
                'desc': '',
                'serialization_error': type(exc).__name__,
            })
            errors += 1
        out_file.write(encoded + '\n')
        out_file.flush()
        index += 1
finally:
    out_file.close()
    marker_file.close()

print('CATALOG_CHUNK:' + json.dumps({
    'start': start,
    'end': end,
    'total': len(proxies),
    'errors': errors,
    'initial_proxy_guid_sha256': initial_proxy_hash,
    'final_proxy_guid_sha256': proxy_guid_hash(list(server.ObjectProxies)),
    'catalog_changed': catalog_changed,
}, sort_keys=True))
"""


def _result_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return str(raw.get("result") or raw.get("message") or "")
    return str(raw or "")


def _tagged_json(text: str, tag: str) -> Dict[str, Any]:
    for line in text.splitlines():
        marker = line.find(tag)
        if marker >= 0:
            return json.loads(line[marker + len(tag):].strip())
    raise ValueError(f"Rhino response lacked {tag.rstrip(':')} metadata")


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as stream:
        return sum(1 for line in stream if line.strip())


def _pending_marker_guid(marker_path: Path, written_count: int) -> str | None:
    if not marker_path.exists():
        return None
    marker = marker_path.read_text(encoding="utf-8", errors="replace").strip()
    parts = marker.split("|", 2)
    if len(parts) < 2:
        return None
    try:
        marker_index = int(parts[0])
    except ValueError:
        return None
    return parts[1].lower() if marker_index >= written_count else None


def _rhino_path(path: Path, *, is_wsl: bool | None = None) -> str:
    """Resolve a host path into the path syntax understood by Rhino."""
    use_wsl = _is_wsl() if is_wsl is None else is_wsl
    if not use_wsl:
        return str(path.resolve())
    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if not value:
        raise RuntimeError(f"wslpath returned no Windows path for {path}")
    return value


def _render_chunk_code(
    *,
    start: int,
    chunk: int,
    skipped_guids: Iterable[str],
    windows_jsonl: str,
    windows_marker: str,
    expected_proxy_hash: str,
) -> str:
    return (
        _CHUNK_CODE.replace("__START__", str(start))
        .replace("__CHUNK__", str(chunk))
        .replace("__SKIP__", json.dumps(sorted(set(skipped_guids))))
        .replace("__OUT__", json.dumps(windows_jsonl))
        .replace("__MARKER__", json.dumps(windows_marker))
        .replace("__EXPECTED_PROXY_HASH__", json.dumps(expected_proxy_hash))
    )


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            entries.append(value)
    return entries


def _assemble_catalog(
    jsonl_path: Path,
    output_path: Path,
    *,
    rhino_version: str,
    expected_count: int,
    expected_proxy_hash: str,
) -> Dict[str, Any]:
    entries = _load_jsonl(jsonl_path)
    if len(entries) != expected_count:
        raise ValueError(
            f"catalog JSONL has {len(entries)} entries; live runtime has "
            f"{expected_count} proxies"
        )

    by_guid: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        guid = str(entry.get("guid") or "").strip().lower()
        if not guid:
            raise ValueError("catalog entry has no GUID")
        if guid in by_guid:
            raise ValueError(f"duplicate catalog GUID: {guid}")
        normalized = dict(entry)
        normalized["guid"] = guid
        by_guid[guid] = normalized

    components = [by_guid[guid] for guid in sorted(by_guid)]
    skipped = sorted(
        entry["guid"] for entry in components if entry.get("ports_skipped")
    )
    meta: Dict[str, Any] = {
        "catalog_metadata_schema": 2,
        "component_count": len(components),
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "rhino_version": rhino_version,
        "source": (
            "Grasshopper.Instances.ComponentServer.ObjectProxies "
            "(live introspection)"
        ),
        "ports_skipped_guids": skipped,
        "note": (
            "in/out are ordered input/output port records {n, nn, t}; "
            "param_type describes standalone parameters"
        ),
    }
    catalog = {"meta": meta, "components": components}
    contract = catalog_contract(catalog)
    if contract["proxy_guid_sha256"] != expected_proxy_hash:
        raise ValueError(
            "catalog JSONL stable proxy GUID hash differs from the live runtime; "
            "run again with --reset after Grasshopper plug-ins finish loading"
        )
    meta.update({
        "catalog_contract_schema": contract["schema_version"],
        "proxy_guid_sha256": contract["proxy_guid_sha256"],
        "component_contract_sha256":
            contract["component_contract_sha256"],
    })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_name = stream.name
            # Keep the generated catalog reviewable as one deterministic
            # artifact instead of creating a six-figure line-only diff.
            json.dump(
                catalog,
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, output_path)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
    return catalog


def _probe_runtime(rhino: Any) -> Tuple[int, str, str]:
    raw = rhino.send_command(
        "execute_rhinoscript_python_code",
        {"code": _PROBE_CODE},
        timeout=30,
    )
    meta = _tagged_json(_result_text(raw), "CATALOG_META:")
    count = meta.get("proxy_count")
    version = str(meta.get("rhino_version") or "")
    proxy_hash = str(meta.get("proxy_guid_sha256") or "")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ValueError(f"invalid live proxy count: {count!r}")
    if not version:
        raise ValueError("live Rhino version was empty")
    if len(proxy_hash) != 64:
        raise ValueError("live proxy GUID hash was invalid")
    return count, version, proxy_hash


def _known_skipped_guids(*paths: Path) -> set:
    """Preserve published hang exclusions even on a fresh/reset sweep."""
    skipped = set()
    for path in set(paths):
        if not path.exists():
            continue
        catalog = json.loads(path.read_text(encoding="utf-8"))
        skipped.update(catalog_contract(catalog)["ports_skipped_guids"])
        skipped.update(str(entry["guid"]).lower() for entry in catalog["components"]
                       if "ports_skipped" in entry and entry.get("guid"))
    return skipped


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(os.environ.get(
            "RHINOCLAW_GH_CATALOG_WORK_DIR", DEFAULT_WORK_DIR)),
        help="scratch directory shared with the connected Rhino process",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="final catalog JSON path",
    )
    parser.add_argument("--chunk", type=int, default=110)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="remove only generator-owned JSONL/marker files first",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not 1 <= args.chunk <= 500:
        raise ValueError("--chunk must be between 1 and 500")

    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = work_dir / "gh_components.jsonl"
    marker_path = work_dir / "gh_marker.txt"
    if args.reset:
        jsonl_path.unlink(missing_ok=True)
        marker_path.unlink(missing_ok=True)

    rhino_jsonl = _rhino_path(jsonl_path)
    rhino_marker = _rhino_path(marker_path)
    rhino = get_rhino_connection()
    expected_count, rhino_version, expected_proxy_hash = _probe_runtime(rhino)

    start = _line_count(jsonl_path)
    if start > expected_count:
        raise ValueError(
            f"resume JSONL has {start} lines but runtime has only "
            f"{expected_count} proxies; run again with --reset"
        )
    skipped_guids = _known_skipped_guids(DEFAULT_OUTPUT, args.output.resolve())
    pending = _pending_marker_guid(marker_path, start)
    if pending:
        skipped_guids.add(pending)

    print(
        f"[CATALOG] Rhino {rhino_version}; resume {start}/{expected_count}; "
        f"work={work_dir}"
    )
    while start < expected_count:
        code = _render_chunk_code(
            start=start,
            chunk=args.chunk,
            skipped_guids=skipped_guids,
            windows_jsonl=rhino_jsonl,
            windows_marker=rhino_marker,
            expected_proxy_hash=expected_proxy_hash,
        )
        try:
            raw = rhino.send_command(
                "execute_rhinoscript_python_code",
                {"code": code},
                timeout=90,
            )
            status = _tagged_json(_result_text(raw), "CATALOG_CHUNK:")
        except Exception:
            pending = _pending_marker_guid(marker_path, _line_count(jsonl_path))
            if not pending:
                raise RuntimeError(
                    "catalog chunk failed without a pending proxy marker"
                )
            skipped_guids.add(pending)
            # A timeout does not establish that CreateInstance stopped. Do not
            # restart/replay a sweep behind a possibly blocked Rhino UI.
            from rhinoclaw.tools.get_ui_state import get_ui_state
            print("[WARN] UI state after failed chunk: " + get_ui_state(None, timeout=5))
            raise RuntimeError(
                f"Proxy {pending} did not finish. Inspect Rhino, end the blocked call, "
                "then rerun without --reset; the marker excludes this proxy. No automatic replay."
            )

        live_total = status.get("total")
        end = status.get("end")
        initial_hash = status.get("initial_proxy_guid_sha256")
        final_hash = status.get("final_proxy_guid_sha256")
        if (
            live_total != expected_count
            or not isinstance(end, int)
            or initial_hash != expected_proxy_hash
            or final_hash != expected_proxy_hash
            or status.get("catalog_changed") is True
        ):
            raise RuntimeError(
                "ComponentServer GUID set changed during generation; rerun "
                "with --reset after Grasshopper plug-ins finish loading"
            )
        new_start = _line_count(jsonl_path)
        if new_start != end or new_start <= start:
            raise RuntimeError(
                f"chunk publication mismatch: expected {end} lines, found "
                f"{new_start}"
            )
        start = new_start
        print(
            f"[CATALOG] {start}/{expected_count}; "
            f"chunk_errors={status.get('errors', 0)}"
        )

    catalog = _assemble_catalog(
        jsonl_path,
        args.output.resolve(),
        rhino_version=rhino_version,
        expected_count=expected_count,
        expected_proxy_hash=expected_proxy_hash,
    )
    meta = catalog["meta"]
    print(
        f"[OK] {meta['component_count']} entries -> {args.output.resolve()}\n"
        f"     proxy_guid_sha256={meta['proxy_guid_sha256']}\n"
        f"     component_contract_sha256="
        f"{meta['component_contract_sha256']}\n"
        f"     ports_skipped={len(meta['ports_skipped_guids'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
