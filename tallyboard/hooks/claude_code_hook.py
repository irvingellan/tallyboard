#!/usr/bin/env python3
"""Optional Claude Code hook: publishes this session's status to Tallyboard.

Wire it to UserPromptSubmit, PreToolUse (AskUserQuestion), PermissionRequest,
PostToolUse, Notification, Stop and SessionEnd (see README.md).
It writes one small JSON file per session into <state-dir>/agents.d/ and
nothing else: no network, no stdout, and it always exits 0 so it can never
block a Claude Code turn.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get('TALLYBOARD_STATE_DIR', '~/.local/state/tallyboard')).expanduser()
STALE_FILE_S = 2 * 86400
APP_SESSIONS = Path('~/Library/Application Support/Claude/claude-code-sessions').expanduser()
EVENT_LOG_BYTES = 64 * 1024


def _git(cwd, *args):
    try:
        out = subprocess.run(('git', '-C', cwd) + args, capture_output=True, text=True, timeout=2)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def branch_of(cwd):
    return _git(cwd, 'rev-parse', '--abbrev-ref', 'HEAD')


def project_of(cwd):
    common = _git(cwd, 'rev-parse', '--git-common-dir')
    if common:  # worktrees report the real repository, not the worktree folder
        return (Path(cwd) / common).resolve().parent.name
    return Path(cwd).name


def desktop_session(cli_session, root=None):
    """The Claude desktop app's own id and title for this session, if it is one of its sessions.

    Lets the console show the name you see in the sidebar and open the
    session on a tap. Only the newest few files are read; terminal sessions
    simply have no match."""
    try:
        files = sorted((root or APP_SESSIONS).glob('*/*/local_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:12]
    except OSError:
        return None, None
    for path in files:
        try:
            text = path.read_text(encoding='utf-8')
            if cli_session not in text:
                continue
            data = json.loads(text)
        except (OSError, ValueError):
            continue
        if data.get('cliSessionId') == cli_session and isinstance(data.get('sessionId'), str):
            title = data.get('title')
            return data['sessionId'], title[:60] if isinstance(title, str) and title.strip() else None
    return None, None


SERVERS = {'Claude_Browser': '@browser', 'claude-in-chrome': '@chrome', 'computer-use': '@computer'}


def activity(tool, tool_input):
    """What the session is doing right now, from the tool it is about to run.

    Only the tool's name, a file's base name, or the short description the
    agent itself wrote for a command: never the command, a path or content.
    Phrases the board words itself are codes ("@editing:state.py") that the
    page turns into the viewer's language."""
    given = tool_input if isinstance(tool_input, dict) else {}
    name = os.path.basename(str(given.get('file_path') or given.get('notebook_path') or ''))[:40]
    if tool == 'Bash':
        said = ' '.join(str(given.get('description') or '').split())
        return said.lstrip('@')[:60] or '@command'
    if tool in ('Edit', 'Write', 'NotebookEdit'):
        return '@editing:%s' % name if name else '@editing_files'
    if tool == 'Read':
        return '@reading:%s' % name if name else '@reading_files'
    if tool in ('Grep', 'Glob', 'ToolSearch'):
        return '@searching'
    if tool in ('WebSearch', 'WebFetch'):
        return '@web'
    if tool in ('Agent', 'Task'):
        return '@subagent'
    if tool.startswith('mcp__'):
        server = tool.split('__')[1] if tool.count('__') >= 2 else ''
        if re.match(r'^[0-9a-f]{8}-', server) or not server:
            return '@connector'
        return SERVERS.get(server) or '@using:%s' % server.replace('_', ' ')[:40]
    return None


def _waiting(record, now, reason, kind):
    # A question also raises a permission-style prompt in the app: it stays a question.
    if kind == 'approval' and record.get('state') == 'blocked' and record.get('reason_kind') == 'input':
        return
    if record.get('state') != 'blocked':
        record['blocked_since'] = now
    record.update(state='blocked', reason=reason, reason_kind=kind)


