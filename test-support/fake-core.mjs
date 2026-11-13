// 가짜 herdr-core: 진짜 코어와 같은 한 줄 JSON-RPC를 유닉스 소켓으로 받는다. 실제 코어를 띄우지 않는 테스트용.
// 다룬 요청은 calls에 쌓인다. 터미널은 add()로 넣고 set()으로 바꾼다(바꾸면 구독자에게 event 한 줄이 간다).
import { createServer } from 'node:net'
import { existsSync, unlinkSync, writeFileSync } from 'node:fs'
import { pipeName } from '../src/platform.mjs'

export const term = (address, over = {}) => ({
  address, argv: ['/bin/zsh', '-l'], cols: 120, created_ms: 1794000000000 + Number(String(address).replace(/\D/g, '')), cwd: '/work', die_with_parent: false, exit_code: null,
  finished_ms: null, foreground: { argv: ['/bin/zsh', '-l'], cwd: '/work', name: 'zsh', pid: 70000 + Number(String(address).replace(/\D/g, '')) }, identity: 'test', keep: false, labels: {},
  name: null, notify: true, parent: null, pid: 60000 + Number(String(address).replace(/\D/g, '')), reason: null, reported: Boolean(over.status), rm: false, rows: 40, screen: 'exact',
  signal: null, state: 'live', status: null, status_ms: null, template: null, title: '', turn: 0, ...over,
  labels: { ...(over.labels || {}) },   // 터미널마다 자기 라벨 — 시험이 같은 객체를 여러 터미널에 넘겨도 서로 물들지 않게
})
// 에이전트가 도는 터미널: status = { app, state, kind?, msg? }
// turn: 갓 떠서 쉬는(idle) 에이전트는 0(아직 끝낸 턴이 없다), 그 밖에는 1. 끝낸 턴이 있는데 idle인 경우(Codex)는 turn을 직접 준다.
export const agentTerm = (address, state, over = {}) => term(address, {
  argv: ['zsh', '-ic', 'claude'], foreground: { argv: ['node', 'claude'], cwd: over.cwd || '/work', name: 'node', pid: 70000 + Number(String(address).replace(/\D/g, '')) },
  status: { app: 'claude-code', state, ...(over.kind ? { kind: over.kind } : {}), ...(over.msg ? { msg: over.msg } : {}) }, status_ms: 1794000100000, title: 'Claude Code', turn: state === 'idle' ? 0 : 1,
  ...Object.fromEntries(Object.entries(over).filter(([k]) => !['kind', 'msg'].includes(k))),
})

export function startFakeCore(path) {
  if (existsSync(path)) unlinkSync(path)
  const terminals = new Map()
  const screens = new Map()
  const calls = []
  const subs = new Set()
  let seq = 0
  let next = 1
  const emit = (type, terminal, data = {}) => { for (const s of subs) s.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type, terminal, seq: ++seq, data } })}\n`) }
  const notFound = (t) => ({ code: -32000, message: `no terminal "${t}"`, data: { kind: 'not_found', hint: 'see `hc ls --all`' } })
  const handle = (method, p, sock) => {
    calls.push({ method, params: p })
    const t = p.terminal ? terminals.get(p.terminal) : null
    if (['terminal.get', 'terminal.read', 'terminal.send', 'terminal.keys', 'terminal.kill', 'terminal.label'].includes(method) && !t) return { error: notFound(p.terminal) }
    switch (method) {
      case 'terminal.list': return { result: { hidden_finished: 0, terminals: [...terminals.values()].filter((x) => p.all || x.state === 'live') } }
      case 'terminal.get': return { result: t }
      case 'terminal.read': return { result: { complete: true, how: 'screen', text: screens.get(p.terminal) || '' } }
      case 'terminal.send': return { result: { started: null, status: t.status?.state ?? null, turn: t.turn } }
      case 'terminal.keys': return { result: { status: t.status?.state ?? null, turn: t.turn } }
      case 'terminal.label': Object.assign(t.labels, p.labels || {}); return { result: t }
      case 'terminal.kill': Object.assign(t, { state: 'finished', reason: 'killed', exit_code: 1, finished_ms: Date.now() }); emit('finished', t.address); return { result: t }
      case 'terminal.run': {
        while (terminals.has(`t${next}`)) next++
        const made = term(`t${next}`, { cwd: p.cwd || '/work', labels: { ...(p.labels || {}) }, created_ms: Date.now(), foreground: { argv: ['/bin/zsh', '-l'], cwd: p.cwd || '/work', name: 'zsh', pid: 80000 + next } })
        terminals.set(made.address, made); emit('created', made.address)
        return { result: made }
      }
      case 'events.subscribe': subs.add(sock); return { result: { channel: null, seq, terminals: [...terminals.values()] } }
      default: return { error: { code: -32601, message: `unknown method ${method}` } }
    }
  }
  const server = createServer((sock) => {
    let buf = ''
    sock.setEncoding('utf8')
    sock.on('data', (chunk) => {
      buf += chunk
      let i
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1)
        let req
        try { req = JSON.parse(line) } catch { continue }
        // 시험이 응답을 바꿔 끼운다: override(method, params, sock) → 문자열이면 그대로 쓰고, 'close'면 답 없이 끊고, false면 답하지 않는다.
        const forced = api.override ? api.override(req.method, req.params || {}, sock) : undefined
        if (forced === 'close') { sock.destroy(); continue }
        if (forced === false) continue
        if (typeof forced === 'string') { sock.write(forced); continue }
        sock.write(`${JSON.stringify({ jsonrpc: '2.0', id: req.id, ...handle(req.method, req.params || {}, sock) })}\n`)
      }
    })
    sock.on('close', () => subs.delete(sock)); sock.on('error', () => subs.delete(sock))
  })
  const api = { override: null }
  // 윈도우: 코어처럼 named pipe(\\.\pipe\<경로>)에서 듣고, 소켓 파일 자리에는 표시 파일을 둔다(available()가 그 파일을 본다 — herdr와 같은 규칙이라는 가정).
  const win = process.platform === 'win32'
  return new Promise((resolve) => server.listen(win ? pipeName(path) : path, () => { if (win) writeFileSync(path, 'fake-core'); resolve(Object.assign(api, {
    path, terminals, screens, calls,
    emitRaw(line) { for (const s of subs) s.write(line) },
    add(t) { terminals.set(t.address, t); emit('created', t.address); return t },
    set(address, patch) { Object.assign(terminals.get(address), patch); emit('status', address, { status: terminals.get(address).status }) },
    sent: () => calls.filter((c) => c.method === 'terminal.send').map((c) => [c.params.terminal, c.params.text]),
    // 끄면 소켓 자리도 비운다. 유닉스 소켓은 server.close가 파일을 지우지만, 윈도우의 표시 파일은 직접 지워야 한다
    // (남아 있으면 available()가 꺼진 코어를 켜진 것으로 본다 — 진짜 코어도 끝날 때 그 파일을 지운다는 가정).
    close: () => new Promise((r) => { for (const s of subs) s.destroy(); server.close(() => { if (win) { try { unlinkSync(path) } catch {} } r() }) }),
  })) }))
}
