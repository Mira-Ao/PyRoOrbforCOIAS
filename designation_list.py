#!/usr/bin/env python3
"""Extract MPC object designations from mixed-format, annotation-heavy text lists."""
from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict

# MPC packed provisional designations (e.g. K24T47G), packed comet
# designations (e.g. CK26B030 / PK26B03a), and natural-satellite provisionals.
_PACKED_ASTEROID = re.compile(r"(?<![A-Za-z0-9_])([IJK_][0-9]{2}[A-Z][0-9A-Za-z][0-9][0-9A-Za-z])\*?(?![A-Za-z0-9])")
_PACKED_COMET = re.compile(r"(?<![A-Za-z0-9])([CPDXAI][IJK][0-9]{2}[A-Z][0-9A-Za-z][0-9][0-9A-Za-z])\*?(?![A-Za-z0-9])")
_PACKED_SATELLITE = re.compile(r"(?<![A-Za-z0-9])(S[IJK][0-9]{2}[JSUN][0-9A-Za-z][0-9]0)\*?(?![A-Za-z0-9])")
_PACKED_NUMBER = re.compile(r"(?<![A-Za-z0-9])((?:[0-9]{5}|[A-Z][0-9]{4}|~[0-9A-Za-z]{4}))\*?(?![A-Za-z0-9])")
_PACKED_SURVEY = re.compile(r"(?<![A-Za-z0-9])(PLS[0-9]{4}|T[123]S[0-9]{4})\*?(?![A-Za-z0-9])")
_PACKED_LONG_NUMBER_AT_START = re.compile(r"^\s*[\[(#]*\s*(0[0-9]{5,7})\b")
_PACKED_LONG_NUMBER_LABEL = re.compile(r"\b(?:designation|object|number|番号|仮符号|小惑星番号)\s*[:=#]?\s*([0-9]{6,8})\b", re.IGNORECASE)

# Human-readable forms. The first regex covers asteroid provisional
# designations such as '2024 TG47'; the second covers comet provisionals
# such as 'C/2024 A1' and fragments such as 'P/2026 B3-A'.
_UNPACKED_ASTEROID = re.compile(r"(?<![A-Za-z0-9])((?:18|19|20|21|22)[0-9]{2})\s+([A-HJ-Z][A-HJ-Z][0-9]*)(?![A-Za-z0-9])", re.IGNORECASE)
_UNPACKED_COMET = re.compile(r"(?<![A-Za-z0-9])([CPDXAI])\s*/\s*((?:18|19|20|21|22)[0-9]{2})\s+([A-HJ-Z][0-9]+)(?:\s*-\s*([A-Z]))?(?![A-Za-z0-9])", re.IGNORECASE)
_UNPACKED_SATELLITE = re.compile(r"(?<![A-Za-z0-9])S\s*/\s*((?:18|19|20|21|22)[0-9]{2})\s+([JSUN])\s+([0-9]+)(?![A-Za-z0-9])", re.IGNORECASE)
_NUMBERED_COMET = re.compile(r"(?<![A-Za-z0-9])([0-9]{1,7}[PDCXAI](?:-[A-Z])?)\*?(?![A-Za-z0-9])", re.IGNORECASE)
# Bare numbered asteroids are inherently ambiguous in free-form notes. They
# are accepted only at the beginning of a line, or after an explicit label.
_BARE_NUMBER_AT_START = re.compile(r"^\s*[\[(#]*\s*([0-9]{1,7})\b")
_BARE_NUMBER_LABEL = re.compile(r"\b(?:designation|object|number|番号|仮符号|小惑星番号)\s*[:=#]?\s*([0-9]{1,7})\b", re.IGNORECASE)


def _normalise_line(line: str) -> str:
    # NFKC handles full-width Latin letters, digits, slashes and punctuation.
    return unicodedata.normalize("NFKC", line).replace("\u3000", " ")


