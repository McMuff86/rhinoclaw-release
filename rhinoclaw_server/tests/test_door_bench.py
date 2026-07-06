"""CI regression gate over the COLD/WARM door benchmark (3.3).

These thresholds guard the whole verified loop at once:
- If the judge ever starts passing wrong rotations (orientation
  regression), COLD first-try jumps to 1.0 → the `<= 0.6` gate fails.
- If recall/distill breaks, WARM drops → the `>= 0.9` gate fails.
- If the hint-retry loop breaks, final success drops below 1.0.
"""
import importlib.util
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent / "bench" / "door_bench.py"


def _load_bench():
    spec = importlib.util.spec_from_file_location("door_bench", BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cold_warm_gate(tmp_path):
    bench = _load_bench()
    report = bench.run_benchmark(mode="sim", log_dir=tmp_path)

    cold = report["cold"]
    warm = report["warm"]

    # The published reliability claim — frozen like a test oracle.
    assert cold["first_try_success_rate"] <= 0.6, (
        "COLD first-try too HIGH — is the judge passing wrong orientations?")
    assert warm["first_try_success_rate"] >= 0.9, (
        "WARM first-try too low — recall/distill regression?")
    assert report["first_try_delta"] >= 0.3, "the loop no longer learns"

    # Hint-guided retries must converge for every opening in both modes.
    assert cold["final_success_rate"] == 1.0
    assert warm["final_success_rate"] == 1.0
    # WARM needs fewer attempts than COLD — the corpus does real work.
    assert warm["mean_attempts"] < cold["mean_attempts"]


def test_scene_has_at_least_12_openings_on_two_axes():
    import json

    bench = _load_bench()
    scene = json.loads(Path(bench.DEFAULT_SCENE).read_text(encoding="utf-8"))
    openings = scene["openings"]
    axes = {o["wall_axis"] for o in openings}

    assert len(openings) >= 12
    assert axes == {"x", "y"}
    # Answer-key consistency: segment length must equal the Lichtbreite.
    from rhinoclaw.utils.door_judge import opening_metrics
    for o in openings:
        width = opening_metrics(o["start"], o["end"])["width"]
        assert abs(width - o["lichtbreite"]) < 0.01, o["id"]
