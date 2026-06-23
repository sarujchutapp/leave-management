"""Coverage Radar — pure overlap math over plain inputs (no DB, no Slack).

A soft heads-up for a manager: when a leave request overlaps the leave of the
requester's peers (employees sharing the same manager), surface the busiest day
and who is off then. Counts approved *and* pending peer leave, labelled
distinctly. Never blocks a decision — it is context the manager weighs.
"""

from collections import namedtuple
from datetime import timedelta

# The busiest overlapping day: `peak_day`, how many peers are off then (`count`),
# and `contributors` — the (name, status) of each peer off on that day.
PeerOverlap = namedtuple("PeerOverlap", "peak_day count contributors")


def peer_overlap(start, end, peers):
    """The peak per-day peer overlap within the requested [start, end] range, or
    None if no peer is off on any day of it. `peers` is an iterable of
    (name, p_start, p_end, status). Ties on count resolve to the earliest day."""
    best = None
    d = start
    while d <= end:
        on_day = [(name, status) for name, ps, pe, status in peers if ps <= d <= pe]
        if on_day and (best is None or len(on_day) > best.count):
            best = PeerOverlap(d, len(on_day), sorted(on_day))
        d += timedelta(days=1)
    return best


_STATUS_MARK = {"approved": "✅", "pending": "⏳"}


def format_coverage_warning(overlap):
    """Render a PeerOverlap as the ticket warning line: the peak day, how many
    peers are off, and each one by name + status (approved/pending marked
    distinctly). Never names the leave type — it isn't part of the input."""
    peers = overlap.count
    who = "peer is" if peers == 1 else "peers are"
    lines = [
        f"⚠️ *Coverage check* — on {overlap.peak_day.isoformat()}, "
        f"{peers} other {who} already off:"
    ]
    for name, status in overlap.contributors:
        lines.append(f"{_STATUS_MARK.get(status, '•')} {name} ({status})")
    return "\n".join(lines)
