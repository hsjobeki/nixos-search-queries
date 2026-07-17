#!/usr/bin/env python3
"""Reproducible no-regression gate for engine relevance tuning.

Two subcommands, both scoring relevance on the committed yardstick
(``corpus/full.json`` + ``queries/queries.json``) via the same
``searcheval.harness.evaluate`` the report uses -- no separate metric code:

    python scripts/tune.py baseline   # capture per-category success@10 + MRR
    python scripts/tune.py check      # re-measure, diff vs baseline, gate

``check`` exits non-zero if ANY per-category success@10, overall success@10, or
overall MRR drops below the locked baseline (minus EPS float-noise tolerance),
for either engine. Ranking is deterministic for a fixed index, so the per-query
success@10 is exact and the gate is reproducible.

Latency is irrelevant to the gate, so queries run once (``repeat=1, warmup=0``)
to keep the loop fast; only relevance is read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from searcheval.engines import ENGINES  # noqa: E402
from searcheval.harness import evaluate  # noqa: E402
from searcheval.schema import load_corpus, load_queries, validate_queries  # noqa: E402

CORPUS = ROOT / "corpus" / "full.json"
QUERIES = ROOT / "queries" / "queries.json"
BASELINE = ROOT / "results" / "baseline.json"
EPS = 0.005  # float-noise tolerance; ranking is deterministic so this is generous


def _measure() -> dict:
    """Relevance-only pass for both engines. Returns {engine: metrics}."""
    docs = load_corpus(CORPUS)
    queries = load_queries(QUERIES)
    problems = validate_queries(queries, docs)
    if problems:
        raise SystemExit("golden set references unknown ids: " + "; ".join(problems))
    out: dict = {}
    for name in sorted(ENGINES):
        with ENGINES[name]() as engine:
            rep = evaluate(engine, docs, queries, k=10, repeat=1, warmup=0)
        agg = rep.aggregate()
        out[name] = {
            "overall": {"success@10": agg["success@10"], "mrr": agg["mrr"]},
            "by_category": {
                cat: {"success@10": c["success@10"], "mrr": c["mrr"]}
                for cat, c in agg["by_category"].items()
            },
        }
    return out


def cmd_baseline() -> int:
    data = _measure()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True))
    print(f"wrote {BASELINE.relative_to(ROOT)}")
    for engine, m in data.items():
        print(f"\n[{engine}] overall success@10={m['overall']['success@10']:.3f} "
              f"mrr={m['overall']['mrr']:.3f}")
        for cat in sorted(m["by_category"]):
            print(f"  {cat:<10} success@10={m['by_category'][cat]['success@10']:.3f}")
    return 0


def cmd_check() -> int:
    if not BASELINE.exists():
        raise SystemExit(f"no baseline at {BASELINE}; run 'baseline' first")
    base = json.loads(BASELINE.read_text())
    cur = _measure()
    regressed = False
    for engine in sorted(cur):
        b, c = base[engine], cur[engine]
        print(f"\n[{engine}]  (baseline -> current, Δ)")
        # per-category success@10
        for cat in sorted(c["by_category"]):
            bs = b["by_category"].get(cat, {}).get("success@10", 0.0)
            cs = c["by_category"][cat]["success@10"]
            delta = cs - bs
            flag = "  REGRESSED" if delta < -EPS else ""
            if delta < -EPS:
                regressed = True
            print(f"  {cat:<10} s@10 {bs:.3f} -> {cs:.3f}  {delta:+.3f}{flag}")
        # overall success@10 and MRR
        for key in ("success@10", "mrr"):
            bv = b["overall"][key]
            cv = c["overall"][key]
            delta = cv - bv
            flag = "  REGRESSED" if delta < -EPS else ""
            if delta < -EPS:
                regressed = True
            print(f"  overall {key:<7} {bv:.3f} -> {cv:.3f}  {delta:+.3f}{flag}")
    if regressed:
        print("\nGATE FAILED: a category or overall metric dropped below baseline.")
        return 1
    print("\nGATE PASSED: no metric below baseline for either engine.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("baseline", "check"):
        print(__doc__)
        return 2
    return cmd_baseline() if argv[0] == "baseline" else cmd_check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
