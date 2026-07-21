# Changelog

## [0.7.2] - 2026-07-16

ClawChat now keeps dashboard endpoints per agent surface, safely migrates old
Hermes defaults, and the Yak publishing path no longer suggests an impossible
yank-and-overwrite workflow.

### Changed — configurable agent-surface dashboards
- **Each built-in ClawChat surface has its own URL override.** Editing the URL
  for OpenClaw, Hermes, Open WebUI, or LibreChat now persists only for that
  preset instead of turning the selection into one global custom endpoint.
- **Hermes defaults to a secure (HTTPS) general-profile dashboard.**
  Existing explicit custom URLs remain untouched, while the former
  `http://localhost:8080` default migrates automatically.
- **Preset defaults remain upgradeable.** Returning an edited URL to its
  catalog default clears the override, so future releases can update that
  default without leaving a stale saved copy behind.

### Fixed — safe, immutable Yak publishing
- **Duplicate releases are now idempotent and non-destructive.**
  `build-and-install.ps1` checks all visible stable and prerelease versions and
  skips a push when the exact version is already live. It no longer offers to
  yank and re-push a version, because Yak versions cannot be overwritten even
  after yanking.
- **Failed pushes give an actionable recovery path.** The script preserves Yak
  output and distinguishes the two valid next steps: bump the version if it was
  ever published, or refresh `yak login` for a genuinely new version.

### Tests
- Added a Rhino-independent .NET 7 test executable covering the built-in
  surface catalog, per-preset override keys, legacy Hermes migration, and
  default-versus-custom URL persistence.

## [0.7.1] - 2026-07-07

### Improved — blocked-prompt diagnosis on TIMEOUT (agent-smoke feedback)
- **Plugin `TIMEOUT` responses now carry the live command prompt**: when a
  command times out on the UI thread, the error includes `command_prompt`
  (from `RhinoApp.CommandPrompt`) and — when a command is visibly waiting for
  input — a `hint` pointing at `send_command_input` `{"input": "_Cancel"}`.
  Lets an agent distinguish "slow command" from "scripted token stream came
  up short and a prompt is blocking the UI thread" without a second
  `get_command_history` round-trip. Found while driving RhinoSheetMetal
  smoke tests through the TCP gateway.
- **`test_mcp_client.py` rewritten to the real wire protocol**: the old
  example spoke MCP JSON-RPC (`tools/list`) and assumed newline-framed
  responses — both wrong for the plugin's TCP port (raw
  `{"type", "params", "request_id", "auth", "timeout"}` JSON, no newline
  delimiter; accumulate-and-parse). The example now documents framing, auth
  via `RHINOCLAW_AUTH_TOKEN`, and doubles as a CLI probe
  (`python test_mcp_client.py <command> '<params-json>'`).

## [0.7.0] - 2026-07-06

ClawChat gets a live Terminal view, the RhinoSheetMetal plugin becomes
agent-drivable via the native-command allowlist, and the release pipeline's
CI publishing (Yak + PyPI) actually fires for the first time.

### Added — ClawChat Terminal view
- **Terminal tab in the ClawChat panel.** Toolbar toggle between "Chat"
  (the embedded agent dashboard) and a new "Terminal" view: live Rhino
  command-line output (monospace, dark, 2000-line buffer, auto-scroll),
  the current prompt, and an input line that scripts commands via
  `RhinoApp.RunScript` on the UI thread — same mechanism as the WebSocket
  `send_input`. Works without the WebSocket server running.
- **One shared command-line feed.** The WebSocket server's polling loop
  moved into a ref-counted `CommandLineMonitor` (first subscriber starts
  the thread, last one stops it); the WS server and the Terminal view now
  share a single poller. WS wire format unchanged; the WS heartbeat became
  a 30 s timer.

### Added — RhinoSheetMetal commands allowlisted
- **`run_native_command` accepts the 16 production `RSM*` commands** of the
  RhinoSheetMetal plugin (loaded alongside RhinoClaw), enabling the
  agent-driven sheet-metal workflow described in that repo's
  `integrations/skill/SKILL.md`. The spike-only `RSMPrototypeCustomObject`
  stays excluded.

### Fixed — release pipeline actually publishes
- **CI publish workflows fire now.** `rhino-plugin-publish.yml` (Yak) and
  `mcp-server-publish.yml` (PyPI) triggered on `release: published` in the
  dev repo — an event that never occurs because GitHub Releases are created
  in the `rhinoclaw-release` mirror. Neither workflow had ever run; as a
  side effect the `rhinoclaw` package was never published to PyPI, so the
  documented `uvx rhinoclaw` onboarding could not work. Both now fire on
  `vX.Y.Z` tag pushes (plus `workflow_dispatch`), and `deploy.ps1` phase 4
  pushes the tag. The CI Yak push is idempotent (skips if the version is
  already on the server, since phase 3 usually pushed locally first).
- **Stale `dist/` artefacts removed from git.** A checked-in
  `rhinoclaw-0.1.3.6` package sat exactly where the CI workflow builds its
  release artefact — `find -name "*.yak" | head -1` could have shipped the
  ancient package. `dist/` was already gitignored; the tracked files are
  gone and the workflow now clears `*.yak` before `yak build`.

