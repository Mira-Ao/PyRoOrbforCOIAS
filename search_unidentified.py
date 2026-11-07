#!/usr/bin/env python3
"""Search local ITF for links to unidentified HelioLinC clusters or trksub pairs.

Cluster files contain MPC80 observations. Tracklet-list files contain only ITF
tracklet names, e.g. ``H300000 2d`` or ``H300010 = H300020``; their observations
are retrieved from the local ITF-derived SQLite index before orbit fitting.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from search_common import append_jsonl, execute_search, open_local_source
from unidentified_inputs import parse_tracklet_list, read_heliolinc_clusters, utc_night_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--itf", type=Path, default=ROOT / "data/input/itf.txt",
                        help="Local MPC80 ITF text file")
    parser.add_argument("--cluster-file", type=Path, action="append", default=[],
                        help="HelioLinC finalout_itfMPC80.txt; may be repeated")
    parser.add_argument("--tracklet-list", type=Path, action="append", default=[],
                        help="ITF trksub-name list; may be repeated")
    parser.add_argument("--sqlite-index", type=Path,
                        default=ROOT / "data/cache/local_itf_index.sqlite",
                        help="Derived local SQLite index")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/output/unidentified",
                        help="Directory for per-input search artifacts")
    parser.add_argument("--summary", type=Path, default=None,
                        help="JSONL summary (default: OUTPUT_DIR/search_summary.jsonl)")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="Rebuild the local SQLite index")
    parser.add_argument("--quiet-trace", action="store_true",
                        help="Disable detailed per-search trace")
    args = parser.parse_args()

    if not args.itf.is_file():
        parser.error(f"ITF file does not exist: {args.itf}")
    if not args.cluster_file and not args.tracklet_list:
        parser.error("Specify at least one --cluster-file or --tracklet-list")
    for path in args.cluster_file + args.tracklet_list:
        if not path.is_file():
            parser.error(f"Input file does not exist: {path}")

    jobs = []
    for path in args.cluster_file:
        clusters = read_heliolinc_clusters(path)
        print(f"HelioLinC file {path}: {len(clusters)} clusters")
        for i, cluster in enumerate(clusters, 1):
            label = f"{path.stem}_{cluster['label']}_{i:05d}"
            jobs.append({"kind": "cluster", "label": label,
                         "obs80": cluster["obs80"], "source": str(path),
                         "source_line": None, "expected_nights": None})

    for path in args.tracklet_list:
        entries, stats = parse_tracklet_list(path)
        print(f"Tracklet list {path}: {len(entries)} entries; "
              f"{stats['ignored']} ignored; {stats['duplicates']} duplicates")
        for i, entry in enumerate(entries, 1):
            joined = "=".join(entry["names"])
            label = f"{path.stem}_{i:05d}_{joined}"
            jobs.append({**entry, "label": label, "source": str(path)})

    if not jobs:
        parser.error("No usable clusters or tracklet-list entries were found")

    summary_path = args.summary or (args.output_dir / "search_summary.jsonl")
    print(f"Total searches : {len(jobs):,}")
    print("Magnitude gate : DISABLED")
    print("MPC submission : DISABLED")

    source, cfg = open_local_source(args)
    counts = {"LINKED": 0, "POSSIBLE": 0, "NONE": 0, "ERROR": 0}
    try:
        for index, job in enumerate(jobs, 1):
            label = job["label"]
            print(f"\n===== [{index}/{len(jobs)}] {job['kind']} {label} =====")
            try:
                if job["kind"] == "cluster":
                    seed_obs80 = job["obs80"]
                    names = []
                    expected_nights = None
                    nobs = sum(1 for line in seed_obs80.splitlines()
                               if len(line) >= 80 and line[14] not in "sv")
                    actual_nights = utc_night_count(seed_obs80)
                    print(f"Seed observations  : {nobs}; UTC nights: {actual_nights}")
                else:
                    seed_obs80, found, missing, nobs = source.observations_for_tracklet_names(job["names"])
                    if missing:
                        raise RuntimeError(
                            "tracklet name(s) not found in local ITF: " + ", ".join(missing)
                        )
                    if nobs < 2:
                        raise RuntimeError(
                            f"only {nobs} optical observation(s) retrieved; at least 2 are required"
                        )
                    names = job["names"]
                    expected_nights = job.get("expected_nights")
                    actual_nights = utc_night_count(seed_obs80)
                    print(f"Retrieved trksubs : {', '.join(found)}")
                    print(f"Seed observations  : {nobs}; UTC nights: {actual_nights}")
                    if expected_nights and actual_nights != expected_nights:
                        print(f"WARNING: list says {expected_nights}d but retrieved data span "
                              f"{actual_nights} UTC night(s); searching the retrieved data as-is")

                if not seed_obs80.strip():
                    raise RuntimeError("input contains no usable MPC80 observations")
                result, record = execute_search(
                    source, cfg, output_dir=args.output_dir, label=label,
                    seed_obs80=seed_obs80,
                    primary_desigs=[],
                    verbose=True,
                    trace=None if args.quiet_trace else print,
                )
                verdict = getattr(result.verdict, "name", str(result.verdict)).upper()
                if verdict not in counts:
                    verdict = "NONE"
                counts[verdict] += 1
                record.update({"kind": job["kind"], "source": job["source"],
                               "source_line": job.get("source_line"),
                               "tracklet_names": names, "expected_nights": expected_nights,
                               "observation_count": nobs, "utc_nights": actual_nights,
                               "status": "OK"})
                print(f"Verdict: {result.verdict}")
                print(f"Reason : {result.reason}")
            except Exception as exc:
                counts["ERROR"] += 1
                record = {"label": label, "kind": job["kind"],
                          "source": job["source"], "source_line": job.get("source_line"),
                          "tracklet_names": job.get("names", []),
                          "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
                print(f"ERROR: {record['error']}")
            append_jsonl(summary_path, record)
            print(f"Progress: {index}/{len(jobs)}; counts={counts}")
    finally:
        source.close()

    print("\n===== BATCH COMPLETE =====")
    print(f"Processed : {len(jobs):,}")
    print(f"Counts    : {counts}")
    print(f"Summary   : {summary_path}")


if __name__ == "__main__":
    main()
