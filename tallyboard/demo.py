"""Sample screens for trying the board without any agent: open /?demo=<name>.

Demo data never mixes with real sessions and is always labelled on screen.
"""
from state import _item, agent_label, humanize_error

SCENARIOS = ('idle', 'waiting', 'running', 'blocked', 'question', 'ambient', 'done', 'failed', 'multi')
CYCLE_SECONDS = 12


def _job(agent, state, now, **fields):
    return _item(id='demo:%s:%s' % (agent, state), source='demo', agent=agent,
                 agent_label=agent_label(agent), state=state, **fields)


def scenario(name, now):
    """-> (resolved_name, items)"""
    if name == 'cycle':
        name = SCENARIOS[int(now // CYCLE_SECONDS) % len(SCENARIOS)]
    if name not in SCENARIOS:
        name = 'idle'
    now -= now % 60  # samples are pinned to the minute, so the timers on screen really tick
    running = _job('claude', 'running', now, project='bakery-site', session_title='Checkout redesign',
                   title='make the cart total update without a page reload',
                   detail='Running the tests', started_at=now - 754, branch='feature/live-cart-total')
    blocked = _job('codex', 'blocked', now, project='orders-api', session_title='Orders schema migration',
                   title='move delivery windows to the new schema',
                   started_at=now - 1460, blocked_since=now - 95, reason_kind='approval',
                   reason='@permission:Bash')
    done = _job('codex', 'done', now, project='bakery-site', session_title='Footer cleanup',
                title='remove the dead links from the footer',
                started_at=now - 1125, ended_at=now - 40, duration_s=1085, branch='chore/footer-links')
    failed = _job('codex', 'failed', now, project='price-watcher', title='update the price scraper',
                  started_at=now - 1300, ended_at=now - 410, duration_s=890)
    failed['reason'], failed['reason_raw'] = humanize_error(
        "The 'example-model-1' model is not supported with this account.")
    waiting = [
        dict(_job('claude', 'done', now, project='bakery-site', title='reword the order button',
                  started_at=now - 1300, ended_at=now - 720, duration_s=580), id='demo:w1', awaiting=True, session_title='Order button copy'),
        dict(_job('codex', 'done', now, project='price-watcher', title='review the scraper design',
                  started_at=now - 4000, ended_at=now - 3000, duration_s=1000), id='demo:w2', awaiting=True, session_title='Scraper design review'),
        dict(_job('gemini', 'done', now, project='recipe-notes', title='finish the recent recipes screen',
                  started_at=now - 9000, ended_at=now - 8200, duration_s=800), id='demo:w3', awaiting=True, session_title='Recent recipes screen'),
    ]
    items = {
        'idle': [], 'running': [running], 'blocked': [blocked],
        'question': [dict(blocked, agent='claude', agent_label=agent_label('claude'), id='demo:q', reason_kind='input',
                          reason='@question', session_title='Checkout redesign')],
        'waiting': waiting,
        'ambient': [dict(blocked, started_at=now - 3100, blocked_since=now - 1560)],
        'done': [done], 'failed': [failed],
        'multi': [
            blocked, running,
            _job('gemini', 'running', now, project='recipe-notes', session_title='Weekly menu planner',
                 title='draft the weekly menu view', detail='@reading_files', started_at=now - 95),
            dict(done, ended_at=now - 1900), dict(failed, ended_at=now - 5200),
        ] + waiting[:1],
    }[name]
    return name, items


def extras(name, now):
    """Sample agenda and plan-usage so screenshots never need anyone's real data."""
    if name not in SCENARIOS and name != 'cycle':
        return None, None
    now -= now % 60
    agenda = {'events': [{'title': 'Stand-up', 'start': now + 2400}, {'title': 'Dentist', 'start': now + 86400 + 5400},
                         {'title': 'Demo day rehearsal', 'start': now + 3 * 86400}]}
    usage = {'at': now, 'windows': [{'label': '@u_5h', 'used': 42, 'resets_at': now + 7800},
                                    {'label': '@u_week', 'used': 23, 'resets_at': now + 4 * 86400},
                                    {'label': 'Fable', 'used': 81, 'resets_at': now + 4 * 86400}]}
    return agenda, usage
