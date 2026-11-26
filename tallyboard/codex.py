"""Optional read-only view of Codex sessions on this Mac.

Off unless config.json has "codex": true. It never writes to ~/.codex and adds
no hook there: it asks Codex's own thread index (opened read-only) which
threads were touched in the last hours, then reads the tail of each thread's
log for the last "turn started / turn finished" marker. What reaches the
tablet is the thread's name, its title as Codex stores it (the first line of
your first message), the folder and the branch. Replies are never read.
"""
import json
import os
import sqlite3
import time
from pathlib import Path

from state import from_dropin

HOME = Path('~/.codex').expanduser()
RECENT_S = 6 * 3600
MAX_THREADS = 12
TAIL_BYTES = 256 * 1024
INTERACTIVE = ('cli', 'vscode')  # a person is on the other end; "exec" and sub-agents answer to a program
MARKERS = (b'"task_started"', b'"task_complete"', b'"turn_aborted"')


def enabled(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('codex') is True
    except (OSError, ValueError, AttributeError):
        return False


def last_turn(path):
    """-> (kind, epoch) for the newest turn marker in the log's tail, or (None, None)."""
    try:
        with open(path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            lines = handle.read().split(b'\n')
    except OSError:
        return None, None
    for line in reversed(lines):
        if not any(marker in line for marker in MARKERS):
            continue
        try:
            payload = json.loads(line.decode('utf-8')).get('payload') or {}
        except (ValueError, AttributeError):
            continue
        kind = payload.get('type')
        if kind == 'task_started':
            return 'running', _number(payload.get('started_at'))
        if kind in ('task_complete', 'turn_aborted'):
            return 'done', _number(payload.get('completed_at'))
    return None, None


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_for(row, now):
    """One thread row -> a drop-in style record, or None when there is nothing to show."""
    ident, rollout, updated, source, cwd, title, name, branch = row
    try:
        touched = os.stat(rollout).st_mtime
    except (OSError, TypeError):
        return None
    kind, at = last_turn(rollout)
    if kind is None:  # a long turn pushed its start marker out of the tail
        kind = 'running'
    interactive = source in INTERACTIVE
    record = {'agent': 'codex', 'session': ident, 'project': os.path.basename(str(cwd).rstrip('/')) or None,
              'session_title': name or None, 'title': (title or '').splitlines()[0][:140] if title else None,
              'branch': branch, 'updated_at': touched}
    if kind == 'running':
        record.update(state='running', started_at=at or touched)
        return record
    if not interactive:
        return None  # a finished background run is nobody's turn
    ended = at or touched
    record.update(state='done', ended_at=ended, updated_at=ended, awaiting=True)
    return record


class CodexSource:
    def __init__(self, config=None, home=HOME):
        self.config, self.home = config or {}, Path(home)

    def rows(self, now):
        database = self.home / 'state_5.sqlite'
        if not database.exists():
            return []
        link = sqlite3.connect('file:%s?mode=ro' % database, uri=True, timeout=1)
        try:
            return link.execute(
                'select id, rollout_path, updated_at, source, cwd, title, name, git_branch from threads '
                'where archived = 0 and attached_thread_parent_id is null and updated_at > ? '
                'order by updated_at desc limit ?', (int(now - RECENT_S), MAX_THREADS)).fetchall()
        finally:
            link.close()

    def read(self, now=None):
        """Raises sqlite3.Error when the index cannot be read, so the caller keeps its last answer."""
        now = time.time() if now is None else now
        items = []
        for row in self.rows(now):
            try:
                record = record_for(row, now)
                item = from_dropin(record, now, self.config) if record else None
            except (ValueError, TypeError, OverflowError):
                item = None
            if item:
                items.append(item)
        return items
