#! /usr/bin/env node

import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'

import {
  describePatchMatch,
  exec,
  getPatchBaseCmd,
  log,
  resolvePatchVersion,
  validPackagesNames,
} from './utils/index.js';

// Everything the run must account for, reported line by line.
const report = {
  installedVersion: null,
  selectedVersion: null,
  matchKind: null,
  codeTarget: null,
  patchStatus: null,
  result: null,
  resolved: null,
}

const logSelection = () => {
  const r = report.resolved
  log('Patch selection:')
  log(`  installed version = ${report.installedVersion === null ? 'unknown' : report.installedVersion}`)
  log(`  selected version = ${report.selectedVersion === null ? 'none' : report.selectedVersion}`)
  log(`  match kind = ${report.matchKind === null ? 'none' : report.matchKind}`)
  log(`  codeTarget = ${report.codeTarget}`)
  if (r && (r.matchKind === 'same-minor' || r.matchKind === 'newest')) {
    log(`  ${describePatchMatch(r)}`)
  }
}

const STATUS_ICONS = { patched: '🟩', unpatched: '🟧', unknown: '⬜' }

let statusLogged = false
const logPatchStatus = () => {
  statusLogged = true
  const icon = STATUS_ICONS[report.patchStatus] || STATUS_ICONS.unknown
  log(`Current patch status = ${icon} ${report.patchStatus}`)
}

// Ensure the status line is printed exactly once per run, even on an early abort.
const ensurePatchStatusLogged = (status) => {
  if (statusLogged) return
  if (report.patchStatus === null) report.patchStatus = status
  logPatchStatus()
}

const resultText = {
  success: '🟢 success',
  'nothing changed': '🟡 nothing changed',
  error: '🔴 error',
}

// Print the final outcome and exit with its exit code: error -> 1, everything else -> 0.
const finish = (result) => {
  report.result = result
  log(`Result: ${resultText[result]}`)
  process.exit(result === 'error' ? 1 : 0)
}

// Abort with an error outcome: the fatal message, then the error result line, then exit 1.
const abort = (message, detail) => {
  report.result = 'error'
  console.error('❌ FATAL ERROR:', message)
  if (detail) console.error(detail)
  log(`Result: ${resultText.error}`)
  process.exit(1)
}

// An unexpected throw (e.g. an exact patch that doesn't apply) keeps its original error, but still
// ends the run with the "error" result line and exit code 1.
const onFatalThrow = (err) => {
  report.result = 'error'
  console.error(err)
  log(`Result: ${resultText.error}`)
  process.exit(1)
}
process.on('uncaughtException', onFatalThrow)
process.on('unhandledRejection', onFatalThrow)

