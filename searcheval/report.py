"""Render engine reports into an auditable Markdown matrix + raw JSON dumps."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from . import metrics
from .harness import EngineReport, QueryResult
from .stats import paired_bootstrap_ci


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "n/a"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def _footprint(index_agg: dict) -> str:
    """Format footprint with its per-engine measurement kind, e.g. ``18KB
    (on-disk store)``. The label is required: the number means different things
    per engine and is misleading without it."""
    size = _fmt_bytes(index_agg.get("index_bytes"))
    kind = index_agg.get("footprint_kind")
    return f"{size} ({kind})" if kind and size != "n/a" else size


def write_raw(report: EngineReport, out_dir: str | Path) -> Path:
    """Dump per-query results so every headline number is traceable to a query.

    Per-query latency lives alongside the relevance judgments, and the indexing
    stats are in ``summary.index``, so every figure in the matrix is auditable
    from this single raw file."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"raw_{report.engine}.json"
    payload = {
        "engine": report.engine,
        "summary": report.aggregate(),
        "per_query": [
            {
                "id": r.id, "q": r.q, "category": r.category,
                "latency_ms": r.latency_ms, "ranked": r.ranked,
                "relevant": r.relevant,
                "recall@10": r.recall_at_10, "mrr": r.mrr,
                "success@10": r.success_at_10,
            }
            for r in report.results
        ],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def write_matrix(reports: list[EngineReport], out_dir: str | Path) -> Path:
    """Render the comparison matrix.

    Relevance, latency and indexing all come from the same single-corpus run, so
    a single ``reports`` list carries every figure. Relevance is reported with
    known-item metrics only; see the header for why Precision and nDCG are
    intentionally omitted on an incompletely-judged corpus."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    aggs = {r.engine: r.aggregate() for r in reports}
    engines = list(aggs)

    lines: list[str] = ["# Search backend evaluation", ""]

    doc_count = reports[0].index_stats.doc_count if reports else 0
    lines.append(
        f"> Relevance, latency and indexing are all measured on the full "
        f"{doc_count:,}-doc corpus (144,174 packages + 24,505 options). "
        "Relevance uses **known-item metrics** — Success@10, MRR, Recall@10 — "
        "which stay valid when the corpus is not exhaustively judged; Precision "
        "and nDCG are intentionally omitted because on an unlabeled corpus they "
        "count genuine-but-unlabeled hits as misses, unequally per engine.")
    lines.append("")

    lines.append("## Relevance (higher is better)")
    lines.append("")
    lines += _table(["metric", *engines], [
        [m] + [f"{aggs[e][m]:.3f}" for e in engines]
        for m in ("success@10", "mrr", "recall@10")
    ])
    lines.append("")

    lat = {e: metrics.latency_summary([r.latency_ms for r in rep.results])
           for e, rep in zip(engines, reports)}
    lines.append("## Latency, ms (lower is better)")
    lines.append("")
    lines += _table(["stat", *engines], [
        [s] + [f"{lat[e][s]:.2f}" for e in engines]
        for s in ("p50", "p95", "p99", "mean", "max")
    ])
    lines.append("")

    lines.append("## Indexing")
    lines.append("")
    index = {e: rep.index_stats for e, rep in zip(engines, reports)}
    lines += _table(["metric", *engines], [
        ["docs"] + [str(index[e].doc_count) for e in engines],
        ["index time (s)"] + [f"{index[e].seconds:.2f}" for e in engines],
        ["footprint"] + [_footprint({
            "index_bytes": index[e].index_bytes,
            "footprint_kind": index[e].footprint_kind,
        }) for e in engines],
    ])
    lines.append("")
    lines.append("> Footprint is measured differently per engine because their "
                 "architectures differ: Elasticsearch reports on-disk index "
                 "store size, Typesense reports in-RAM process RSS. Not directly "
                 "comparable across engines.")
    lines.append("")

    # Per-category Success@10: did the canonical answer surface in the top 10.
    cats = sorted({c for e in engines for c in aggs[e]["by_category"]})
    lines.append("## Success@10 by query category")
    lines.append("")
    rows = []
    for c in cats:
        row = [c]
        for e in engines:
            cell = aggs[e]["by_category"].get(c)
            row.append(f"{cell['success@10']:.3f}" if cell else "-")
        rows.append(row)
    lines += _table(["category", *engines], rows)
    lines.append("")

    lines += _significance_section(reports)

    path = out / "report.md"
    path.write_text("\n".join(lines))
    return path


def _significance_section(reports: list[EngineReport]) -> list[str]:
    """Paired-bootstrap CI of the per-query MRR difference, overall and per
    category, for every unordered engine pair. The CI answers 'is the gap real
    or noise' rather than trusting a bare point-estimate ordering. With three or
    more engines this emits one sub-block per pair; the multiple-comparison
    caveat (more pairs -> more chances for a spurious CI) is noted in the README."""
    if len(reports) < 2:
        return []
    lines = ["## Significance: paired MRR by engine pair (95% bootstrap CI)", ""]
    lines.append("Each block reports engine A \u2212 B; positive favors A; "
                 "* = CI excludes 0 (significant).")
    lines.append("")
    for a, b in itertools.combinations(reports, 2):
        lines += _pair_significance(a, b)
    return lines


def significance_rows(a: list[QueryResult], b: list[QueryResult]) -> list[dict]:
    """Paired-bootstrap MRR CI overall and per category, as structured rows.

    Groups are ``overall`` plus each category present in ``a`` (sorted). A group
    with no paired observations is skipped, matching the Markdown behavior. This
    is the single source of truth for significance: the Markdown report and the
    site JSON builder both format these deterministic (seed=0) rows."""
    groups = [("overall", None)] + [(c, c) for c in sorted(
        {r.category for r in a})]
    rows: list[dict] = []
    for label, cat in groups:
        xs, ys = _paired_mrr(a, b, cat)
        if not xs:
            continue
        ci = paired_bootstrap_ci(xs, ys)
        rows.append({
            "group": label,
            "n": ci.n,
            "mean_diff": ci.mean_diff,
            "lo": ci.lo,
            "hi": ci.hi,
            "significant": ci.significant,
        })
    return rows


def _pair_significance(a: EngineReport, b: EngineReport) -> list[str]:
    """One `### A \u2212 B` sub-block: paired MRR diff overall and per category."""
    lines = [f"### {a.engine} \u2212 {b.engine}", ""]
    rows = []
    for r in significance_rows(a.results, b.results):
        mark = " *" if r["significant"] else ""
        rows.append([r["group"], str(r["n"]),
                     f"{r['mean_diff']:+.3f}",
                     f"[{r['lo']:+.3f}, {r['hi']:+.3f}]{mark}"])
    lines += _table(["group", "n", "mean MRR diff", "95% CI"], rows)
    lines.append("")
    return lines


def _paired_mrr(a: list[QueryResult], b: list[QueryResult],
                category: str | None) -> tuple[list[float], list[float]]:
    """Align the two engines' per-query MRR by query id (optionally one category)."""
    bi = {r.id: r for r in b}
    xs, ys = [], []
    for r in a:
        if category is not None and r.category != category:
            continue
        other = bi.get(r.id)
        if other is None:
            continue
        xs.append(r.mrr)
        ys.append(other.mrr)
    return xs, ys


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out
