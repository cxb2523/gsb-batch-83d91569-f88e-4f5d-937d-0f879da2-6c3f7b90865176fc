<#
.SYNOPSIS
  GatherRadar final Excel acceptance: offline tests, ONE fresh bounded crawl, ONE review bundle.

.DESCRIPTION
  Run from the repository root (or anywhere; the script finds the repository):
    powershell -ExecutionPolicy Bypass -File scripts\final_excel_acceptance.ps1

  1. Reports branch/SHA and checks Python packages and local OCR engines (never installs).
  2. Runs the offline test suite; stops before collecting if any test fails.
  3. Runs exactly one `refresh --all-enabled --limit 5 --days 14` into a new isolated
     directory data\qa-final-<timestamp>\ (its own SQLite, workbook and exports; the
     production database and workbook are not touched). It reuses the existing local
     Instagram browser profile; an authentication problem is reported, never prompted for.
     Raw/evidence stores under data\ are append-only shared history, not isolated.
  4. Validates the workbook and writes ONE review bundle (zip) to return.

  Never changes Git branches, pulls, installs packages, uploads anything or asks for
  credentials. -IncludeMedia copies a bounded selection of stored public media for the
  tracked OCR cases into the bundle; it is off by default.

.PARAMETER OfflineReplay
  Test-only: analyze already stored observations (`refresh --stored`) instead of
  collecting. It does NOT validate current parsing of live pages.
#>
[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$DataDir = 'data',
    [int]$Limit = 5,
    [int]$Days = 14,
    [switch]$IncludeMedia,
    [switch]$OfflineReplay
)

$ErrorActionPreference = 'Continue'   # native-command stderr must not abort the run
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

if (-not $Python) {
    $windows = Join-Path $repo '.venv\Scripts\python.exe'
    $posix = Join-Path $repo '.venv/bin/python'
    if (Test-Path $windows) { $Python = $windows } elseif (Test-Path $posix) { $Python = $posix }
}
if (-not $Python -or -not (Test-Path $Python)) {
    Write-Host 'error: project .venv not found. Create it first: python -m venv .venv; .venv\Scripts\python.exe -m pip install -e .'
    exit 3
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dataRoot = if ([System.IO.Path]::IsPathRooted($DataDir)) { $DataDir } else { Join-Path $repo $DataDir }
$out = Join-Path $dataRoot ("qa-final-" + $stamp)
New-Item -ItemType Directory -Path $out -Force | Out-Null
$log = Join-Path $out 'acceptance-log.txt'

function Say([string]$text) {
    Write-Host $text
    Add-Content -Path $log -Value $text -Encoding UTF8
}

function Run-Logged([string]$name, [string[]]$arguments) {
    # Runs the project Python, mirrors output to the console and a UTF-8 log file.
    $target = Join-Path $out $name
    & $Python @arguments 2>&1 | ForEach-Object { "$_" } | Tee-Object -Variable lines | Write-Host
    $code = $LASTEXITCODE
    $lines | Out-File -FilePath $target -Encoding UTF8
    return $code
}

Say "GatherRadar final Excel acceptance  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Say "Output directory: $out"

# 1. Repository state (read-only).
$branch = (& git rev-parse --abbrev-ref HEAD 2>$null)
$sha = (& git rev-parse HEAD 2>$null)
Say "Branch: $branch"
Say "Commit: $sha"
if ($branch -ne 'fix/gatherradar-source-field-hardening') {
    Say "WARNING: expected branch fix/gatherradar-source-field-hardening. Not switching branches."
}
if (& git status --porcelain 2>$null) { Say 'Note: the working tree has local changes; they are left untouched.' }

# 2. Dependencies and OCR engines (diagnosis only; nothing is installed).
# No quotes inside the Python argument: Windows PowerShell 5.1 strips embedded
# double quotes when passing arguments to native programs.
$depCode = Run-Logged 'dependencies.txt' @('-c', 'import gatherradar, openpyxl, persiantools, playwright')
if ($depCode -ne 0) { Say 'error: required Python packages are missing. Install the project into .venv, then rerun.'; exit 3 }
Say 'Python packages: ok'
$null = Run-Logged 'ocr-check.txt' @('-m', 'gatherradar', 'ocr', 'check')
Say 'OCR engines: see ocr-check.txt (an unavailable optional engine is reported, not fatal).'

# 3. Offline tests first.
Say 'Running the offline test suite...'
$testCode = Run-Logged 'test-summary.txt' @('-m', 'unittest', 'discover', '-s', 'tests')
if ($testCode -ne 0) {
    Say "Tests FAILED. Stopping before the crawl. Return: $(Join-Path $out 'test-summary.txt')"
    exit 1
}
Say 'Tests passed.'

# 4. Exactly one fresh bounded crawl into the isolated directory.
$refreshArgs = @('-m', 'gatherradar', 'refresh', '--all-enabled', '--limit', "$Limit", '--days', "$Days",
                 '--data-dir', $DataDir, '--db', (Join-Path $out 'state.sqlite3'),
                 '--workbook', (Join-Path $out 'GatherRadar.xlsx'), '--export-dir', (Join-Path $out 'exports'))
if ($OfflineReplay) {
    $refreshArgs += '--stored'
    Say 'OFFLINE REPLAY (test-only): stored observations, no collection. This does not validate live parsing.'
} else {
    Say "Collecting: all enabled sources, latest $Limit items each, $Days-day window. Chrome may open with your existing GatherRadar profile."
}
$refreshCode = Run-Logged 'refresh-output.txt' $refreshArgs
if ($refreshCode -ne 0) {
    Say 'Refresh reported a partial collection or an export problem (details in refresh-output.txt). Validating what was stored.'
}
if (-not (Test-Path (Join-Path $out 'state.sqlite3'))) {
    Say 'error: no run was persisted. Return refresh-output.txt and acceptance-log.txt from the output directory.'
    exit 4
}

# 5. Validate and write ONE review bundle.
$acceptArgs = @('-m', 'gatherradar', 'acceptance', '--run-dir', $out, '--data-dir', $DataDir,
                '--test-log', (Join-Path $out 'test-summary.txt'))
# The Python tool writes the zip (forward-slash entry names); Windows PowerShell
# 5.1 Compress-Archive would store backslash paths such as media\slide.png.
foreach ($name in @('refresh-output.txt', 'ocr-check.txt', 'dependencies.txt', 'acceptance-log.txt')) {
    $acceptArgs += @('--include', (Join-Path $out $name))
}
if ($IncludeMedia) { $acceptArgs += '--include-media' }
$acceptCode = Run-Logged 'acceptance-output.txt' $acceptArgs
$bundle = Join-Path $out 'GatherRadar-review-bundle.zip'

Say ''
if ($acceptCode -eq 0) { Say "Workbook: $(Join-Path $out 'GatherRadar.xlsx')" }
else { Say 'Workbook: problems found (see acceptance-output.txt); the bundle still contains the report.' }
Say "Review bundle to return: $bundle"
exit $acceptCode
