# Changelog

## [0.8.2] - 2026-10-13

### Packaging

- Yak staging explicitly selects the required runtime files for .NET 7/8/10
  and includes the license. Archive gates inspect Yak, wheel and source-package
  contents, version/platform metadata, size ceilings, unsafe paths and checksums
  before publication. CI retains inventories for review.
- Public exports are fresh allowlisted snapshots containing the complete Yak,
  Python runtime sources and current installation/migration documentation.
  Local logs, caches, models and development scratch files are excluded without
  deleting them from the development repository. Both shell entry points share
  one exporter and publisher; validation and exact-commit CI precede mirror writes.
- `prepare-release.ps1` runs offline gates and produces reviewable artifacts
  without installation, commits, tags or publication. Source distributions now
  include the shared test fixtures alongside their test modules.
- These packaging changes preserve the 0.8.2 runtime behavior and MCP tool names.

### Verified on Rhino 8

- The installed .NET 8 candidate passed native Undo/Redo, owned failure rollback,
  measured Boolean geometry and attributes, actual 3DM reopening, and
  Grasshopper bake/save/reload with quantitative output checks.
- Native canvas/viewport captures, basic ClawChat Stop/Freigeben with rejected
  operations and no replay, and WebSocket activity authentication passed.
- Rhino 9/.NET 10, older .NET 7 hosts, VisualARQ and cancellation of already
  running/concurrent operations remain separate acceptance scopes. The bundled
  GH catalog can differ from the host; every used component retains its runtime
  contract check.

### Reliability

- Fix the 3DM open verification exposed by the first Rhino 8 stabilization
  acceptance run. Enumerate active objects explicitly: LINQ's indexed table
  materialization can dereference internal phantom slots after a successful
  native open. Regression coverage models the distinct indexed/enumerated views.
- Acceptance evidence preserves the concrete cause inside MCP/AnyIO exception
  groups, including a changed-document refusal. The runner still stops before
  further mutation when a different document becomes active.

## [0.8.1] - 2026-10-10

### Security

- WebSocket commands and event subscriptions use the TCP token/auth guard.
  Only metadata ping is public; unauthenticated connections receive no prompt,
  history, activity or document events. Rejected credentials revoke subscriptions.
- The Python WebSocket client authenticates subscriptions on connect/reconnect
  and attaches credentials to every command. Authentication errors complete
  requests immediately and stop automatic reconnect attempts.
- Debug logs no longer emit raw TCP request frames. Python formatters,
  interaction logs and the plugin logger redact the configured secret; malformed
  commands no longer log their body.

### Tests

- Exercise the production Fleck WebSocket listener using real loopback clients
  with Rhino stubs: command authorization, private events, revocation and
  missing-authorizer rejection. Python regressions cover token forwarding,
  subscription rejection and text/JSON exception-log redaction.

### Reliability

- The actual C# TCP reader now handles split UTF-8, concatenated JSON and
  negotiated big-endian length framing. Frames are limited to 32 MiB, partial
  requests have an absolute deadline, clean disconnects end their handlers and
  server shutdown closes accepted sockets. Client connections are bounded.
- Session-bound operation receipts prevent duplicate mutations after a dropped
  reply. Reconnect only joins/retrieves an existing operation in the same session;
  restart, eviction or an old plugin produces `OUTCOME_UNKNOWN` without replay.
  New `get_operation_result` retrieves pending/completed receipts without UI
  dispatch. Timeout errors preserve operation/session IDs through MCP wrappers.
- Ten legacy annotation/material/layer/debug tools now return structured JSON
  and retain native identities/refusals. Annotation tools never run a second
  creation script after an uncertain failure. Layer deletion checks Rhino's
  actual return value. This changes the previous plain-text response format.
- A real-MCP scratch acceptance CLI records Undo/Redo, owned rollback, boolean
  attributes/volume, 3DM reload and GH recipe bake/save/reload measurements.
  Default invocation only inspects. Live Rhino 8/9 and UI acceptance remain
  separate gates; see `docs/STABILIZATION-ACCEPTANCE.md`.

### Packaging and release

- Constrain MCP to 1.x and FastMCP to 2.x: fresh wheel installation previously
  selected MCP 2.x and failed before startup (`mcp.server.fastmcp` removed).
- Ship matching .NET 8/10 builds, retaining .NET 7 for older Rhino 8 hosts.
  CI compiles all targets, runs offline C# tests on .NET 8/10 and tests Python
  3.10–3.13, with Windows and Linux coverage.
- Both publishers depend on the complete reusable CI workflow at the release
  commit and require a tag matching the package version. Isolated wheel smokes
  initialize actual MCP and query packaged catalog data.
- Build-only Yak preparation works while Rhino is open. Installation refuses a
  running Rhino, retains older versions and does not uninstall after an error.
  Local deploy gates fail on test/lint/version/catalog errors; local publication
  additionally requires clean tagged source and successful CI for that commit.

## [0.8.0] - 2026-10-06

Command prefix release. Rhino 9 Beta (9.0.26272) ships its own `MCPStart` /
`MCPStop` / `MCPStatus` commands for RhinoAI, and Rhino runs the built-in
command when a plug-in registers the same name: on 2026-10-06 `mcpstart`
started RhinoAI, its HTTP server took port 1999 and RhinoClaw could no longer
bind. Every RhinoClaw command now carries the `Claw` prefix. This is a breaking
change for users and scripts that type the old names.

### Changed

- **All Rhino commands renamed** (old → new). Typing `Claw` and pressing Tab
  lists the whole family.

  | Old | New |
  |---|---|
  | `mcpstart` | `ClawStart` (127.0.0.1:1999) |
  | `mcpstop` | `ClawStop` |
  | `MCPStatus` | `ClawStatus` |
  | `mcpversion` | `ClawVersion` |
  | `mcploglevel` | `ClawLogLevel` |
  | `mcpautostart` | `ClawAutoStart` |
  | `tcpstart` | `ClawTcpStart` (0.0.0.0, warning unchanged) |
  | `CodexTerminal` | `ClawCodexTerminal` |
  | `CodexTerminalPermissions` | `ClawCodexTerminalPermissions` |
  | `GrokTerminal` | `ClawGrokTerminal` |
  | `GrokTerminalPermissions` | `ClawGrokTerminalPermissions` |
  | `ClawChat`, `ClawGrasshopperChat`, `ClawTerminal`, `ClawTerminalPermissions`, `ClawCodex`, `ClawGrok` | unchanged |

- **Transitional names.** `mcpversion`, `mcploglevel`, `mcpautostart`,
  `tcpstart`, `CodexTerminal`, `CodexTerminalPermissions`, `GrokTerminal` and
  `GrokTerminalPermissions` still work: each prints
  `[RhinoClaw] '<old>' is now '<new>'` and runs the new command. They are
  removed in 0.10.0. `mcpstart`, `mcpstop` and `MCPStatus` get **no**
  forwarder because Rhino 9 owns those names; typing them runs RhinoAI.
- **`hello` handshake `mode`** now reports `tcp` (0.0.0.0) or `mcp`
  (127.0.0.1) instead of the old command names `tcpstart` / `mcpstart`. The
  Python server only displays this value; `preflight` and `rhinoclaw_doctor`
  accept both spellings.
- All command-line hints, panel texts, workspace seeds (`AGENTS.md` written
  into `~/.RhinoClaw`), doctor/preflight fixes, docs, integrations and scripts
  use the new names. Plug-in settings keys (`CodexTerminalSkipPermissions`,
  `GrokTerminalWorkingDir`, ...) are unchanged, so existing preferences persist.
