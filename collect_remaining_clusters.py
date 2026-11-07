#!/usr/bin/env python3
"""Collect HelioLinC clusters whose first observation is still in the local MPC80 ITF index.

Run from the PyRoOrb project root.  The script reuses LocalMPC80Source and its
SQLite index; it does not modify the source cluster files, JSON files, or ITF.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from local_itf_source import LocalMPC80Source, _parse_obs80

CLUSTER_RE = re.compile(r"^\s*Cluster\s+(\d+)\s*$", re.IGNORECASE)
OBS_COUNT_RE = re.compile(r"^Observations\s*:\s*(\d+)\s*$", re.IGNORECASE)
SEPARATOR = "########################################################################"


def mpc_date_to_epoch(value: str) -> float | None:
    """Convert a JSON trksubs date such as '2016 05 01.12977' to Unix seconds."""
    try:
        parts = str(value).split()
        if len(parts) != 3:
            return None
        year = int(parts[0])
        month = int(parts[1])
        day = float(parts[2])
        if not (1.0 <= day < 32.0):
            return None
        base = datetime(year, month, 1, tzinfo=timezone.utc)
        return (base + timedelta(days=day - 1.0)).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def signature_from_cluster(cluster: dict) -> frozenset:
    """One first observation per (trksub, station), independent of TXT order."""
    first_by_tracklet = {}
    for _raw_line, rec in cluster["observations"]:
        key = (rec["trksub"], rec["stn"])
        first_by_tracklet.setdefault(key, round(rec["epoch_sec"], 2))
    return frozenset(
        (name, station, epoch)
        for (name, station), epoch in first_by_tracklet.items()
    )


def signature_from_link(link: dict) -> frozenset | None:
    trksubs = link.get("trksubs")
    if not isinstance(trksubs, list) or not trksubs:
        return None
    entries = set()
    for item in trksubs:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            return None
        name = str(item[0]).replace("*", "").strip()
        epoch = mpc_date_to_epoch(item[1])
        station = str(item[2]).strip()
        if not name or not station or epoch is None:
            return None
        entries.add((name, station, round(epoch, 2)))
    return frozenset(entries) if entries else None


def read_cluster_file(path: Path) -> tuple[list[dict], list[tuple[str, dict]]]:
    """Read real clusters and separately collect trailing one-row summary blocks.

    A singleton block is treated as a summary row only when its tracklet name
    also occurs in a multi-observation cluster in the same file. This avoids
    treating an ordinary, unrelated one-observation cluster as a footer row.
    """
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc

    clusters: list[dict] = []
    current = None
    explicit_footer_rows: list[tuple[str, dict]] = []
    in_footer = False

    def finish_current():
        if current is not None and current["observations"]:
            clusters.append(current.copy())

    for line in lines:
        if re.search(r"first observation of each", line, re.IGNORECASE):
            finish_current()
            current = None
            in_footer = True
            continue

        if in_footer:
            rec = _parse_obs80(line)
            if rec is not None:
                explicit_footer_rows.append((line, rec))
            continue

        match = CLUSTER_RE.match(line)
        if match:
            finish_current()
            current = {
                "number": match.group(1),
                "cluster_line": line.strip(),
                "astrom_line": None,
                "count_line": None,
                "expected_observations": None,
                "observations": [],
                "source_file": path.name,
            }
            continue

        if current is None:
            continue

        stripped = line.lstrip()
        if stripped.lower().startswith("astromrms"):
            current["astrom_line"] = stripped
            continue
        if stripped.lower().startswith("observations:"):
            current["count_line"] = stripped
            count_match = OBS_COUNT_RE.match(stripped)
            if count_match:
                current["expected_observations"] = int(count_match.group(1))
            continue

        # Leading spaces are part of the fixed-width MPC80 columns.
        rec = _parse_obs80(line)
        if rec is not None:
            expected = current["expected_observations"]
            if expected is not None and len(current["observations"]) >= expected:
                # The declared cluster is complete. Following MPC80 rows are
                # the appended one-row-per-cluster summary, not cluster data.
                explicit_footer_rows.append((line, rec))
            else:
                current["observations"].append((line, rec))

    finish_current()

    # Some source files encode the summary as one-observation Cluster blocks
    # instead of using a textual footer marker. Separate those from real
    # clusters when their tracklet names are already represented in a real
    # (multi-row) cluster.
    multi_tracklets = {
        rec["trksub"]
        for cluster in clusters if len(cluster["observations"]) >= 2
        for _raw, rec in cluster["observations"]
    }
    singleton_candidates = [
        cluster for cluster in clusters
        if cluster["expected_observations"] is None
        and len(cluster["observations"]) == 1
        and cluster["observations"][0][1]["trksub"] in multi_tracklets
    ]
    candidate_names = [c["observations"][0][1]["trksub"] for c in singleton_candidates]
    # The summary convention has one row per distinct tracklet. If names are
    # repeated, do not guess: retain those blocks as clusters.
    if len(candidate_names) == len(set(candidate_names)):
        summary_ids = {id(c) for c in singleton_candidates}
        explicit_footer_rows.extend(
            c["observations"][0] for c in singleton_candidates
        )
        clusters = [c for c in clusters if id(c) not in summary_ids]

    return clusters, explicit_footer_rows


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: cannot read JSON {path.name}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"WARNING: JSON root is not an object: {path.name}", file=sys.stderr)
        return None
    return data


def build_link_map(data: dict | None, json_name: str) -> dict[frozenset, list[tuple[str, dict]]]:
    """Map a trksubs signature to its original link key/value."""
    result: dict[frozenset, list[tuple[str, dict]]] = {}
    if not data:
        return result
    links = data.get("links", {})
    if not isinstance(links, dict):
        print(f"WARNING: 'links' is not an object in {json_name}", file=sys.stderr)
        return result
    for link_key, link_value in links.items():
        if not isinstance(link_value, dict):
            continue
        signature = signature_from_link(link_value)
        if signature is None:
            print(f"WARNING: invalid trksubs in {json_name}:{link_key}", file=sys.stderr)
            continue
        result.setdefault(signature, []).append((link_key, link_value))
    return result


def still_in_itf(source: LocalMPC80Source, rec: dict) -> bool:
    """Check the exact first OBS80 record against indexed observations."""
    row = source.con.execute(
        """SELECT 1
             FROM observations
            WHERE trksub = ?
              AND stn = ?
              AND epoch_sec BETWEEN ? AND ?
              AND ABS(ra - ?) < 0.000001
              AND ABS(dec - ?) < 0.000001
            LIMIT 1""",
        (
            rec["trksub"], rec["stn"],
            rec["epoch_sec"] - 0.01, rec["epoch_sec"] + 0.01,
            rec["ra"], rec["dec"],
        ),
    ).fetchone()
    return row is not None


def write_cluster_txt(path: Path, kept: list[dict], summary_rows: list[tuple[str, dict]]) -> None:
    lines: list[str] = []
    for i, cluster in enumerate(kept):
        if i:
            lines.extend(["", SEPARATOR, "", SEPARATOR, ""])
        lines.append(cluster["cluster_line"])
        if cluster["astrom_line"]:
            lines.append(cluster["astrom_line"])
        if cluster["count_line"]:
            lines.append(cluster["count_line"])
        else:
            lines.append(f"Observations: {len(cluster['observations'])}")
        lines.append("")
        lines.extend(raw_line for raw_line, _rec in cluster["observations"])

    lines.extend(["", SEPARATOR, "", "# First observation of each kept cluster"])
    if summary_rows:
        # These are the one-row extracts deliberately removed from cluster
        # classification. Preserve every extracted row at the end of the TXT,
        # regardless of whether its parent cluster passed the ITF test.
        written = set()
        for raw, rec in summary_rows:
            key = (rec["trksub"], rec["stn"], round(rec["epoch_sec"], 2))
            if key not in written:
                lines.append(raw)
                written.add(key)
    else:
        for cluster in kept:
            lines.append(cluster["observations"][0][0])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect clusters whose first observation remains in the local MPC80 ITF index."
    )
    parser.add_argument("--input-dir", required=True,
                        help="Directory containing cluster TXT files; same-stem JSON files are optional")
    parser.add_argument("--output-dir", default="data/output/remaining_itf_clusters",
                        help="Output directory (default: data/output/remaining_itf_clusters)")
    parser.add_argument("--itf", default="data/input/itf.txt",
                        help="Source MPC80 ITF file (default: data/input/itf.txt)")
    parser.add_argument("--index", default="data/cache/local_itf_index.sqlite",
                        help="SQLite index path (default: data/cache/local_itf_index.sqlite)")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="Force rebuilding the local SQLite index")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not input_dir.is_dir():
        parser.error(f"Input directory does not exist: {input_dir}")

    txt_files = sorted(p for p in input_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == ".txt")
    if not txt_files:
        parser.error(f"No .txt cluster files found in: {input_dir}")

    # LocalMPC80Source checks the ITF path, size, and mtime_ns and rebuilds
    # automatically when the source signature differs from the SQLite metadata.
    source = LocalMPC80Source(
        args.itf, args.index, rebuild=args.rebuild_index, log=print
    )

    all_kept: list[dict] = []
    output_links: dict[str, dict] = {}
    output_header = None
    total_clusters = checked_clusters = remaining_clusters = matched_json = 0
    unmatched_json_clusters = 0
    missing_json_files = 0
    link_number = 0
    all_summary_rows: list[tuple[str, dict]] = []

    try:
        for txt_path in txt_files:
            clusters, summary_rows = read_cluster_file(txt_path)
            all_summary_rows.extend(summary_rows)
            if not clusters:
                continue
            total_clusters += len(clusters)

            # A same-stem JSON is optional. Its absence must never prevent
            # classifying the TXT clusters or writing retained clusters to TXT.
            json_path = txt_path.with_suffix(".json")
            json_data = load_json(json_path)
            if json_data is None:
                if not json_path.is_file():
                    missing_json_files += 1
                    print(
                        f"INFO: no same-stem JSON for {txt_path.name}; "
                        "will classify and output retained clusters from TXT only",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"WARNING: unusable JSON {json_path.name}; "
                        "will classify and output retained clusters from TXT only",
                        file=sys.stderr,
                    )
            else:
                header = json_data.get("header")
                if output_header is None and isinstance(header, dict):
                    output_header = header
                elif isinstance(header, dict) and output_header is not None and header != output_header:
                    print(f"WARNING: header differs in {json_path.name}; keeping the first header", file=sys.stderr)

            link_map = build_link_map(json_data, json_path.name)

            for cluster in clusters:
                checked_clusters += 1
                first_rec = cluster["observations"][0][1]
                if not still_in_itf(source, first_rec):
                    continue

                remaining_clusters += 1
                all_kept.append(cluster)

                signature = signature_from_cluster(cluster)
                candidates = link_map.get(signature, [])
                if len(candidates) == 1:
                    _old_key, link_value = candidates[0]
                    link_number += 1
                    output_links[f"link_{link_number}"] = link_value
                    matched_json += 1
                elif len(candidates) > 1:
                    unmatched_json_clusters += 1
                    print(
                        f"WARNING: ambiguous JSON link match for {txt_path.name} / Cluster {cluster['number']}; "
                        "keeping the cluster in TXT only",
                        file=sys.stderr,
                    )
                else:
                    unmatched_json_clusters += 1
                    print(
                        f"WARNING: no matching JSON link for {txt_path.name} / Cluster {cluster['number']}; "
                        "keeping the cluster in TXT only",
                        file=sys.stderr,
                    )

        output_dir.mkdir(parents=True, exist_ok=True)
        txt_out = output_dir / "remaining_clusters.txt"
        json_out = output_dir / "remaining_clusters.json"
        write_cluster_txt(txt_out, all_kept, all_summary_rows)

        # Preserve the top-level JSON shape and header from the first usable input.
        output_json = {"header": output_header if output_header is not None else {},
                       "links": output_links}
        json_out.write_text(
            json.dumps(output_json, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print("\nFinished")
        print(f"  Input TXT files       : {len(txt_files)}")
        print(f"  Clusters examined     : {checked_clusters:,}")
        print(f"  Clusters still in ITF : {remaining_clusters:,}")
        print(f"  JSON links collected  : {matched_json:,}")
        print(f"  TXT-only clusters     : {unmatched_json_clusters:,}")
        print(f"  TXT files without JSON: {missing_json_files:,}")
        print(f"  TXT output            : {txt_out}")
        print(f"  JSON output           : {json_out}")
    finally:
        source.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
