#!/usr/bin/env python3
"""Readers for HelioLinC cluster files and ITF trksub-name lists."""
from __future__ import annotations

import re
from pathlib import Path

from designation_list import _decode_list_file
from local_itf_source import _parse_obs80

_TRACKLET_TOKEN = r"([A-Za-z0-9~_-]{1,12}\*?)"
_PAIR_RE = re.compile(rf"^\s*{_TRACKLET_TOKEN}\s*=\s*{_TRACKLET_TOKEN}(?:\s+.*)?$", re.IGNORECASE)
_MULTI_NIGHT_RE = re.compile(
    rf"^\s*{_TRACKLET_TOKEN}\s*[,;:]?\s+(\d+)\s*d(?:\s*ays?)?(?:\s+.*)?$",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(rf"^\s*{_TRACKLET_TOKEN}(?:\s+.*)?$")
_CLUSTER_RE = re.compile(r"^\s*Cluster\s+(.+?)\s*$", re.IGNORECASE)


def _clean_tracklet_name(value: str) -> str:
    return value.strip().rstrip("*").strip()


def parse_tracklet_list(path: Path):
    """Parse single/multi-night trksubs and equality pairs, preserving order.

    Accepted examples include ``H300000 2d``, ``H300000 2 d``,
    ``H300010=H300020`` and any spacing around the equality sign.
    Inline #, ! and ; notes are ignored.
    """
    entries = []
    seen = set()
    stats = {"lines": 0, "ignored": 0, "duplicates": 0}
    for raw in _decode_list_file(path).splitlines():
        stats["lines"] += 1
        line = raw.strip()
        if not line or line.startswith(("#", "!", ";")):
            stats["ignored"] += 1
            continue
        # Treat these as inline comment delimiters. They are not part of MPC
        # trksub identifiers and are common in manually annotated lists.
        cut = [p for p in (line.find("#"), line.find("!"), line.find(";")) if p >= 0]
        if cut:
            line = line[:min(cut)].strip()
        if not line:
            stats["ignored"] += 1
            continue

        pair = _PAIR_RE.match(line)
        if "=" in line and not pair:
            stats["ignored"] += 1
            continue
        if pair:
            names = (_clean_tracklet_name(pair.group(1)),
                     _clean_tracklet_name(pair.group(2)))
            if not all(names) or names[0] == names[1]:
                stats["ignored"] += 1
                continue
            key = ("pair", *sorted(names))
            entry = {"kind": "pair", "names": list(names), "expected_nights": None,
                     "source_line": raw}
        else:
            multi = _MULTI_NIGHT_RE.match(line)
            if multi:
                name = _clean_tracklet_name(multi.group(1))
                nights = int(multi.group(2))
                if not name or nights < 1:
                    stats["ignored"] += 1
                    continue
                key = ("tracklet", name)
                entry = {"kind": "tracklet", "names": [name],
                         "expected_nights": nights, "source_line": raw}
            else:
                single = _SINGLE_RE.match(line)
                if not single:
                    stats["ignored"] += 1
                    continue
                name = _clean_tracklet_name(single.group(1))
                if not name:
                    stats["ignored"] += 1
                    continue
                key = ("tracklet", name)
                entry = {"kind": "tracklet", "names": [name],
                         "expected_nights": None, "source_line": raw}

        if key in seen:
            stats["duplicates"] += 1
            continue
        seen.add(key)
        entries.append(entry)
    return entries, stats


def read_heliolinc_clusters(path: Path):
    """Read Cluster N / astromRMS / Observations blocks containing MPC80 rows.

    If no Cluster header is present, all OBS80 rows in the file form one cluster.
    Satellite/roving companion lines are retained with their primary records.
    """
    text = _decode_list_file(path)
    clusters = []
    current_label = None
    current_lines = []
    saw_header = False
    want_companion = False

    def flush():
        nonlocal current_lines, current_label
        if current_lines:
            clusters.append({"label": current_label or f"cluster_{len(clusters)+1:05d}",
                             "obs80": "\n".join(current_lines) + "\n",
                             "observation_lines": sum(
                                 1 for x in current_lines if len(x) >= 80 and x[14] not in "sv")})
        current_lines = []
        current_label = None

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        header = _CLUSTER_RE.match(line)
        if header:
            saw_header = True
            flush()
            current_label = f"cluster_{header.group(1).strip()}"
            want_companion = False
            continue
        if len(line) >= 160 and _parse_obs80(line[:80]) is not None:
            current_lines.extend((line[:80], line[80:160]))
            want_companion = False
            continue
        if _parse_obs80(line[:80]) is not None:
            current_lines.append(line[:80])
            want_companion = line[14] in "SV"
            continue
        if want_companion and len(line) >= 80 and line[14] in "sv":
            current_lines.append(line[:80])
        want_companion = False
    flush()

    # The no-header case is intentionally one input cluster, even if the file
    # has no explicit blank-line separators between observation rows.
    return clusters


def utc_night_count(obs80_text: str) -> int:
    nights = set()
    for raw in obs80_text.splitlines():
        line = raw[:80]
        if _parse_obs80(line) is None:
            continue
        try:
            nights.add((int(line[15:19]), int(line[20:22]), int(float(line[23:32]))))
        except (ValueError, IndexError):
            pass
    return len(nights)