def apply(event, record, now):
    """Pure transition: (hook payload, previous record, now) -> record or None (= remove)."""
    name = event.get('hook_event_name')
    cwd = event.get('cwd') or os.getcwd()
    tool = str(event.get('tool_name') or '')[:40]
    record = dict(record or {})
    if name == 'SessionEnd':
        return None
    record.update(agent='claude', session=str(event.get('session_id') or 'default')[:64], updated_at=now)
    record.setdefault('project', project_of(cwd))
    live = record.get('state') in ('running', 'blocked')
    if name == 'UserPromptSubmit':
        # Harness notices (task notifications, pasted blocks) also arrive as prompts;
        # only a line the person actually typed may rename what the session is doing.
        prompt = re.sub(r'<pasted_content[^>]*>.*?</pasted_content[^>]*>', '', str(event.get('prompt') or ''), flags=re.S)
        typed = [line.strip() for line in prompt.splitlines() if line.strip() and line.strip()[0] not in '<[>']
        if typed or not live:
            record.update(started_at=now, title=typed[0][:140] if typed else record.get('title'))
        record.update(state='running', branch=branch_of(cwd), reason=None, ended_at=None, awaiting=False, detail='@thinking')
    elif name in ('PermissionRequest', 'PreToolUse') and tool == 'AskUserQuestion' and live:
        _waiting(record, now, '@question', 'input')
    elif name == 'PermissionRequest' and live:
        _waiting(record, now, '@permission:%s' % tool if tool else '@permission', 'approval')
    elif name == 'PreToolUse' and live:
        record.update(state='running', reason=None, detail=activity(tool, event.get('tool_input')) or record.get('detail'))
    elif name == 'Notification':
        # idle_prompt only ever follows Stop, when the turn is already "done"
        if event.get('notification_type') == 'permission_prompt' and live:
            wanted = re.search(r'permission to use (\S+)', str(event.get('message') or ''))
            _waiting(record, now, '@permission:%s' % wanted.group(1)[:40] if wanted else '@permission', 'approval')
    elif name == 'Stop':
        if live:
            record.update(state='done', ended_at=now, reason=None, awaiting=True, detail=None)  # the turn ended: the person's move
    elif name == 'PostToolUse' and record.get('state') == 'blocked':
        record.update(state='running', reason=None, detail='@thinking')  # a tool ran, so the person already answered
    return record if record.get('state') else None


def _housekeeping(folder, event, now):
    """Sessions that never said goodbye, and a tiny log of which events really fire."""
    if event.get('hook_event_name') != 'UserPromptSubmit':
        return
    for stale in folder.glob('claude--*.json'):
        try:
            if now - stale.stat().st_mtime > STALE_FILE_S:
                stale.unlink()
        except OSError:
            pass


def _log(event, now):
    try:
        path = STATE_DIR / 'hook-events.log'
        if path.exists() and path.stat().st_size > EVENT_LOG_BYTES:
            path.write_text('', encoding='utf-8')
        with path.open('a', encoding='utf-8') as handle:  # event names only, never content
            handle.write('%s %s %s %s\n' % (time.strftime('%m-%d %H:%M:%S', time.localtime(now)),
                                            str(event.get('session_id') or '')[:8], event.get('hook_event_name'),
                                            event.get('notification_type') or event.get('tool_name') or ''))
    except OSError:
        pass


def main():
    try:
        event = json.load(sys.stdin)
        now = time.time()
        session = ''.join(c for c in str(event.get('session_id') or 'default') if c.isalnum() or c in '-_')[:64]
        folder = STATE_DIR / 'agents.d'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ('claude--%s.json' % session)
        _log(event, now)
        try:
            previous = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = None
        record = apply(event, previous, now)
        if record is not None and (event.get('hook_event_name') in ('UserPromptSubmit', 'Stop') or not record.get('app_lookup')):
            app_id, title = desktop_session(record['session'])
            record['app_lookup'] = True  # one attempt outside turn edges; terminal sessions never match
            if app_id:
                record.update(app_session=app_id, session_title=title or record.get('session_title'))
        if record is None:
            target.unlink() if target.exists() else None
            return
        temporary = target.with_suffix('.%d.tmp' % os.getpid())
        temporary.write_text(json.dumps(record), encoding='utf-8')
        os.replace(str(temporary), str(target))
        _housekeeping(folder, event, now)
    except Exception:  # a status light must never break the agent it reports on
        pass


if __name__ == '__main__':
    main()
    sys.exit(0)
