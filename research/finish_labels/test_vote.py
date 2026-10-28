"""Vote and shader mapping — no network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from labels import CHECK_PAIRS, SHADER_EXPECT, mismatches, parse_label, tuning_advice, vote_labels


class VoteTests(unittest.TestCase):
    def test_unknown_when_too_few(self) -> None:
        rows = [
            parse_label({"spread": "wide", "sheen": "dull", "particles": "none"}, "blush", "matte"),
        ]
        self.assertEqual(vote_labels(rows)[("blush", "matte")]["spread"], "unknown")

    def test_majority_keeps_wide_blush_matte(self) -> None:
        rows = [
            parse_label({"spread": "wide", "sheen": "dull", "particles": "none"}, "blush", "matte"),
            parse_label({"spread": "wide", "sheen": "dull", "particles": "none"}, "blush", "matte"),
            parse_label({"spread": "tight", "sheen": "unknown", "particles": "none"}, "blush", "matte"),
        ]
        got = vote_labels(rows)[("blush", "matte")]
        self.assertEqual(got["spread"], "wide")
        self.assertEqual(got["sheen"], "dull")

    def test_matching_vote_does_not_touch_tuning(self) -> None:
        rows = []
        for zone, texture in CHECK_PAIRS:
            expect = SHADER_EXPECT[(zone, texture)]
            for _ in range(3):
                rows.append(parse_label(expect, zone, texture))
        found = mismatches(vote_labels(rows))
        self.assertEqual(found, [])
        self.assertEqual(tuning_advice(found), [])

    def test_disagreeing_blush_spread_asks_for_blushpow(self) -> None:
        rows = [
            parse_label({"spread": "tight", "sheen": "dull", "particles": "none"}, "blush", "matte"),
            parse_label({"spread": "tight", "sheen": "dull", "particles": "none"}, "blush", "matte"),
            parse_label({"spread": "tight", "sheen": "dull", "particles": "none"}, "blush", "matte"),
        ]
        found = mismatches(vote_labels(rows))
        self.assertEqual(found[0]["axis"], "spread")
        self.assertTrue(any("blushPow" in line for line in tuning_advice(found)))

    def test_rejects_hex_and_junk_choices(self) -> None:
        got = parse_label({"spread": "#FF0000", "sheen": "shiny", "particles": "glitter"}, "blush", "matte")
        self.assertEqual(got["spread"], "unknown")
        self.assertEqual(got["sheen"], "unknown")
        self.assertEqual(got["particles"], "unknown")


if __name__ == "__main__":
    unittest.main()