- `ClawAutoStart` is the recommended way to run RhinoClaw. On the very first
  load without any auto-start setting the plug-in prints one command-line hint
  (no dialog) and never repeats it.
- `ClawStatus` and `set_debug_mode` read the server that is actually running
  (`RhinoClawServerController.Current`). Before, both looked only at the
  auto-start instance, so after `ClawStart`/`ClawTcpStart` the status wrongly
  said "not running" and debug toggles were silently ignored (found during
  live acceptance in Rhino 8.35).
- The plug-in now declares `PlugInLoadTime.AtStartup`. Before, Rhino loaded
  it on the first `Claw*` command, so `OnLoad` and therefore auto-start never
  ran on launch: `ClawAutoStart On` had no effect unless something else
  loaded the plug-in first (found during live acceptance in Rhino 8.35).
  Rhino records the load time after the first load, so the first launch
  after installing 0.8.0 still needs one `ClawStart`; every launch after
  that starts the server automatically.

### Fixed

Four findings from a live session on 2026-10-06 (Rhino 8.35):

- **`undo` left the document stuck.** The handler called `doc.Undo()`
  directly from the dispatcher (outside a Rhino command); afterwards
  `UndoActive` stayed set and a record stayed open (`recording_active true,
  current_record_serial 13`), and every later call failed with
  `undo_redo_active` until Rhino was restarted. `undo`, `redo` and the
  failed-script rollback now run Rhino's own `_Undo` / `_Redo` commands
  (`OwnedUndoRecord.NativeUndo/NativeRedo`) and report
  `outcome: undo_state_dirty` if the state is still not clean afterwards.
- **`undo` reverted the user's work, not the tool call.** The plugin now
  remembers the serial of its own last closed record per document and
  refuses with `foreign_record_on_top` when Rhino recorded a user action
  (gumball move, native command) after it, or `no_owned_record` when it has
  not recorded anything in the document. `undo(force=True)` overrides.
- **`get_ui_state` crashed with `list index out of range`** when the probe
  script could not run (for example because of the stuck undo state above),
  exactly when its diagnosis was needed. It now reports `busy: true` with
  `probe_error` and a diagnosis instead of raising.
- **`send_rhino_input` reported "Failed to send input" for input that ran.**
  `RunScript` blocks while an interactive command runs, so the confirmation
  arrived after the 5 s timeout, and a `!`-prefixed macro reports `false`
  even though the command started. The tool now distinguishes
  `sent`/`confirmed`/`rhino_result` ("sent, completion unconfirmed",
  "delivered, Rhino reported it did not complete", "not sent"). The
  WebSocket client gained `send_input_detailed`; `send_input` keeps its
  boolean contract (true only on confirmed success).

### Added

- `rhinoclaw_plugin/Commands/CommandNames.cs`: single source for every
  command name, the transitional map and a maintained block list of built-in
  Rhino commands (`MCPStart`, `MCPStop`, `MCPStatus`).
- `rhinoclaw_plugin.Tests/CommandNamingTests.cs`: every registered name
  starts with `Claw`, no duplicates, no block-list collision, forwarders
  point at existing commands, and no `Command` class defines `EnglishName`
  as a string literal (source scan).
- Root `AGENTS.md` rewritten as a short repository guide (purpose, start
  here, build/test/run, repository map, conventions, live checks, definition
  of done, doc map, when stuck). The door loop, the GH authoring loop and the
  script-engine table moved to `docs/DOOR-PLACEMENT-LOOP.md`,
  `docs/GH-AUTHORING-LOOP.md` and `docs/SCRIPT-ENGINES.md`;
  `rhinoclaw_plugin/AGENTS.md` shortened to the same style and brought to the
  new command names. `docs/INDEX.md` lists the new files.

### Live acceptance

Offline gates pass (plugin build, `rhinoclaw_plugin.Tests`, pytest, ruff,
`sync_version --check`). Rhino 8.35 is accepted live: `ClawStart` on 1999,
doctor ready, all 17 `Claw*` commands and 8 forwarders registered, forwarder
notices print, `ClawStatus` reports the running server, and after
`ClawAutoStart` (mode mcp) a restart brings the server up without any
command. Rhino 9 Beta (`mcpstart` must only start RhinoAI) is still open.
Details in
[docs/HANDOFF-2026-10-06-COMMAND-PREFIX.md](docs/HANDOFF-2026-10-06-COMMAND-PREFIX.md).

## [0.7.15] - 2026-09-13

Panel redesign release: the native RhinoClaw panel gets a cool graphite palette,
a single ink tile for the last-used agent, a framed agent list, a segmented
Agent / Rhino-Konsole control and a quieter activity footer. Also ships the
session-reliability wave, the shared Grasshopper workspace and the verified BIM
bake contract listed below.

### Changed

- Native panel appearance: cool graphite palette in light and dark, colour used
  only for meaning (ready, running, stop), no headline copy, no all-caps labels.
  The last-used agent is one ink tile that opens it; other agents sit in a framed
  list without a second arrow. The workspace switches agents through the agent
  name instead of a combo box, tabs are a segmented control, text inputs and the
  Rhino console use hairline frames, palette focus colour and Consolas. Left
  buttons align their text. Verified with the native Eto/WPF fixture at 360/440
  pixels; docked Rhino acceptance remains separate.

### Added

- Native panel redesign with compact agent rows, last-agent launch, address and
  settings menus, persistent light/dark/system appearance and a fixed activity /
  Stop footer. Theme changes preserve embedded sessions and console text. An
  optional installed-Eto/WPF fixture checks narrow layouts, address persistence,
  Stop/Resume and actual WebView2 retention; docked Rhino acceptance is separate.
- Session reliability development wave: exact-ID GH SaveCopy/SaveAs with archive
  readback, Windows canvas PNG capture, unbaked Box/Brep/Extrusion measurements,
  MCP/TCP inventory comparison and a maintained stdio preflight client. Undo
  ownership, native Open, Boolean attribute inheritance, localized viewport names,
  canvas sizing/framing and slider validation are hardened. See
  [the evidence ledger](docs/SESSION-RELIABILITY.md); native acceptance is pending.
- `create_layer`, `delete_object` and `get_object_info` now use the standard
  JSON success/message/data envelope. Callers of the former raw object response
  must read `data`. Partial mutations retain native evidence and exact IDs.

- Embedded agent dashboard with saved view selection, editable per-agent
  endpoints, bounded HTTP checks and explicit Rhino/GH context handoff. Embedded
  views survive agent switching; automatic reloads are removed. Dashboard ttyd
  startup no longer waits on Rhino's UI thread. See [dashboard](docs/AGENT-DASHBOARD.md).
- Agent views default to **In Rhino** with the host's Chromium/WebView2 on Windows;
  Chrome is explicitly external. Native terminal clipboard buttons and Ctrl+Shift+C/V,
  Ctrl+V and Shift+Insert support text and local screenshot paths. Plain Ctrl+C
  retains terminal interrupt behavior; multiline paste requires bracketed-paste
  support and no Enter is appended. Clipboard actions reject inactive/changed pages.
- `attach_grasshopper_definition` binds an already-open user graph by exact
  document ID without reload/solve. Canvas reads expose named ports, wire owners
  and current input controls; shared handles reject operations after graph closure.

- Shared Grasshopper workspace: `get_grasshopper_canvas`,
  `show_grasshopper_definition`, opt-in visible build/load, exact node
  highlighting/framing and `ClawGrasshopperChat` companion/menu reusing the
  configured ClawChat surface and activity controls. Open graphs are protected
  from reload/overwrite; presented graphs remain user-owned on agent unload.
  Offline-tested; native Rhino 9 UI acceptance still pending. See
  [shared canvas/chat](docs/GRASSHOPPER-WORKSPACE.md).
