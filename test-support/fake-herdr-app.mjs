#!/usr/bin/env node
// 가짜 herdr-app: 받은 인자를 FAKE_APP_LOG에 한 줄씩 적고, 가짜 코어(HC_SOCKET)의 터미널을 Herdr 앱처럼 다룬다.
// FAKE_APP_MODE=no_window 이면 진짜처럼 "no Herdr window" 를 내고 종료 코드 2로 끝난다(앱이 꺼져 있는 경우).
// FAKE_APP_PROBE=<파일> 이면 space.close를 받은 순간 그 파일의 내용을 <파일>.at-close 에 적어 둔다(닫기 전에 무엇이 적혀 있었는지 보는 용도).
// 공간 = 터미널 라벨 herdr.space, 이름 = 라벨 where 의 " / " 앞.
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { createConnection } from 'node:net'
import { connectTarget } from '../src/platform.mjs'

const args = process.argv.slice(2)
if (process.env.FAKE_APP_LOG) appendFileSync(process.env.FAKE_APP_LOG, `${JSON.stringify(args)}\n`)
if (process.env.FAKE_APP_MODE === 'no_window') { process.stderr.write('herdr-app: no Herdr window at /nowhere/herdr-app.sock: No such file or directory (os error 2)\n'); process.exit(2) }

const rpc = (method, params = {}) => new Promise((resolve, reject) => {
  const sock = createConnection(connectTarget(process.env.HC_SOCKET))   // 윈도우는 named pipe
  let buf = ''
  sock.setEncoding('utf8')
  sock.on('connect', () => sock.write(`${JSON.stringify({ jsonrpc: '2.0', id: 1, method, params })}\n`))
  sock.on('data', (c) => { buf += c; const i = buf.indexOf('\n'); if (i < 0) return; sock.destroy(); const r = JSON.parse(buf.slice(0, i)); r.error ? reject(new Error(r.error.message)) : resolve(r.result) })
  sock.on('error', reject)
})
const fail = (msg) => { process.stderr.write(`herdr-app: ${msg}\n`); process.exit(1) }
const live = async () => (await rpc('terminal.list', {})).terminals.filter((t) => t.state === 'live')
const nameOf = (t) => { const w = t.labels?.where || ''; const i = w.lastIndexOf(' / '); return i > 0 ? w.slice(0, i) : null }

if (args[0] === 'ls') {
  const spaces = new Map()
  for (const t of await live()) {
    const id = t.labels?.['herdr.space']
    if (!id) continue
    if (!spaces.has(id)) spaces.set(id, { id, name: nameOf(t), folder: process.env.FAKE_APP_FOLDER || t.cwd, machine: null, active: false, tabs: [] })
    spaces.get(id).tabs.push({ id: t.labels['herdr.tab'] || `tb-${t.address}`, name: '1', active: false, settled: true, terminals: [{ terminal: t.address, pane: `pe-${t.address}`, status: t.status?.state ?? null, app: t.status?.app ?? null, name: t.name, sub_agents: [] }] })
  }
  process.stdout.write(JSON.stringify({ spaces: [...spaces.values()], recent: [] }))
} else if (args[0] === 'do') {
  const cmd = args[1]
  const a = args[2] ? JSON.parse(args[2]) : {}
  const all = await live()
  if (cmd === 'pane.focus') { if (!all.find((t) => t.address === a.terminal && t.labels?.['herdr.space'])) fail(`no pane shows ${a.terminal}`) }
  else if (cmd === 'terminal.keep') { if (process.env.FAKE_APP_NO_KEEP) fail('cannot keep'); await rpc('terminal.label', { terminal: a.terminal, labels: { 'herdr.space': 'spkept', 'herdr.tab': 'tbkept', where: 'kept / 1' } }) }
  else if (cmd === 'tab.new') {
    const mate = all.find((t) => t.labels?.['herdr.space'] === a.space)
    if (!mate) fail(`no space ${a.space}`)
    await rpc('terminal.run', { cwd: a.folder, labels: { 'herdr.space': a.space, 'herdr.tab': `tb-new-${Date.now()}`, where: `${nameOf(mate) || 'space'} / new` } })
  } else if (cmd === 'space.new') {
    const id = `spnew${Date.now()}`
    await rpc('terminal.run', { cwd: a.folder, labels: { 'herdr.space': id, 'herdr.tab': `tb-${id}`, where: `${a.name || 'new'} / 1` } })
  } else if (cmd === 'space.close') {
    if (process.env.FAKE_APP_PROBE) writeFileSync(`${process.env.FAKE_APP_PROBE}.at-close`, existsSync(process.env.FAKE_APP_PROBE) ? readFileSync(process.env.FAKE_APP_PROBE, 'utf8') : '')
    for (const t of all.filter((x) => x.labels?.['herdr.space'] === a.id)) await rpc('terminal.kill', { terminal: t.address })
  } else if (cmd === 'pane.close') { await rpc('terminal.kill', { terminal: String(a.pane).replace(/^pe-/, '') }) }
  else fail(`unknown command ${cmd}`)
  process.stdout.write('{}')
} else fail(`unknown argument "${args.join(' ')}"`)
