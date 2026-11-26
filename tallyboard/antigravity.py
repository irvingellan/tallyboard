"""Optional read-only view of Antigravity (Gemini) conversations on this Mac.

Off unless config.json has "antigravity": true. It reads the conversation
index Antigravity keeps for its own sidebar and adds no hook or setting there.
Only a conversation's title and workspace folder reach the tablet.

Status values come from Antigravity's own enum. RUNNING, BUSY and CANCELING
are shown as running, WAITING_FOR_USER as "needs you", IDLE as a finished
turn. Anything else, including values this file has never seen, shows nothing.
"""
import calendar
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from state import from_dropin

HOME = Path('~/.gemini/antigravity').expanduser()
RECENT_S = 6 * 3600
MAX_ROWS = 12
RUNNING = ('CASCADE_RUN_STATUS_RUNNING', 'CASCADE_RUN_STATUS_BUSY', 'CASCADE_RUN_STATUS_CANCELING')
WAITING = 'CASCADE_RUN_STATUS_WAITING_FOR_USER'
IDLE = 'CASCADE_RUN_STATUS_IDLE'
STAMP = re.compile(r'^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:\.\d+)?\+00:00$')


def enabled(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('antigravity') is True
    except (OSError, ValueError, AttributeError):
        return False


def epoch(text):
    """Antigravity's UTC text stamps -> seconds; None for garbage and for year 1 ("never")."""
    match = STAMP.match(str(text or ''))
    if not match or int(match.group(1)) < 2000:
        return None
    return float(calendar.timegm(tuple(int(part) for part in match.groups()) + (0, 0, 0)))


def folder(uris):
    try:
        first = json.loads(uris)[0]
        return os.path.basename(unquote(urlsplit(first).path).rstrip('/')) or None
    except (ValueError, TypeError, IndexError, AttributeError):
        return None


def record_for(row, now):
    ident, title, status, modified, asked, uris, source = row
    touched, asked_at = epoch(modified), epoch(asked)
    if touched is None or now - touched > RECENT_S:
        return None
    record = {'agent': 'gemini', 'session': ident, 'project': folder(uris), 'session_title': title or None,
              'updated_at': now, 'started_at': asked_at or touched}
    if status in RUNNING:
        return dict(record, state='running')
    if status == WAITING:
        return dict(record, state='blocked', blocked_since=touched, reason_kind='input', reason='@agy_waiting')
    if status == IDLE and asked_at is not None and not source:  # a person started it, in the app
        return dict(record, state='done', ended_at=touched, updated_at=touched, awaiting=True)
    return None


class AntigravitySource:
    def __init__(self, config=None, home=HOME):
        self.config, self.home = config or {}, Path(home)

    def rows(self):
        database = self.home / 'conversation_summaries.db'
        if not database.exists():
            return []
        link = sqlite3.connect('file:%s?mode=ro' % database, uri=True, timeout=1)
        try:
            return link.execute(
                "select conversation_id, title, status, last_modified_time, last_user_input_time, workspace_uris, source "
                "from conversation_summaries where parent_conversation_id = '' and agent_name = '' and killed = 0 "
                "order by last_modified_time desc limit ?", (MAX_ROWS,)).fetchall()
        finally:
            link.close()

    def read(self, now=None):
        """Raises sqlite3.Error when the index cannot be read, so the caller keeps its last answer."""
        now = time.time() if now is None else now
        items = []
        for row in self.rows():
            try:
                record = record_for(row, now)
                item = from_dropin(record, now, self.config) if record else None
            except (ValueError, TypeError, OverflowError):
                item = None
            if item:
                items.append(item)
        return items
