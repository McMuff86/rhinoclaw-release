"""Door-placement regression benchmark — COLD vs WARM (NEXT-LEVEL-PLAN 3.3).

Measures whether the self-improving loop actually improves placement:

- **COLD**: the policy has no memory — it places every door with the
  default rotation 0 and learns only from judge hints (retry +90° per
  failed attempt, max 3 attempts).
- **WARM**: the policy seeds each placement from ``recall_placements``
  (the corpus the COLD phase built) and falls back to the default on miss.

The reported number is **First-Try-Success-Rate** per mode — computed by
the domain judge from measured geometry, never from policy claims. The
COLD→WARM delta IS the "it learned" proof.

Two modes:
- ``--mode sim`` (default): deterministic, Rhino-free. Simulates the baked
  geometry from the construction rule and judges with the pure core. Runs
  in CI as a regression gate (tests/test_door_bench.py).
- ``--mode live``: drives the real ``place_doors`` → ``judge_door_placement``
  loop against a running Rhino. Slow (one Player run per attempt).

Usage:
    uv run python bench/door_bench.py                       # sim, default scene
    uv run python bench/door_bench.py --mode live --keep    # against Rhino
"""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

# Allow running as a script from rhinoclaw_server/ without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rhinoclaw.utils.door_judge import judge_door, opening_metrics  # noqa: E402
from rhinoclaw.utils.interaction_logger import InteractionLogger  # noqa: E402
from rhinoclaw.utils.recipe_distiller import distill, lookup  # noqa: E402

DEFAULT_SCENE = Path(__file__).resolve().parent / "scenes" / "door_bench_12.json"
FRAME_HALF_MM = 110.0       # UD5: frame adds 110 mm per side
DOOR_DEPTH_MM = 185.0       # measured UD5 footprint depth
DOOR_HEIGHT_MM = 2180.0
MAX_ATTEMPTS = 3
DEFAULT_ROTATION = 0.0      # the no-memory policy


def _rot_xy(rotation_deg, dx, dy):
    rad = math.radians(rotation_deg)
    c, s = math.cos(rad), math.sin(rad)
    return (dx * c - dy * s, dx * s + dy * c)


def placement_point(opening, rotation_deg):
    """The pt the policy passes to the door definition: the door extends
    from pt by (Lichtbreite/2 + frame) along its own rotated axis, so the
    policy derives pt from the opening center and ITS OWN rotation guess."""
    m = opening_metrics(opening["start"], opening["end"])
    half = opening["lichtbreite"] / 2.0 + FRAME_HALF_MM
    off = _rot_xy(rotation_deg, half, 0.0)
    return (m["center"][0] - off[0], m["center"][1] - off[1], 0.0)


def simulate_bake(opening, rotation_deg):
    """The AABB the player WOULD bake for this opening + rotation guess.

    Wrong rotation ⇒ wrong principal axis (and wrong width along the
    opening) — exactly the live forced-fail signature (axis 90, width -935).
    """
    pt = placement_point(opening, rotation_deg)
    half = opening["lichtbreite"] / 2.0 + FRAME_HALF_MM
    center = (pt[0] + _rot_xy(rotation_deg, half, 0.0)[0],
              pt[1] + _rot_xy(rotation_deg, half, 0.0)[1])
    long_half = half
    depth_half = DOOR_DEPTH_MM / 2.0
    if rotation_deg % 180 == 0:
        ext = (long_half, depth_half)
    else:
        ext = (depth_half, long_half)
    return [[center[0] - ext[0], center[1] - ext[1], 0.0],
            [center[0] + ext[0], center[1] + ext[1], DOOR_HEIGHT_MM]]


class SimRunner:
    """Rhino-free attempt runner: simulate bake, judge with the pure core."""

    def __init__(self, log_dir, definition):
        self.logger = InteractionLogger(log_dir=str(log_dir))
        self.definition = definition

    def attempt(self, opening, rotation_deg):
        bbox = simulate_bake(opening, rotation_deg)
        verdict = judge_door(bbox, opening["start"], opening["end"])
        self.logger.log_outcome({
            "door_id": opening["id"],
            "pass": verdict["pass"],
            "off_center_mm": verdict["off_center_mm"],
            "axis_deg_error": verdict["axis_deg_error"],
            "width_error_mm": verdict["width_error_mm"],
            "wall_axis": opening["wall_axis"],
            "width_requested": opening["lichtbreite"],
            "rotation_applied": rotation_deg,
            "definition": self.definition,
        })
        return verdict

    def cleanup(self):
        pass