- Optional VisualARQ BIM acceptance in `bake_grasshopper`: exact outputs,
  guarded native baking, expected Wall/Slab/Space/Door/Window kind, count,
  style and opening host. Independent product/host readback rejects Brep
  lookalikes and retains evidence on partial mutation. Offline-tested; the
  new combined path still requires live Rhino 9 acceptance.
- [Architectural BIM workflow](docs/BIM-AUTHORING.md), with explicit direct
  VisualARQ vs geometry-only GH routing and a one-room live acceptance plan.
- ClawChat activity strip in setup, chat and terminal views: observed Rhino
  commands, elapsed time, queue/running state, measured batch counts, timeout
  state, last execution result and a local status check.
- User-controlled Stop/Resume gate for Rhino requests, cooperative batch
  cancellation with retained partial results, and token-checked WebSocket
  activity snapshots/subscriptions and stop requests. Native blocking calls
  and external agent planning remain explicitly outside guaranteed control.

### Fixed

- `save_file` uses `RhinoDoc.WriteFile` instead of command-line Save/SaveAs
  tokens, fixing the path failure observed during the Rhino 9 Villa Luce run.
  Success requires a non-empty, readable 3DM containing every active document
  object ID. A failed post-write check preserves the file and reports the
  partial outcome; the MCP wrapper rejects missing/failed verification.
- Native-save regression tests cover full-document options, current paths,
  spaces/Unicode, invalid paths, missing archive objects and read/write failures.
- Agent capability manifests now enumerate all 174 registered tools and
  categorize the six previously omitted layer/door/Grasshopper/BIM tools.

- TCP retries now join an in-flight request by idempotency key, including
  cancellation outcomes; late UI completion no longer signals a disposed
  timeout wait handle. Authentication receives the actual remote endpoint
  across the worker-to-UI dispatch boundary.
- Rhino-free C# activity, cancellation, retry and preset checks now run in CI.
  Live acceptance on a newly loaded plugin remains pending; see
  [activity controls](docs/ACTIVITY-CONTROLS.md).

## [0.7.14] - 2026-08-19

### Added — agent-friction quick wins from the Plot-9 session

- New TCP command `list_commands`: returns the exact wire catalog straight
  from the dispatch dictionary (plus the pre-dispatch `hello`), with an
  explicit note that MCP-only tools such as `get_ui_state` are not TCP
  commands. `hello` now advertises the catalog via `tcp_command_catalog`,
  and the `UNKNOWN_COMMAND` error explains where to look instead of leaving
  agents guessing wire names.
- New MCP tool `ensure_layer_path`: idempotently creates every missing level
  of a nested `A::B::C` layer path with a correct `ParentLayerId` chain and
  returns the leaf layer GUID, created levels, and an `already_existed`
  flag. Optional `[r, g, b]` color applies only to a newly created leaf.
  Umlaut-safe: parameters are embedded ASCII-only into the IronPython body.
- `va_list_objects` accepts `layer_prefix`: restricts the scan to objects
  whose full layer path starts with the given text (e.g. `"Plot9::"`)
  before any VisualARQ classifier runs, and every returned snapshot now
  carries the object's full layer path as `layer`.

### Fixed — MCP handshake failure with a parallel rhinoclaw session

- Root cause of `rhinoclaw handshake failed: connection closed: initialize
  response` (Grok Build, 2026-08-19): local MCP configs launched the server
  via `uv run` **without** `--no-sync`. Whenever the project metadata had
  changed (e.g. a version bump) while any other rhinoclaw.exe session was
  running, uv's startup sync tried to replace the locked entry point, died
  with Windows `os error 32` before the initialize response, and the client
  saw only a closed connection with the server invisible among hidden
  tools. Reproduced deterministically and fixed by adding `--no-sync` to
  `~/.RhinoClaw/.grok/config.toml` and `~/.RhinoClaw/.mcp.json`; the
  editable install still serves current source. Dependency syncs are now a
  deliberate dev step (`uv sync` with no agent session running), never an
  implicit MCP startup side effect.

### Changed — honest document identity and RhinoCommon-first guidance

- `get_document_info.meta_data` now reports `unsaved`, `modified`, and
  `template_file`, so an unsaved document opened from a template (null
  `path`/`name`) no longer costs agents an exploration round to identify.
- `execute_python3_code` documents the RhinoCommon-first style contract:
  prefer `Rhino.*` with `scriptcontext.doc` over `rhinoscriptsyntax`, and
  use `ensure_layer_path` instead of scripting nested layers.

## [0.7.13] - 2026-08-19

### Added — referenced Grasshopper curves and complete house fixtures

- `build_gh_definition` SDK Curve parameters now accept an optional
  `reference_object_id`. The builder verifies the exact active Rhino curve and
  stores a real `GH_Curve` reference, matching Grasshopper's **Set one Curve**
  behavior instead of embedding a detached copy.
- Loaded definitions explicitly resolve and report persistent curve-reference
  GUIDs before headless use. The Rhino 9 Python 3 path was also verified to
  pass generic referenced geometry through its ghdoc identity table, where
  `rhinoscriptsyntax.coercecurve` restores the live curve for script code.
- The WSL parametric-house package now contains the script-free
  `house-native-v1.gh` GH01 fixture and a separate reusable
  `house-curve-parametric-v1.gh` with storey, entrance, window and room
  controls plus separate wall/slab/door/window outputs.

### Changed — robust UNC publication

- Atomic Grasshopper publication now falls back from same-directory
  `File.Replace` to same-directory overwrite-move when Windows reports that
  replace is unsupported on a WSL UNC target. Publication evidence records the
  fallback and original failure type; staging cleanup remains mandatory.

### Verified — Rhino 9 parametric-house vertical

- The fixed GH01 graph reopened with 20 exact schema-v2 output paths, baked 20
  valid closed solids with the contracted bbox and volume, and proved cleanup
  of every owned GUID.
- A referenced 12,000 x 9,000 mm outer curve drove the user-facing graph to
  38 valid solid Breps: 3 exterior wall rings, 4 slabs, 6 interior wall pieces,
  7 doors and 18 windows. Exact bake/readback measured
  `[0,0,-250]..[12000,9000,9000]`. An atomic parameter variant with 2 storeys,
  2 entrances, 4 windows/storey and 4 rooms/storey returned exactly 27 items
  with no runtime messages.
- Release builds installed locally for both Rhino 8 and Rhino 9 WIP with zero
  warnings and zero errors. No Yak publication was requested or performed.

## [0.7.12] - 2026-08-19

### Added — exact multi-role Grasshopper runtime contract

- New `verify_gh_component_contract` performs a read-only live verification
  without creating a GH document. It instantiates every declared component
  GUID once, rejects obsolete/name/ordered-port drift, records detailed
  assembly, exposure, access and optionality facts, then disposes the exact
  instances.
- The response carries the complete sorted raw runtime proxy-GUID inventory,
  its derived count/SHA-256, Rhino/Grasshopper/RhinoClaw process identity and
  all loaded VisualARQ assembly versions. Optional runtime pins fail closed.
- The GH02 contract package is now bound to the 2,767-proxy Rhino 9 WIP /
  VisualARQ 3.11 catalog. Its Rectangle contract was intentionally revised
  from the old `Generic Data` output to the live Rhino 9 `Geometry` output.

### Changed — truthful catalog completeness

- Catalog contracts now carry `ports_skipped_guids`. A matching proxy
  count/hash yields `full_catalog` only when no proxy port introspection was
  skipped; otherwise only the explicitly instantiated used roles can pass.