def extract_from_line(line: str) -> list[str]:
    """Return candidate designation tokens from one annotation-bearing line.

    Strong syntactic forms are searched anywhere in the line. Bare numeric
    asteroid numbers are considered only at line start or after an explicit
    label, because arbitrary notes commonly contain unrelated numbers.
    A trailing '*' is treated as a list marker and is not passed to the MPC API.
    """
    s = _normalise_line(line)
    matches: list[tuple[int, str]] = []

    def add(rx, builder=lambda m: m.group(1)):
        for m in rx.finditer(s):
            matches.append((m.start(), builder(m)))

    add(_PACKED_COMET)
    add(_PACKED_SATELLITE)
    add(_PACKED_ASTEROID)
    add(_PACKED_NUMBER)
    add(_PACKED_SURVEY)

    def comet(m):
        frag = f"-{m.group(4).upper()}" if m.group(4) else ""
        return f"{m.group(1).upper()}/{m.group(2)} {m.group(3).upper()}{frag}"
    add(_UNPACKED_COMET, comet)

    add(_UNPACKED_SATELLITE,
        lambda m: f"S/{m.group(1)} {m.group(2).upper()} {m.group(3)}")
    add(_UNPACKED_ASTEROID,
        lambda m: f"{m.group(1)} {m.group(2).upper()}")
    add(_NUMBERED_COMET, lambda m: m.group(1).upper())

    if not matches:
        m = (_PACKED_LONG_NUMBER_AT_START.search(s)
             or _PACKED_LONG_NUMBER_LABEL.search(s)
             or _BARE_NUMBER_AT_START.search(s)
             or _BARE_NUMBER_LABEL.search(s))
        if m:
            matches.append((m.start(), m.group(1)))

    # Sort by text position, then deduplicate without changing source order.
    out: list[str] = []
    seen = set()
    for _, value in sorted(matches, key=lambda item: item[0]):
        value = value.strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


def _decode_list_file(path):
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    # UTF-16 files without a BOM often contain many NUL bytes in the ASCII
    # half of each code unit. Detect this before attempting UTF-8 replacement.
    if raw and raw.count(b"\x00") / len(raw) > 0.10:
        even_nuls = raw[0::2].count(0)
        odd_nuls = raw[1::2].count(0)
        encoding = "utf-16-le" if odd_nuls >= even_nuls else "utf-16-be"
        return raw.decode(encoding, errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp932")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def parse_designation_list(path, ensure_unpacked):
    """Read a text list, extract designations, normalize them, and deduplicate.

    Returns (designations, stats). One designation is selected per source line;
    if notes contain multiple candidates, the first textual match is used and
    the row is counted as ambiguous. `ensure_unpacked` must be PyRoOrb's own
    helper so MPC packing rules remain centralized in PyRoOrb.
    """
    ordered: OrderedDict[str, str] = OrderedDict()
    stats = {"lines": 0, "matched_lines": 0, "ignored_lines": 0,
             "multi_match_lines": 0, "duplicates": 0}

    for raw in _decode_list_file(path).splitlines():
        stats["lines"] += 1
        line = raw.strip()
        if not line or line.startswith(("#", "!", ";")):
            stats["ignored_lines"] += 1
            continue
        candidates = extract_from_line(line)
        if not candidates:
            stats["ignored_lines"] += 1
            continue
        stats["matched_lines"] += 1
        if len(candidates) > 1:
            stats["multi_match_lines"] += 1
        # A source row is expected to describe one target. If notes quote
        # additional designations, use the first one and report the row as
        # ambiguous rather than silently adding every mentioned object.
        candidate = candidates[0].rstrip("*").strip()
        normalized = _to_api_designation(candidate, ensure_unpacked)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in ordered:
            stats["duplicates"] += 1
        else:
            ordered[key] = normalized

    return list(ordered.values()), stats


def parse_single_designation(value: str, ensure_unpacked) -> str:
    """Apply the same annotation extraction to --designation input."""
    candidates = extract_from_line(value)
    if not candidates:
        raise ValueError(
            "--designation contains no recognizable MPC designation: "
            f"{value!r}"
        )
    # Same policy as list rows: the first designation in the text is the target.
    return _to_api_designation(candidates[0].rstrip("*").strip(), ensure_unpacked)


def _to_api_designation(candidate: str, ensure_unpacked) -> str:
    """Convert recognized packed MPC tokens to API-readable designations."""
    token = candidate.strip().rstrip("*").strip()
    # PyRoOrb's ensure_unpacked() handles numbered, asteroid-provisional,
    # comet-provisional and satellite forms. Its current shape guard does not
    # include the MPC survey packings, so route those through the same native
    # packing module directly.
    if _PACKED_SURVEY.fullmatch(token):
        from pyroorb import packing
        unpacked = packing.unpack(token)
        if unpacked:
            return str(unpacked).strip()
    return str(ensure_unpacked(token)).strip()
