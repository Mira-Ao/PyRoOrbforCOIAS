#!/usr/bin/env python3
"""Regression tests for mixed MPC designation-list parsing."""
from pathlib import Path
import tempfile
import unittest

from pyroorb.obs_sources import ensure_unpacked
from designation_list import (
    extract_from_line,
    parse_designation_list,
    parse_single_designation,
)


class DesignationListTests(unittest.TestCase):
    def test_packed_and_unpacked_forms(self):
        cases = {
            "K24T47G*": "2024 TG47",
            "2024 TG47": "2024 TG47",
            "CK26B030*": "C/2026 B3",
            "PK26B03a": "P/2026 B3-A",
            "SK21J070": "S/2021 J 7",
            "00433": "433",
            "D4340": "134340",
            "PLS2040": "2040 P-L",
            "T1S2040": "2040 T-1",
            "73P-C": "73P-C",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(
                    parse_single_designation(source, ensure_unpacked), expected
                )

    def test_annotation_and_full_width_characters(self):
        self.assertEqual(
            parse_single_designation("候補: Ｋ２４Ｔ４７Ｇ＊ (要確認)", ensure_unpacked),
            "2024 TG47",
        )

    def test_first_designation_wins_when_notes_quote_another(self):
        self.assertEqual(
            parse_single_designation(
                "K24T47G* note: possibly related to 2025 AB", ensure_unpacked
            ),
            "2024 TG47",
        )

    def test_list_deduplicates_packed_and_unpacked(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "targets.txt"
            p.write_text(
                "K24T47G* candidate A\n"
                "2024 TG47 (same object)\n"
                "2025 AB memo\n"
                "# comment only\n"
                "20261106 is a date, not an object\n",
                encoding="utf-8",
            )
            names, stats = parse_designation_list(p, ensure_unpacked)
        self.assertEqual(names, ["2024 TG47", "2025 AB"])
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["ignored_lines"], 2)

    def test_utf16_list(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "targets.txt"
            p.write_text("K24T47G* memo\n", encoding="utf-16")
            names, _ = parse_designation_list(p, ensure_unpacked)
        self.assertEqual(names, ["2024 TG47"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
