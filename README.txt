PyRoOrb local-ITF production scripts
====================================

Overview
--------
These scripts use PyRoOrb's native ITF search pipeline with a local MPC 80-column
ITF text file. The local file is indexed into a derived SQLite cache. No
PostgreSQL/SBN connection is made. MPC submission is always disabled.

Files
-----
scripts/local_itf_source.py
    Local MPC80 source adapter and SQLite index. Also retrieves all observations
    for a supplied ITF tracklet/subtrack name from the local index.

scripts/designation_list.py
    Shared parser for mixed packed/unpacked MPC designations with annotations.
    Supports UTF-8, UTF-8-BOM, UTF-16, and CP932; full-width normalization;
    trailing '*' list markers; comments; duplicate removal; and PyRoOrb's own
    packed-to-unpacked designation conversion.

scripts/search_designation_list.py
    PRODUCTION batch runner for known provisional designations. Reads the whole
    list, deduplicates it, and searches every target sequentially in source order.
    Each target is fetched from the MPC through PyRoOrb before local-ITF search.
    The predicted-magnitude gate is explicitly disabled (+infinity).

scripts/unidentified_inputs.py
    Input readers for HelioLinC cluster OBS80 files and ITF tracklet-name lists.

scripts/search_unidentified.py
    Separate runner for unidentified seeds. It accepts one or more HelioLinC
    cluster files and/or tracklet-name lists. Tracklet-list entries can be:

      H300000 2d
      H300010=H300020
      H300010 = H300020
      H300010= H300020
      H300010 =H300020

    ``2d`` records the expected number of UTC observing nights for that trksub.
    The script retrieves every indexed OBS80 observation carrying that trksub.
    An equality pair retrieves both trksubs from the local ITF and combines their
    observations as one seed. Spacing around '=' is immaterial. If the listed
    night count differs from the retrieved count, the discrepancy is warned
    about but the retrieved observations are still searched as-is.

scripts/test_designation_list.py
scripts/test_unidentified_inputs.py
    Parser regression tests.

Expected layout
---------------
PyRoOrb/
  data/
    input/
      itf.txt
      designations.txt
      heliolinc_clusters.txt
      tracklet_names.txt
    cache/
      local_itf_index.sqlite
    output/
      designations/
      unidentified/
  scripts/
    ...

Setup
-----
Run from the PyRoOrb project directory with its virtual environment active:

  cd ~/PyRoOrb
  source .venv/bin/activate

Known provisional designations: full batch
-------------------------------------------
  python scripts/search_designation_list.py \
      --itf data/input/itf.txt \
      --list-file data/input/designations.txt

This processes every unique designation from top to bottom. To resume from a
known list index or run a bounded segment, use --start-index and --limit.
The JSONL summary is appended after each target, so completed rows remain
available if a later target or the process fails. Individual fetch/search
errors are recorded and the batch continues to the next designation.

Unidentified HelioLinC clusters and tracklet pairs
--------------------------------------------------
  python scripts/search_unidentified.py \
      --itf data/input/itf.txt \
      --cluster-file data/input/heliolinc_clusters.txt \
      --tracklet-list data/input/tracklet_names.txt

Both input options may be repeated. If both are supplied, clusters are queued
first, followed by tracklet-list entries. A cluster file may contain multiple
``Cluster N`` blocks in the usual HelioLinC ``finalout_itfMPC80.txt`` layout;
without cluster headers, all OBS80 rows in that file are treated as one seed.

Magnitude handling
------------------
Both runners set ``ItfConfig.mag_limit`` explicitly to +infinity. This disables
the predicted-V-magnitude corridor gate and the per-object default magnitude
floor. It does not disable geometric, uncertainty, motion, candidate-budget,
trial-fit, or linkage-acceptance criteria. The local source does not filter
tracklets by the measured magnitude column.

Outputs
-------
Per-seed output files are written only when PyRoOrb returns the corresponding
artifact: linked ITF OBS80, combined candidate OBS80, and linkage JSON. A
linkage file is therefore not expected when no linkage is returned. Every input
is recorded in ``search_summary.jsonl`` with its verdict, reason, telemetry,
artifact paths, or error.

The runners are dry-run only. A LINKED verdict is a search result, not an
automatic MPC submission; review the output before any separate submission.
