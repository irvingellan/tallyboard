"""Pure state model for Tallyboard.

No I/O lives here. Sources hand over raw records, this module normalizes them
into agent-neutral work items and derives the single view the tablet renders.
"""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

VIEW_VERSION = 1

DEFAULTS = {
    'done_ttl': 300,          # a finished job stays on screen this long, then IDLE
    'interrupted_ttl': 120,
    'failed_ttl': 1800,       # a failure nobody can acknowledge on a read-only screen
    'failed_headline': 180,   # a failure outranks running work only this long
    'alert_strong_s': 180,    # full amber alert lasts this long after the last state change
    'recent_window': 86400,
    'dropin_running_stale': 2700,
    'dropin_blocked_stale': 86400,
    'awaiting_ttl': 21600,    # a finished session stays listed as "your turn" this long
    'roster': ['claude'],
    'available_agents': ['claude'],  # agents with a wired source even while they have no work
}

AGENT_LABELS = {'claude': 'Claude', 'codex': 'Codex', 'gemini': 'Gemini'}
STATES = ('running', 'blocked', 'done', 'failed', 'interrupted')

_CONTROL = re.compile(r'[\x00-\x1f\x7f]+')
_SPACES = re.compile(r'\s+')
_LOCAL_PATH = re.compile(r'/(?:Users|home|private|tmp|var|opt|Volumes|Applications|etc|usr|bin)/[^\s"\'<>]+')
_MESSAGE = re.compile(r'"message"\s*:\s*"([^"{}]{4,})"')


# Conservative redaction before any string is serialized to the tablet.
_CREDENTIAL = re.compile(r'\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b')
_ASSIGNMENT = re.compile(r"(?i)(\b[\w-]*(?:api[_-]?key|token|password|secret|authorization)[\w-]*[\"']?\s*[:=]\s*)(?:Bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)")
_BEARER = re.compile(r'(?i)\bBearer\s+[^\s,;]+')
_URL_AUTH = re.compile(r'(https?://)[^/\s@]+@', re.I)


def normalize_config(raw):
    raw = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = raw.get(key)
        if key in ('roster', 'available_agents'):
            if isinstance(value, list):
                cfg[key] = [agent_id(v) for v in value[:8] if isinstance(v, str)]
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 604800:
            cfg[key] = value
    return cfg


