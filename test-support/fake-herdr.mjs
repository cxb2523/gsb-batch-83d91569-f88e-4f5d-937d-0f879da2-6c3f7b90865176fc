#!/usr/bin/env node
// 가짜 herdr(node 스크립트): 실행 중 세션 없음. 실제 herdr를 띄우지 않는 시험용. whosup은 .mjs 실행 파일을 지금 도는
// node로 돌린다(src/platform.mjs commandFor) — 윈도우에서도 shebang 없이 같은 방식으로 돈다. 예전 셸 스크립트판 가짜 herdr를 대신한다.
const a = process.argv.slice(2).join(' ')
if (a === '--version') console.log('herdr 0.0.0-fake')
else if (a === 'session list --json') console.log('{"sessions":[]}')
else if (a === 'session list') console.log('NAME STATUS DIRECTORY SOCKET')
else if (a.includes('pane read')) console.log('FAKE PANE SCREEN')
else { process.stderr.write(`fake herdr: ${a}\n`); process.exitCode = 1 }
