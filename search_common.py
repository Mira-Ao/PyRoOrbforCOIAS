#!/usr/bin/env python3
"""Shared production runner for PyRoOrb searches against a local MPC80 ITF."""
from __future__ import annotations

import json
import re
from pathlib import Path

from local_itf_source import LocalMPC80Source


def safe_stem(value: str, max_length: int = 72) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._-")
    return (stem or "target")[:max_length]


def open_local_source(args, log=print):
    from pyroorb.itf.config import ItfConfig

    cfg = ItfConfig(candidate_path="index", ranking_mode="certainty", submit=False)
    # Explicit +infinity disables the predicted-magnitude corridor gate and
    # prevents the per-object default magnitude floor from being applied.
    cfg.set_mag_limit(float("inf"))
    cfg.submit = False
    source = LocalMPC80Source(
        args.itf, args.sqlite_index, cfg=cfg,
        rebuild=args.rebuild_index, log=log,
    )
    return source, cfg


def execute_search(source, cfg, *, output_dir: Path, label: str,
                   designations=None, seed_obs80=None, primary_desigs=None,
                   verbose=True, trace=None):
    """Run one native itf_search call and persist every artifact it returns."""
    from pyroorb.itf.search import itf_search

    output_dir.mkdir(parents=True, exist_ok=True)
    result = itf_search(
        source,
        designations=designations,
        seed_obs80=seed_obs80,
        primary_desigs=primary_desigs,
        cfg=cfg,
        do_submit=False,
        verbose=verbose,
        log=print,
        trace=trace,
    )

    stem = safe_stem(label)
    files = {}
    if result.itf_obs80:
        path = output_dir / f"{stem}_linked_itf_obs80.txt"
        path.write_text(result.itf_obs80, encoding="ascii", errors="replace")
        files["linked_itf_obs80"] = str(path)
    if result.combined_obs80:
        path = output_dir / f"{stem}_combined_candidate_obs80.txt"
        path.write_text(result.combined_obs80, encoding="ascii", errors="replace")
        files["combined_obs80"] = str(path)
    if result.linkage:
        path = output_dir / f"{stem}_linkage.json"
        path.write_text(
            json.dumps(result.linkage, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        files["linkage"] = str(path)

    summary = {
        "label": label,
        "verdict": str(result.verdict),
        "reason": result.reason,
        "telemetry": result.telemetry,
        "files": files,
    }
    return result, summary


def append_jsonl(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        fh.flush()
