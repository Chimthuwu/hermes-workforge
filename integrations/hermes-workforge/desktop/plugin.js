/**
 * HERMES WORKFORGE - Hermes Desktop plugin.
 *
 * Unified package half: installed at
 *   <hermes home>/plugins/hermes-workforge/desktop/plugin.js
 * and copied by the app into desktop-plugins/<id>/. It reads the same scoped
 * backend namespace as the web dashboard (/api/plugins/hermes-workforge/*)
 * through ctx.rest - never raw fetch, never a second source of truth.
 */
import {
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  PALETTE_AREA,
  STATUSBAR_AREAS,
  host
} from '@hermes/plugin-sdk'
import { useState, useEffect } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'hermes-workforge'
const PATH = '/workforge'

function tone(status) {
  if (status === 'completed') return 'text-emerald-400'
  if (status === 'running' || status === 'testing' || status === 'implementing') return 'text-sky-400'
  if (status === 'blocked') return 'text-amber-400'
  if (status === 'failed') return 'text-rose-400'
  return 'text-(--ui-text-tertiary)'
}

function WorkforgePage({ ctx }) {
  const [snap, setSnap] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    const load = () => ctx.rest('/snapshot')
      .then(data => { if (alive) { setSnap(data); setError('') } })
      .catch(err => { if (alive) setError(String(err?.message || err)) })
    load()
    const timer = setInterval(load, 3000)
    return () => { alive = false; clearInterval(timer) }
  }, [ctx])

  const o = snap?.overall || {}
  const project = snap?.projects || []
  const attention = snap?.attention || []

  return jsxs('div', {
    className: 'flex h-full flex-col gap-4 overflow-y-auto p-5 text-sm',
    children: [
      jsxs('div', {
        className: 'flex items-start justify-between gap-3',
        children: [
          jsxs('div', {
            children: [
              jsx('h1', { className: 'text-lg font-semibold tracking-tight', children: 'HERMES // WORKFORGE' }),
              jsx('p', {
                className: 'text-xs text-(--ui-text-tertiary)',
                children: 'Mission control - the collector owns state; this page only observes it.'
              })
            ]
          }),
          jsx('span', {
            className: 'rounded-full border px-2 py-0.5 text-[11px] ' + (error ? 'border-rose-500/40 text-rose-400' : 'border-emerald-500/40 text-emerald-400'),
            children: error ? 'OFFLINE' : 'LIVE'
          })
        ]
      }),
      error
        ? jsxs('div', {
            className: 'rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-300',
            children: [
              'Collector unreachable (', error, '). Start it with ',
              jsx('code', { children: 'python -m workforge serve' }),
              '. Workers keep running; this page reconnects automatically.'
            ]
          })
        : null,
      snap?.session?.id
        ? jsxs('div', {
            className: 'grid grid-cols-2 gap-3 lg:grid-cols-4',
            children: [
              jsxs('div', { className: 'rounded-xl border border-border p-3', children: [
                jsx('div', { className: 'text-[11px] uppercase text-(--ui-text-tertiary)', children: 'progress' }),
                jsx('div', { className: 'mt-1 text-2xl font-semibold tabular-nums', children: `${o.progress || 0}%` })
              ] }),
              jsxs('div', { className: 'rounded-xl border border-border p-3', children: [
                jsx('div', { className: 'text-[11px] uppercase text-(--ui-text-tertiary)', children: 'projects' }),
                jsx('div', { className: 'mt-1 text-2xl font-semibold tabular-nums', children: o.projects_total || 0 })
              ] }),
              jsxs('div', { className: 'rounded-xl border border-border p-3', children: [
                jsx('div', { className: 'text-[11px] uppercase text-(--ui-text-tertiary)', children: 'workers active' }),
                jsx('div', { className: 'mt-1 text-2xl font-semibold tabular-nums', children: `${o.workers_active || 0}/${o.workers_total || 0}` })
              ] }),
              jsxs('div', { className: 'rounded-xl border border-border p-3', children: [
                jsx('div', { className: 'text-[11px] uppercase text-(--ui-text-tertiary)', children: 'attention' }),
                jsx('div', { className: 'mt-1 text-2xl font-semibold tabular-nums', children: attention.length })
              ] })
            ]
          })
        : null,
      project.length
        ? jsxs('section', {
            className: 'rounded-xl border border-border',
            children: [
              jsx('h2', { className: 'border-b border-border px-4 py-2.5 text-sm font-semibold', children: 'Projects' }),
              jsx('div', {
                className: 'divide-y divide-border/60',
                children: project.map(p => jsxs('div', {
                  key: p.project_id,
                  className: 'flex items-center gap-3 px-4 py-3',
                  children: [
                    jsx('span', { className: 'min-w-0 flex-1 truncate', children: p.name || p.project_id }),
                    jsx('span', { className: 'text-xs text-(--ui-text-tertiary)', children: p.current_task || '-' }),
                    jsx('span', { className: `text-xs font-medium ${tone(p.status)}`, children: String(p.status || '').toUpperCase() }),
                    jsx('span', { className: 'w-10 text-right text-xs tabular-nums', children: `${p.progress || 0}%` })
                  ]
                }))
              })
            ]
          })
        : null,
      attention.length
        ? jsxs('section', {
            className: 'rounded-xl border border-border',
            children: [
              jsx('h2', { className: 'border-b border-border px-4 py-2.5 text-sm font-semibold', children: 'Attention' }),
              jsx('div', {
                className: 'divide-y divide-border/60',
                children: attention.map((a, i) => jsxs('div', {
                  key: i,
                  className: 'px-4 py-3 text-xs',
                  children: [
                    jsx('div', { className: 'font-medium', children: `${a.project} / ${a.worker}` }),
                    jsx('div', { className: 'text-(--ui-text-tertiary)', children: a.reason }),
                    jsx('div', { className: 'text-(--ui-text-tertiary)', children: a.action })
                  ]
                }))
              })
            ]
          })
        : null,
      snap?.latest_events?.length
        ? jsxs('section', {
            className: 'rounded-xl border border-border',
            children: [
              jsx('h2', { className: 'border-b border-border px-4 py-2.5 text-sm font-semibold', children: 'Latest events' }),
              jsx('div', {
                className: 'p-4 font-mono text-[11px]',
                children: snap.latest_events.slice().reverse().map((e, i) => jsxs('div', {
                  key: e.event_id || i,
                  className: 'flex gap-2 py-0.5',
                  children: [
                    jsx('span', { className: 'text-(--ui-text-tertiary)', children: String(e.timestamp || '').slice(11, 19) }),
                    jsx('span', { className: 'text-sky-400', children: e.project_id }),
                    jsx('span', { children: e.event + (e.message ? ' - ' + e.message : '') })
                  ]
                }))
              })
            ]
          })
        : null
    ]
  })
}

