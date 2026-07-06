#!/usr/bin/env python3
"""Regenerate the GH component catalog (src/rhinoclaw/static/gh_components.json).

Run from rhinoclaw_server/ with a live Rhino (tcpstart) whenever installed
GH plugins change:

    RHINOCLAW_HOST=<host> uv run python scripts/generate_gh_catalog.py

Produces a JSONL on the Windows side; assemble it into the catalog JSON
(dedupe by guid, add meta incl. ports_skipped_guids) and place it under
src/rhinoclaw/static/gh_components.json.

Chunked with hang detection: some components block on CreateInstance
(UI components / dialogs) — those get proxy-only entries and are skipped
on resume. Chunk results are written FILE-side (UTF-8 via codecs) because
some plugins emit non-UTF-8 bytes to stdout during instantiation, which
kills the plugin's output capture.
"""
import json
import os

from rhinoclaw.server import get_rhino_connection



OUT_WIN = 'C:/Users/YourName/Desktop/rhinoclaw_test/gh_components.jsonl'
OUT_WSL = '/mnt/c/Users/YourName/Desktop/rhinoclaw_test/gh_components.jsonl'
MARK_WSL = '/mnt/c/Users/YourName/Desktop/rhinoclaw_test/gh_marker.txt'
CHUNK = 110

rhino = get_rhino_connection()

CODE = """
import clr
clr.AddReference('Grasshopper')
import Grasshopper
import json
import codecs
server = Grasshopper.Instances.ComponentServer
proxies = list(server.ObjectProxies)
start = __START__
end = min(start + __CHUNK__, len(proxies))
skip = set(__SKIP__)
errors = 0
def ports(plist):
    res = []
    for p in plist:
        try:
            res.append({'n': p.Name, 'nn': p.NickName, 't': p.TypeName})
        except:
            res.append({'n': '?', 'nn': '?', 't': '?'})
    return res
f = codecs.open(r'__OUT__', 'a', encoding='utf-8')
m = codecs.open(r'__MARK__', 'w', encoding='utf-8')
try:
    idx = start
    for proxy in proxies[start:end]:
        try:
            desc = proxy.Desc
            entry = {
                'guid': str(proxy.Guid),
                'name': desc.Name,
                'nick': desc.NickName,
                'cat': desc.Category,
                'sub': desc.SubCategory,
                'desc': (desc.Description or '')[:140],
            }
            if proxy.Obsolete:
                entry['obsolete'] = True
            if str(proxy.Guid) in skip:
                entry['ports_skipped'] = 'instantiation hangs'
            else:
                m.seek(0)
                m.write(str(idx) + '|' + str(proxy.Guid) + '|' + desc.Name)
                m.flush()
                try:
                    inst = proxy.CreateInstance()
                    if inst is not None:
                        try:
                            if hasattr(inst, 'Params'):
                                entry['in'] = ports(inst.Params.Input)
                                entry['out'] = ports(inst.Params.Output)
                            elif hasattr(inst, 'TypeName'):
                                entry['param_type'] = inst.TypeName
                        finally:
                            try:
                                inst.Dispose()
                            except:
                                pass
                except:
                    errors += 1
            f.write(json.dumps(entry, ensure_ascii=True) + '\\n')
        except:
            errors += 1
        idx += 1
finally:
    f.close()
    m.close()
print('OK:' + str(start) + '-' + str(end) + '/' + str(len(proxies)) + ' e:' + str(errors))
"""


def lines_in_file():
    if not os.path.exists(OUT_WSL):
        return 0
    with open(OUT_WSL, 'rb') as fh:
        return sum(1 for _ in fh)


skip_guids = []
start = lines_in_file()
total = 2639
print('Resume ab Index', start)
while start < total:
    code = (CODE.replace('__START__', str(start))
                .replace('__CHUNK__', str(CHUNK))
                .replace('__OUT__', OUT_WIN)
                .replace('__MARK__', 'C:/Users/YourName/Desktop/rhinoclaw_test/gh_marker.txt')
                .replace('__SKIP__', json.dumps(skip_guids)))
    try:
        raw = rhino.send_command('execute_rhinoscript_python_code',
                                 {'code': code}, timeout=90)
        text = str(raw if isinstance(raw, str) else (raw or {}).get('result', ''))
    except Exception:
        # Hänger: Marker lesen → Schuldigen überspringen, ab Dateistand weiter
        marker = ''
        if os.path.exists(MARK_WSL):
            marker = open(MARK_WSL, encoding='utf-8', errors='replace').read().strip()
        print('HÄNGER bei start=%d — Marker: %s' % (start, marker[:120]))
        if marker:
            guid = marker.split('|')[1]
            skip_guids.append(guid)
        # Rhino Zeit geben, den hängenden Call zu beenden
        import time
        for _ in range(24):
            time.sleep(5)
            try:
                rhino.send_command('ping', {}, timeout=5)
                break
            except Exception:
                continue
        start = lines_in_file()
        continue
    if 'OK:' not in text:
        print('FEHLER bei start=%d: %s' % (start, text[:200]))
        raise SystemExit(1)
    status = text.split('OK:', 1)[1].strip()
    print('chunk', status)
    start = lines_in_file()

print('FERTIG:', lines_in_file(), 'Einträge | übersprungen:', skip_guids)
