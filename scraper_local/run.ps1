param([string]$Redes = "", [switch]$ReintentarFallidas = $false)
# Corrida del scraper local de la Boca de Urna (la dispara Task Scheduler).
# Parámetro -Redes: lista separada por comas, p.ej. -Redes "twitter,tiktok".
# Si se omite, run.py usa las redes del config.json.
# Parámetro -ReintentarFallidas: corre SÓLO las redes cuyo resultado en el último
# logs\resultados\*.json no fue "ok". Combinado con -Redes, acota a esas redes.
# Si no hay último resultado (o no trae redes fallidas) run.py sale non-cero sin scrapear.
# El exit code de run.py se propaga para que el Task Scheduler registre fallos.
Set-Location $PSScriptRoot

# Variables de entorno: carga scraper_local\.env (en la PC de desarrollo cae al
# backend\.env, que ya tiene las keys). Formato KEY=VALOR por linea, # comenta.
# No pisa variables que ya vengan del entorno: lo que configure Task Scheduler
# o la sesion tiene prioridad sobre el archivo.
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) { $envFile = Join-Path (Split-Path $PSScriptRoot) "backend\.env" }
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([^=#][^=]*)=(.*)$') {
            $name = $Matches[1].Trim(); $value = $Matches[2].Trim()
            if (-not (Test-Path "env:$name")) { Set-Item "env:$name" $value }
        }
    }
}

$argumentos = @("run.py")
# En modo reintento el nombre de red va pegado al flag (--reintentar-fallidas REDES),
# no a --redes: run.py sólo corre lo que no salió ok.
if ($ReintentarFallidas) { $argumentos += "--reintentar-fallidas"; if ($Redes) { $argumentos += $Redes } }
elseif ($Redes) { $argumentos += @("--redes", $Redes) }
& "$PSScriptRoot\.venv\Scripts\python.exe" @argumentos
exit $LASTEXITCODE