### Fixed — post-A3/A4 review hardening
- **Wire framing survives multi-byte UTF-8 at chunk boundaries.** A recv chunk
  boundary landing inside a multi-byte character (umlauts in layer/object
  names) raised an uncaught `UnicodeDecodeError` in
  `wire.read_json_frame` instead of continuing the read loop. Now treated as
  a partial frame; truncation at end-of-stream maps to `IncompleteFrameError`.
- **Per-call timeout is honoured on receive.** `receive_full_response`
  overrode the caller's clamped per-call timeout with the global
  `timeout_seconds` default, silently cutting long-running commands short.
  The timeout now threads through `_execute_command` → `receive_full_response`.
- **`rhinoclaw_client/config.json` is now actually loaded.** `CONFIG_PATH`
  pointed one directory too high (`scripts/config.json`, which never existed),
  so the config file was silently ignored in both the repo and the deployed
  skill. It went unnoticed because the hardcoded fallbacks matched the file's
  values — no behavioural change with the shipped config.

### Changed — agent-neutral integrations (Workstream A)
- **`scripts/clawdbot/` renamed → `scripts/rhinoclaw_client/` (A4).** The raw-TCP
  Python client dropped its OpenClaw-specific brand name. A `scripts/clawdbot`
  **compatibility symlink** points at the new directory for **one release** —
  update any local scripts/aliases to `scripts/rhinoclaw_client/`; the symlink
  will be removed next release. **The deployed skill target
  `~/clawd/skills/rhinoclaw/` is unchanged** (that is OpenClaw's own skill-dir
  convention, not ours); `sync-skill.sh` still deploys there.
- **One wire transport (A3).** The TCP wire framing now lives once in
  `rhinoclaw/transport/wire.py`, shared by the MCP server's `RhinoConnection` and
  the `rhinoclaw_client` `RhinoClient` (no adapter re-rolls its own socket).
  Behaviour-preserving; `sync-skill.sh` ships `wire.py` flat like `door_batch.py`.
- **Hermes skill pulled in-repo (A2).** `integrations/hermes/` is now the source
  of truth, deployed via `scripts/sync-hermes-skill.sh`.
- **Capability manifest + integrations hub (A1).** `integrations/CAPABILITIES.md`
  + `capabilities.json`, generated from the live MCP registry.

### Added — the verified GH authoring loop
- **`build_gh_interactive`** (tool 124) — ONE verified iteration of the
  graph-authoring loop per call: offline lint (fails in milliseconds,
  before any round-trip) → `build_and_bake_gh` with **catalog-derived
  `bake_output`** + automatic retry on a nickname mismatch → headless
  verdict via `inspect` of the written file → re-measured geometry
  (`get_objects_info` union bbox) judged against caller `expect`
  (`dims_mm`/`bbox_min`/`bbox_max`/`min_count`) → actionable hints →
  one `graph_outcome` JSONL record per iteration (the corpus the recipe
  registry distills from; separate field, door corpus untouched).
  Live-verified 2026-06-12: hallucinated GUID caught offline (iter 1),
  Center-Box half-extent semantics caught by measured dims (iter 2),
  PASS with 4/4 expectations met (iter 3) — flawed prompt → passing
  headless-solvable graph in 3 iterations.
- **`utils/gh_critic.py`** — pure critique core (Rhino-free, like
  `door_judge.py`): terminal-component detection, catalog-derived
  bake-output candidates (geometry ports before numeric), expectation
  checks with per-axis error hints.
- 19 new tests (`test_build_gh_interactive.py`).

### Added — composition recipes
- **`utils/gh_recipes.py`** — four named composition recipes instantiated
  from the component catalog as SDK-native graphs: `rect_extrude`
  (rectangle→extrude), `box_difference` (native solid CSG — box minus
  through-cut; the GH Cylinder outputs an uncapped surface that Solid
  Difference rejects, so box-minus-box is the reliable form), `box_array`
  (Linear Array along X), `box_orient` (WorldXY→WorldXZ). Every recipe
  computes its OWN measurable expectation from its params (dims/corners/
  count), so verification means re-measured-geometry-matched-contract,
  never bake-returned-success.
- **`build_and_bake_recipe` extended** — one entry point, two registries:
  plugin primitives (box/sphere/cylinder/cone) unchanged; composition
  recipes route through the full verified loop (`build_gh_interactive`)
  and return its verdict (`data.pass`, `measured`, `hints`).
  `recipe="list"` merges both registries and degrades to the offline
  composition list when Rhino is unreachable.
- Live-verified 2026-06-12: **all four compositions PASS first-try
  headless** — measured dims exact ([400,200,100] extrude; 4 objects,
  X-extent 550 = 2·50+3·150 array; [400,100,200] orient = the Y↔Z axis
  swap measured, not claimed). Outcomes logged as `recipe:<name>` records.
- Registry drift-guard: every recipe lints against the REAL shipped
  catalog in tests — GUID/port drift after a Rhino update fails offline.
- 19 new tests (`test_gh_recipes.py`); offline suite 555 passing.

## [0.6.0] - 2026-06-12

The verified-vertical release: door placement is now **judged against real
geometry, learned from, and benchmarked** — the planned self-improving loop
is closed and live-verified. 111 MCP tools (was 88 in docs / 91 registered),
474 tests.

