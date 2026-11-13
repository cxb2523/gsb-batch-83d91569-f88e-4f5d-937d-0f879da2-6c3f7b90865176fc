import { exec as execNative } from 'node:child_process'
import { readdirSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const promisifiedExec = promisify(execNative)

export const validPackagesNames = ['puppeteer-core', 'playwright-core']

export const exec = async (...args) => {
  if (isDebug()) {
    log('[debug][exec]', args)
  }

  const execRes = await promisifiedExec(...args)

  if (isDebug()) {
    log('[debug][execRes]', execRes)
  }

  return execRes
}
export const log = console.log

export const getPatcherPackagePath = () => {
  return resolve(dirname(fileURLToPath(import.meta.url)), '../..')
}

export const fatalError = (...args) => {
  console.error('❌ FATAL ERROR:', ...args)
  process.exit(1)
}

export const getPatchBaseCmd = (patchFilePath) => {
  return `patch --batch -p1 --input=${patchFilePath} --verbose --no-backup-if-mismatch --reject-file=- --forward --silent`
}

// Compare two "x.y.z" (or "x.y.z-tag") versions. Returns <0, 0, >0.
// The numeric x.y.z decides; a version without a pre-release tag ranks above one with a tag.
const compareVersions = (a, b) => {
  const parse = (v) => {
    const [core, ...pre] = String(v).split('-')
    const nums = core.split('.').map((n) => parseInt(n, 10) || 0)
    return { nums, pre: pre.join('-') }
  }
  const pa = parse(a)
  const pb = parse(b)
  for (let i = 0; i < Math.max(pa.nums.length, pb.nums.length); i++) {
    const diff = (pa.nums[i] || 0) - (pb.nums[i] || 0)
    if (diff) return diff
  }
  if (pa.pre === pb.pre) return 0
  if (!pa.pre) return 1
  if (!pb.pre) return -1
  return pa.pre < pb.pre ? -1 : 1
}

const patchFilePath = (packageName, version, codeTarget) => {
  return resolve(getPatcherPackagePath(), `./patches/${packageName}/${version}/${codeTarget}.patch`)
}

const hasPatchFile = (packageName, version, codeTarget) => {
  return existsSync(patchFilePath(packageName, version, codeTarget))
}

// List the versioned patch directories for a package, newest first.
export const listPatchVersions = (packageName) => {
  const dir = resolve(getPatcherPackagePath(), `./patches/${packageName}`)
  if (!existsSync(dir)) return []
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort((a, b) => compareVersions(b, a))
}

// Pick the patch version directory to try for an installed package version, in order:
// 1) exact match, 2) newest with the same major.minor, 3) newest overall.
//
// matchKind records which of those steps won:
//   exact      - there is a patch directory for exactly this version
//   same-minor - fallback level 1: newest patch with the same major.minor
//   newest     - fallback level 2: newest patch overall
//   none       - no patch file for this package/codeTarget at all
//
// The match kind and the selected version are derived from the patch directories on disk (see
// listPatchVersions) and from whether that directory actually contains <codeTarget>.patch -- never hardcoded.
// Returns a descriptor:
//   { version, path, exact, matchKind, fallbackLevel, installedVersion, codeTarget }
// matchKind is 'none' (and path/version are null) when there is no usable patch file at all.
export const resolvePatchVersion = (packageName, installedVersion, codeTarget) => {
  const installed = String(installedVersion)
  const versions = listPatchVersions(packageName)
  const has = (v) => hasPatchFile(packageName, v, codeTarget)
  const pick = (version, matchKind, fallbackLevel) => ({
    version,
    path: patchFilePath(packageName, version, codeTarget),
    exact: version === installed,
    matchKind,
    fallbackLevel,
    installedVersion: installed,
    codeTarget,
  })

  if (versions.includes(installed) && has(installed)) return pick(installed, 'exact', 0)

  const [maj, min] = installed.split('.')
  const sameMinor = versions.filter((v) => {
    const [vMaj, vMin] = v.split('.')
    return vMaj === maj && vMin === min && has(v)
  })
  if (sameMinor.length) return pick(sameMinor[0], 'same-minor', 1)

  const anyWithTarget = versions.filter(has)
  if (anyWithTarget.length) return pick(anyWithTarget[0], 'newest', 2)

  return {
    version: null,
    path: null,
    exact: false,
    matchKind: 'none',
    fallbackLevel: null,
    installedVersion: installed,
    codeTarget,
  }
}

// Human-readable fallback level for the selected patch, derived from the match kind.
export const describePatchMatch = (resolved) => {
  switch (resolved?.matchKind) {
    case 'exact':
      return 'no fallback (exact version match)'
    case 'same-minor':
      return `fallback level 1: newest patch for the same major.minor (${resolved.installedVersion.split('.').slice(0, 2).join('.')}.x)`
    case 'newest':
      return 'fallback level 2: newest patch overall'
    case 'none':
      return 'no patch available'
    default:
      return 'unknown fallback'
  }
}

export const isDebug = () => {
  return !!process.env.REBROWSER_PATCHES_DEBUG
}
