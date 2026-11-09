"""Unit tests for charge_notifier.CompletionDetector.

Drives the state machine with synthetic frames (no real audio, no files). Run:
    python -m unittest test_charge_notifier
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import charge_notifier as cn

T0 = datetime.datetime(2026, 1, 1, 12, 0, 0)


def frames(seq):
    """seq: list of (offset_seconds, S, lifetime_Wh). Yields (when, S, fields)."""
    for off, S, L in seq:
        f = {"S": S}
        if L is not None:
            f["L"] = str(L)
        yield T0 + datetime.timedelta(seconds=off), S, f


def run(seq, confirm=30, gap=60, min_wh=100):
    fired = []
    det = cn.CompletionDetector(confirm, gap, min_wh, lambda when, wh: fired.append((when, wh)))
    for when, S, f in frames(seq):
        det.observe(when, S, f)
    return fired


class TestCompletionDetector(unittest.TestCase):
    def test_clean_session_fires_once_with_energy(self):
        # charge 0..600s gaining 10 kWh, then idle holding past the confirm window.
        seq = [(t, "2", 1000 + t * 15) for t in range(0, 601, 9)]
        seq += [(600 + t, "1", 10000 + 1000) for t in range(9, 120, 9)]
        fired = run(seq)
        self.assertEqual(len(fired), 1)
        when, wh = fired[0]
        self.assertEqual(when, T0 + datetime.timedelta(seconds=609))  # first S1 (last S2 at 594, +15s)
        self.assertGreater(wh, 9000)

    def test_zero_energy_blip_suppressed(self):
        # 6 seconds of S2 with no energy, then long idle -> not a real charge.
        seq = [(0, "1", 5000), (3, "2", 5000), (6, "2", 5000)]
        seq += [(6 + t, "1", 5000) for t in range(9, 120, 9)]
        self.assertEqual(run(seq), [])

    def test_small_real_topup_fires(self):
        # 0.3 kWh delivered -> above the 0.1 kWh default gate.
        seq = [(t, "2", 2000 + t * 5) for t in range(0, 61, 9)]  # ~0.3 kWh over ~60s
        seq += [(60 + t, "1", 2300) for t in range(9, 120, 9)]
        self.assertEqual(len(run(seq)), 1)

    def test_starting_idle_never_fires(self):
        # Already plugged-idle at startup, never charged -> silent.
        seq = [(t, "1", 7000) for t in range(0, 200, 9)]
        self.assertEqual(run(seq), [])

    def test_gap_disarms_no_cross_gap_fire(self):
        # Charging, then a >gap outage, then idle resumes -> the edge was never watched.
        seq = [(t, "2", 1000 + t * 15) for t in range(0, 300, 9)]
        seq += [(300 + 600 + t, "1", 10000) for t in range(0, 120, 9)]  # 600s gap > 60s
        self.assertEqual(run(seq), [])

    def test_pause_resume_within_session(self):
        # S2 -> brief S1 pause (>confirm) -> S2 again: a mid-session pause of a real
        # charge fires on each completed sub-run that delivered energy. Documents the
        # behavior rather than asserting a single fire.
        seq = [(t, "2", 1000 + t * 15) for t in range(0, 300, 9)]      # ~gain
        seq += [(300 + t, "1", 5500) for t in range(0, 60, 9)]          # pause, holds > confirm
        seq += [(360 + t, "2", 5500 + t * 15) for t in range(0, 300, 9)]
        seq += [(660 + t, "1", 11000) for t in range(0, 120, 9)]        # final idle
        fired = run(seq)
        self.assertEqual(len(fired), 2)

    def test_s1_not_held_long_enough(self):
        # S1 appears but flips back to S2 before confirm -> no fire for that blip.
        seq = [(t, "2", 1000 + t * 15) for t in range(0, 300, 9)]
        seq += [(300, "1", 5500), (309, "1", 5500)]   # only ~9s of S1 (< 30s confirm)
        seq += [(318 + t, "2", 5500 + t * 15) for t in range(0, 300, 9)]
        seq += [(618 + t, "1", 11000) for t in range(0, 120, 9)]
        fired = run(seq)
        self.assertEqual(len(fired), 1)               # only the final real completion


if __name__ == "__main__":
    unittest.main()
