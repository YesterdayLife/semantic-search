"""Compare dictionary search and local BGE-M3 search. Bind nothing except local reads."""

from __future__ import annotations

import argparse
import json
import sys

from .adapters import MODES, BGEM3SearchAdapter, DictionarySearchAdapter, dispatch
from .search import build_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run dictionary search, local BGE-M3 search, or both.")
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--crop-id", default=None)
    parser.add_argument("--year-ce", type=int, default=None)
    parser.add_argument("--region-code", default=None)
    parser.add_argument("--season", default=None)
    parser.add_argument("--spatial-level", default=None)
    parser.add_argument("--source-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    filters = {
        "crop_id": args.crop_id,
        "year_ce": args.year_ce,
        "region_code": args.region_code,
        "season": args.season,
        "spatial_level": args.spatial_level,
        "source_id": args.source_id,
    }
    semantic = None
    try:
        dictionary = DictionarySearchAdapter() if args.mode in {"dictionary", "compare", "semantic-fallback"} else None
        if args.mode in {"semantic", "compare", "semantic-fallback"}:
            semantic = BGEM3SearchAdapter(build_service())
        payload = dispatch(args.mode, args.query, args.top_k, filters, dictionary, semantic)
    except Exception:
        payload = {
            "ok": False,
            "mode": args.mode,
            "error": {"code": "internal_error", "message": "The comparison request could not be completed."},
            "dictionary": None,
            "semantic": None,
            "score_comparison": None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    finally:
        if semantic is not None:
            semantic.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