- The installed Rhino 9 / VisualARQ 3.11 vertical verified the complete raw
  `2767`-GUID inventory/hash and all `14` native plus `19` VisualARQ GH02
  roles. The two known diagnostic-only proxies remain outside those roles, so
  `used_components_only` passes while `authoring_search_complete=false` stays
  visible.

## [0.7.11] - 2026-08-19

### Added — VisualARQ BIM state and semantic critic

- New `va_bim_snapshot` reads Buildings, contained Levels, every reflected
  public VisualARQ style inventory and every typed document-resident VA
  product in one operation. Rich arrays are bound to sorted
  `identity/state_sha256` inventories, per-category hashes and one aggregate
  state fingerprint. Document identity, VisualARQ identity and raw source
  evidence also receive derived hashes and one separate evidence fingerprint.
- New `va_critique_bim` revalidates a supplied baseline from its raw entities,
  source evidence and eligibility facts, computes exact added/removed/changed
  deltas, and judges exact kind counts, hierarchy, style, height, thickness,
  area, verified volume, alignment, paths, BBoxes and measured Level datums.
- The critic uses deterministic one-to-one matching for repeated expectations
  and refuses unknown fields, non-finite tolerances, cross-document baselines
  and invented Product-to-Level IDs.

### Changed — truthful VisualARQ private-state boundary

- Loaded VisualARQ 3.11 reflection exposes Building-contained Levels but no
  global `GetAllLevelIds` or Product-to-Level getter. Snapshots therefore
  separate complete measured-state comparison from GH02 promotion eligibility
  and report the missing global/orphan coverage as a blocker.
- Formula-derived wall/slab quantities are named `gross_area` / `gross_volume`;
  only independent typed quantity getters populate `volume` with
  `volume_verified=true`.
- The installed 0.7.11 Rhino 9 / VA 3.11 vertical caught a real residual
  wall-style mutation after the baked wall object had been removed (`5 -> 6`
  styles). The final exact-output run then passed all semantic wall checks,
  independently verified `4,812,500,000 mm³`, unloaded the definition, deleted
  the owned object and unused style, and restored the exact `0/0/5/0` baseline
  counts and aggregate state fingerprint.

## [0.7.10] - 2026-08-19

### Added — exact atomic loaded-definition parameters

- New `set_grasshopper_parameters` MCP tool sets Number Sliders, Panels and
  Boolean Toggles only through exact `parameter_instance_id` values returned
  by `load_grasshopper_definition`.
- The complete batch resolves and validates before mutation, including GUID
  uniqueness, types, finite numbers and slider bounds. Every committed value
  is read back; a failure restores applied values in reverse order and reports
  whether rollback was independently proven.
- Loaded parameter inventories now contain one canonical record per input
  instead of duplicate generic/specialized slider rows.

### Changed — proof-carrying loaded solves

- `solve_grasshopper` now uses the shared instrumented solver, removes its
  temporary event handlers and proves exactly one silent SolutionStart and
  SolutionEnd cycle.
- Responses include the complete structured Remark/Warning/Error inventory,
  per-level counts, duration, solution state and the actual `expire_all`
  behavior. Missing or inconsistent evidence fails verification.

### Verified — Rhino 9 loaded-definition vertical

- Rhino 9 WIP loaded the saved
  `LoadedConformance_AtomicParams_20260819.gh` fixture with five unique,
  settable parameter IDs and no duplicate slider rows. An out-of-range slider
  batch failed preflight with `mutation_attempted=false`; the following
  five-input Slider/Panel/Toggle batch preserved the default baseline and
  passed every post-set readback.
- The incremental solve produced exactly one `SolutionStart` and one
  `SolutionEnd` in Silent mode with a complete empty runtime-message inventory.
  Exact-output bake/readback measured the requested
  `[-300,-150,-75]..[300,150,75]` box, and one Undo restored the empty document.

## [0.7.9] - 2026-08-19

### Changed — guarded exact-output BakeAware workflow

- Exact `bake_grasshopper.output_targets` containing `IGH_BakeAwareData` now
  route through `GrasshopperBakeService` instead of the legacy direct loop.
  Each non-null Goo receives one native invocation with fresh object,
  attribute, layer, instance-definition and current-layer evidence.
- Mixed BakeAware/geometry batches and missing target layers fail before
  mutation. Successful invocations must report the same single GUID observed
  in the active-object delta.
- A later batch failure cleans proven additions in reverse baseline order and
  returns the complete evidence. Because VisualARQ-private state is still
  unmeasured, every post-mutation failure remains `PARTIAL_MUTATION` even when
  covered Rhino state was restored.
- Live Rhino 9 WIP / VisualARQ 3.11 verification passed for both a native
  `GH_Box` and an exact `GhVaWall`: one invocation, one owned GUID and active
  object readback in each case. VisualARQ semantic readback additionally
  measured the requested 5,000 x 350 x 2,750 mm wall, style and core layer.
  The VisualARQ bake retained no usable Rhino Undo record, so private plugin
  state and successful custom-Goo undoability remain explicitly unclaimed;
  the isolated scratch document was discarded.

### Added — verified parametric Rahmentuer insertion

- New `insert_rahmentuer` MCP tool wraps the proven
  `build_rahmentuer_block` workflow with prompt-free dimensions, engagement,
  detail switches and an explicit insertion point.
- Asset preflight requires both Python modules and only the selected vendor
  3DM files. Resolution supports `RHINOCLAW_RAHMENTUER_ROOT`, explicit roots
  and complete known workspaces; incomplete roots fail before mutation.
- Success is based on separate object and block-definition reads: exact
  instance identity/name, ERP prefixes, part and reference counts, requested
  outer dimensions and the translated local/world bbox must all match.
  Unproved rollback or a readback mismatch is truthfully reported as
  `PARTIAL_MUTATION`.
- The shared kit launcher now prepends an entry script's folder to `sys.path`,
  allowing reviewed actions to import adjacent helper modules such as
  `block_hardware.py`.

### Added — CodexTerminal: OpenAI Codex CLI inside ClawChat

- New `CodexTerminal` Rhino command (alias `ClawCodex`) and **Codex CLI
  Terminal** ClawChat preset. It auto-starts a local `ttyd` bound only to
  `127.0.0.1:7683`, next to Claude on `:7681` and Grok on `:7682`.
- Shares `~/.RhinoClaw` with the other agent terminals and seeds a
  project-scoped `.codex/config.toml` for the `rhinoclaw` MCP server without
  overwriting existing files.
- New `CodexTerminalPermissions` command. `Ask` keeps normal Codex approvals
  and sandboxing (default); opt-in `Skip` uses the official
  `--dangerously-bypass-approvals-and-sandbox` flag after a warning.
- Plugin settings `CodexTerminalTtydPath`, `CodexTerminalCommand`,
  `CodexTerminalWorkingDir` and `CodexTerminalSkipPermissions` mirror the
  existing Claude/Grok terminal controls. Plugin shutdown stops only the
  Codex ttyd process that RhinoClaw itself started.

### Changed — Rhino 9 / VisualARQ 3.11 Grasshopper catalog

- The live catalog generator now runs natively on Windows as well as WSL and
  records proxy library/location/exposure, runtime type, assembly/file/product
  versions, and each port's access, optionality and runtime type.
- Every chunk now proves the sorted live proxy-GUID hash both before and after
  instantiation, and final publication requires that same hash. A plug-in may
  no longer change the proxy set while keeping the same count unnoticed.
