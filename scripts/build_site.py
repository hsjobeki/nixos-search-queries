#!/usr/bin/env python3
"""Regenerate the GitHub Pages visualization data from the eval's raw dumps.

Decoupled from the live eval run on purpose: rebuilding the viz must NOT require
Docker + reindexing 168k docs. Significance is seeded (``seed=0``), so this rebuild
reproduces the ``results/report.md`` numbers exactly (same seeded bootstrap).

    python scripts/build_site.py            # results/raw_*.json -> docs/data.json

Adding a backend: run the eval (writes a new ``results/raw_<engine>.json``), then
run this, then commit ``docs/``. Kept behind an explicit command so a partial
``--engine <subset>`` dev run can never clobber the published artifact.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from searcheval import site  # noqa: E402


def parse_versions(compose_path: Path) -> dict[str, str]:
    """Map each compose service name -> pinned image tag.

    ``docker-compose.yml`` is the single source of truth for engine versions, so
    the header can show them without a second place to update. Service names match
    engine names (``elasticsearch``/``typesense``/``quickwit``). Best-effort: any
    service we can't parse a tag for is simply omitted (site tolerates missing keys).
    """
    if not compose_path.exists():
        return {}
    versions: dict[str, str] = {}
    current: str | None = None
    for line in compose_path.read_text().splitlines():
        svc = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if svc:
            current = svc.group(1)
            continue
        img = re.match(r"^\s+image:\s*(\S+)", line)
        if img and current and current not in versions:
            ref = img.group(1)
            if ":" in ref:
                versions[current] = ref.rsplit(":", 1)[1]
    return versions


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(ROOT / "results"),
                    help="directory holding raw_<engine>.json (default: results/)")
    ap.add_argument("--out", default=str(ROOT / "docs"),
                    help="output directory for data.json (default: docs/)")
    args = ap.parse_args(argv)

    results_dir = Path(args.results)
    raw_files = sorted(results_dir.glob("raw_*.json"))
    if not raw_files:
        raise SystemExit(
            f"no raw_*.json in {results_dir}; run the eval first "
            f"(docker compose up -d && nix run . -- ...) to produce them.")

    reports = [site.load_report(p) for p in raw_files]
    versions = parse_versions(ROOT / "docker-compose.yml")
    path = site.write_site(reports, args.out, versions=versions)

    engines = ", ".join(sorted(r.engine for r in reports))
    print(f"wrote {path} for {len(reports)} engine(s): {engines}")
    if versions:
        print("versions: " + ", ".join(f"{k}={v}" for k, v in sorted(versions.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
