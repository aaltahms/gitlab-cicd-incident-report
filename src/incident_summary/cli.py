"""Command-line interface with input protection and actionable error messages."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence
from .core import _parse_timestamp, build_summary, load_incidents, render_html


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic JSON and HTML incident summaries.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--json", dest="json_output", type=Path, required=True)
    parser.add_argument("--html", dest="html_output", type=Path, required=True)
    parser.add_argument("--as-of", help="Timezone-aware snapshot timestamp for active incident aging")
    return parser


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (left.exists() and right.exists() and os.path.samefile(left, right))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    staged = []
    try:
        paths = [args.input, args.json_output, args.html_output]
        if any(_same_file(paths[i], paths[j]) for i in range(3) for j in range(i + 1, 3)):
            raise ValueError("input and output paths must refer to three different files")
        snapshot = _parse_timestamp(args.as_of, "as_of", "report") if args.as_of else None
        summary = build_summary(load_incidents(args.input), as_of=snapshot)
        outputs = [(args.json_output, json.dumps(summary, indent=2, sort_keys=True) + "\n"),
                   (args.html_output, render_html(summary))]
        # Stage both complete files before replacing either destination. Each replace is atomic;
        # the pair is not a filesystem transaction if replacement itself fails midway.
        for target, content in outputs:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as handle:
                staged.append((Path(handle.name), target))
                handle.write(content)
        for temporary, target in staged:
            temporary.replace(target)
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"incident-summary: {exc}", file=sys.stderr)
        return 2
    finally:
        for temporary, _ in staged:
            if temporary.exists():
                temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
