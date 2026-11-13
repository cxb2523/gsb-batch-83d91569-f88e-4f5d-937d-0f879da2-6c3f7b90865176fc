// 운영체제 판단은 process.platform 하나로 한다(파일에 저장한 감지 결과로 분기하지 않는다).
// 시험만 _setPlatform으로 다른 값을 넣어 윈도우 분기를 맥·리눅스에서도 돌린다.
let override = null
export const platform = () => override || process.platform
export const isWindows = () => platform() === 'win32'
export const _setPlatform = (p) => { override = p || null }

// 윈도우의 herdr는 소켓 경로를 이름으로 한 named pipe(\\.\pipe\<경로>)에서 듣는다(Windows 실기기 실측, 3abbb93).
// 소켓 파일 자리에는 pid:nonce만 들어 있다. 이미 pipe 이름이면 그대로 둔다.
const PIPE = '\\\\.\\pipe\\'
export const pipeName = (socket) => (String(socket).startsWith(PIPE) ? String(socket) : `${PIPE}${socket}`)
export const connectTarget = (socket) => (isWindows() ? pipeName(socket) : socket)

// 실행 파일이 node 스크립트(.mjs·.js)면 지금 도는 node로 돌린다. 윈도우는 shebang을 읽지 않기 때문이다
// (시험의 가짜 herdr·herdr-app이 이 경우다). 그 밖에는 그대로 실행한다.
export const commandFor = (file, args = []) => (/\.m?js$/i.test(String(file)) ? [process.execPath, [file, ...args]] : [file, args])

// PowerShell 작은따옴표 문자열: 안의 ' 는 '' 로 겹친다. 그 밖의 글자는 그대로 글자로 읽힌다.
export const psQuote = (s) => `'${String(s).replace(/'/g, "''")}'`