- Grasshopper `.ghuser` proxies use their persistent `LibraryGuid` for catalog
  lookup and runtime verification. Their process-random proxy GUID remains as
  diagnostic `runtime_guid`, preventing false global drift after restarting
  Rhino while keeping user objects authorable by a stable identity.
- Regenerated against Rhino 9 WIP `9.0.26223.12303` and VisualARQ
  `3.11.0.15030`: 2,767 unique proxies, including 249 VisualARQ components.
  The VisualARQ Pipeline and the interactive Grasshopper Button remain
  explicitly non-authorable because their `CreateInstance` calls exceeded the
  90-second live gate; all other proxy rows completed.

### Added — External toolbox kits

- New MCP tools `kit_list`, `kit_describe`, `kit_invoke` discover
  `rhinoclaw-kit.json` manifests and run silent `run()` entry points
  through `execute_python3_code`. Spec: `docs/rhinoclaw-kit.md`.
- Search path: `RHINOCLAW_KITS`, else `cwd` / `~/repos`, plus optional
  `RHINOCLAW_KITS_ROOT`. Interactive-only actions fail closed.

## [0.7.8] - 2026-08-19

### Changed — ClawChat dropdown starts Claude / Grok terminals

- Selecting **Claude Code Terminal** or **Grok Build Terminal** in the
  ClawChat surface dropdown (or the setup buttons) now auto-starts the
  same local `ttyd` as `ClawTerminal` / `GrokTerminal`. Reload does the
  same if the process is not listening. Other presets are unchanged.
- Shared launcher `AgentTerminalLauncher` so the panel and the Rhino
  commands (`ClawTerminal`, `GrokTerminal`) start ttyd the same way.

## [0.7.7] - 2026-08-18

### Added — GrokTerminal: Grok Build inside the ClawChat panel

- New `GrokTerminal` Rhino command (alias `ClawGrok`): opens the ClawChat
  panel on a local web terminal running Grok Build, auto-starting `ttyd`
  bound to `127.0.0.1:7682` so it can run next to ClawTerminal on `:7681`.
  The ttyd instance the plugin started is killed again on plugin shutdown;
  user-started ones are left alone.
- New "Grok Build Terminal" agent-surface preset in the ClawChat setup view
  and toolbar dropdown.
- Reuses `~/.RhinoClaw` when ClawTerminal already created it; otherwise asks
  once, seeds `AGENTS.md`, `.grok/config.toml` and `.mcp.json` (never
  overwrites existing files), and persists the choice in
  `GrokTerminalWorkingDir`.
- Plugin settings `GrokTerminalTtydPath` (falls back to
  `ClawTerminalTtydPath`), `GrokTerminalCommand` (default: official
  `grok.exe` if present, else `grok` via absolute-path PowerShell) and
  `GrokTerminalWorkingDir`.
- New `GrokTerminalPermissions` command: opt-in autonomous mode that
  launches grok with `--yolo` (`Skip`), back to normal prompts with `Ask`.
  Off by default, warning dialog on enable, persisted in
  `GrokTerminalSkipPermissions`; only shapes the default command. Offers
  to restart a running ttyd but never kills a session silently.

### Fixed — GrasshopperPlayer automation on Rhino 9

- `place_doors` / `gh_player` were effectively broken on Rhino 9: typing
  `_-GrasshopperPlayer "<path>"` via `SendKeystrokes` drops characters in
  long strings (arrived as `_-GrasshoppePlayer`), and partial command-line
  input wedges the UI thread via the autocomplete popup (up to a frozen
  Rhino). The player is now started through the plugin's
  `start_script_async` (RunScript on the UI thread, no typing); on Rhino 9
  its path prompt appears with the macro argument as default and is
  answered with a plain Enter.
- New undo-free plugin command `send_keystrokes` for answering pending
  prompts. Feeding keystrokes through `execute_rhinoscript_python_code`
  opened that handler's undo record while the keys pumped the message
  queue — Begin/End interleaved with Rhino's own command records and left
  a record dangling open, after which every later `BeginUndoRecord`
  returned 0 and failed-script rollback silently stopped working
  (observed live; the dangling record had to be closed manually).
  `gh_player._send_input` prefers `send_keystrokes` and falls back to the
  legacy path on pre-0.7.7 plugins. RunScript-based `send_command_input`
  cannot feed a pending getter on Rhino 9 at all (verified live).
- The GH parameter pre-load in `run_player_for_door` now uses a 60 s
  timeout — the first Grasshopper load of a session initialises GH on the
  UI thread and regularly exceeded the 15 s default.

## [0.7.6] - 2026-08-17

### Changed — execute_python3_code now runs through the official RhinoCode API

- The plugin's primary Python-3 path is now the official `Rhino.Runtime.Code`
  API: resolve the CPython language (`RhinoCode.Languages.QueryLatest
  (LanguageSpec.Python3)`), `CreateCode(source)`, `Run` with a `RunContext`
  capturing stdout/stderr. User code reaches the engine **verbatim** (no
  wrapper indentation), `# r:` package requirements are resolved by the run
  pipeline itself, and failed scripts return the real CPython traceback
  (`ExecuteException`). The API is late-bound because McNeel ships no NuGet
  for `Rhino.Runtime.Code.dll` and CI builds without a Rhino install; every
  member used is verified identical in Rhino 8.34 and Rhino 9 WIP. Details in
  `docs/learnings/rhinocode-python3-engine.md`.
- Removed the old reflection path into
  `RhinoCodePlatform.Rhino3D.Languages.Python3Script`: per McNeel its
  `Create()` **always builds an IronPython script**, so whenever that path
  won, "Python 3" was silently IronPython 2.7. A static test now bans the
  type. The temp-file + `-_ScriptEditor _Run` route remains as fallback
  (`method: "ScriptEditor"`) when the RhinoCode language cannot be resolved.
- The CPython engine is **warmed once at server start** (deferred to an Idle
  tick, opt-out via `RHINOCLAW_SKIP_PY3_WARMUP=1`), so the first
  `execute_python3_code` call no longer pays multi-second engine spin-up.
- `get_script_capabilities` additionally reports `python3_engine`
  (`RhinoCode` | `ScriptEditor`) and `python3_warm`.

### Fixed

- `execute_python3_code` had the same destructive nested-undo bug fixed for
  `execute_rhinoscript_python_code` in 0.7.5: the dispatcher wrapped it in
  its own undo record, the handler's nested `BeginUndoRecord` returned 0,
  and the unconditional `doc.Undo()` on a failed script could pop the
  PREVIOUS successful operation. The command is now undo-free at the
  dispatcher, owns its transaction, adds a rollback marker before undoing,
  and reports `rollback_performed` (static regression:
  `tests/test_execute_python3_undo_safety.py`).
- The tool-level `timeout` parameter never reached the plugin — the wire
  frame carried no `timeout`, so the UI-thread wait was always the 60 s
  default and longer timeouts (first-time `# r:` pip installs) were
  silently unreachable. `wire.build_command` now ships `timeout` (plugin
  clamps to [1, 300] s) and the server pads its socket deadline by a 5 s
  grace so the plugin's structured `TIMEOUT` error beats a raw socket
  timeout. `RHINOCLAW_MAX_TIMEOUT`'s default rose from 120 to 300 so the
  server-side clamp no longer undercuts the plugin's cap.
- The `rhinoclaw_client` CLI now always puts its effective per-command
  budget on the wire (`RhinoClient.send_command`, new `timeout=` arg on
  both `script_exec` engines plus `--timeout`), so the plugin's wait and
  the client's socket deadline agree instead of racing 60 s vs 15 s. New
  `script_exec.run_python` / `run_python3` helpers give the skill docs'
  previously dangling `script_exec.run_python` reference a real target
  (`execute_script` stays as an alias).