function WorkforgeStatus({ ctx }) {
  const [online, setOnline] = useState(false)
  useEffect(() => {
    let alive = true
    const check = () => ctx.rest('/status')
      .then(s => { if (alive) setOnline(!!s.reachable) })
      .catch(() => { if (alive) setOnline(false) })
    check()
    const timer = setInterval(check, 10000)
    return () => { alive = false; clearInterval(timer) }
  }, [ctx])
  return jsx('button', {
    type: 'button',
    title: `Workforge collector ${online ? 'online' : 'offline'}`,
    onClick: () => host.navigate(PATH),
    className: 'inline-flex h-full items-center gap-1.5 px-2 text-[11px] text-(--ui-text-tertiary) hover:text-foreground',
    children: [
      jsx('span', {
        className: online ? 'text-emerald-400' : 'text-rose-400',
        children: online ? '●' : '○'
      }),
      'WF'
    ]
  })
}

export default {
  id: ID,
  name: 'Hermes Workforge',
  register(ctx) {
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: PATH },
        render: () => jsx(WorkforgePage, { ctx })
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: PATH, label: 'Workforge', codicon: 'pulse' }
      },
      {
        id: 'palette',
        area: PALETTE_AREA,
        data: {
          id: 'workforge.open',
          label: 'Open Workforge Mission Control',
          keywords: ['workforge', 'mission', 'workers', 'monitor'],
          run: () => host.navigate(PATH)
        }
      },
      {
        id: 'status',
        area: STATUSBAR_AREAS.right,
        order: 135,
        render: () => jsx(WorkforgeStatus, { ctx })
      }
    ])
  }
}
