#!/usr/bin/env python3
"""One-object end-to-end test: MPC seed fetch -> PyRoOrb fit -> local ITF search.

No PostgreSQL/SBN connection is made. The local ITF file is indexed in a
SQLite cache, then PyRoOrb's native itf_search() pipeline is run on that source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_itf_source import LocalMPC80Source
from designation_list import parse_designation_list, parse_single_designation


def read_designation(args):
    # PyRoOrb owns MPC packed/unpacked designation conversion. Use its helper
    # only after extracting a complete token from the potentially annotated line.
    from pyroorb.obs_sources import ensure_unpacked

    if args.designation:
        return parse_single_designation(args.designation, ensure_unpacked)
    if not args.list_file.is_file():
        raise FileNotFoundError(
            f"Designation list not found: {args.list_file}\n"
            "Pass --designation '2023 AB' or provide --list-file."
        )
    names, stats = parse_designation_list(args.list_file, ensure_unpacked)
    print(
        "Designation list: "
        f"{stats['lines']} lines, {len(names)} unique designations, "
        f"{stats['ignored_lines']} ignored lines, "
        f"{stats['duplicates']} duplicates, "
        f"{stats['multi_match_lines']} lines with multiple matches"
    )
    if not names:
        raise ValueError(f"No MPC designations found in {args.list_file}")
    if args.index < 0 or args.index >= len(names):
        raise IndexError(
            f"--index {args.index} is outside the parsed designation list "
            f"(0..{len(names)-1})"
        )
    return names[args.index]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--itf", type=Path, default=ROOT / "data/input/ITF.txt",
                   help="Local MPC80 ITF text file")
    p.add_argument("--list-file", type=Path,
                   default=ROOT / "data/input/designations.txt",
                   help="Text file containing MPC designations, optionally mixed with notes")
    p.add_argument("--index", type=int, default=0,
                   help="Zero-based index in the extracted, deduplicated designation list (default: 0)")
    p.add_argument("--designation", default=None,
                   help="Extract one MPC designation from this text instead of reading the list")
    p.add_argument("--sqlite-index", type=Path,
                   default=ROOT / "data/cache/local_itf_index.sqlite",
                   help="Generated local SQLite index (not an SBN database)")
    p.add_argument("--rebuild-index", action="store_true",
                   help="Rebuild the SQLite index even if the ITF file is unchanged")
    p.add_argument("--mag-limit", type=float, default=float("inf"),
                   help="Predicted V magnitude cut; default inf disables this gate; e.g. 28")
    p.add_argument("--output-dir", type=Path, default=ROOT / "data/output",
                   help="Directory for search result files")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    designation = read_designation(args)
    if not args.itf.is_file():
        p.error(f"ITF file does not exist: {args.itf}")

    from pyroorb.itf.config import ItfConfig
    from pyroorb.itf.search import itf_search
    from pyroorb.itf.verdict import SearchVerdict

    args.output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in designation)
    log = (lambda message: None) if args.quiet else print

    print(f"Target designation : {designation}")
    print(f"Local ITF          : {args.itf.resolve()}")
    print(f"Magnitude gate     : {'DISABLED' if args.mag_limit == float('inf') else args.mag_limit}")
    print("MPC submission     : DISABLED (dry run only)")

    cfg = ItfConfig(candidate_path="index", ranking_mode="certainty", submit=False)
    source = LocalMPC80Source(args.itf, args.sqlite_index, cfg=cfg,
                              rebuild=args.rebuild_index, log=log)
    try:
        # An explicit +infinity cut disables the predicted-magnitude corridor gate.
        # A finite user value (e.g. 28) is applied exactly, without the default faintness floor.
        cfg.set_mag_limit(args.mag_limit)
        cfg.submit = False

        result = itf_search(
            source,
            designations=designation,
            cfg=cfg,
            do_submit=False,
            verbose=not args.quiet,
            log=log,
            trace=None if args.quiet else print,
        )

        print("\n===== SEARCH RESULT =====")
        print(f"Verdict : {result.verdict}")
        print(f"Reason  : {result.reason}")
        if result.telemetry:
            print("Telemetry:", json.dumps(result.telemetry, ensure_ascii=False, default=str))

        if result.itf_obs80:
            linked_path = args.output_dir / f"{safe_name}_linked_itf_obs80.txt"
            linked_path.write_text(result.itf_obs80, encoding="ascii", errors="replace")
            print(f"Linked ITF observations : {linked_path}")

        if result.combined_obs80:
            combined_path = args.output_dir / f"{safe_name}_combined_candidate_obs80.txt"
            combined_path.write_text(result.combined_obs80, encoding="ascii", errors="replace")
            print(f"Combined candidate file : {combined_path}")

        if result.linkage:
            linkage_path = args.output_dir / f"{safe_name}_linkage.json"
            linkage_path.write_text(
                json.dumps(result.linkage, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"Linkage metadata        : {linkage_path}")

        if result.verdict is SearchVerdict.LINKED:
            print("\nA LINKED result was produced. Review the observation file before any MPC submission.")
        elif result.verdict is SearchVerdict.POSSIBLE:
            print("\nPOSSIBLE is for manual review; it is not a submittable linkage.")
        else:
            print("\nNo accepted linkage was found. This does not prove that no matching ITF tracklet exists.")
    finally:
        source.close()


if __name__ == "__main__":
    main()
