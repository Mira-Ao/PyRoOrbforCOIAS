#!/usr/bin/env python3
"""Regression tests for unidentified tracklet-list parsing."""
from pathlib import Path
import tempfile
import unittest

from unidentified_inputs import parse_tracklet_list, read_heliolinc_clusters, utc_night_count


class TrackletListTests(unittest.TestCase):
    def test_multinight_and_pair_spacing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tracklets.txt"
            path.write_text(
                "H300000 2d\n"
                "H300010=H300020\n"
                "H300030 = H300040\n"
                "H300050= H300060\n"
                "H300070 =H300080\n"
                "H300090 2 d memo\n",
                encoding="utf-8",
            )
            entries, stats = parse_tracklet_list(path)
        self.assertEqual(entries[0]["names"], ["H300000"])
        self.assertEqual(entries[0]["expected_nights"], 2)
        self.assertEqual(entries[1]["names"], ["H300010", "H300020"])
        self.assertEqual(entries[2]["names"], ["H300030", "H300040"])
        self.assertEqual(entries[3]["names"], ["H300050", "H300060"])
        self.assertEqual(entries[4]["names"], ["H300070", "H300080"])
        self.assertEqual(entries[5]["expected_nights"], 2)
        self.assertEqual(stats["ignored"], 0)

    def test_comments_duplicates_and_bad_equality(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tracklets.txt"
            path.write_text(
                "H300000 2d # note\n"
                "H300000 2d\n"
                "H300010 = H300020\n"
                "H300020=H300010\n"
                "H300030 =\n"
                "! comment\n",
                encoding="utf-8",
            )
            entries, stats = parse_tracklet_list(path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(stats["duplicates"], 2)
        self.assertEqual(stats["ignored"], 2)

    def test_heliolinc_cluster_blocks(self):
        def obs(name, day):
            c = [" "] * 80
            c[:12] = list(name.ljust(12))
            c[14] = "C"
            c[15:19] = list("2024")
            c[20:22] = list("01")
            c[23:32] = list(f"{day:09.6f}")
            c[32:34] = list("12")
            c[35:37] = list("34")
            c[38:44] = list("56.78")
            c[44] = "+"
            c[45:47] = list("12")
            c[48:50] = list("34")
            c[51:56] = list("56.7")
            c[65:70] = list("20.0 ")
            c[70] = "R"
            c[77:80] = list("W84")
            return "".join(c)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "clusters.txt"
            path.write_text(
                "Cluster 1\nastromRMS: 0.2\nObservations:\n"
                + obs("H300000", 1.0) + "\n" + obs("H300000", 2.0) + "\n"
                + "Cluster 2\nObservations:\n" + obs("H300001", 3.0) + "\n",
                encoding="ascii",
            )
            clusters = read_heliolinc_clusters(path)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["observation_lines"], 2)
        self.assertEqual(utc_night_count(clusters[0]["obs80"]), 2)
        self.assertEqual(clusters[1]["observation_lines"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
