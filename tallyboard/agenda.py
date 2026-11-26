"""Optional next-appointments line, from a small file a scheduled task refreshes.

The console has no calendar access of its own. A scheduled Claude task writes
<state-dir>/agenda.json a few times a day:

    {"updated_at": 1795136000,
     "events": [{"title": "...", "start": "2026-11-30T11:00:00-08:00", "end": "2026-11-30T11:30:00-08:00"}]}

This file only validates and trims it: timed events that have not ended, the
next few, titles capped. All-day entries (birthdays) are left out. Nothing is
shown once the file is more than a day and a half old.
"""
import json
from datetime import datetime
from pathlib import Path

STALE_S = 36 * 3600
MAX_BYTES = 64 * 1024
HORIZON_S = 7 * 86400
SHOWN = 3


def _epoch(value):
    if not isinstance(value, str) or 'T' not in value:
        return None  # a bare date is an all-day entry
    try:
        moment = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment.timestamp() if moment.tzinfo else None


def view(path, now):
    try:
        path = Path(path)
        if path.stat().st_size > MAX_BYTES:
            return None
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get('events'), list):
        return None
    updated = raw.get('updated_at')
    if isinstance(updated, bool) or not isinstance(updated, (int, float)) or not 0 <= now - updated <= STALE_S:
        return None
    events = []
    for entry in raw['events'][:200]:
        if not isinstance(entry, dict) or not isinstance(entry.get('title'), str):
            continue
        start, end = _epoch(entry.get('start')), _epoch(entry.get('end'))
        if start is None or (end if end is not None else start + 1800) <= now or start - now > HORIZON_S:
            continue
        title = ' '.join(entry['title'].split())[:80]
        if title:
            events.append({'title': title, 'start': start})
    events.sort(key=lambda event: event['start'])
    return {'events': events[:SHOWN]}