### Added — the verified door loop
- **`place_doors`** — batch door placement over the proven Player mechanic
  (prompt-feeding, GUID diff, layer→rotation→group post-processing). Per
  door returns `{object_ids, baked_bbox, rotation_applied, point,
  width_requested, wall_axis, group, layer, status}` — `baked_bbox` is
  measured back via `get_objects_info`, never echoed from the request.
  Core shared with the clawdbot CLI (`utils/door_batch.py`); fails fast
  when Rhino can't see the definition; honest `no_geometry` status.
- **`judge_door_placement`** — the domain judge: re-measures every door
  and scores it against independently drawn opening axes (explicit or
  from layer `01_OPENING_AXES`): `off_center_mm`, `axis_deg_error`,
  `width_error_mm` → `pass` + actionable `hint`. Ignores all claims in
  the input (anti-self-grading; the forced wrong-rotation test passes).
- **`recall_placements`** + outcome corpus — every verdict is logged as a
  `placement_outcome` JSONL record; `utils/recipe_distiller.py` distills
  them into `logs/door_recipes.json`; recall is a deterministic lookup
  (best = lowest judge-measured off-center, `confidence` = n passing).
- **COLD/WARM benchmark** (`bench/door_bench.py`, 12-opening scene):
  **live Rhino 8 result: first-try success 50% → 100% with recall**.
  Sim mode runs as a CI regression gate (`tests/test_door_bench.py`).
- **`examples/floorplan_6_openings.3dm`** — agent-authored floor plan
  with walls + opening-axis ground truth; full loop live-verified on it
  (6/6 first-try pass via `opening_layer`).

### Added — platform
- **`execute_python3_code`** — real CPython 3.9+ via the Rhino 8 Script
  Editor runtime (f-strings, `pathlib`, pip packages via `# r:`), plus
  **`get_script_capabilities`**. The plugin command existed but had no
  MCP wrapper.
- **`rhinoclaw_doctor`** — six setup checks (connection, auth, version
  match, Grasshopper, WSL host, outcome corpus), every FAIL with the
  exact fix.
- **`deploy_gh_to_compute`** — deploy `.gh`/`.ghx` + `.meta.json` into
  the Compute Platform `definitions/` contract, with **RH_OUT validation**:
  a script output named `RH_OUT:*` can never bind (empty solves) and now
  blocks the deploy with the fix hint (`force=True` overrides).
- **14 dormant tools unlocked** — decorated but never imported
  (`solve/bake_grasshopper`, `get_grasshopper_outputs`,
  `set_grasshopper_parameter`, `load/unload/list_grasshopper_definitions`,
  mesh trio, session/logging tools). Registration drift-guard test added.
- **Inspect verdicts** — `inspect_grasshopper_definition` now reports
  `groups` (the RH_OUT contract carrier), `script_components`,
  `script_component_count`, and a `headless_solvable` verdict.
- **CI builds the C# plugin** on every PR (`dotnet build`, NuGet
  RhinoCommon — no Rhino install needed); GitHub Actions bumped to
  Node-24-ready majors ahead of the 2026-06-16 forced switch.

### Fixed
- `# r:` / `# requirements:` package comments in `execute_python3_code`
  were invisible to the RhinoCode resolver (user code is indented into a
  try block) — now hoisted into the wrapper's leading block.
- `capture_viewport` mangled absolute Windows paths on a WSL server
  (`PosixPath.is_absolute()` is false for `C:/...`).
- `place_doors` ran blind into the full player timeout when the
  definition path wasn't visible to Rhino — now fails fast with a
  WSL-path hint.
- `create_layer` NRE on duplicate names; `hello` auth semantics
  clarified (post-0.5.0 follow-ups).

### Removed
- `learning/learning_data*.json` — orphaned demo schema, 0 producers.

### Known limitations
- The numeric judge cannot distinguish door swing direction (0° vs 180°
  pass identically) — Bandseite needs the planned visual judge.

## [0.5.0] - 2026-06-05

Grasshopper authoring + native headless bake + agent auth stabilization. An
agent can now author and bake parametric geometry, and the auth/connection
handshake is deterministic.