def safe_count(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1000000 else None


def parse_time(value):
    """ISO-8601 or epoch (s or ms) -> epoch seconds, or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return (value / 1000.0 if value > 1e11 else float(value)) if math.isfinite(value) and value >= 0 else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def clean(value, limit=160):
    """Single-line, path-free, bounded text that is safe to put on a desk."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    text = _SPACES.sub(' ', _CONTROL.sub(' ', value)).strip()
    text = _URL_AUTH.sub(r'\1[redacted]@', text)
    text = _ASSIGNMENT.sub(r'\1[redacted]', text)
    text = _BEARER.sub('Bearer [redacted]', text)
    text = _CREDENTIAL.sub('[redacted]', text)
    text = _LOCAL_PATH.sub('[local]', text)
    if not text:
        return None
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def agent_id(value):
    text = re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')
    for known in AGENT_LABELS:
        if known in text:
            return known
    return text[:24] or 'agent'


def agent_label(identifier):
    return AGENT_LABELS.get(identifier) or identifier.replace('-', ' ').title()


def error_summary(value):
    """Engines nest JSON inside error strings; surface the human sentence."""
    if not value:
        return None
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    match = _MESSAGE.search(raw.replace('\\', ''))
    return clean(match.group(1) if match else raw, 220)


# Ordered: the first family that matches names the failure. Heuristic by design;
# the raw engine text always travels alongside as secondary information.
_FAILURE_FAMILIES = (
    (re.compile(r"model\b.{0,80}\b(not supported|not found|does not exist|unavailable|no access)", re.I), '@err_model'),
    (re.compile(r"\b(401|403|unauthori[sz]ed|authentication|not logged in|login required|invalid api key|token (has )?expired)\b", re.I), '@err_auth'),
    (re.compile(r"\b(429|rate.?limit|quota|usage limit|too many requests)\b", re.I), '@err_limit'),
    (re.compile(r"\b(context (length|window)|maximum context|too many tokens|prompt is too long)\b", re.I), '@err_context'),
    (re.compile(r"\b(timed? ?out|timeout|ETIMEDOUT|deadline exceeded)\b", re.I), '@err_timeout'),
    (re.compile(r"\b(ECONNREFUSED|ECONNRESET|ENOTFOUND|EAI_AGAIN|network|connection (refused|reset|closed)|fetch failed|socket hang up)\b", re.I), '@err_network'),
    (re.compile(r"\b(permission denied|EACCES|EPERM|operation not permitted|sandbox)\b", re.I), '@err_denied'),
    (re.compile(r"\b(50[0-4]|overloaded|internal server error|service unavailable|bad gateway)\b", re.I), '@err_service'),
)
_QUOTED_MODEL = re.compile(r"['\"]([A-Za-z0-9][A-Za-z0-9._:-]{2,40})['\"]\s+model|model\s+['\"]([A-Za-z0-9][A-Za-z0-9._:-]{2,40})['\"]", re.I)


def humanize_error(raw):
    """Technical error text -> (headline, raw detail or None).

    Headlines the board words itself are phrase codes ("@err_limit",
    "@err_model:name"); the page turns them into the viewer's language."""
    raw = clean(raw, 220)
    if not raw:
        return '@err_unknown', None
    for pattern, headline in _FAILURE_FAMILIES:
        if pattern.search(raw):
            model = _QUOTED_MODEL.search(raw) if headline == '@err_model' else None
            if model:
                headline = '@err_model:%s' % (model.group(1) or model.group(2))
            return headline, raw
    if len(raw) <= 60:
        return raw, None  # already short enough to be the headline
    return '@err_generic', raw


def _item(**fields):
    item = {
        'id': None, 'source': None, 'agent': 'agent', 'agent_label': 'Agent',
        'project': None, 'title': None, 'state': 'running', 'detail': None,
        'reason': None, 'reason_raw': None, 'reason_kind': None, 'started_at': None,
        'session_title': None, 'awaiting': False, 'touch': False,
        'blocked_since': None, 'ended_at': None, 'duration_s': None,
        'branch': None, 'checks': None, 'files_changed': None,
    }
    item.update(fields)
    return item


_APP_SESSION = re.compile(r'^local_[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')


def app_session(record):
    """The desktop app's own id for a session, when the agent reported a well-formed one."""
    value = record.get('app_session') if isinstance(record, dict) else None
    return value if isinstance(value, str) and _APP_SESSION.match(value) else None


def from_dropin(record, now, config=None):
    """A status file written by any local agent -> work item (or None)."""
    cfg = normalize_config(config)
    if not isinstance(record, dict):
        return None
    state = str(record.get('state') or '').lower()
    if state not in STATES:
        return None
    agent = agent_id(record.get('agent'))
    started = parse_time(record.get('started_at'))
    updated = parse_time(record.get('updated_at')) or started
    if updated is None:
        return None
    age = now - updated
    if age < -30:
        return None  # an implausible future heartbeat cannot attest current work
    if state == 'running' and age > cfg['dropin_running_stale']:
        return None  # no heartbeat: the session most likely died without saying so
    if state == 'blocked' and age > cfg['dropin_blocked_stale']:
        return None
    checks = record.get('checks')
    if isinstance(checks, dict):
        passed = safe_count(checks.get('passed')) or 0
        failed = safe_count(checks.get('failed')) or 0
        checks = {'passed': passed, 'failed': failed, 'total': safe_count(checks.get('total')) or passed + failed}
        if not checks['total']:
            checks = None
    else:
        checks = None
    item = _item(
        id='dropin:%s:%s' % (agent, clean(record.get('session'), 64) or 'default'),
        source='dropin', agent=agent,
        agent_label=clean(record.get('agent_label'), 24) or agent_label(agent),
        project=clean(record.get('project'), 48), title=clean(record.get('title'), 140),
        state=state, detail=clean(record.get('detail'), 60), started_at=started,
        branch=clean(record.get('branch'), 60), checks=checks,
    )
    item['session_title'] = clean(record.get('session_title'), 60)
    item['touch'] = app_session(record) is not None
    if state == 'blocked':
        item['blocked_since'] = parse_time(record.get('blocked_since')) or updated
        item['reason'] = clean(record.get('reason'), 220) or '@waiting'
        item['reason_kind'] = clean(record.get('reason_kind'), 16) or 'input'
    elif state != 'running':
        item['ended_at'] = parse_time(record.get('ended_at')) or updated
        item['detail'] = None
        item['awaiting'] = state == 'done' and record.get('awaiting') is True
        if started is not None and item['ended_at'] >= started:
            item['duration_s'] = int(item['ended_at'] - started)
        if state == 'failed':
            item['reason'], item['reason_raw'] = humanize_error(error_summary(record.get('reason')))
            if clean(record.get('summary'), 80):  # the agent's own words beat our heuristic
                item['reason'], item['reason_raw'] = clean(record.get('summary'), 80), item['reason_raw'] or item['reason']
    return item


def _roster(items, roster, fresh, wired=('claude',)):
    order = []
    for name in list(roster) + [item['agent'] for item in items]:
        identifier = agent_id(name)
        if identifier not in order:
            order.append(identifier)
    rank = {'blocked': 0, 'running': 1, 'failed': 2, 'done': 3, 'interrupted': 3}
    agents = []
    for identifier in order[:8]:
        mine = [i for i in items if i['agent'] == identifier and (i['state'] in ('blocked', 'running') or i in fresh)]
        mine.sort(key=lambda i: rank[i['state']])
        top = mine[0] if mine else None
        agents.append({
            'id': identifier,
            'label': top['agent_label'] if top else agent_label(identifier),
            'state': ('done' if top['state'] == 'interrupted' else top['state']) if top else 'idle',
            'detail': (top['detail'] or top['project']) if top else None,
            'available': identifier in wired or any(i['agent'] == identifier for i in items),
            'jobs': sum(1 for i in mine if i['state'] in ('blocked', 'running')),
        })
    return agents


def build_view(items, now, config=None, demo=None, memory=None):
    """Derive what the tablet shows. Precedence: blocked > fresh failure >
    running > failure > done > idle.

    `memory` is a dict the caller keeps between calls; it lets a change in the
    set of live jobs re-arm the strong alert even when no timestamp moved."""
    cfg = normalize_config(config)
    items = [i for i in items if i]
    age = lambda i: now - (i['ended_at'] or now)
    blocked = sorted((i for i in items if i['state'] == 'blocked'), key=lambda i: i['blocked_since'] or now)
    running = sorted((i for i in items if i['state'] == 'running'), key=lambda i: -(i['started_at'] or 0))
    terminal = sorted((i for i in items if i['ended_at'] is not None and i['state'] not in ('blocked', 'running')),
                      key=lambda i: -i['ended_at'])
    failed = [i for i in terminal if i['state'] == 'failed' and age(i) < cfg['failed_ttl']]
    done = [i for i in terminal if (i['state'] == 'done' and age(i) < cfg['done_ttl'])
            or (i['state'] == 'interrupted' and age(i) < cfg['interrupted_ttl'])]

    mode, focus, expires = 'idle', None, None
    if blocked:
        mode, focus = 'blocked', blocked[0]
    elif failed and (not running or age(failed[0]) < cfg['failed_headline']):
        mode, focus = 'failed', failed[0]
        expires = focus['ended_at'] + (cfg['failed_headline'] if running else cfg['failed_ttl'])
    elif running:
        mode, focus = 'running', running[0]
    elif done:
        mode, focus = 'done', done[0]
        expires = focus['ended_at'] + (cfg['done_ttl'] if focus['state'] == 'done' else cfg['interrupted_ttl'])

    recent = [i for i in terminal if age(i) < cfg['recent_window']]
    live = blocked + running
    # A session whose turn ended is not "finished": it is waiting for the person's next message.
    awaiting = [i for i in terminal if i.get('awaiting') and age(i) < cfg['awaiting_ttl'] and i is not focus]

    # ACTION REQUIRED starts loud, then settles into an ambient amber so it can
    # sit on a desk for an hour. Any state change makes it loud again.
    alert = None
    if mode == 'blocked':
        marks = [i['blocked_since'] for i in blocked] + [i['started_at'] for i in running] + [i['ended_at'] for i in failed + done]
        since = max([m for m in marks if m is not None and m <= now] or [now])
        if memory is not None:
            signature = sorted(json.dumps({k: i.get(k) for k in ('id', 'state', 'reason', 'reason_kind', 'blocked_since', 'started_at')}, sort_keys=True) for i in live)
            if memory.get('signature') not in (None, signature):
                memory['changed_at'] = now
            memory['signature'] = signature
            since = max(since, memory.get('changed_at') or 0)
        alert = 'strong' if now - since < cfg['alert_strong_s'] else 'ambient'
    elif memory is not None:
        memory.clear()
    view = {
        'v': VIEW_VERSION,
        'mode': mode,
        'alert': alert,
        'focus': focus,
        'focus_expires_at': expires,
        'agents': _roster(items, cfg['roster'], failed + done,
                          [agent_id(a) for a in cfg['available_agents']] if isinstance(cfg['available_agents'], list) else ('claude',)),
        'counts': {
            'active': len(running),
            'waiting': len(blocked),
            'done': sum(1 for i in recent if i['state'] == 'done'),
            'failed': sum(1 for i in recent if i['state'] == 'failed'),
            'awaiting': len(awaiting),
            'projects': len({i['project'] for i in live if i['project']}),
        },
        'queue': [i for i in live if i is not focus][:5],
        'awaiting': awaiting[:5],
        'recent': [i for i in recent if i is not focus and not any(i is a for a in awaiting)][:4],
        'demo': demo,
    }
    view['rev'] = hashlib.sha1(json.dumps(view, sort_keys=True).encode()).hexdigest()[:12]
    view['now'] = round(now, 3)
    return view