class LiveRunner:
    """Real place_doors → judge_door_placement against a running Rhino."""

    def __init__(self, log_dir, definition, timeout_per_door=120.0, keep=False):
        # The live corpus is the REAL logs dir (judge logs via the global
        # interaction_logger) — the bench teaches the production recall.
        from rhinoclaw.utils.interaction_logger import interaction_logger
        self.logger = interaction_logger
        self.definition = definition
        self.timeout = timeout_per_door
        self.keep = keep
        self._all_ids = []

    def attempt(self, opening, rotation_deg):
        from rhinoclaw.tools.judge_door_placement import judge_door_placement
        from rhinoclaw.tools.place_doors import place_doors

        pt = placement_point(opening, rotation_deg)
        result = json.loads(place_doors(
            None, self.definition,
            items=[{
                "id": f"BENCH_{opening['id']}",
                "pt": list(pt),
                "rotation": rotation_deg,
                "lichtbreite": opening["lichtbreite"],
                "wall_axis": opening["wall_axis"],
            }],
            defaults={"lichthoehe": 2100},
            timeout_per_door=self.timeout,
        ))
        door = (result.get("data") or {}).get("doors", [{}])[0]
        object_ids = door.get("object_ids") or []
        self._all_ids.extend(object_ids)
        if not object_ids:
            return {"placed": False, "pass": False, "off_center_mm": None,
                    "axis_deg_error": None, "width_error_mm": None,
                    "hint": door.get("message", "no geometry")}

        judged = json.loads(judge_door_placement(
            None, [door], openings=[opening], definition=self.definition))
        verdict = (judged.get("data") or {}).get("verdicts", [{}])[0]

        if not verdict.get("pass"):
            self._delete(object_ids)  # clear the failed attempt for the retry
        return verdict

    def _delete(self, object_ids):
        from rhinoclaw.tools.execute_rhinoscript_python_code import (
            execute_rhinoscript_python_code,
        )
        code = (
            "import rhinoscriptsyntax as rs\n"
            f"rs.DeleteObjects({json.dumps(list(object_ids))})\n"
            "print('OK')\n"
        )
        execute_rhinoscript_python_code(None, code)

    def cleanup(self):
        if not self.keep and self._all_ids:
            self._delete(self._all_ids)


def run_mode(runner, openings, warm, recall_log_dir, definition,
             max_attempts=MAX_ATTEMPTS):
    """Run one benchmark pass; returns per-mode metrics."""
    recipes = distill(recall_log_dir) if warm else {}

    first_try = 0
    final_pass = 0
    attempts_used = []
    off_centers = []
    axis_errors_first = []
    rows = []

    for opening in openings:
        rotation = DEFAULT_ROTATION
        if warm:
            recipe = lookup(recipes, definition, opening["wall_axis"])
            if recipe and recipe.get("rotation") is not None:
                rotation = float(recipe["rotation"])

        verdict = None
        for attempt in range(1, max_attempts + 1):
            verdict = runner.attempt(opening, rotation)
            if attempt == 1:
                if verdict.get("axis_deg_error") is not None:
                    axis_errors_first.append(verdict["axis_deg_error"])
                if verdict.get("pass"):
                    first_try += 1
            if verdict.get("pass"):
                final_pass += 1
                attempts_used.append(attempt)
                if verdict.get("off_center_mm") is not None:
                    off_centers.append(verdict["off_center_mm"])
                break
            # Follow the judge's hint family: wrong axis → rotate 90°.
            rotation = (rotation + 90.0) % 360.0
        else:
            attempts_used.append(max_attempts)

        rows.append({
            "opening": opening["id"],
            "wall_axis": opening["wall_axis"],
            "first_try_pass": attempts_used and verdict.get("pass")
                              and attempts_used[-1] == 1,
            "attempts": attempts_used[-1],
            "final_pass": bool(verdict and verdict.get("pass")),
        })

    n = len(openings)
    return {
        "openings": n,
        "first_try_success_rate": round(first_try / n, 3),
        "final_success_rate": round(final_pass / n, 3),
        "mean_off_center_mm": round(sum(off_centers) / len(off_centers), 2)
                              if off_centers else None,
        "mean_first_try_axis_deg_error": round(
            sum(axis_errors_first) / len(axis_errors_first), 2)
            if axis_errors_first else None,
        "mean_attempts": round(sum(attempts_used) / len(attempts_used), 2)
                         if attempts_used else None,
        "rows": rows,
    }