### Added
- **`build_gh_definition` / `build_and_bake_gh`** MCP tools — thin wrappers over
  the C# `GrasshopperDefinitionBuilder` engine (which was dispatched but had no
  Python wrapper). An agent can now author a `.gh` programmatically. (#13)
- **`build_and_bake_recipe`** — parametric headless bake from verified
  SDK-native recipes (`box`/`sphere`/`cylinder`/`cone`); GUIDs + input ports
  introspected from a live Rhino 8.31 install. (#16)
- **`bake_output`** parameter on `build_and_bake_gh` (native outputs are
  `B`/`S`/`C`, not `a`). (#16)
- **`hello`** — an **auth-free handshake** (bypasses the auth gate + the
  brute-force counter) returning plugin version, auth-required, mode, GH
  availability, and this client's auth/block state. Discover the server's state
  without a token or risking a block.
- **`preflight`** — the deterministic "run this FIRST" tool: one call → the full
  connection/auth state + an exact `next_action`. Ends auth/ping trial-and-error.
- Door-placement post-processing in `scripts/clawdbot/grasshopper.py`
  (z-rotation / grouping / layer routing + `run_doors_batch`) — foundation for
  the upcoming `place_doors` MCP tool.
- **`get_objects_info`**, document/selection events, `subscribe_events` (0.4.0
  Wave-4 features, now on main).
- First **real-socket transport tests** (`tests/test_transport_loopback.py`).

### Fixed
- **Reconnect-retry double-execution ("double bake")** — a mutating command that
  ran server-side then lost the socket was re-executed on reconnect. Added a
  stable `idempotency_key` per `send_command` (client) + a server-side dedup
  cache + a structured `TIMEOUT` frame on UI-thread overrun (plugin). (#13)
- **`build_and_bake_gh` baked nothing for typed/generic goo** — `BakeGoo` now
  unwraps generic `GH_ObjectWrapper` (Python3 outputs) via `ScriptVariable()`;
  added `data.diagnostics`. (#14)
- **Native headless bake produced nothing** — the re-read `GH_Document` was
  never registered on `Instances.DocumentServer` / enabled, so `NewSolution`
  computed no components (every output 0 items, native too). Register + enable
  before solve, remove after, in both the bake and SDK-solve paths.
  `build_and_bake_recipe`, `solve_grasshopper`, `bake_grasshopper` now produce
  geometry headlessly. Verified in Rhino 8.31. (#17)
- **CI broken by PEP-668 runners** — `uv pip install --system` → `uv run
  --extra dev` / `uvx`. (#13 follow-up)

### Known limitations
- **Grasshopper script components (Python 3 / GhPython) do not solve in headless
  GH** on Rhino 8 (editor-wired runtime) — confirmed in-Rhino. Use
  `build_and_bake_recipe` (native components) or `execute_rhinoscript_python_code`
  for guaranteed geometry. `build_gh_definition` (authoring) is unaffected.

## [0.4.1] - 2026-05-05

Combines the 0.4.0 Wave-4 features (which never reached Yak — see note
below) with release-pipeline fixes uncovered during the 0.3.2 deploy.

### Fixed
- `release.ps1`: replaced the
  `(& git diff --cached --quiet; $LASTEXITCODE)` subexpression idiom
  with explicit two-statement form. The compact pattern was tripping
  "Missing closing ')' in expression." on some Windows / PowerShell
  versions even though it's syntactically valid.
- `release.ps1` GitHub Release call: switched from `New-TemporaryFile`
  to `[System.IO.Path]::GetTempFileName()` and inlined the
  multi-line `gh release create ... \` backtick continuation — both
  changes remove parser ambiguity sources that share the same error
  signature.

### Changed
- `deploy.ps1` got Phase 6: ClawHub skill publish. One-shot release
  is now `.\scripts\deploy.ps1 0.X.Y` → bump → tests → build → Yak
  push → dev push → release-repo + tag + GitHub Release → ClawHub
  publish. `-SkipClawHub` flag for opt-out. Final summary lists all
  five distribution endpoints.

### Note on numbering
Yak briefly carried `0.3.2` (a Wave-4-feature build that got bumped as
patch by mistake). Bumping to `0.4.1` here both restores the
semantic-versioning intent (Wave-4 is a minor) and skips the orphan
`0.4.0` CHANGELOG entry that never reached Yak.

## [0.4.0] - 2026-05-05 (orphan — never published)

Wave 4 — real-time TCP. The plugin now pushes live document- and
selection-change events to subscribed agents, exposes a bulk read
path for the common "info for N objects" case, and resists brute-
force attacks against the optional auth token.

### Added
- **`get_objects_info(ids)`** MCP tool — bulk version of
  `get_object_info`. One TCP round-trip for N objects instead of N
  individual calls or a custom `execute_python3_code` loop. Missing
  / invalid GUIDs reported separately rather than failing the whole
  call. `BuildObjectInfoPayload` shared helper means singular and
  plural handlers can never schema-drift.
- **Document-change events** broadcast through the existing port-
  2000 WebSocket channel: `object_added`, `object_deleted`,
  `object_modified` (with attribute diff), `object_replaced`.
- **Selection-change events**: `selection_changed` with full id
  array plus `by_layer` and `by_type` histograms. 50 ms coalesce
  window so a marquee select fires one event, not 50.
- **`subscribe_events`** MCP tool — agent's entry point for the
  event stream. Connects (idempotent), returns a manifest of
  available types, sub-events, filter keys, and follow-up tools.
- **`wait_for_object_event(event=, layer=, object_type=, timeout=)`**
  typed wait with AND-combined client-side filters.
- **Brute-force protection** for the auth gate. Per-remote sliding
  failure counter; 5 fails inside 60 s trips a 15-minute block,
  during which commands return `AUTH_BLOCKED` with a
  `blocked_until` ISO-8601 timestamp. Tunable via env vars
  (`RHINOCLAW_AUTH_MAX_FAILURES`, `_FAILURE_WINDOW`,
  `_BLOCK_DURATION`).
- **Persistent audit log** at
  `%LOCALAPPDATA%\rhinoclaw\logs\auth_YYYYMMDD.jsonl` — one JSON-Line
  per auth event (success / failure / blocked / rejected_pre_block)
  with timestamp, remote endpoint, command, reason. Best-effort
  writes; daily rotation.

### Changed
- Auth gate now does pre-block check → token compare. Blocked
  remotes get no timing oracle while the cooldown runs.
- `RhinoClawWebSocketServer.BroadcastEvent` scope `private` →
  `internal` so the new event broadcasters in the same assembly
  can push through it.

## [0.3.1] - 2026-05-05

### Fixed
- `release.ps1`: PowerShell parser choked on `'/home/<user>/[^\s"'']*'`
  (escaped single quote inside single-quoted regex). Dropped the
  apostrophe from the character class — paths essentially never contain
  apostrophes anyway.
- `deploy.ps1`: phase 4 was using `git add -A` which dragged in build
  artefacts (`dist/`, `*.yak`), Yak output, scratch test JSON, and
  `__pycache__` noise. Now selectively stages only the eight version-
  bearing files and commits only when something actually changed.
- Partial-class collision fixes: `ParsePoint3d`, `Environment`,
  `NativeCommandAllowlist` were all defined twice across partials of
  `RhinoClawFunctions`. Renamed / consolidated each.

### Changed
- `.gitignore` now blocks `rhinoclaw_plugin/bin/`, `dist/`, `*.yak`,
  `scripts/clawdbot/batch_*.json`, and `__pycache__` paths.
- ListCapabilities now reads the `RunNativeCommand` allowlist via
  reflection over the shared HashSet — single source of truth for
  which native Rhino commands the agent may fire.

## [0.3.0] - 2026-05-05

### Added
- **`scripts/deploy.ps1`** — one-command end-to-end release pipeline
  for Windows: bump version → quality gates → build .rhp → Yak install
  + push → dev-repo commit + push → release-repo mirror + git tag +
  GitHub Release. Five phases each individually skippable
  (`-SkipBuild`, `-SkipYak`, `-SkipDevPush`, `-SkipRelease`), plus
  `-DryRun` and `-Resume` for retry-after-fail. Auto-creates uv venv
  if missing.
- **`scripts/release.ps1`** — native PowerShell port of `release.sh`
  with all 9 steps (mirror, sanitise, README-badge sync, leak check,
  commit, tag, push, GitHub Release). Idempotent — safe to re-run.
- **`scripts/bump.ps1`** — PowerShell wrapper for `sync_version.py`
  that picks `python` over `python3` (the latter is the Microsoft
  Store stub on most Windows installs).

### Changed
- `release.sh` (bash side) gained the same README-badge sync + git
  tag + GitHub Release support so Linux/WSL workflows match Windows.
- The release pipeline now parses the per-version section out of
  `CHANGELOG.md` and uses it as the GitHub Release body — first time
  the GitHub-Release notes match the user's hand-curated changelog
  rather than a generic "see commits" placeholder.

## [0.2.9] - 2026-05-05

### Added
- **`run_native_command` MCP tool**. Last-resort hatch for Rhino native
  commands without a clean RhinoCommon SDK path (`_Sweep1`, `_Loft`,
  `_NetworkSrf`, `_BooleanSplit`, `_Trim`, …). Plugin enforces an
  allowlist (49 commands at first cut) so a misbehaving agent can't
  fire arbitrary Rhino script. Same allowlist is exposed via
  `list_capabilities` so the agent can check before calling.
- **`find_objects` MCP tool**. Selection by attribute / geometry filter:
  `layer`, `type`, `name_contains`, `name_regex`, `min/max_volume`,
  `min/max_x/y/z` (bbox-center filter), `selected`, `has_material`,
  `limit`. Cheap O(n) walk; volume only computed when bounds are set.
  Replaces a recurring reason agents fell back to `execute_python3_code`.
- **`list_capabilities` MCP tool** + skill-side `clawdbot/inventory.py`
  helper. Returns plugin/Rhino version, typed commands grouped into 16
  categories, native-command allowlist, scripting-path entry points
  (rhinoscriptsyntax + RhinoCommon with doc URLs), and a preferences
  ladder. Single source of truth for "what this plugin can do" — agent
  calls it once at session start.
- **`scripts/sync-skill.sh`** — push the dev copy of the OpenClaw /
  Clawdbot skill from `scripts/clawdbot/` into the location the agent
  actually loads from (`~/clawd/skills/rhinoclaw/` by default; first
  positional arg overrides). `--dry-run` and `--remove` modes;
  verifies that the deployed `rhino_client.py` carries the
  `RHINOCLAW_AUTH_TOKEN` Wave-2 fix.
- **`scripts/clawdbot/SKILL.md` rewritten** as agent-first material:
  decision tree at the top (typed tool → batch → rhinoscriptsyntax →
  RhinoCommon → native command), five concrete cookbook recipes,
  scripting paths section explaining when to use `rhinoscriptsyntax`
  vs RhinoCommon, negative-examples list, troubleshooting matrix.
  Replaces a flat 568-line listing with a structured guide.
- **`docs/rhinocommon-cookbook.md`** — curated hot-path patterns for
  the cases where typed tools and `rhinoscriptsyntax` don't reach.
  Eleven sections: object lookup, Brep ops + boolean + volume, curve
  math, surface ops, mesh, transforms, layers/materials, intersection
  events, vector math, native command escape, save-and-redraw rules.
  Cross-linked from SKILL.md and AGENTS.md.
- **`batch_operations` MCP tool** (#11). Multi-step transactions in
  one TCP round-trip. Each step is `{"tool": str, "args": dict}`. Four
  on-error policies: `rollback` (default — undo every successful step
  on failure), `abort` (stop, leave completed steps), `continue` (skip
  failure, keep going), `best_effort` (continue + outer success stays
  true). The whole batch executes inside one Rhino undo record so a
  single Ctrl+Z rolls back the entire macro for the user. Per-step
  results are returned in order with `success`/`result`/`error` so the
  caller can introspect partial progress.
- **Scene-analysis MCP tools** (#5). Four new tools that give the
  agent spatial reasoning without dragging the whole document over the
  wire:
  - `find_nearby(point, radius, by="center"|"closest", layer?)` —
    O(n) AABB scan, returns ID + name + layer + type + distance for
    each match, sorted ascending. Optional layer filter.
  - `is_inside(object_id, container_id, strictly_inside=true)` —
    AABB-reject first; if the container is a closed (solid) Brep,
    confirms with `Brep.IsPointInside` on bbox center (and all 8
    corners in strict mode). Otherwise the AABB result stands.
  - `get_relationships(object_id, touch_tolerance?, limit=50)` —
    classifies every other object as touching (bboxes within
    tolerance, interiors disjoint), overlapping (bbox overlap), and/
    or aligned (shared min/max on at least one axis, grouped per
    axis-and-side: `x_min`, `x_max`, …, `z_max`).
  - `scene_summary(include_layers=true, include_types=true)` —
    full-document overview: object count, document bounding box,
    type histogram (Brep/Mesh/Curve/…), per-layer counts and
    bounding boxes.

### Fixed
- **`create_object type="BOX"` now creates a Brep** instead of an
  Extrusion. Lets `is_inside` use the accurate
  `Brep.IsPointInside` path (`method: "brep_point_in_volume"`) for
  containment tests against boxes. Spheres/Cylinders were already
  Breps; this brings boxes in line.

## [0.2.8] - 2026-05-05

### Added
- **`undo` and `redo` MCP tools** (#4). The agent can now roll back
  its own mistake without asking the human user to reach for Ctrl+Z.
  Each MCP tool call is wrapped in a single Rhino undo record, so one
  `undo()` rolls back one tool call atomically. The undo / redo
  commands themselves are *not* wrapped (they'd push their own action
  onto the stack and produce confusing "undo the undo" semantics) —
  same convention Rhino's native Ctrl+Z uses for itself.
- Undo records now carry the actual MCP command name (`MCP: create_object`
  instead of the previous generic `Run MCP command`), so the user's
  Edit → Undo menu and the undo history dialog show what's actually
  being rolled back.
- **Auth-token setup helper.** New `scripts/setup-auth-token.ps1`
  generates a cryptographically-random 256-bit token (43 URL-safe
  Base64 characters, via .NET's `RandomNumberGenerator`), persists it
  as the Windows User-environment variable `RHINOCLAW_AUTH_TOKEN`,
  and prints copy-paste blocks for the WSL / Cursor / Claude Desktop
  client side. `-Reveal` re-prints the token, `-Show` outputs it
  plain for piping, `-Remove` revokes, `-Generate` prints a fresh
  token without persisting.
- **`get_auth_status` MCP tool.** Round-trips a `ping` through the
  plugin and reports whether the client is sending an auth token
  and whether the plugin accepted it. Exposes only a fingerprint
  (first 4 + last 4 chars) of the token so you can spot-check that
  both sides match without ever logging the secret in full.
- **Plugin auto-start** (#1). New `mcpautostart` Rhino command lets
  the user persist the choice "start the RhinoClaw server when Rhino
  launches" across restarts. Uses Rhino's `RhinoApp.Idle` hook to defer
  startup until the UI thread is fully initialised — sidesteps the
  race condition that broke the previous attempt at OnLoad-time.
  - Default after install/update: **off**. The user opts in via
    `mcpautostart` → "On". Mode toggle stays at the default `tcp`
    (binds `0.0.0.0` for WSL/LAN access) unless changed; an `mcp` mode
    binds loopback only.
  - When auto-start fires in TCP mode, the plugin prints a multi-line
    SECURITY warning at the top of the Rhino command line if no
    `RHINOCLAW_AUTH_TOKEN` is configured. With a token set, it prints
    "Auth: enforcing RHINOCLAW_AUTH_TOKEN" instead.
  - Settings persisted in Rhino's `PlugIn.Settings` (no env-var, no
    extra config file).

### Changed
- `scripts/build-and-install.ps1` now reads name + version straight from
  `manifest.yml` (no hardcoded strings) and grew an optional Yak-publish
  step. `-Push` skips the prompt; without it the script asks once after
  install whether to publish to https://yak.rhino3d.com/. The push step
  warns + interactive-yanks if the same version is already on the
  server, and verifies the version surfaces in `yak search` after push.

## [0.2.7] - 2026-05-04

### Fixed
- **Plug-Ins-Dialog and panel icons not displaying.** The earlier
  attempt embedded a PNG and tried to load it as a
  `System.Drawing.Icon` — that constructor only accepts ICO format
  and silently fails (no exception, no icon). A dedicated
  `rhinoclaw_panel.ico` (16/24/32/48) is now embedded and used by
  the Chat panel. Both `rhinoclaw.ico` (plug-in dialog) and the
  panel `.ico` carry an explicit `<LogicalName>` in the csproj so
  the resource path is independent of how MSBuild infers the
  RootNamespace; both `<RootNamespace>` and `<AssemblyName>` are
  now pinned to `rhinoclaw` for the same reason. On plugin load
  the embedded icon resources are listed at Verbose level so a
  next-time mismatch is diagnosable from the Rhino command line.

### Added
- **`inspect_grasshopper_definition` MCP tool** (#2). Loads a `.gh` /
  `.ghx` file, walks the document, and returns the parameter surface —
  inputs (sliders, toggles, panels, value lists, GrasshopperPlayer
  prompts, bare floating params), outputs (unconnected output ports),
  and an optional `components_by_type` summary. Stateless: the
  document is disposed immediately, so the call is safe to issue
  against an arbitrary file path without polluting the in-memory
  definition cache.

  Prompt detection is now type-name-pattern-based (`Get*Parameter`)
  rather than GUID-list-based, so it transparently picks up
  `GetIntegerParameter`, `GetNumberParameter`, `GetPointParameter`,
  `GetStringParameter`, `GetBooleanParameter`, `GetCurveParameter`
  and any future `Get*Parameter` siblings without having to maintain
  a list of GUIDs. Reflection lookups for `Prompt` and `Presets` try
  property → field → auto-property backing field in turn so the
  value is returned regardless of the GH SDK's internal layout.

  Each input now carries an `is_player_input` flag: prompts are
  always true, sliders / toggles / panels / value-lists are true
  when they feed into a prompt parameter, bare params are false. A
  new `only_player_inputs=True` query parameter applies that filter
  server-side, which is usually what an agent wants — a definition
  with 21 internal sliders and 5 prompts collapses to those 5.

  When a slider / panel / toggle / value-list is the **direct**
  upstream source of a prompt (the "Slider 960 → Get-Number
  Lichtbreite" pattern that keeps the definition usable in manual
  GH), the prompt now **absorbs** that source's metadata. The slider
  vanishes from `only_player_inputs` view; the prompt picks up its
  `value` (= the prompt's `default`), and for slider sources also
  `min` / `max` / `decimals`. A small `default_source` summary on
  the prompt and matching `is_prompt_default_source` /
  `feeds_prompt_guid` flags on the slider make the relationship
  inspectable in the unfiltered view too. A `Rahmentuer_UD5.gh`-style
  definition collapses from 38 → ~4 logical Player inputs.

### Changed
- **Documentation consolidation.** Repository root now ships only the
  documents end users and contributors actually need; stale plans and
  historical snapshots moved to an internal archive, and GitHub Issues
  became the source of truth for open work.

## [0.2.6] - 2026-05-03

### Added
- **`rhinoclaw/config.py`** — runtime configuration via environment
  variables. All connection settings are now overridable without code
  changes:
  - `RHINOCLAW_HOST`, `RHINOCLAW_PORT`, `RHINOCLAW_WS_PORT`
  - `RHINOCLAW_TIMEOUT`, `RHINOCLAW_MAX_TIMEOUT`
  - `RHINOCLAW_DEBUG`, `RHINOCLAW_LOG_FORMAT` (`text` or `json`)
  - `RHINOCLAW_LOG_DIR` (defaults to OS-appropriate state dir)
  - `RHINOCLAW_AUTH_TOKEN` (see below)
- **Optional bearer-token authentication.** When `RHINOCLAW_AUTH_TOKEN`
  is set on both server and client, every TCP command must carry a
  matching `auth` field. Plugin uses constant-time comparison to defeat
  timing attacks. Backwards-compatible: with no token configured,
  behaviour is identical to 0.2.5.
- **Structured logging** with optional JSON output
  (`RHINOCLAW_LOG_FORMAT=json`). Each tool call now carries a
  `request_id` that the plugin echoes back, so logs on either side of
  the TCP boundary can be correlated.
- **Bandit security scan** added to CI; **`.pre-commit-config.yaml`**
  for local hooks (ruff, large-file guard, version-consistency check).

### Changed
- `RhinoConnection` no longer hardcodes host/port/timeout — they come
  from `Settings`. The `send_command(timeout=...)` argument is still
  honoured, clamped to `[1.0, settings.max_timeout_seconds]`.
- `tcpstart` logs an explicit auth-status line on startup ("enforcing
  RHINOCLAW_AUTH_TOKEN" or "NO token configured").

### Fixed
- `scripts/sync_version.py` regex was matching `target-version =`
  inside `[tool.ruff]` and corrupting it on every bump. Now anchored
  to start-of-line.
- **Plugin/Yak icons.** The Yak Package Manager card and the embedded
  Chat panel were missing a logo, and the Rhino Plug-ins dialog was
  still showing the Visual Studio default icon. Now wired up:
  - `manifest.yml` references `icon.png` (200×200) so the Yak
    Package Manager card shows the RhinoClaw logo.
  - `EmbeddedResources/rhinoclaw.ico` (multi-size 16/24/32/48/64/128/256)
    referenced from `AssemblyInfo.cs` for the Plug-ins dialog.
  - `EmbeddedResources/rhinoclaw_panel_32.png` loaded by
    `ClawChatPanel.LoadPanelIcon()` for the panel header.
- Plugin description metadata (Organization, Email, Country, WebSite,
  UpdateUrl) was empty across the board; now filled in.
- `RhinoClawServer.cs` — `Environment.GetEnvironmentVariable` was
  ambiguous against `Rhino.DocObjects.Environment`. Fully qualified
  with `System.Environment`.

## [0.2.5] - 2026-03-22

### Added
- **Python 3 (CPython) execution** via `execute_python3_code` command
  - Hybrid approach: tries RhinoCodePlatform reflection API first, falls back to ScriptEditor temp file execution
  - Full stdout/stderr capture with structured JSON result
  - Proper error handling with traceback
  - Undo transaction support (auto-rollback on failure)
  - Requires Rhino 8+ (returns clear error on Rhino 7)
- **`get_script_capabilities` command** — query available scripting engines
  - Returns `ironpython2`, `python3` availability, and `rhino_version`
  - Useful for agents to determine which script executor to use

## [0.2.4] - 2026-03-22

### Added
- **VisualARQ BIM Integration** – Complete BIM workflow with graceful degradation
  - **`visualarq.py` script** (1553 lines) with 24 commands for BIM object management
  - **Walls, doors, windows, columns, beams, slabs** – Full architectural BIM objects
  - **Building hierarchy** – Buildings and levels with elevation management
  - **Custom BIM parameters** – Add/set/get custom properties (text, number, boolean, length)
  - **IFC import/export** – Support for IFC2x3, IFC4, IFC4.3 formats
  - **Style management** – Query and create wall/door/window styles
  - **Object queries** – List all BIM objects with properties
  - **Graceful degradation** – No crashes when VisualARQ not installed

#### VisualARQ Commands Added

| Category | Commands | Description |
|----------|----------|-------------|
| **Setup** | `check`, `info` | Verify installation, get styles/levels overview |
| **Geometry** | `wall`, `door`, `window`, `column`, `beam`, `slab` | Create BIM objects with styles |
| **Hierarchy** | `levels`, `add-level`, `add-building` | Building structure management |
| **Parameters** | `add-param`, `set-param`, `get-param` | Custom BIM properties |
| **IFC** | `ifc-export`, `ifc-import` | Industry standard exchange |
| **Queries** | `list-walls`, `list-doors`, `list-windows`, `list-objects` | BIM object inspection |
| **Styles** | `wall-styles`, `door-styles`, `window-styles`, `add-wall-style` | Style management |

## [0.2.3] - 2026-03-19

### Added
- **`build_gh_definition` command** – programmatic Grasshopper definition builder
  - Python 3 Script components with custom named inputs/outputs
  - Number Sliders, Boolean Toggles, Panels
  - SDK (native) components by GUID
  - Custom Preview components with Material input
  - Colour Swatch with named presets (wood, oak, walnut, birch, steel, glass, etc.)
  - Automatic wiring between components by name or index
- **`build_and_bake_gh` command** – build + solve + bake to named Rhino layer
  - Optional layer colour and material assignment
  - Configurable bake output parameter
- **Template catalog** at `skills/rhinoclaw/templates/ghscripts/`
  - Parametric Chair (curved backrest, tapered legs, stretchers)
  - Parametric Table (tapered legs, aprons, overhang)
  - Parametric Shelf (adjustable shelves, divisions, back panel, plinth)
  - TwistedTower (helix sculpture with 8 parameters)

### Key Discovery
Rhino 8 Python 3 Script components require specific initialization:
1. Add to active GH_Document BEFORE parameter manipulation
2. Use `CreateParameter()` + `VariableParameterMaintenance()` for new params
3. `SetParametersToScript()` to bind params to script runtime
4. `#! python3` shebang in source code

## [0.2.2] - 2026-03-19

### Changed
- Version bump for GH builder integration

## [0.2.1] - 2026-03-18

### Changed
- **Renamed SentinelChat → ClawChat** – generic branding for public release
  - Rhino Command: `ClawChat` (was `SentinelChat`)
  - Panel title: "RhinoClaw Chat" (was "Sentinel Chat")
  - Settings key: `ClawChatUrl` (auto-migrates from `SentinelChatUrl`)
- Updated manifest description

### Fixed
- Panel registration stability

## [0.2.0] - 2026-03-16

### Added
- **ClawChat Panel** – embedded AI chat directly inside Rhino 8
  - Eto.Forms WebView, Rhino Command: `ClawChat`
  - Setup screen with presets: OpenClaw, Tailscale, Ollama, LibreChat, Custom URL
  - Persistent URL, ⚙ Settings button
- Smart Grasshopper prompt handling with parameter metadata pre-loading
- Build-and-install PowerShell script

### Changed
- Bumped version to 0.2.0
- Updated Yak manifest for publish

## [0.1.3.9] - 2026-02

### Added
- 72 MCP tools for geometry, transforms, booleans, materials
- Grasshopper integration (SDK, Player, Presets)
- Viewport control, screenshots, render settings
- Groups & Blocks management
- File operations (import/export)
- Boolean operations (union, difference, intersection)
- PBR material support
- Enhanced debugging and logging

## [0.1.0] - 2026-01

### Added
- Initial release
- TCP/WebSocket server in Rhino plugin
- Python MCP server
- Basic geometry creation and manipulation
- Document inspection
- Script execution