;(async () => {
  // config and preparations
  const cliArgs = yargs(hideBin(process.argv))
    .usage('Usage: <command> [options]')
    .command('patch', 'Apply patch')
    .command('unpatch', 'Reverse patch')
    .command('check', 'Check if patch is already applied')
    .describe('packageName', `Target package name: ${validPackagesNames.join(', ')}`)
    .describe('packagePath', 'Path to the target package')
    .describe('codeTarget', 'What code to patch: src or lib')
    .boolean('debug')
    .describe('debug', 'Enable debugging mode')
    .demandCommand(1, 1, 'Error: choose a command (patch, unpatch, check)')
    .parse()

  let {
    packageName,
    packagePath,
    codeTarget = 'lib',
    debug,
  } = cliArgs

  if (debug) {
    process.env.REBROWSER_PATCHES_DEBUG = 1
  }

  const command = cliArgs._[0]

  if (!packagePath && !packageName) {
    abort('You need to specify either packageName or packagePath.')
  }

  if (!packagePath) {
    packagePath = `${process.cwd()}/node_modules/${packageName}`
  }

  if (!['patch', 'unpatch', 'check'].includes(command)) {
    abort(`Unknown command: ${command}`)
  }

  if (!['src', 'lib'].includes(codeTarget)) {
    abort(`Unknown codeTarget: ${codeTarget}`)
  }

  log('Config:')
  log(`command = ${command}, packageName = ${packageName}, codeTarget = ${codeTarget}`)
  log(`packagePath = ${packagePath}`)
  log('------')

  // find package
  let packageJson
  const packageJsonPath = resolve(packagePath, 'package.json')
  try {
    const packageJsonText = await readFile(packageJsonPath, { encoding: 'utf8' })
    packageJson = JSON.parse(packageJsonText)
  } catch (err) {
    abort('Cannot read package.json', err)
  }
  if (!packageName) {
    if (!validPackagesNames.includes(packageJson.name)) {
      abort(`Package name is "${packageJson.name}", but we only support ${validPackagesNames.join(', ')}.`)
    } else {
      packageName = packageJson.name
    }
  } else if (packageJson.name !== packageName) {
    abort(`Package name is "${packageJson.name}", but we're looking for "${packageName}". Check your package path.`)
  }
  report.installedVersion = packageJson.version
  report.codeTarget = codeTarget
  log(`Found package "${packageJson.name}", version ${packageJson.version}`)

  // Patches are stored per upstream version under patches/<package>/<version>/<codeTarget>.patch.
  // Pick the exact version, else the newest patch for the same major.minor, else the newest overall.
  // The selection is a real directory scan (see resolvePatchVersion), and it reports how it got there.
  const resolved = resolvePatchVersion(packageName, packageJson.version, codeTarget)
  report.resolved = resolved
  report.matchKind = resolved.matchKind
  report.selectedVersion = resolved.version
  logSelection()

  if (resolved.matchKind === 'none') {
    ensurePatchStatusLogged('unknown')
    abort(`No ${codeTarget}.patch found for ${packageName}. This rebrowser-patches version may not support it.`)
  }

  const patchFilePath = resolved.path
  log(`Using patch version ${resolved.version} (${codeTarget})`)
  if (!resolved.exact) {
    log(`⚠️  Warning: this patch was NOT tested on ${packageName}@${packageJson.version}; it was tested on version ${resolved.version}.`)
    log(`⚠️  ${describePatchMatch(resolved)}.`)
    log(`⚠️  If this fails or misbehaves, use the matching drop-in package instead: rebrowser-${packageName}@${packageJson.version}.`)
  }

  // check patch status
  let patchStatus
  let dryRunError = null
  try {
    const { stdout, stderr } = await exec(`${getPatchBaseCmd(patchFilePath)} --dry-run`, {
      cwd: packagePath,
    })
    patchStatus = 'unpatched'
  } catch (e) {
    if (e.stdout?.includes('No file to patch')) {
      ensurePatchStatusLogged('unknown')
      abort('Internal error, patch command cannot find file to patch')
    } else if (
      // GNU patch wording varies by version: "Ignoring previously applied (or reversed) patch"
      // vs "Reversed (or previously applied) patch detected!  Skipping patch." — match the common part.
      e.stdout?.includes('previously applied') ||
      e.stdout?.includes('Reversed (or previously applied)')
    ) {
      patchStatus = 'patched'
    } else if (e.stderr?.includes('is not recognized')) {
      ensurePatchStatusLogged('unknown')
      let message = 'patch command not found!'
      if (process.platform === 'win32') {
        message += '\nCheck README for how to install patch.exe on Windows.'
      }
      abort(message)
    } else if (!resolved.exact) {
      // A non-exact patch that doesn't apply cleanly: don't risk a half-patched install.
      // Nothing was modified (this was --dry-run), so the target files stay untouched.
      report.patchStatus = 'unpatched'
      logPatchStatus()
      abort(
        `The selected fallback patch does not apply to ${packageName}@${packageJson.version}. Nothing was changed.\n` +
        `  selected version = ${resolved.version} (match kind: ${resolved.matchKind}; installed version = ${packageJson.version})\n` +
        `  ${describePatchMatch(resolved)}\n` +
        `Use the matching drop-in package instead: rebrowser-${packageName}@${packageJson.version} ` +
        `(see https://github.com/rebrowser/rebrowser-patches#readme), or install a ${packageName} version that has a patch.`
      )
    } else {
      dryRunError = e
    }
  }
  if (dryRunError) {
    // an exact patch that doesn't apply is a real failure: throw the original error as before
    ensurePatchStatusLogged('unpatched')
    log('[debug] patch error:', dryRunError)
    throw dryRunError
  }
  report.patchStatus = patchStatus
  logPatchStatus()

  // run command
  let execCmd
  if (command === 'patch') {
    if (patchStatus === 'patched') {
      log('Package already patched.')
    } else {
      execCmd = getPatchBaseCmd(patchFilePath)
    }
  } else if (command === 'unpatch') {
    if (patchStatus === 'unpatched') {
      log('Package already unpatched.')
    } else {
      execCmd = `${getPatchBaseCmd(patchFilePath)} --reverse`
    }
  } else if (command === 'check') {
    // "check" only reports status; there is nothing to execute.
    log(`Patch is ${patchStatus}.`)
  }

  if (!execCmd) {
    finish('nothing changed')
  }

  try {
    await exec(execCmd, {
      cwd: packagePath,
    })
    finish('success')
  } catch (e) {
    log('patch exec error:', e)
    finish('error')
  }
})()

