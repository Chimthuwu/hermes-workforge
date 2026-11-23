/**
 * HERMES WORKFORGE - Hermes Web Dashboard plugin.
 *
 * Plain IIFE, no build step. Uses the host SDK globals (React + auth-aware
 * fetch) and the plugin's own backend at /api/plugins/hermes-workforge/.
 * The collector owns all state; this bundle only renders it.
 */
(function () {
  'use strict'

  var SDK = window.__HERMES_PLUGIN_SDK__
  var REG = window.__HERMES_PLUGINS__
  if (!SDK || !REG) return

  var React = SDK.React
  var h = React.createElement
  var useState = SDK.hooks.useState
  var useEffect = SDK.hooks.useEffect
  var useCallback = SDK.hooks.useCallback
  var BASE = '/api/plugins/hermes-workforge'

  function getJSON(path, init) { return SDK.fetchJSON(BASE + path, init) }

  var TONES = {
    green: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
    blue: 'border-sky-500/30 bg-sky-500/10 text-sky-400',
    amber: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
    red: 'border-rose-500/30 bg-rose-500/10 text-rose-400',
    slate: 'border-border bg-muted/40 text-muted-foreground'
  }

  function statusTone(status) {
    if (status === 'completed') return 'green'
    if (status === 'running' || status === 'implementing' || status === 'testing') return 'blue'
    if (status === 'blocked') return 'amber'
    if (status === 'failed') return 'red'
    return 'slate'
  }

  function Pill(props) {
    return h('span', {
      className: 'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ' + (TONES[props.tone] || TONES.slate)
    }, props.children)
  }

  function Bar(props) {
    var p = Math.max(0, Math.min(100, Number(props.value) || 0))
    return h('div', { className: 'h-1.5 w-full overflow-hidden rounded-full bg-muted' },
      h('div', {
        className: 'h-full rounded-full bg-emerald-500 transition-all duration-500',
        style: { width: p + '%' }
      }))
  }

  function Stat(props) {
    return h('div', { className: 'rounded-xl border border-border bg-card p-3' },
      h('div', { className: 'text-[11px] uppercase tracking-wide text-muted-foreground' }, props.label),
      h('div', { className: 'mt-1 text-2xl font-semibold tabular-nums' }, props.value),
      props.sub ? h('div', { className: 'mt-1 text-[11px] text-muted-foreground' }, props.sub) : null)
  }

  function Card(props) {
    return h('section', { className: 'rounded-xl border border-border bg-card' },
      h('header', { className: 'flex items-center justify-between border-b border-border px-4 py-2.5' },
        h('h2', { className: 'text-sm font-semibold' }, props.title),
        props.right || null),
      h('div', { className: 'p-4' }, props.children))
  }

  function WorkforgeTab() {
    var snapPair = useState(null)
    var snap = snapPair[0], setSnap = snapPair[1]
    var statusPair = useState(null)
    var status = statusPair[0], setStatus = statusPair[1]
    var errorPair = useState('')
    var error = errorPair[0], setError = errorPair[1]
    var pendingPair = useState('')
    var pending = pendingPair[0], setPending = pendingPair[1]
    var confirmPair = useState(false)
    var confirm = confirmPair[0], setConfirm = confirmPair[1]

    var load = useCallback(function () {
      return getJSON('/status').then(function (s) {
        setStatus(s)
        if (!s.reachable) { setSnap(null); return null }
        return getJSON('/snapshot').then(function (d) { setSnap(d); setError(''); return d })
      }).catch(function (e) {
        setStatus({ reachable: false, error: String((e && e.message) || e) })
        setSnap(null)
      })
    }, [])

    useEffect(function () {
      load()
      var id = setInterval(load, 3000)
      return function () { clearInterval(id) }
    }, [load])

    function act(action) {
      if (action === 'cancel' && !confirm) { setConfirm(true); return }
      var sid = snap && snap.session && snap.session.id
      if (!sid) return
      setPending(action)
      getJSON('/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session: sid, target: sid, action: action, requested_by: 'dashboard' })
      }).then(load).catch(function (e) { setError(String((e && e.message) || e)) })
        .then(function () { setPending(''); setConfirm(false) })
    }

    var live = h(Pill, { tone: status && status.reachable ? 'green' : 'red' },
      status && status.reachable ? '● LIVE' : '○ OFFLINE')
    var head = h('div', { className: 'flex flex-wrap items-center justify-between gap-3' },
      h('div', {},
        h('h1', { className: 'text-xl font-semibold tracking-tight' }, 'HERMES // WORKFORGE'),
        h('p', { className: 'text-xs text-muted-foreground' },
          'Mission control · one event stream across CLI, Discord, dashboard and Desktop')),
      live)

    var banners = []
    if (status && !status.reachable) {
      banners.push(h('div', {
        className: 'rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300'
      }, 'Workforge collector is offline. Start it with ',
        h('code', { className: 'rounded bg-black/30 px-1 py-0.5' }, 'python -m workforge serve'),
        ' (default 127.0.0.1:8765). Workers keep running - interfaces can reconnect.'))
    }
    if (error) {
      banners.push(h('div', { className: 'rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-300' }, error))
    }

    if (!snap || !snap.session || !snap.session.id) {
      return h('div', { className: 'workforge-root flex h-full flex-col gap-4 overflow-y-auto p-5' },
        head, banners,
        h(Card, { title: 'No session yet' },
          h('p', { className: 'text-sm text-muted-foreground' },
            'Waiting for the first Workforge event. Emit from a worker with EventReporter, or run the demo:'),
          h('code', { className: 'mt-3 block rounded bg-muted px-3 py-2 text-xs' },
            'python examples/demo_session.py --fast')))
    }

    var o = snap.overall || {}
    var stats = h('div', { className: 'grid grid-cols-2 gap-3 lg:grid-cols-4' },
      h(Stat, { label: 'Plan progress', value: (o.progress || 0) + '%',
        sub: (o.tasks_completed || 0) + ' / ' + (o.tasks_total || 0) + ' weighted tasks' }),
      h(Stat, { label: 'Projects', value: o.projects_total || 0,
        sub: (o.verified || 0) + ' verified · ' + (o.committed || 0) + ' committed' }),
      h(Stat, { label: 'Workers', value: (o.workers_active || 0) + ' / ' + (o.workers_total || 0),
        sub: (o.events || 0) + ' events recorded' }),
      h(Stat, { label: 'Attention', value: (snap.attention || []).length,
        sub: 'blocked / stalled - investigate, never auto-kill' }))

    var controls = h('div', { className: 'flex flex-wrap items-center gap-2' },
      h('span', { className: 'mr-1 text-xs text-muted-foreground' }, 'Control requests:'),
      ['pause', 'resume', 'cancel'].map(function (action) {
        return h('button', {
          key: action,
          type: 'button',
          disabled: !!pending,
          onClick: function () { act(action) },
          className: 'rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50 ' +
            (action === 'cancel' && confirm ? 'border-rose-500 text-rose-400' : '')
        }, pending === action ? 'sending…' : (action === 'cancel' && confirm ? 'confirm cancel?' : action))
      }),
      h('span', { className: 'text-[11px] text-muted-foreground' },
        'recorded for the orchestrator - never a direct process kill'))

    var projects = h(Card, { title: 'Projects', right: h(Pill, { tone: 'slate' }, snap.session.id) },
      h('div', { className: 'flex flex-col gap-3' },
        (snap.projects || []).map(function (p) {
          return h('div', { key: p.project_id, className: 'rounded-lg border border-border/60 p-3' },
            h('div', { className: 'flex items-center justify-between gap-2' },
              h('span', { className: 'truncate text-sm font-medium' }, p.name || p.project_id),
              h(Pill, { tone: statusTone(p.status) }, String(p.status || 'queued').toUpperCase())),
            h('div', { className: 'mt-2 flex items-center gap-3' },
              h(Bar, { value: p.progress }),
              h('span', { className: 'w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground' },
                (p.progress || 0) + '%')),
            h('div', { className: 'mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground' },
              h('span', { className: 'truncate' }, p.current_task || 'no current task'),
              p.verified ? h(Pill, { tone: 'green' }, 'verified') : null,
              p.committed ? h(Pill, { tone: 'blue' }, 'committed' + (p.commit ? ' ' + p.commit.slice(0, 7) : '')) : null))
        })))

    var attention = h(Card, { title: 'Attention', right: h(Pill, { tone: (snap.attention || []).length ? 'amber' : 'green' },
      (snap.attention || []).length + ' item(s)') },
      (snap.attention || []).length
        ? h('div', { className: 'flex flex-col gap-2' }, snap.attention.map(function (a, i) {
          return h('div', { key: i, className: 'rounded-lg border border-border/60 p-3 text-xs' },
            h('div', { className: 'flex items-center gap-2' },
              h(Pill, { tone: a.level === 'critical' ? 'red' : 'amber' }, a.level),
              h('span', { className: 'font-medium' }, a.project + ' / ' + a.worker)),
            h('div', { className: 'mt-1.5 text-muted-foreground' }, a.reason),
            h('div', { className: 'mt-1 text-muted-foreground' }, a.action))
        }))
        : h('p', { className: 'text-sm text-muted-foreground' }, 'No blocked or stalled workers.'))

    var events = h(Card, { title: 'Live event stream', right: h('span', { className: 'text-[11px] text-muted-foreground' }, 'latest 8') },
      h('div', { className: 'flex flex-col gap-1.5 font-mono text-[11px]' },
        (snap.latest_events || []).slice().reverse().map(function (e, i) {
          return h('div', { key: e.event_id || i, className: 'flex gap-2 rounded px-2 py-1 hover:bg-muted/40' },
            h('span', { className: 'shrink-0 text-muted-foreground' },
              String(e.timestamp || '').slice(11, 19)),
            h('span', { className: 'shrink-0 text-sky-400' }, e.project_id || ''),
            h('span', { className: 'truncate text-foreground/80' },
              e.event + (e.message ? ' — ' + e.message : '')))
        })))

    return h('div', { className: 'workforge-root flex h-full flex-col gap-4 overflow-y-auto p-5' },
      head, banners, stats, controls,
      h('div', { className: 'grid gap-4 xl:grid-cols-2' }, projects,
        h('div', { className: 'flex flex-col gap-4' }, attention, events)))
  }

  REG.register('hermes-workforge', WorkforgeTab)
})()