## [0.7.5] - 2026-08-12

### Added — ClawTerminal: Claude Code inside the ClawChat panel

- New `ClawTerminal` Rhino command: opens the ClawChat panel on a local web
  terminal running Claude Code, auto-starting `ttyd` (bound to `127.0.0.1`
  only) when nothing is listening yet. The ttyd instance the plugin started is
  killed again on plugin shutdown; user-started ones are left alone.
- New "Claude Code Terminal" agent-surface preset (`http://127.0.0.1:7681`) in
  the ClawChat setup view and toolbar dropdown.
- Dedicated `~/.RhinoClaw` Claude Code workspace: ClawTerminal asks once
  whether to create it (falls back to the user profile on "No"), seeds it
  with a `CLAUDE.md` and a `.mcp.json` declaring the `rhinoclaw` MCP server,
  and persists the choice in `ClawTerminalWorkingDir`. Keeps Claude Code's
  trust scope to one folder instead of the whole user profile and gives
  saved files a defined home.
- Plugin settings `ClawTerminalTtydPath`, `ClawTerminalCommand` and
  `ClawTerminalWorkingDir` override the ttyd binary location, the command it
  runs (default: `claude` via an absolute-path PowerShell so npm's
  `claude.cmd` also resolves) and the shell working directory.
- New `ClawTerminalPermissions` Rhino command: opt-in autonomous mode that
  launches claude with `--dangerously-skip-permissions` (`Skip`), back to
  normal prompts with `Ask`. Off by default, warning dialog on enable,
  persisted in `ClawTerminalSkipPermissions`; only shapes the default
  command (a custom `ClawTerminalCommand` is never rewritten, a `[WARN]`
  log points that out). Applies on the next terminal start — the command
  offers to restart a running ttyd but never kills a session silently.
