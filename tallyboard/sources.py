"""Read-only sources for Tallyboard.

Every source returns agent-neutral work items (see state.py). Nothing here
answers an agent, approves anything, or talks to anything off this computer.
"""
import json
import threading
import time
from pathlib import Path

from state import app_session, from_dropin

MAX_DROPIN_BYTES = 16 * 1024
MAX_DROPIN_FILES = 32


class DropinSource:
    """Status files any local agent may write into <state-dir>/agents.d/.

    This is how an agent appears on the board without the board knowing
    anything about it: the Claude Code hook writes one file per session.
    """

    def __init__(self, directory, config=None):
        self.directory = Path(directory)
        self.config = config or {}
        self.links = {}  # item id -> desktop app session, for the touch-to-open action

    def read(self, now=None):
        now = time.time() if now is None else now
        items, links = [], {}
        try:
            paths = sorted(self.directory.glob('*.json'))[:MAX_DROPIN_FILES]
        except OSError:
            return items
        for path in paths:
            try:
                if path.is_symlink() or path.stat().st_size > MAX_DROPIN_BYTES:
                    continue
                with path.open('rb') as handle:
                    body = handle.read(MAX_DROPIN_BYTES + 1)
                if len(body) > MAX_DROPIN_BYTES:
                    continue
                record = json.loads(body.decode('utf-8'))
                item = from_dropin(record, now, self.config)
            except (OSError, ValueError, TypeError, OverflowError):
                continue
            if item:
                items.append(item)
                if item['touch']:
                    links[item['id']] = app_session(record)
        self.links = links
        return items


class Collector:
    """Single-flight cache so a slow source can never stack up requests."""

    def __init__(self, dropin, min_interval=2.5, extra=()):
        self.dropin = dropin
        self.min_interval = min_interval
        self.extra = list(extra)  # further read-only sources, each with read() -> items
        self._kept = {}           # source index -> its last good answer
        self._lock = threading.Lock()
        self._at = None  # monotonic() may start near zero, so 0.0 is not "never"
        self._value = []

    def snapshot(self):
        """-> items"""
        if self._at is not None and time.monotonic() - self._at < self.min_interval:
            return self._value
        if not self._lock.acquire(blocking=False):
            return self._value  # someone else is refreshing; serve what we have
        try:
            items = self.dropin.read()
            for index, source in enumerate(self.extra):
                try:
                    self._kept[index] = source.read()
                except Exception:
                    # A busy index must not make its sessions blink out for one poll:
                    # that would re-ring the chime and forget waved-off rows.
                    pass
                items = items + self._kept.get(index, [])
            self._value = items
            self._at = time.monotonic()
        finally:
            self._lock.release()
        return self._value
