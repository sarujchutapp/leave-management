"""Pure-function tests for Coverage Radar's overlap core. Hand-built peer
intervals only — no DB, no Slack. Peers are (name, start, end, status) tuples."""

from datetime import date

from leave.coverage import PeerOverlap, format_coverage_warning, peer_overlap


def test_peak_day_counts_overlapping_peers_with_status():
    # Bob (approved) and Carol (pending) both overlap the requested week; the peak
    # day is the first day both are off, and each contributor keeps its status.
    peers = [
        ("Bob", date(2026, 6, 9), date(2026, 6, 11), "approved"),
        ("Carol", date(2026, 6, 10), date(2026, 6, 15), "pending"),
    ]
    overlap = peer_overlap(date(2026, 6, 8), date(2026, 6, 12), peers)
    assert overlap.peak_day == date(2026, 6, 10)
    assert overlap.count == 2
    assert overlap.contributors == [("Bob", "approved"), ("Carol", "pending")]


def test_no_peer_overlap_returns_none():
    peers = [("Bob", date(2026, 7, 1), date(2026, 7, 3), "approved")]
    assert peer_overlap(date(2026, 6, 8), date(2026, 6, 12), peers) is None
    assert peer_overlap(date(2026, 6, 8), date(2026, 6, 12), []) is None


def test_peak_is_the_busiest_day_not_the_first_overlap():
    # Mon: only Bob off. Wed-Thu: Bob + Carol. The peak must be the busier Wed,
    # not the earlier Mon that already had an overlap.
    peers = [
        ("Bob", date(2026, 6, 8), date(2026, 6, 11), "approved"),   # Mon-Thu
        ("Carol", date(2026, 6, 10), date(2026, 6, 12), "pending"),  # Wed-Fri
    ]
    overlap = peer_overlap(date(2026, 6, 8), date(2026, 6, 12), peers)
    assert overlap.peak_day == date(2026, 6, 10)  # Wed, first day count hits 2
    assert overlap.count == 2


def test_format_warning_distinguishes_approved_and_pending():
    overlap = PeerOverlap(date(2026, 6, 10), 2, [("Bob", "approved"), ("Carol", "pending")])
    text = format_coverage_warning(overlap)
    assert "2026-06-10" in text
    assert "Bob" in text and "Carol" in text
    # Approved and pending are visually distinguished by distinct markers.
    assert "✅" in text and "⏳" in text
    assert "approved" in text and "pending" in text