def run_benchmark(scene_path=DEFAULT_SCENE, mode="sim", log_dir=None,
                  timeout_per_door=120.0, keep=False,
                  max_attempts=MAX_ATTEMPTS, definition=None):
    scene = json.loads(Path(scene_path).read_text(encoding="utf-8"))
    openings = scene["openings"]
    # live mode needs the full Windows path to the .gh; the scene only
    # records the basename (which is also the recall key).
    definition = definition or scene.get("definition", "door.gh")

    if mode == "sim":
        if log_dir is None:
            log_dir = Path(tempfile.mkdtemp(prefix="door_bench_"))
        log_dir = Path(log_dir)
        cold_runner = SimRunner(log_dir, definition)
        warm_runner = SimRunner(log_dir, definition)
    else:
        from rhinoclaw.utils.interaction_logger import interaction_logger
        log_dir = interaction_logger._log_dir
        cold_runner = LiveRunner(log_dir, definition,
                                 timeout_per_door=timeout_per_door, keep=keep)
        warm_runner = LiveRunner(log_dir, definition,
                                 timeout_per_door=timeout_per_door, keep=keep)

    # COLD first: no memory. Its judged outcomes (incl. hint-guided retries)
    # build the corpus WARM recalls from.
    cold = run_mode(cold_runner, openings, warm=False,
                    recall_log_dir=log_dir, definition=definition,
                    max_attempts=max_attempts)
    cold_runner.cleanup()
    warm = run_mode(warm_runner, openings, warm=True,
                    recall_log_dir=log_dir, definition=definition,
                    max_attempts=max_attempts)
    warm_runner.cleanup()

    return {
        "scene": scene.get("name", str(scene_path)),
        "mode": mode,
        "definition": definition,
        "cold": cold,
        "warm": warm,
        "first_try_delta": round(
            warm["first_try_success_rate"] - cold["first_try_success_rate"], 3),
    }


def _print_report(report):
    print(f"\nDoor-placement benchmark — scene {report['scene']} "
          f"({report['mode']} mode)\n")
    print(f"{'':14}{'COLD':>10}{'WARM':>10}")
    for label, key in [("First-try", "first_try_success_rate"),
                       ("Final", "final_success_rate"),
                       ("Ø attempts", "mean_attempts"),
                       ("Ø off-center", "mean_off_center_mm"),
                       ("Ø axis err 1st", "mean_first_try_axis_deg_error")]:
        print(f"{label:14}{str(report['cold'][key]):>10}"
              f"{str(report['warm'][key]):>10}")
    print(f"\nFirst-try delta (WARM - COLD): {report['first_try_delta']:+.3f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["sim", "live"], default="sim")
    parser.add_argument("--scene", default=str(DEFAULT_SCENE))
    parser.add_argument("--log-dir", default=None,
                        help="corpus dir for sim mode (default: fresh tmp)")
    parser.add_argument("--timeout-per-door", type=float, default=120.0)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    parser.add_argument("--keep", action="store_true",
                        help="live mode: keep the baked benchmark doors")
    parser.add_argument("--definition", default=None,
                        help="live mode: full Windows path to the door .gh")
    parser.add_argument("--json", action="store_true",
                        help="print the full report as JSON")
    args = parser.parse_args()

    report = run_benchmark(scene_path=args.scene, mode=args.mode,
                           log_dir=args.log_dir,
                           timeout_per_door=args.timeout_per_door,
                           keep=args.keep, max_attempts=args.max_attempts,
                           definition=args.definition)
    _print_report(report)

    # Trend history: one line per run → the README number becomes a curve.
    import datetime
    history = Path(__file__).resolve().parent.parent / "logs" / "bench_history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with open(history, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": report["mode"], "scene": report["scene"],
            "cold_first_try": report["cold"]["first_try_success_rate"],
            "warm_first_try": report["warm"]["first_try_success_rate"],
            "delta": report["first_try_delta"],
        }) + "\n")

    if args.json:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