- Works around the ttyd Windows crash-on-connect (tsl0922/ttyd#1292, #1412):
  ttyd's win32 build exits the moment a client connects unless BOTH an
  absolute `-w` working directory AND an absolute command path are passed —
  the service now always does both.

### Added — verified VisualARQ Slab/Space Style-to-product vertical

- Added `va_create_slab_style` and `va_create_space_style` with exact loaded-
  assembly CLR preflight, complete global style/component inventory deltas,
  duplicate-name rejection, persistent identity/product readback and
  ownership-gated rollback. A residual last-of-kind Slab Style is reported as
  `PARTIAL_MUTATION`, never as successful cleanup.
- Added `va_create_slab` and `va_create_space` with server-side planar-
  boundary validation and independent runtime-generation, kind, style,
  contour/boundary, quantity, label and semantic-BBox judges. Failed creation
  removes only the exact command-owned generation.
- VisualARQ 3.7.2's empty `GetSlabLayers` result is retained as evidence and
  can fall back only to a complete `GetSubStyleComponents` inventory whose
  children all pass `IsSlabLayer`. Space elevation uses read-before-write so
  an already matching value is treated as a verified no-op rather than a
  failed setter.
- Live conformance created a 255 mm Normal/Core/Normal Slab Style and a Space
  Style, consumed both in native products, performed the first save through a
  top-level WebSocket `SaveAs`, then reopened the unchanged 3DM in a different
  Rhino process. Both styles and both products passed complete semantic
  readback after reload. See
  `docs/learnings/visualarq-slab-space-mcp-contract-20260809.md`.

### Added — fail-closed VisualARQ Roof MCP contract

- Added five centralized Roof tools for runtime capabilities, Roof Style
  inventory, Roof inventory/readback and curve-based authoring. VisualARQ
  3.7.2 is detected from its loaded file/product version and exact reflected
  method shapes; the Python wrapper does not send a create command on its
  broken two-parameter API.
- Direct VisualARQ `>=3.8,<4` authoring requires the exact three-parameter API
  and is Hip-only until ridge-axis input/readback is authoritative. Shed and
  Gable fail before mutation with `axis_control_unavailable`.
- Direct success requires an owned single-object delta, native Product/Style/
  type readback and a real contour-form proof: valid manifold single-face Brep,
  one Outer Loop, no inner/unknown loops, simple planar curves, matching area
  and perimeter, and 257 bidirectional closest-point samples. A matching BBox
  alone is never accepted.
- The installed 3.7.2 conformance run read the persisted A03 Gable and two A04
  Composite Roofs. Both the Python no-send gate and the raw C# pre-mutation
  gate preserved the complete measured document/style baselines exactly.
- Persisted Roof readback now handles an unset top-level
  `InstanceReferenceGeometry` BBox through a bounded, ownership-checked,
  world-transform-aware traversal of the exact nested Instance Definitions.
  The public wrapper validates finite ordered BBoxes, root/definition GUIDs,
  counts, cycle/limit evidence and failure state before accepting the fallback.
  A real A06 Composite Roof passed this path after process restart and Open,
  followed by the unchanged 17/17 independent artifact judge.

- Fixed failed IronPython transaction isolation. The script executor now owns
  one non-nested undo record and inserts a no-op custom rollback marker before
  undoing a failed script. A read-only diagnostic exception can no longer undo
  the preceding successful modeling operation; when undo recording is
  unavailable, the executor refuses to touch older history and reports that
  rollback was not performed.
- Fixed object/document inventory after `_New` or `_Open`: serializers now
  resolve layers against the current document instead of a stale statically
  cached `RhinoDoc`, and tolerate transient objects without a valid layer.
- Live-installed regressions now cover both fixes: an intentionally failing
  script preserves the preceding named sentinel while rolling back its own
  non-zero undo record, and document inventory survives a fresh `_New` plus a
  populated saved-model reload.

### Fixed — localized and layout-aware viewport control

- Viewport, zoom, camera, capture, render, and orbit tools now share one
  RhinoCommon resolver. An omitted name follows Rhino's active viewport;
  localized names, viewport/detail-object GUIDs, `Layout::Detail`, and legacy
  English standard-view aliases are supported without a hard-coded
  `Perspective` default. Duplicate names/projections fail with GUID candidates
  instead of mutating the first match.
- `set_view` now uses `DefinedViewportProjection`, so Top/Front/Perspective and
  TwoPointPerspective change both orientation and projection correctly.
  `set_view` and `set_camera` now report the post-commit RhinoViewport state,
  keep requested values separate from measured values, and require a passing
  native readback before the Python wrapper reports success. A mismatch pops
  the pushed projection, persists detail rollback, and independently verifies
  camera, target, lens, projection, and construction-plane restoration;
  unproven recovery is surfaced as `PARTIAL_MUTATION`.
- Navigation rejects layout-page main viewports and locked details with an
  actionable error. Mutations of inactive details are committed through their
  `DetailViewObject`, including display-mode restore. Captures of detail
  targets truthfully report that the complete owning layout page was captured;
  `render_view` rejects a page-main target whose child details could not share
  the claimed display mode.
- `orbit_camera` is now one native RhinoCommon operation. It supports explicit
  layout details, commits them persistently, and no longer invokes a script
  executor whose failure path could undo unrelated document work.
- Capture and render now share one cross-OS image router: relative/POSIX targets
  are decoded and saved by the MCP server, while absolute Windows/UNC targets
  are saved by Rhino with truthful location/format/byte metadata. Both Python
  and the C# trust boundary reject traversal, reserved DOS names, unsafe path
  components, and Windows device namespaces.
- The shared Rhino-host image-path validator now accepts provider-specific UNC
  roots whose `Path.GetPathRoot` omits the separator after the share (observed
  live for `\\wsl.localhost\Ubuntu\...`). It consumes exactly that one root
  boundary separator while continuing to reject repeated empty components.
- Four installed-plugin captures were written directly by Windows Rhino to a
  `\\wsl.localhost\Ubuntu\...` case-study directory and independently checked
  from WSL, closing the live UNC artifact gate.
- The deployable raw-TCP viewport helper now sends the native
  `direction`/`angle_degrees` orbit contract instead of stale `yaw`/`pitch`
  fields.

### Tests

- Added source contracts and wrapper regressions for localized names, active
  views, both detail identifiers, duplicate-name rejection, detail commit,
  locked/page navigation, layout capture scope, real projection changes, and
  native orbit failures.
- Added the shared host-boundary regression for the WSL UNC root-separator
  normalization used by both capture and render.
- Added a document-lifecycle regression that rejects statically cached
  `RhinoDoc` layer resolution after `_New`/`_Open`.
- The current 0.7.4 source gate passes 1009 tests with 5 skipped and registers
  164 MCP tools. The final Release RHP built with zero warnings/errors, was
  installed locally while Rhino was closed, and matched the installed package
  byte for byte (`SHA-256 98d1318b...e8b4047`); no Yak push was performed.
- A post-install Rhino restart verified the localized `Perspective` projection
  fallback and a 320x240 capture. In a fresh unsaved VisualARQ millimeter
  scratch, `va_documentation_capabilities` verified the exact 3.7.2.20500
  Script/GH version pair and every pinned GH proxy contract without document
  mutation, GH document construction, solve or bake. Section, Section View and
  Plan View inventories remained `0/0/0`; both unsupported creation gates
  stopped before mutation with passing Rhino/style/hierarchy guards. Positive
  Section and Section-View creation remains conditional on authoritative,
  pre-existing documentation-style GUID fixtures.
- A final truth-contract audit now requires every positive documentation mode
  to correlate with its exact Script and GH evidence. Plan View reads no longer
  depend on create-only proxies; Section/Section-View create probes verify the
  public style-Goo identity bridge, and cleanup/dispose failures invalidate a
  capability instead of being swallowed. The installed live endpoint accepted
  all tightened contracts without constructing or solving a GH document.

### Improved — fail-closed Grasshopper authoring and output identity

- `build_gh_interactive` now validates a successful bake's count and unique,
  non-empty GUIDs, resolves every GUID through `get_objects_info`, and drives
  `min_count` from that active readback. A ghost/deleted object, malformed
  report, missing bbox or failed readback can no longer produce `pass=true`.
- Loaded-definition outputs now expose and accept exact
  `component_instance_id` + `output_instance_id` selectors. Exact targets are
  fully resolved before layer/object mutation; ambiguous legacy component
  names fail closed. Standalone final `IGH_Param` outputs are inventoried too.
- Grasshopper output schema v2 preserves every `GH_Path`, path indices,
  item index/type/validity and real JSON nulls. Duplicate nicknames retain all
  outputs under stable instance-GUID-disambiguated keys.
- `bake_grasshopper` and the interactive authoring loop share GUID and active
  object verification helpers. A contradictory result after dispatch reports
  an unverified/partial mutation rather than optimistic success.
- The v1 component catalog derives authorability centrally. Entries with
  `Guid.Empty`, skipped ports, failed instantiation or no instantiation evidence
  are hidden from normal lookup and rejected by the linter; diagnostic lookup
  can expose their structured issue codes explicitly.
- Both direct authoring entry points (`build_gh_definition` and
  `build_and_bake_gh`) now run that catalog-backed lint before any Rhino
  round-trip, so an unknown or unauthorable SDK GUID cannot write or bake a
  partial graph.
- Authoring now carries a runtime catalog contract into Rhino. `full_catalog`
  requires the live proxy GUID count and hash to match; the explicit
  `used_components_only` mode permits scoped global drift only when every used
  SDK component is instantiated and its exact port contract passes, while
  marking search completeness unverified. Missing `catalog_verification` from
  an older plugin fails closed, including primitive-recipe authoring.
- Author-only writes without solving. Build-and-bake performs exactly one
  instrumented solve and uses the same in-memory GH document for graph
  construction, runtime-message collection, bake and archive. All messages
  from that solve are returned, and transient `DocumentServer` cleanup is
  independently verified.
- Definition writes use staging plus atomic replacement. This is deliberately
  not compare-and-swap: a concurrent external edit between the observed
  baseline and replacement cannot be detected or protected.
- `build_gh_interactive` now exposes `solved`, `baked` and `verified` as
  distinct evidence states. Semantic contracts can independently check Rhino
  geometry/object type, layer, validity, closed/solid state, complete
  area/volume totals and aggregate face/edge/vertex topology. Unknown or
  non-finite expectations fail before mutation; partial mass-property data can
  never satisfy a total.
- Failed interactive iterations delete only their canonical reported Bake
  GUIDs by default and prove exact `not_found` readback. Cleanup does not claim
  the written definition, layer or material state; an inconsistent ownership
  report or retained/failed cleanup is surfaced as `PARTIAL_MUTATION`.

### Fixed — truthful VisualARQ capability and result contract

- `va_status` now reads the loaded VisualARQ file/product version, document
  units/tolerances, method flags, and exact .NET parameter shapes. Rhino 8's
  IronPython returns `None` from `clr.AddReference`, so the runtime assembly is
  resolved from the current AppDomain before reading `FileVersionInfo`.
- VisualARQ API-generation branches use loaded assembly reflection instead of
  `__doc__` signature text.
- Door width/height overrides are preflighted before `AddDoor`; VisualARQ
  3.7.2 returns `UNSUPPORTED_OPERATION` rather than echoing requested values
  as actual dimensions. Requested, applied, and getter-read values are
  separate fields, with `GetOpeningHost` preferred for host readback.
- Wall inputs are validated and height is read back when supported. IFC export
  validates the written STEP file and reports `requested_schema` separately
  from the parsed `actual_schema`, including schema-drift warnings.

### Added — verified VisualARQ style-to-wall vertical

- Added canonical style and object queries plus verified wall-style lifecycle
  tools: `va_get_style`, `va_create_wall_style`, `va_rename_style`,
  `va_delete_style`, `va_list_objects`, and `va_get_object`.
- Wall-style creation validates layer order, unique names, positive thickness,
  Core/Normal and wrapping before Rhino, then compares persistent style and
  layer readback. Deletion requires explicit confirmation and refuses styles
  still referenced by document products.
- VisualARQ script transport now uses Newtonsoft JSON end to end so localized
  names such as `Außenwand` survive IronPython/.NET encoding boundaries.
- VisualARQ 3.7.2's unset `-1e307` values are normalized to `null`; effective
  wall-layer thickness is resolved from its reported Object/Style source.
- Wall quantities are independently measured from valid solid leaf geometry
  in the transformed instance definition. Because VisualARQ populates that
  definition asynchronously after `AddWall`, creation performs a bounded
  follow-up readback and reports creation and quantity verdicts separately.
- Live G3 cleanup restored the document to `0` VisualARQ walls and `12` wall
  styles after proving the in-use style-delete guard and all measured values.

### Added — VisualARQ opening profiles, Sections and documentation views

- `va_documentation_capabilities` now reports the loaded runtime's semantic
  list/read/create/style-create modes for Sections, Section Views and Plan
  Views. It reflects exact public Script signatures and version-pinned GH
  contracts without constructing a GH document, solving or baking, and guards
  Rhino, VisualARQ style and Building/Level state before and after the read.

- Added `va_create_door_style`, `va_create_window_style` and
  `va_add_rectangular_opening_size_profile`. They pin exact VA 3.7.2 CLR
  signatures and compare complete global style/component/profile inventories;
  ownership-gated cleanup never deletes a pre-existing style or profile.
- Door and Window placement now share one audited fail-closed opening core.
  `va_create_window` uses the exact `AddWindow(Guid, Point3d, Double)` contract;
  both kinds resolve requested width/height through exactly one rectangular
  style-owned Size Profile and treat `GetOpeningHost` as authoritative.
  Host-cut verification fingerprints every instance-definition leaf, transform
  path and relevant attribute; cleanup must restore every candidate host
  baseline or reports `PARTIAL_MUTATION`.
- Added explicit, hierarchy-verified Building/Level lifecycle operations.
- Added typed `va_list_sections`, `va_get_section` and `va_create_section`
  contracts. Section creation uses the installed native VisualARQ Grasshopper
  components and one BakeAware strategy, is version-pinned to VA GH
  `3.7.2.20500`, redraws before authoritative readback, and verifies the
  document-resident Section independently. List/Get wrap their transient
  `LoadObject`/GH solves in covered Rhino-state and global VisualARQ-style
  guards. Mutation-phase failures stay `PARTIAL_MUTATION`; plugin-private,
  view and other unmeasured document state is never claimed as restored.
- Added `va_list_section_views`, `va_get_section_view` and
  `va_create_section_view`. Because VA Script 3.7.2 has no `IsSectionView`,
  classification and readback use exact version-pinned `GhVaSectionView` goo
  plus native Deconstruct components. Create links one existing Section and
  Section View Style through one BakeAware path, then verifies source GUID,
  insertion point, title, projection, auto-update, style, non-empty instance
  output and owned definition delta. Dynamic update and delete cascades remain
  explicit live-scratch gates. Failure cleanup never deletes the new view,
  because VisualARQ may cascade that delete into its pre-existing source
  Section; the partial-mutation response exposes both IDs and requires outer
  Undo or scratch discard.
- Added typed `va_list_plan_views` and `va_get_plan_view` using exact
  `GhVaPlanView(Guid)` loading and `ReferenceID` readback. VisualARQ 3.7.2 does
  not expose a trustworthy Level GUID through that path, so it remains
  explicitly unresolved. `va_create_plan_view` validates hierarchy and
  boundary contracts but is an undo-free, pre-solve/pre-bake
  `UNSUPPORTED_OPERATION` capability gate; positive Plan View creation is not
  claimed.
- Added `va_create_section_style` as a deliberately fail-closed capability
  gate, not a creator. The installed API has no public complete Section Style
  enumeration or name-to-GUID lookup, so the tool records its read-only
  baselines and stops before proxy construction, graph, solve or bake rather
  than reporting an unverifiable persistent style.

## [0.7.2] - 2026-07-16

ClawChat now keeps dashboard endpoints per agent surface, safely migrates old
Hermes defaults, and the Yak publishing path no longer suggests an impossible
yank-and-overwrite workflow.

### Changed — configurable agent-surface dashboards
- **Each built-in ClawChat surface has its own URL override.** Editing the URL
  for OpenClaw, Hermes, Open WebUI, or LibreChat now persists only for that
  preset instead of turning the selection into one global custom endpoint.
- **Hermes uses the secure general-profile dashboard by default:**
  `https://numbercruncher.tailfc0b86.ts.net:9443/chat?profile=general`.
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

### Added — the verified GH authoring loop (Next-Level 5.3, G3)
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

### Added — composition recipes (Recipe-Registry 2.3, G4)
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
geometry, learned from, and benchmarked** — the self-improving loop from
`docs/NEXT-LEVEL-PLAN.md` is closed and live-verified. 111 MCP tools
(was 88 in docs / 91 registered), 474 tests.

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
  pass identically) — Bandseite needs the planned visual judge (5.1).

