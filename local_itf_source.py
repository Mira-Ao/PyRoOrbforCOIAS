"""SQLite-backed local MPC80 candidate source for PyRoOrb's native ITF search.

This is a LOCAL, derived index. It does not connect to PostgreSQL/SBN and does not
modify the original ITF file. Tracklet geometry is computed with PyRoOrb's own
index feature code, then the native search's corridor predicates and trial-fit
logic are reused.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pyroorb.itf.candidates import (
    cap_rank_key, match_chi2, motion_bound_ok, tracklet_in_window,
    window_tolerances,
)
from pyroorb.itf.index import IndexConfig, compute_tracklet_features

BOX_PAD_DEG = 0.04
GROUP_GAP_SEC = 12 * 3600


def _parse_obs80(line: str):
    """Parse the astrometric fields needed for a tracklet feature from MPC80.

    Companion satellite/roving lines (s/v) and non-observation records are
    skipped. The original 80-column observation line is retained verbatim.
    """
    if len(line) < 80:
        return None
    try:
        # An ordinary optical observation has two decimal RA-hour digits here.
        if not line[32:34].strip().isdigit():
            return None
        year = int(line[15:19])
        month = int(line[20:22])
        day = float(line[23:32])
        if not (1.0 <= day < 32.0):
            return None
        base = datetime(year, month, 1, tzinfo=timezone.utc)
        when = base + timedelta(days=day - 1.0)

        rah = int(line[32:34])
        ram = int(line[35:37])
        ras = float(line[38:44])
        if not (0 <= rah < 24 and 0 <= ram < 60 and 0 <= ras < 60):
            return None
        ra = 15.0 * (rah + ram / 60.0 + ras / 3600.0)

        sign = line[44]
        if sign not in ("+", "-"):
            return None
        dd = int(line[45:47])
        dm = int(line[48:50])
        ds = float(line[51:56])
        if not (0 <= dd <= 90 and 0 <= dm < 60 and 0 <= ds < 60):
            return None
        if dd == 90 and (dm != 0 or ds != 0):
            return None
        dec = dd + dm / 60.0 + ds / 3600.0
        if sign == "-":
            dec = -dec

        trksub = line[:12].replace("*", "").strip()
        stn = line[77:80].strip()
        if not trksub or not stn:
            return None

        try:
            mag = float(line[65:70])
            if not math.isfinite(mag):
                mag = None
        except ValueError:
            mag = None
        band = line[70:71].strip() or None

        return {
            "epoch_sec": when.timestamp(),
            "ra": ra,
            "dec": dec,
            "mag": mag,
            "band": band,
            "trksub": trksub,
            "stn": stn,
            "obs80": line[:80],
        }
    except (ValueError, OverflowError, IndexError):
        return None


class LocalMPC80Source:
    """Candidate source implementing the interface consumed by itf_search()."""

    def __init__(self, itf_path, index_path, cfg=None, rebuild=False, log=print):
        self.itf_path = Path(itf_path).expanduser().resolve()
        self.index_path = Path(index_path).expanduser().resolve()
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.base = None
        self.trace = None
        self.last_sweep_skipped = 0
        self.last_sweep_cancelled = 0
        self.last_sweep_lowmem = 0
        self.index_cfg = IndexConfig()
        if cfg is None:
            from pyroorb.itf.config import ItfConfig
            cfg = ItfConfig(candidate_path="index", ranking_mode="certainty")
        self.cfg = cfg

        if not self.itf_path.is_file():
            raise FileNotFoundError(f"ITF file not found: {self.itf_path}")
        stat = self.itf_path.stat()
        signature = f"{self.itf_path}|{stat.st_size}|{stat.st_mtime_ns}"
        valid = False
        if self.index_path.exists() and not rebuild:
            try:
                with sqlite3.connect(self.index_path) as con:
                    row = con.execute(
                        "SELECT value FROM meta WHERE key='source_signature'"
                    ).fetchone()
                    valid = bool(row and row[0] == signature)
            except sqlite3.Error:
                valid = False
        if valid:
            log(f"Local ITF index: reusing {self.index_path}")
        else:
            log(f"Building local ITF index from {self.itf_path}")
            self._build(signature, log)

        self.con = sqlite3.connect(self.index_path)
        self.con.row_factory = sqlite3.Row

    def _build(self, signature, log):
        if self.index_path.exists():
            self.index_path.unlink()
        con = sqlite3.connect(self.index_path)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=OFF")
            con.execute("PRAGMA synchronous=OFF")
            con.execute("PRAGMA temp_store=MEMORY")
            con.execute("PRAGMA cache_size=-65536")
            con.executescript("""
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE raw_obs (
                    trksub TEXT NOT NULL, stn TEXT NOT NULL,
                    epoch_sec REAL NOT NULL, ra REAL NOT NULL, dec REAL NOT NULL,
                    mag REAL, band TEXT, obs80 TEXT NOT NULL
                );
                CREATE TABLE observations (
                    tracklet_id INTEGER NOT NULL, epoch_sec REAL NOT NULL,
                    ra REAL NOT NULL, dec REAL NOT NULL, mag REAL, band TEXT,
                    trksub TEXT NOT NULL, stn TEXT NOT NULL, obs80 TEXT NOT NULL
                );
                CREATE TABLE tracklets (
                    tracklet_id INTEGER PRIMARY KEY,
                    epoch_mid_sec REAL NOT NULL,
                    epoch_start_sec REAL NOT NULL,
                    epoch_end_sec REAL NOT NULL,
                    center_dec REAL NOT NULL,
                    feature_json TEXT NOT NULL
                );
            """)

            batch = []
            total = valid = 0
            with self.itf_path.open("r", encoding="ascii", errors="replace") as fh:
                pending_raw = None
                while True:
                    raw = pending_raw if pending_raw is not None else fh.readline()
                    pending_raw = None
                    if not raw:
                        break
                    total += 1
                    line = raw.rstrip("\r\n")
                    rec = _parse_obs80(line)
                    if rec is None:
                        continue

                    # MPC space-based / roving records carry a second 80-column
                    # line (s/v) immediately after the astrometric primary. Keep
                    # the pair together as the 160-character record expected by
                    # PyRoOrb's native OBS80 linkage fitter.
                    if line[14] in "SV":
                        companion_raw = fh.readline()
                        if companion_raw:
                            companion = companion_raw.rstrip("\r\n")
                            if (len(companion) >= 61
                                    and companion[:12] == line[:12]
                                    and companion[14] in "sv"):
                                total += 1
                                rec["obs80"] = line[:80] + companion[:80]
                            else:
                                pending_raw = companion_raw

                    valid += 1
                    batch.append((rec["trksub"], rec["stn"], rec["epoch_sec"],
                                  rec["ra"], rec["dec"], rec["mag"], rec["band"],
                                  rec["obs80"]))
                    if len(batch) >= 20000:
                        con.executemany("INSERT INTO raw_obs VALUES (?,?,?,?,?,?,?,?)", batch)
                        con.commit()
                        batch.clear()
            if batch:
                con.executemany("INSERT INTO raw_obs VALUES (?,?,?,?,?,?,?,?)", batch)
                con.commit()
            log(f"  Read {total:,} lines; {valid:,} valid optical observations")

            con.execute("CREATE INDEX raw_group ON raw_obs(trksub, stn, epoch_sec)")
            con.commit()

            cur = con.execute("""SELECT trksub, stn, epoch_sec, ra, dec, mag, band, obs80
                                  FROM raw_obs
                                  ORDER BY trksub, stn, epoch_sec""")
            current_key = None
            group = []
            tracklet_id = 0
            inserted_tracks = inserted_obs = 0

            def flush_group(rows):
                nonlocal tracklet_id, inserted_tracks, inserted_obs
                if len(rows) < 2:
                    return
                tracklet_id += 1
                feat_rows = [{
                    "es": r["epoch_sec"], "ra": r["ra"], "dec": r["dec"],
                    "rms_ra": None, "rms_dec": None, "mag": r["mag"],
                    "band": r["band"], "stn": r["stn"],
                    "trksub": r["trksub"], "provid": None,
                    "tracklet_id": tracklet_id,
                } for r in rows]
                feat = compute_tracklet_features(feat_rows, self.index_cfg)
                if feat is None:
                    return
                con.execute(
                    "INSERT INTO tracklets VALUES (?,?,?,?,?,?)",
                    (tracklet_id, feat["epoch_mid_sec"], feat["epoch_start_sec"],
                     feat["epoch_end_sec"], feat["center_dec"],
                     json.dumps(feat, separators=(",", ":"))),
                )
                con.executemany(
                    "INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)",
                    [(tracklet_id, r["epoch_sec"], r["ra"], r["dec"], r["mag"],
                      r["band"], r["trksub"], r["stn"], r["obs80"]) for r in rows],
                )
                inserted_tracks += 1
                inserted_obs += len(rows)

            for row in cur:
                key = (row["trksub"], row["stn"])
                rec = dict(row)
                if current_key is None:
                    current_key = key
                if key != current_key or (group and rec["epoch_sec"] - group[-1]["epoch_sec"] > GROUP_GAP_SEC):
                    flush_group(group)
                    group = []
                    current_key = key
                group.append(rec)
            flush_group(group)

            con.executescript("""
                DROP TABLE raw_obs;
                CREATE INDEX tracklet_epoch_dec ON tracklets(epoch_mid_sec, center_dec);
                CREATE INDEX observations_tracklet_epoch ON observations(tracklet_id, epoch_sec);
            """)
            con.execute("INSERT INTO meta VALUES ('source_signature', ?)", (signature,))
            con.execute("INSERT INTO meta VALUES ('tracklets', ?)", (str(inserted_tracks),))
            con.execute("INSERT INTO meta VALUES ('observations', ?)", (str(inserted_obs),))
            con.commit()
            log(f"  Indexed {inserted_tracks:,} tracklets / {inserted_obs:,} observations")
        finally:
            con.close()

    def sweep_candidates(self, windows, uncert_mult, extrawidth, want_ranking,
                         row_budget=None, prefilter=None):
        """Yield the same four-tuple as DbSource, but query the local SQLite index."""
        self.last_sweep_skipped = 0
        self.last_sweep_cancelled = 0
        self.last_sweep_lowmem = 0
        budget = self.cfg.sweep_row_budget if row_budget is None else row_budget
        rows_tested = 0

        for i, window in enumerate(windows):
            if budget and rows_tested >= budget:
                self.last_sweep_skipped = len(windows) - i
                return

            ra_tol, dec_tol = window_tolerances(window, uncert_mult, extrawidth)
            feature_rows = self.con.execute("""
                SELECT feature_json FROM tracklets
                WHERE epoch_mid_sec BETWEEN ? AND ?
                  AND center_dec BETWEEN ? AND ?
            """, (window.unix_start, window.unix_end,
                  window.min_dec - dec_tol - BOX_PAD_DEG,
                  window.max_dec + dec_tol + BOX_PAD_DEG)).fetchall()
            rows_tested += len(feature_rows)

            candidates = []
            for item in feature_rows:
                feat = json.loads(item["feature_json"])
                annotated = tracklet_in_window(feat, window, ra_tol, dec_tol)
                if annotated is None:
                    continue
                ok = motion_bound_ok(annotated, window, self.cfg)
                apply_prefilter = (self.cfg.prefilter_motion if prefilter is None
                                   else prefilter)
                if apply_prefilter and not ok:
                    continue
                annotated["_motion_bound_ok"] = ok
                candidates.append(annotated)

            n_in_corridor = len(candidates)
            cap = self.cfg.max_candidates_per_window
            if cap and n_in_corridor > cap:
                candidates.sort(key=lambda c: cap_rank_key(c, window))
                for rank, candidate in enumerate(candidates):
                    candidate["_cap_rank"] = rank
                candidates = candidates[:cap]
            for candidate in candidates:
                candidate["_n_in_corridor"] = n_in_corridor
                candidate.setdefault("_cap_rank", -1)
                candidate["_would_be_capped"] = False

            selected = [int(c["tracklet_id"]) for c in candidates]
            chi2_by_trkid = {}
            feats_by_trkid = {}
            for candidate in candidates:
                tid = int(candidate["tracklet_id"])
                feats_by_trkid[tid] = candidate
                if want_ranking:
                    chi2_by_trkid[tid] = match_chi2(candidate, window)[0]

            obs_rows = []
            for start in range(0, len(selected), 500):
                chunk = selected[start:start + 500]
                if not chunk:
                    continue
                marks = ",".join("?" for _ in chunk)
                found = self.con.execute(f"""
                    SELECT tracklet_id, epoch_sec, ra, dec, mag, band,
                           trksub, stn, obs80
                    FROM observations
                    WHERE tracklet_id IN ({marks})
                    ORDER BY epoch_sec, trksub, stn
                """, chunk).fetchall()
                for r in found:
                    tid = int(r["tracklet_id"])
                    obs_rows.append({
                        "trkid": tid,
                        "epoch_sec": r["epoch_sec"],
                        "ra": r["ra"], "dec": r["dec"],
                        "mag": r["mag"], "band": r["band"],
                        "trksub": r["trksub"], "stn": r["stn"],
                        "provid": None, "obs80": r["obs80"],
                    })
            obs_rows.sort(key=lambda r: (r["epoch_sec"], r["trksub"], r["stn"]))
            yield window, obs_rows, chi2_by_trkid, feats_by_trkid

    def observations_for_tracklet_names(self, names):
        """Return all indexed OBS80 records carrying any requested ITF trksub.

        A trksub can occur in multiple station/time groups (and therefore in
        multiple indexed tracklets). Querying by the original 12-column name
        deliberately gathers all of them, which is required for entries such
        as ``H300000 2d``. The original 80/160-column records are preserved.

        Returns ``(obs80_text, found_names, missing_names, record_count)``.
        """
        wanted = []
        seen = set()
        for name in names:
            value = str(name).strip().rstrip("*").strip()
            if value and value not in seen:
                wanted.append(value)
                seen.add(value)
        if not wanted:
            return "", [], [], 0

        found_rows = []
        found_names = set()
        for start in range(0, len(wanted), 400):
            chunk = wanted[start:start + 400]
            marks = ",".join("?" for _ in chunk)
            rows = self.con.execute(
                f"SELECT trksub, epoch_sec, obs80 FROM observations "
                f"WHERE trksub IN ({marks}) ORDER BY epoch_sec, trksub",
                chunk,
            ).fetchall()
            for row in rows:
                found_rows.append((row["epoch_sec"], row["trksub"], row["obs80"]))
                found_names.add(row["trksub"])

        # A single observation may be indexed more than once only if the source
        # itself repeats it under the same trksub. Preserve distinct MPC records
        # while preventing exact duplicate lines in the seed block.
        lines = []
        seen_lines = set()
        record_count = 0
        for _, _, blob in sorted(found_rows, key=lambda x: (x[0], x[1])):
            for line in str(blob).splitlines():
                if not line.strip() or line in seen_lines:
                    continue
                seen_lines.add(line)
                lines.append(line)
                # Companion s/v lines are part of the record, not a separate
                # optical observation. This count is informational only.
                if len(line) >= 80 and line[14] not in "sv":
                    record_count += 1
        missing = [name for name in wanted if name not in found_names]
        return "\n".join(lines) + ("\n" if lines else ""), sorted(found_names), missing, record_count

    def close(self):
        if getattr(self, "con", None) is not None:
            self.con.close()
            self.con = None
