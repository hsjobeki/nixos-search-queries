#!/usr/bin/env python3
"""Fetch the full NixOS packages + options corpus and normalize it.

Sources:
    packages: https://channels.nixos.org/<channel>/packages.json.br
    options:  https://channels.nixos.org/<channel>/options.json.br

Usage:
    searcheval-fetch-corpus --channel nixos-unstable --out corpus/full.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from .schema import option_to_doc, package_to_doc

BASE = "https://channels.nixos.org"


def _download(url: str) -> bytes:
    print(f"  GET {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "searcheval-fetch"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 (trusted host)
        return resp.read()


def _brotli_decompress(data: bytes) -> bytes:
    try:
        import brotli  # type: ignore
        return brotli.decompress(data)
    except ImportError:
        pass
    if shutil.which("brotli"):
        return subprocess.run(["brotli", "-d", "-c"], input=data,
                              capture_output=True, check=True).stdout
    raise SystemExit(
        "Need brotli to decompress .br files. Install the 'brotli' Python "
        "module (pip install 'searcheval[fetch]') or the brotli CLI "
        "(nix-shell -p brotli)."
    )


def _fetch_json(url: str) -> dict:
    return json.loads(_brotli_decompress(_download(url)))


def fetch(channel: str, include_packages: bool, include_options: bool) -> list[dict]:
    docs = []
    if include_packages:
        data = _fetch_json(f"{BASE}/{channel}/packages.json.br")
        pkgs = data.get("packages", data)  # top-level may be {"packages": {...}}
        for attr, rec in pkgs.items():
            docs.append(package_to_doc(attr, rec))
        print(f"  packages: {len(pkgs)}", file=sys.stderr)
    if include_options:
        data = _fetch_json(f"{BASE}/{channel}/options.json.br")
        for name, rec in data.items():
            docs.append(option_to_doc(name, rec))
        print(f"  options: {len(data)}", file=sys.stderr)
    return [
        {"id": d.id, "kind": d.kind, "name": d.name,
         "description": d.description, "extra": d.extra}
        for d in docs
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--channel", default="nixos-unstable")
    ap.add_argument("--out", default="corpus/full.json")
    ap.add_argument("--no-packages", action="store_true")
    ap.add_argument("--no-options", action="store_true")
    args = ap.parse_args(argv)

    print(f"Fetching corpus for channel {args.channel} ...", file=sys.stderr)
    docs = fetch(args.channel,
                 include_packages=not args.no_packages,
                 include_options=not args.no_options)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(docs, ensure_ascii=False, indent=0))
    print(f"Wrote {len(docs)} docs to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