## [0.5.0] - 2026-06-05

Grasshopper authoring + native headless bake + agent auth stabilization. An
agent can now author and bake parametric geometry, and the auth/connection
handshake is deterministic. See `docs/CONTEXT-HANDOFF.md` and
`docs/NEXT-LEVEL-PLAN.md`.

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
- `release.ps1`: PowerShell parser choked on `'/home/user/[^\s"'']*'`
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

### Added
- **`batch_operations` MCP tool** ([#11]). Multi-step transactions in
  one TCP round-trip. Each step is `{"tool": str, "args": dict}`. Four
  on-error policies: `rollback` (default — undo every successful step
  on failure), `abort` (stop, leave completed steps), `continue` (skip
  failure, keep going), `best_effort` (continue + outer success stays
  true). The whole batch executes inside one Rhino undo record so a
  single Ctrl+Z rolls back the entire macro for the user. Per-step
  results are returned in order with `success`/`result`/`error` so the
  caller can introspect partial progress.

[#11]: https://github.com/McMuff86/rhinoclaw/issues/11

### Fixed
- **`create_object type="BOX"` now creates a Brep** instead of an
  Extrusion. Lets `is_inside` use the accurate
  `Brep.IsPointInside` path (`method: "brep_point_in_volume"`) for
  containment tests against boxes. Spheres/Cylinders were already
  Breps; this brings boxes in line.

### Added
- **Scene-analysis MCP tools** ([#5]). Four new tools that give the
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

[#5]: https://github.com/McMuff86/rhinoclaw/issues/5

## [0.2.8] - 2026-05-05

### Added
- **`undo` and `redo` MCP tools** ([#4]). The agent can now roll back
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

[#4]: https://github.com/McMuff86/rhinoclaw/issues/4

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
- **Plugin auto-start** ([#1]). New `mcpautostart` Rhino command lets
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

[#1]: https://github.com/McMuff86/rhinoclaw/issues/1

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
- **`inspect_grasshopper_definition` MCP tool** ([#2]). Loads a `.gh` /
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

[#2]: https://github.com/McMuff86/rhinoclaw/issues/2

### Changed
- **Documentation consolidation.** Repository root now ships only the
  four documents end users and contributors actually need:
  `README.md`, `CHANGELOG.md`, `SECURITY.md`, `AGENTS.md`. Stale plans
  and historical snapshots moved to `docs/archive/`:
  - `AUTOMATION_PLAN.md` (Vision doc; features long-shipped)
  - `CONTEXT-HANDOFF.md` (session log from 2026-03-22)
  - `FUNCTIONAL_STATUS.md` (duplicated in CHANGELOG)
  - `FUTURE_ISSUES.md` (open items migrated to GitHub Issues #1–#12)
  - `LAND_THE_PLANE_PLAN.md`, `LOESUNG_BESSERE_RHINO_VERBINDUNG.md`,
    `WEBSOCKET_STREAMING_PLAN.md` (designs that have shipped)
  - `README_MCP.md` (architecture content moved to
    `docs/architecture.md`, redundant bits dropped)
- **`AGENTS.md` slimmed from 952 → ~170 lines.** Now a focused
  quick-start; the deep "how to add a new tool" walk-through lives in
  `docs/architecture.md`. Outdated phase tables, the multi-tool Ralph/
  Beads/Cursor workflow comparison and the Land-the-Plane bullet list
  were removed (the underlying scripts and `Ralph/progress.txt` still
  exist for legacy continuity).
- **GitHub Issues** is now the source of truth for open work. Initial
  batch filed (#1 plugin auto-start, #2 GH parameter discovery,
  #3 multi-client, #4 undo/redo tools, #5 scene analysis, #6–#8
  VisualARQ extensions, #9 template library, #10 macOS support, #11
  batch operations, #12 progress streaming) with `P1`/`P2`/`P3`
  priority labels.

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
