PyRoOrb local-ITF one-object test
=================================

Files
-----
scripts/local_itf_source.py
    Reads a local MPC 80-column ITF text file and builds a local SQLite index.
    This is NOT a PostgreSQL/SBN replica and makes no network/database connection.

scripts/test_itf_search_local.py
    Fetches the seed observations through PyRoOrb's own MPC observation-fetch
    path, fits the seed, searches the local index with PyRoOrb's native itf_search
    logic, and writes candidate OBS80 files. Submission is disabled.

scripts/designation_list.py
    Extracts one MPC designation per line from mixed packed/unpacked lists with
    annotations, removes a trailing '*' list marker, normalizes packed forms
    with PyRoOrb's own designation converter, and removes duplicates.

scripts/test_designation_list.py
    Regression tests for packed/unpacked designation parsing.

Expected project layout
-----------------------
PyRoOrb/
  data/
    input/
      ITF.txt                 (your local ITF file; change path if needed)
      designations.txt        (mixed packed/unpacked designations; notes allowed)
    cache/
    output/
  scripts/
    local_itf_source.py
    test_itf_search_local.py

Run
---
  cd ~/PyRoOrb
  source .venv/bin/activate
  python scripts/test_itf_search_local.py --itf data/input/ITF.txt \
      --list-file data/input/designations.txt --index 0

Test one named object directly:
  python scripts/test_itf_search_local.py --itf data/input/ITF.txt \
      --designation '2023 AB'

Designation-list parsing
-----------------------
The list file may contain packed and unpacked MPC designations mixed together,
with notes before or after the designation. Examples accepted include:

  K24T47G*                     -> 2024 TG47
  2024 TG47 (candidate A)       -> 2024 TG47
  CK26B030*                    -> C/2026 B3
  PK26B03a                     -> P/2026 B3-A
  SK21J070                     -> S/2021 J 7
  00433* (numbered object)     -> 433
  D4340 (numbered object)      -> 134340
  PLS2040                      -> 2040 P-L

A trailing '*' is removed as a list marker. Full-width Latin letters/digits
are normalized. UTF-8, UTF-8 with BOM, UTF-16 (with or without BOM), and CP932
are supported. Blank lines and lines beginning with #, !, or ; are ignored.
Duplicate designations are removed after normalization, so a packed and an
unpacked spelling of the same object are treated as one target.

If a line contains more than one recognizable designation, the first one in
text order is selected and the count of such lines is printed. This avoids
mistaking designations merely mentioned in a note for additional targets.
Bare numeric asteroid numbers are accepted at the beginning of a line or
following an explicit label such as 'object:' or 'designation:'. A date or an
unrelated number elsewhere in a note is not treated as a target.

`--index` refers to the zero-based index in the extracted, deduplicated list,
not the original physical line number. For example, `--index 0` selects the
first unique designation found.

Run parser regression tests with:
  python scripts/test_designation_list.py

Magnitude limit
---------------
The default in this test script is infinity, which disables PyRoOrb's predicted-
magnitude corridor gate. To use a finite limit of 28 mag:
  python scripts/test_itf_search_local.py --itf data/input/ITF.txt \
      --designation '2023 AB' --mag-limit 28

The magnitude gate applies to the orbit's predicted V magnitude when creating
search windows. It is not a cut on the measured magnitude column of individual
ITF tracklets. The local source itself does not reject tracklets based on their
measured magnitude. Setting --mag-limit inf therefore keeps the corridor gate
from excluding faint epochs; it does not remove other geometric, uncertainty,
motion, ranking, candidate-budget, or linkage-acceptance rules.

Index behavior
--------------
The first run parses the ITF file and builds data/cache/local_itf_index.sqlite.
Later runs reuse it if the source file path, size, and modification timestamp
are unchanged. Use --rebuild-index to force a rebuild. The original ITF is never
modified. The SQLite index may be larger than the original text file.

Important limitations
---------------------
- The local index pairs MPC satellite/roving primary records (S/V) with their
  following s/v companion line and preserves them as a 160-character OBS80 record.
  Standalone companion lines and non-optical records are skipped.
- The local source groups records by packed trksub + observatory code and splits
  at gaps greater than 12 hours, matching PyRoOrb's current run-length grouping.
- This is an initial local-file adapter for testing, not a replacement for the
  maintained PostgreSQL tracklet index. Its completeness/performance should be
  validated against a known set of MPC-linked objects before batch use.
- `LINKED` and `POSSIBLE` are PyRoOrb's search verdicts. The script never sends
  anything to the MPC. Manually inspect the generated observations and linkage.
