/* Tallyboard: tablet client.
   ES5 only (Fire OS 5 / Android 5.1 WebView): no let/const, arrows, template
   strings, fetch, classList tricks or Intl. Read-only: it only ever GETs. */
(function (root) {
  'use strict';

  /* Every word on screen lives here. The server sends phrase codes ("@editing:state.py")
     and the page words them, so adding a language is adding one table. */
  var LANG = {
    'en': {
      week: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
      month: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
      days: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
      date: '{w}, {m} {d}', today: 'today', tomorrow: 'tomorrow', until: 'until',
      now: 'now', ago_min: '{n} min ago', ago_h: '{n} h ago', ago_d: '{n} d ago',
      checks_failed: '{a} of {b} failed',
      tag_running: 'Running', tag_blocked: 'Needs you', tag_done: 'Done', tag_failed: 'Failed', tag_interrupted: 'Interrupted',
      tag_question: 'Question for you', tag_permission: 'Asks permission',
      r_running: 'running', r_blocked: 'needs you', r_done: 'done', r_failed: 'failed', r_idle: 'idle', r_none: 'not set up',
      k_approval: 'Approval', k_input: 'Answer', k_recovery: 'Recovery',
      c_duration: 'Duration', c_ended: 'Ended', c_started: 'Started', c_project: 'Project', c_request: 'Request', c_branch: 'Branch', c_checks: 'Checks', c_files: 'Files',
      l_running: 'running', l_waiting: 'waiting', l_duration: 'duration',
      failed: 'failed', interrupted: 'interrupted',
      lost: 'no connection to the computer · reconnecting', connecting: 'connecting', online: 'online',
      s_active: 'active', s_waiting: 'waiting', s_done: 'done 24h', s_projects: 'projects', s_agents: 'Agents', s_queue: 'Also in progress', s_recent: 'Recent', s_turn: 'Your turn',
      thinking: 'Thinking', command: 'Running a command', editing: 'Editing {a}', editing_files: 'Editing files', reading: 'Reading {a}', reading_files: 'Reading files',
      searching: 'Searching', web: 'Searching the web', subagent: 'Handing off to a sub-agent', connector: 'Using a connector', using: 'Using {a}',
      browser: 'Using the browser', chrome: 'Using Chrome', computer: 'Using the computer',
      question: 'Has a question for you', permission: 'Asks permission to use {a}', permission_: 'Asks permission to use a tool', waiting: 'Waiting for you', agy_waiting: 'Antigravity is waiting for you',
      err_model: 'Model {a} is not available on this account', err_model_: 'Model not available on this account', err_auth: 'The agent could not sign in', err_limit: 'Usage limit reached',
      err_context: 'Too much context for the model', err_timeout: 'Timed out', err_network: 'Connection failed', err_denied: 'Permission denied by the environment',
      err_service: 'The model service is unavailable', err_unknown: 'Failed with no error detail', err_generic: 'The agent stopped with an error',
      u_5h: '5 h', u_week: 'Week'
    },
    'pt-BR': {
      week: ['domingo', 'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado'],
      month: ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'],
      days: ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'],
      date: '{w}, {d} de {m}', today: 'hoje', tomorrow: 'amanhã', until: 'até',
      now: 'agora', ago_min: 'há {n} min', ago_h: 'há {n} h', ago_d: 'há {n} d',
      checks_failed: '{a} de {b} falharam',
      tag_running: 'Executando', tag_blocked: 'Precisa de você', tag_done: 'Concluído', tag_failed: 'Falhou', tag_interrupted: 'Interrompido',
      tag_question: 'Pergunta para você', tag_permission: 'Pede permissão',
      r_running: 'executando', r_blocked: 'aguarda você', r_done: 'concluído', r_failed: 'falhou', r_idle: 'ocioso', r_none: 'sem fonte',
      k_approval: 'Aprovação', k_input: 'Resposta', k_recovery: 'Recuperação',
      c_duration: 'Duração', c_ended: 'Terminou', c_started: 'Início', c_project: 'Projeto', c_request: 'Pedido', c_branch: 'Branch', c_checks: 'Checks', c_files: 'Arquivos',
      l_running: 'em execução', l_waiting: 'esperando', l_duration: 'duração',
      failed: 'falhou', interrupted: 'interrompido',
      lost: 'sem conexão com o computador · reconectando', connecting: 'conectando', online: 'online',
      s_active: 'ativos', s_waiting: 'aguardando', s_done: 'concluídos 24h', s_projects: 'projetos', s_agents: 'Agentes', s_queue: 'Também em andamento', s_recent: 'Recentes', s_turn: 'Sua vez',
      thinking: 'Pensando', command: 'Rodando um comando', editing: 'Editando {a}', editing_files: 'Editando arquivos', reading: 'Lendo {a}', reading_files: 'Lendo arquivos',
      searching: 'Procurando', web: 'Pesquisando na web', subagent: 'Delegando a um subagente', connector: 'Usando um conector', using: 'Usando {a}',
      browser: 'Usando o navegador', chrome: 'Usando o Chrome', computer: 'Usando o computador',
      question: 'Tem uma pergunta para você', permission: 'Pede permissão para usar {a}', permission_: 'Pede permissão para usar uma ferramenta', waiting: 'Aguardando você', agy_waiting: 'O Antigravity espera você',
      err_model: 'Modelo {a} não disponível nesta conta', err_model_: 'Modelo não disponível nesta conta', err_auth: 'Falha de autenticação do agente', err_limit: 'Limite de uso atingido',
      err_context: 'Contexto grande demais para o modelo', err_timeout: 'Tempo esgotado', err_network: 'Falha de conexão', err_denied: 'Permissão negada no ambiente',
      err_service: 'Serviço do modelo indisponível', err_unknown: 'Falhou sem detalhe de erro', err_generic: 'O agente parou com um erro',
      u_5h: '5 h', u_week: 'Semana'
    }
  };
  var L = LANG.en, langCode = 'en';
  function setLang(code) { langCode = LANG.hasOwnProperty(code) ? code : 'en'; L = LANG[langCode]; return langCode; }
  function fill(pattern, values) {
    return String(pattern).replace(/\{(\w)\}/g, function (all, name) { return values[name] == null ? '' : values[name]; });
  }
  /* A phrase code from the server ("@key" or "@key:argument") -> words; anything else is the agent's own text. */
  function say(value) {
    var text = value == null ? '' : String(value), cut, key, arg;
    if (text.charAt(0) !== '@') return text;
    cut = text.indexOf(':');
    key = cut < 0 ? text.slice(1) : text.slice(1, cut);
    arg = cut < 0 ? '' : text.slice(cut + 1);
    if (!arg && L.hasOwnProperty(key + '_')) key += '_';
    return L.hasOwnProperty(key) && typeof L[key] === 'string' ? fill(L[key], { a: arg }) : arg;
  }
  var POLL_MS = 3000, BACKOFF_MS = [3000, 5000, 8000, 15000], LOST_MS = 12000, XHR_TIMEOUT_MS = 8000;

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function esc(text) {
    return String(text == null ? '' : text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* All wall-clock helpers take "display ms": server time already shifted by
     the Mac's UTC offset, so a tablet with a wrong clock or zone still agrees. */
  function clock(ms) { var d = new Date(ms); return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); }

  function dateLine(ms) {
    var d = new Date(ms);
    return fill(L.date, { w: L.week[d.getUTCDay()], d: d.getUTCDate(), m: L.month[d.getUTCMonth()] });
  }

  function timer(seconds) {
    var s = Math.max(0, Math.floor(seconds));
    if (s < 3600) return pad(Math.floor(s / 60)) + ':' + pad(s % 60);
    return Math.floor(s / 3600) + 'h ' + pad(Math.floor((s % 3600) / 60)) + 'm';
  }

  function ago(seconds) {
    var s = Math.max(0, Math.floor(seconds));
    if (s < 60) return L.now;
    if (s < 3600) return fill(L.ago_min, { n: Math.floor(s / 60) });
    if (s < 86400) return fill(L.ago_h, { n: Math.floor(s / 3600) });
    return fill(L.ago_d, { n: Math.floor(s / 86400) });
  }

  function duration(seconds) {
    var s = Math.max(0, Math.floor(seconds));
    if (s < 60) return s + ' s';
    if (s < 3600) return Math.floor(s / 60) + ' min';
    return Math.floor(s / 3600) + ' h ' + pad(Math.floor((s % 3600) / 60));
  }

  function checksText(checks) {
    if (!checks || !checks.total) return null;
    if (checks.failed) return fill(L.checks_failed, { a: checks.failed, b: checks.total });
    return checks.passed + '/' + checks.total + ' ok';
  }

  function isNight(ms) { var h = new Date(ms).getUTCHours(); return h >= 23 || h < 7; }

  /* Only facts the source really reported become cells; nothing is invented. */
  function metaCells(item, mode, tzMs) {
    var cells = [], checks = checksText(item.checks);
    function add(k, v) { if (v !== null && v !== undefined && v !== '') cells.push({ k: k, v: String(v) }); }
    if (mode === 'failed') add(L.c_duration, item.duration_s != null ? duration(item.duration_s) : null);
    if (mode === 'done' && item.ended_at) add(L.c_ended, clock(item.ended_at * 1000 + tzMs));
    else if (item.started_at) add(L.c_started, clock(item.started_at * 1000 + tzMs));
    if (item.session_title) add(L.c_project, item.project);
    if (mode === 'blocked') add(L.c_request, L['k_' + item.reason_kind] || null);
    add(L.c_branch, item.branch);
    add(L.c_checks, checks);
    if (item.files_changed) add(L.c_files, item.files_changed);
    return cells;
  }

  /* -> {text, label, live}: the one big number of the focus panel. */
  function focusClock(item, mode, nowS) {
    if (mode === 'running' && item.started_at) return { text: timer(nowS - item.started_at), label: L.l_running };
    if (mode === 'blocked' && item.blocked_since) return { text: timer(nowS - item.blocked_since), label: L.l_waiting };
    if (mode === 'done' && item.duration_s != null) return { text: duration(item.duration_s), label: L.l_duration };
    if (mode === 'failed' && item.ended_at) return { text: ago(nowS - item.ended_at), label: '' };
    return { text: '', label: '' };
  }

  function expireFraction(view, nowS) {
    var f = view.focus, end = view.focus_expires_at;
    if (!f || !end || !f.ended_at || end <= f.ended_at) return 0;
    return Math.max(0, Math.min(1, (end - nowS) / (end - f.ended_at)));
  }

  function who(item) { return item.agent_label + (item.project ? ' · ' + item.project : ''); }

  /* data-id marks what a finger can open on the Mac; only the server decides if it may. */
  function touchAttr(item) { return item.touch ? ' data-id="' + esc(item.id) + '"' : ''; }

  function agentsHtml(agents) {
    var html = '', i, a;
    for (i = 0; i < agents.length; i++) {
      a = agents[i];
      html += '<div class="ag s-' + esc(a.state) + '"><i class="dot"></i><span class="as">' + esc(a.available === false ? L.r_none : L['r_' + a.state] || a.state) +
        '</span><span class="an">' + esc(a.label) + (a.jobs > 1 ? ' ×' + a.jobs : '') + '</span>' +
        (a.state !== 'idle' && a.detail ? '<div class="ad">' + esc(say(a.detail)) + '</div>' : '') + '</div>';
    }
    return html;
  }

  function rowsHtml(items, live) {
    var html = '', i, it, at, sub;
    for (i = 0; i < items.length; i++) {
      it = items[i];
      at = live ? (it.state === 'blocked' ? it.blocked_since : it.started_at) : it.ended_at;
      sub = it.state === 'blocked' ? say(it.reason) : it.state === 'running' && it.detail ? say(it.detail) : it.title;
      if (it.state === 'failed') sub = L.failed + (sub ? ' · ' + sub : '');
      if (it.state === 'interrupted') sub = L.interrupted + (sub ? ' · ' + sub : '');
      if (it.session_title && it.project) sub = it.project + (sub ? ' · ' + sub : '');
      html += '<div class="row s-' + esc(it.state) + (it.state === 'blocked' && it.reason_kind === 'input' ? ' q' : '') + (it.awaiting ? ' aw' : '') + '"' + touchAttr(it) + (it.awaiting ? ' data-aw="' + esc(it.id) + '"' : '') + '><i class="dot"></i><span class="rt" data-live="' + (live ? 1 : 0) +
        '" data-at="' + (at || '') + '"></span><span class="rn">' + esc(it.session_title || who(it)) + '</span>' +
        (sub ? '<div class="rd">' + esc(sub) + '</div>' : '') + '</div>';
    }
    return html;
  }

  /* Sound on the tablet itself: two synthesized cues, nothing like a messaging app.
     "turn" = two rising notes; "blocked" = four alternating notes. */
  var audio = null, heard = null, lastUsage = '', lastAgenda = '';
  function chime(kind) {
    try {
      var C = window.AudioContext || window.webkitAudioContext, notes, i, osc, gain, at;
      if (!C) return;
      if (!audio) audio = new C();
      if (audio.resume) audio.resume();
      notes = kind === 'blocked' ? [[784, 0], [587, 0.2], [784, 0.4], [587, 0.6]] : [[392, 0], [587, 0.22]];
      for (i = 0; i < notes.length; i++) {
        osc = audio.createOscillator(); gain = audio.createGain();
        osc.type = 'triangle'; osc.frequency.value = notes[i][0];
        at = audio.currentTime + 0.05 + notes[i][1];
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(0.9, at + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.5);
        osc.connect(gain); gain.connect(audio.destination);
        osc.start(at); osc.stop(at + 0.55);
      }
    } catch (e) {}
  }
  function needs(v) {
    var out = { blocked: {}, done: {} }, lists = [[v.focus], v.queue, v.recent, v.awaiting || []], i, j, it;
    for (i = 0; i < lists.length; i++) for (j = 0; j < lists[i].length; j++) {
      it = lists[i][j];
      if (it && it.id && (it.state === 'blocked' || it.state === 'done')) out[it.state][it.id] = 1;
    }
    return out;
  }
  function cue(before, after) {
    var id;
    if (!before) return null;
    for (id in after.blocked) if (!before.blocked[id]) return 'blocked';
    for (id in after.done) if (!before.done[id]) return 'turn';
    return null;
  }

  /* Plan usage, straight from the Mac: "5 h 50% · 18:10". Amber from 80%, red from 95%. */
  function usageHtml(usage, tz) {
    var html = '', i, w, cls;
    if (!usage || !Array.isArray(usage.windows)) return '';
    for (i = 0; i < usage.windows.length && i < 3; i++) {
      w = usage.windows[i];
      if (!w || typeof w.used !== 'number' || !isFinite(w.used)) continue;
      cls = w.used >= 95 ? 'top' : w.used >= 80 ? 'hi' : '';
      html += '<span class="' + cls + '">' + esc(say(w.label)) + '<b>' + Math.round(w.used) + '%</b>' +
        (i === 0 && typeof w.resets_at === 'number' && isFinite(w.resets_at) ? '<i>' + esc(L.until) + ' ' + clock((w.resets_at + 30) * 1000 + tz) + '</i>' : '') + '</span>';
    }
    return html;
  }

  /* Next appointments under the idle clock: "hoje 11:00  Entrevista". Amber inside the hour. */
  function whenLabel(startS, nowMs, tz) {
    var at = new Date(startS * 1000 + tz), today = new Date(nowMs + tz);
    var days = Math.round((Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate()) -
      Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())) / 86400000);
    var day = days === 0 ? L.today : days === 1 ? L.tomorrow : L.days[at.getUTCDay()] + ' ' + at.getUTCDate();
    return day + ' ' + clock(startS * 1000 + tz);
  }
  function agendaHtml(agenda, nowMs, tz) {
    var html = '', i, e;
    if (!agenda || !Array.isArray(agenda.events)) return '';
    for (i = 0; i < agenda.events.length && i < 3; i++) {
      e = agenda.events[i];
      if (!e || typeof e.start !== 'number' || !isFinite(e.start) || typeof e.title !== 'string') continue;
      html += '<div' + (e.start * 1000 - nowMs < 3600000 ? ' class="soon"' : '') + '><b>' + esc(whenLabel(e.start, nowMs, tz)) + '</b>' + esc(e.title) + '</div>';
    }
    return html;
  }

  function validView(next) {
    if (!next || next.v !== 1 || !isFinite(next.now) || typeof next.now !== 'number' ||
        typeof next.rev !== 'string' || typeof next.build !== 'string' ||
        !next.counts ||
        !Array.isArray(next.agents) || !Array.isArray(next.queue) || !Array.isArray(next.recent)) return false;
    if (['idle', 'running', 'blocked', 'done', 'failed'].indexOf(next.mode) < 0) return false;
    var keys = ['active', 'waiting', 'done', 'projects'], i, lists = [next.queue, next.recent], j;
    for (i = 0; i < keys.length; i++) if (typeof next.counts[keys[i]] !== 'number' || !isFinite(next.counts[keys[i]]) || next.counts[keys[i]] < 0) return false;
    function itemOk(item) {
      if (!item || typeof item !== 'object' || ['running', 'blocked', 'done', 'failed', 'interrupted'].indexOf(item.state) < 0) return false;
      var names = ['started_at', 'ended_at', 'blocked_since', 'duration_s'], k;
      for (k = 0; k < names.length; k++) if (item[names[k]] != null && (typeof item[names[k]] !== 'number' || !isFinite(item[names[k]]))) return false;
      return true;
    }
    if (next.mode !== 'idle' && !itemOk(next.focus)) return false;
    if (next.awaiting != null) { if (!Array.isArray(next.awaiting) || next.awaiting.length > 5) return false; lists.push(next.awaiting); }
    if (next.agents.length > 32 || next.queue.length > 5 || next.recent.length > 4) return false;
    for (i = 0; i < next.agents.length; i++) if (!next.agents[i] || typeof next.agents[i].state !== 'string') return false;
    for (i = 0; i < lists.length; i++) for (j = 0; j < lists[i].length; j++) if (!itemOk(lists[i][j])) return false;
    return true;
  }

  var api = {
    validView: validView, pad: pad, esc: esc, clock: clock, dateLine: dateLine, timer: timer, ago: ago, duration: duration,
    checksText: checksText, isNight: isNight, cue: cue, needs: needs, usageHtml: usageHtml, agendaHtml: agendaHtml, whenLabel: whenLabel, setLang: setLang, say: say, metaCells: metaCells, focusClock: focusClock,
    expireFraction: expireFraction, agentsHtml: agentsHtml, rowsHtml: rowsHtml
  };
  root.Tallyboard = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  /* ------------------------------------------------------------------ DOM */
  var el = {}, ids = ['idleClock', 'idleDate', 'idleLinkText', 'drift', 'topLink', 'topClock', 'demoTag', 'fTagText', 'fDetail', 'usage', 'idleAgenda',
    'fAgent', 'fProject', 'fTitle', 'fReason', 'fRaw', 'fTime', 'fTimeLabel', 'fMeta', 'cActive', 'cWaiting', 'cWaitingCell', 'cDone',
    'cProjects', 'agents', 'queue', 'queueHead', 'recent', 'recentHead', 'expireBar', 'rail', 'brand', 'awaiting', 'awaitHead',
    'idleAwaiting', 'focus'];
  var view = null, rev = null, build = null, offsetMs = 0, tzMs = 0, lastOk = 0, failures = 0, lost = false;
  function localTime() { return root.performance && typeof root.performance.now === 'function' ? root.performance.now() : Date.now(); }
  var loadedAt = localTime(), driftMinute = -1, lastBrightness = null, bodyClass = '', xhr = null;
  var demo = (/[?&]demo=([a-z]+)/.exec(location.search) || [])[1] || '';

  function text(node, value) {
    value = value == null ? '' : String(value);
    if (node._t !== value) { node._t = value; node.textContent = value; }
  }
  function html(node, value) { if (node._h !== value) { node._h = value; node.innerHTML = value; } }
  function show(node, on) { var v = on ? '' : 'none'; if (node._d !== v) { node._d = v; node.style.display = v; } }
  function nowMs() { return localTime() + offsetMs; }

  /* Fixed labels carry data-t="key" in the markup and are worded here. */
  var shownLang = null;
  function labels() {
    var nodes = document.querySelectorAll('[data-t]'), i;
    for (i = 0; i < nodes.length; i++) nodes[i].textContent = L[nodes[i].getAttribute('data-t')] || '';
    document.documentElement.lang = langCode;
  }

  function paintBody() {
    var mode = lost || !view ? 'idle' : view.mode;
    var cls = 'm-' + (mode === 'blocked' && view.alert === 'ambient' ? 'wait' : mode) + (lost ? ' lost' : '') + 
      (view && view.demo ? ' demo' : '') + (isNight(nowMs() + tzMs) ? ' night' : '') + (view && !lost && view.awaiting && view.awaiting.length ? ' has-wait' : '') +
      (mode === 'blocked' && view.focus && view.focus.reason_kind === 'input' ? ' k-input' : '');
    if (cls !== bodyClass) { bodyClass = cls; document.body.className = cls; }
    return mode;
  }

  function brightness(mode) {
    var b = view && view.brightness, level;
    if (!b || !root.fully || typeof root.fully.setScreenBrightness !== 'function') return;
    level = mode === 'blocked' && view.alert === 'ambient' && b.ambient != null ? b.ambient : b[mode] != null ? b[mode] : b.active;
    if (typeof level !== 'number' || level === lastBrightness) return;  /* strong -> ambient changes rev, so this re-runs */
    lastBrightness = level;
    try { root.fully.setScreenBrightness(Math.max(0, Math.min(255, level))); } catch (e) {}
  }

  function render() {
    var f = view.focus, mode = view.mode, cells, i, meta = '';
    text(el.demoTag, view.demo ? 'demo · ' + view.demo : '');
    text(el.cActive, view.counts.active);
    text(el.cWaiting, view.counts.waiting);
    text(el.cDone, view.counts.done);
    text(el.cProjects, view.counts.projects);
    el.cWaitingCell.className = view.counts.waiting ? 'on' : '';
    html(el.agents, agentsHtml(view.agents));
    el.queue.innerHTML = rowsHtml(view.queue, true);
    el.recent.innerHTML = rowsHtml(view.recent, false);
    el.awaiting.innerHTML = el.idleAwaiting.innerHTML = rowsHtml(view.awaiting || [], false);
    if (f && f.touch && view.touch) el.focus.setAttribute('data-id', f.id); else el.focus.removeAttribute('data-id');
    if (!f) return;
    text(el.fTagText, f.state === 'blocked' ? (f.reason_kind === 'input' ? L.tag_question : f.reason_kind === 'approval' ? L.tag_permission : L.tag_blocked) : L['tag_' + f.state] || L['tag_' + mode]);
    text(el.fDetail, mode === 'running' ? say(f.detail) : '');
    text(el.fAgent, f.agent_label);
    text(el.fProject, f.session_title || f.project || '');
    text(el.fTitle, f.title || f.summary || '');
    text(el.fReason, say(f.reason));
    text(el.fRaw, mode === 'failed' ? f.reason_raw : '');
    cells = metaCells(f, mode, tzMs);
    for (i = 0; i < cells.length; i++) meta += '<span class="cell"><span class="k">' + esc(cells[i].k) + '</span><span class="v">' + esc(cells[i].v) + '</span></span>';
    html(el.fMeta, meta);
  }

  /* The rail never scrolls: when the overview is taller than the screen, drop
     the least urgent rows (oldest results first, then extra live work). */
  function fitRail() {
    var lists = [el.recent, el.queue, el.awaiting], i, guard = 16;
    for (i = 0; i < lists.length; i++) {
      while (guard-- > 0 && lists[i].lastChild && el.rail.scrollHeight > el.rail.clientHeight + 1) lists[i].removeChild(lists[i].lastChild);
    }
    show(el.queueHead, el.queue.firstChild);
    show(el.recentHead, el.recent.firstChild);
    show(el.awaitHead, el.awaiting.firstChild);
  }

  function tick() {
    var ms = nowMs(), shown = ms + tzMs, nowS = ms / 1000, mode, fc, nodes, i, at, minute;
    if (!lost && localTime() - (lastOk || loadedAt) > LOST_MS) lost = true;
    mode = paintBody();
    text(el.idleClock, clock(shown));
    text(el.topClock, clock(shown));
    text(el.idleDate, dateLine(shown));
    text(el.idleLinkText, lost ? L.lost : !view ? L.connecting : L.online);

    minute = Math.floor(shown / 60000);
    if (minute !== driftMinute) {  /* nudge the idle clock so no pixel sits lit for days */
      driftMinute = minute;
      el.drift.style.webkitTransform = el.drift.style.transform =
        'translate(' + Math.round((minute * 7 % 9 - 4) * root.innerWidth / 200) + 'px,' + Math.round((minute * 5 % 7 - 3) * root.innerHeight / 200) + 'px)';
    }
    nodes = document.getElementsByClassName('rt');
    for (i = 0; i < nodes.length; i++) {
      at = parseFloat(nodes[i].getAttribute('data-at'));
      text(nodes[i], isNaN(at) ? '' : nodes[i].getAttribute('data-live') === '1' ? timer(nowS - at) : ago(nowS - at));
    }
    if (mode === 'idle') {
      /* old WebViews leak: start fresh once a night, only while nothing is on screen */
      if (!lost && localTime() - loadedAt > 72e6 && new Date(shown).getUTCHours() === 4) location.reload();
      return;
    }
    fc = focusClock(view.focus, mode, nowS);
    text(el.fTime, fc.text);
    text(el.fTimeLabel, fc.label);
    el.expireBar.style.webkitTransform = el.expireBar.style.transform = 'scaleX(' + expireFraction(view, nowS).toFixed(4) + ')';
  }

  function accept(next) {
    if (!validView(next)) return false;
    if (build && next.build && next.build !== build) { location.reload(); return; }  /* new deploy: pick it up unattended */
    build = next.build || build;
    offsetMs = next.now * 1000 - localTime();
    tzMs = (next.tz_offset_min || 0) * 60000;
    lastOk = localTime(); failures = 0; lost = false;
    view = next;
    if (next.lang !== shownLang) { shownLang = next.lang; setLang(next.lang); labels(); rev = null; lastUsage = lastAgenda = null; }
    var strip = usageHtml(next.usage, tzMs);
    if (strip !== lastUsage) { lastUsage = strip; el.usage.innerHTML = strip; }
    var plans = agendaHtml(next.agenda, nowMs(), tzMs);
    if (plans !== lastAgenda) { lastAgenda = plans; el.idleAgenda.innerHTML = plans; }
    var now = needs(next), ring = cue(heard, now);
    heard = now;
    if (ring && next.chime && !isNight(nowMs() + tzMs)) chime(ring);
    var fresh = next.rev !== rev;
    if (fresh) { rev = next.rev; render(); }
    tick();
    if (fresh && next.mode !== 'idle') { show(el.queueHead, true); show(el.recentHead, true); show(el.awaitHead, true); fitRail(); }
    brightness(next.mode);
    return true;
  }

  function schedule() {
    setTimeout(poll, failures ? BACKOFF_MS[Math.min(failures, BACKOFF_MS.length) - 1] : POLL_MS);
  }

  function poll() {
    var done = false, watchdog = null, x = xhr = new XMLHttpRequest();
    function finish(ok) { if (done) return; done = true; if (watchdog !== null) clearTimeout(watchdog); xhr = null; if (!ok) failures++; schedule(); }
    x.open('GET', '/api/state?t=' + Date.now() + (demo ? '&demo=' + demo : ''), true);
    x.timeout = XHR_TIMEOUT_MS;
    x.onload = function () {
      var ok = false;
      if (x.status === 200) { try { ok = accept(JSON.parse(x.responseText)) === true; } catch (e) {} }
      finish(ok);
    };
    x.onerror = x.ontimeout = x.onabort = function () { finish(false); };
    try { x.send(); } catch (e) { finish(false); }
    /* belt and braces: some old WebViews never fire ontimeout after Wi-Fi sleep */
    watchdog = setTimeout(function () { if (!done) { try { x.abort(); } catch (e) {} finish(false); } }, XHR_TIMEOUT_MS + 2000);
  }

  function send(path, id) {
    var x = new XMLHttpRequest();
    x.open('POST', path + '?id=' + encodeURIComponent(id), true);
    x.setRequestHeader('X-Tallyboard', '1');
    x.timeout = XHR_TIMEOUT_MS;
    try { x.send(); } catch (e) {}
  }

  /* Hold a "Sua vez" row to wave it away: it only leaves the list, nothing else changes. */
  var holdTimer = null, heldAt = 0;
  function holdEnd() { if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; } }
  function holdStart(event) {
    var node = event.target, id = null;
    holdEnd();
    while (node && node !== document.body && !(id = node.getAttribute && node.getAttribute('data-aw'))) node = node.parentNode;
    if (!id || !view || !view.touch) return;
    holdTimer = setTimeout(function () {
      holdTimer = null; heldAt = localTime();
      node.style.display = 'none';
      send('/api/dismiss', id);
    }, 800);
  }

  /* A tap asks the Mac to bring that session forward. */
  function onTap(event) {
    var node = event.target, id = null;
    if (localTime() - heldAt < 1200) return;  /* the click that ends a hold is not a tap */
    while (node && node !== document.body && !(id = node.getAttribute && node.getAttribute('data-id'))) node = node.parentNode;
    if (!id || !view || !view.touch) return;
    node.className += ' tap';
    setTimeout(function () { node.className = node.className.replace(' tap', ''); }, 700);
    send('/api/focus', id);
  }

  (function boot() {
    var i;
    for (i = 0; i < ids.length; i++) el[ids[i]] = document.getElementById(ids[i]);
    tick();
    setInterval(tick, 1000);
    document.addEventListener('click', onTap);
    document.addEventListener('touchstart', holdStart);
    document.addEventListener('touchend', holdEnd);
    document.addEventListener('touchmove', holdEnd);
    document.addEventListener('touchcancel', holdEnd);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { tick(); if (xhr) { try { xhr.abort(); } catch (e) {} } } });
    poll();
  })();
})(typeof window !== 'undefined' ? window : this);
