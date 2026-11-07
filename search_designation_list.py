#!/usr/bin/env python3
"""Sequentially search a complete provisional-designation list in a local MPC80 ITF.

Each designation is fetched from the MPC through PyRoOrb, fitted, then searched
against the local SQLite index derived from the supplied MPC80 ITF text file.
No PostgreSQL/SBN connection is made and MPC submission is disabled.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from designation_list import parse_designation_list
from search_common import append_jsonl, execute_search, open_local_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--itf", type=Path, default=ROOT / "data/input/itf.txt",
                        help="Local MPC 80-column ITF text file")
    parser.add_argument("--list-file", type=Path,
                        default=ROOT / "data/input/designations.txt",
                        help="Mixed packed/unpacked MPC designation list")
    parser.add_argument("--sqlite-index", type=Path,
                        default=ROOT / "data/cache/local_itf_index.sqlite",
                        help="Derived local SQLite index (not an SBN database)")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/output/designations",
                        help="Directory for per-object result files")
    parser.add_argument("--summary", type=Path, default=None,
                        help="JSONL run summary (default: OUTPUT_DIR/search_summary.jsonl)")
    parser.add_argument("--start-index", type=int, default=0,
                        help="Start at this zero-based index in the deduplicated list")
    parser.add_argument("--limit", type=int, default=None,
                        help="Maximum number of objects to process; default is the rest of the list")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="Rebuild the local SQLite index even if the ITF file is unchanged")
    parser.add_argument("--quiet-trace", action="store_true",
                        help="Disable the detailed per-search trace")
    args = parser.parse_args()

    if not args.itf.is_file():
        parser.error(f"ITF file does not exist: {args.itf}")
    if not args.list_file.is_file():
        parser.error(f"Designation list does not exist: {args.list_file}")
    if args.start_index < 0:
        parser.error("--start-index must be >= 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")

    from pyroorb.obs_sources import ensure_unpacked
    names, stats = parse_designation_list(args.list_file, ensure_unpacked)
    if not names:
        parser.error("No MPC designations were found in the input list")
    if args.start_index >= len(names):
        parser.error(f"--start-index {args.start_index} is outside 0..{len(names)-1}")

    end = len(names) if args.limit is None else min(len(names), args.start_index + args.limit)
    summary_path = args.summary or (args.output_dir / "search_summary.jsonl")
    print("Designation list:")
    print(f"  physical lines       : {stats['lines']:,}")
    print(f"  unique designations  : {len(names):,}")
    print(f"  ignored lines        : {stats['ignored_lines']:,}")
    print(f"  duplicate entries    : {stats['duplicates']:,}")
    print(f"  multiple matches     : {stats['multi_match_lines']:,}")
    print(f"  processing indices   : {args.start_index}..{end-1} ({end-args.start_index:,} objects)")
    print("Magnitude gate          : DISABLED")
    print("MPC submission          : DISABLED")

    source, cfg = open_local_source(args)
    counts = {"LINKED": 0, "POSSIBLE": 0, "NONE": 0, "ERROR": 0}
    try:
        for index in range(args.start_index, end):
            designation = names[index]
            label = f"{index+1:06d}_{designation}"
            print(f"\n===== [{index+1}/{len(names)}] {designation} =====")
            try:
                result, record = execute_search(
                    source, cfg, output_dir=args.output_dir, label=label,
                    designations=designation,
                    verbose=True,
                    trace=None if args.quiet_trace else print,
                )
                verdict = getattr(result.verdict, "name", str(result.verdict)).upper()
                if verdict not in counts:
                    verdict = "NONE"
                counts[verdict] += 1
                record.update({"list_index": index, "designation": designation,
                               "status": "OK"})
                print(f"Verdict: {result.verdict}")
                print(f"Reason : {result.reason}")
            except Exception as exc:
                counts["ERROR"] += 1
                record = {"list_index": index, "designation": designation,
                          "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
                print(f"ERROR: {record['error']}")
            append_jsonl(summary_path, record)
            print(f"Progress: {index+1}/{len(names)}; counts={counts}")
    finally:
        source.close()

    print("\n===== BATCH COMPLETE =====")
    print(f"Processed : {end-args.start_index:,}")
    print(f"Counts    : {counts}")
    print(f"Summary   : {summary_path}")


if __name__ == "__main__":
    main()
