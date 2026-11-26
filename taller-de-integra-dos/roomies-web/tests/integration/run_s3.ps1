param(
    [ValidateSet('All', 'C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'Web')]
    [string]$Task = 'All',
    [string]$PgBin,
    [switch]$StrictC06
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$web = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$repo = (Resolve-Path -LiteralPath (Join-Path $web '../..')).Path
$venv = Join-Path $repo '.venv'
$python = Join-Path $venv 'Scripts/python.exe'
$services = Join-Path $web 'backend/services'
$listado = Join-Path $services 'listado-applications-service'
$convivencia = Join-Path $services 'convivencia-mensajeria-service'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
        & py -3.13 -m venv $venv
    } else {
        & python -m venv $venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear .venv. Revisa la instalacion de Python 3.13.' }
}

& $python -I -m pip install --quiet --disable-pip-version-check --no-input `
    -r (Join-Path $listado 'requirements.txt') `
    -r (Join-Path $convivencia 'tests/requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Fallo la instalacion de dependencias en .venv.' }

$previousPgBin = $env:POSTGRES_BIN
if (-not $PgBin) { $PgBin = $previousPgBin }
$pgArgument = @()
if ($PgBin) {
    $PgBin = (Resolve-Path -LiteralPath $PgBin).Path
    foreach ($executable in @('initdb.exe', 'pg_ctl.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PgBin $executable) -PathType Leaf)) {
            throw "Falta $executable en la carpeta PostgreSQL indicada."
        }
    }
    $pgArgument = @('--pg-bin', $PgBin)
}

$convivenciaRunner = Join-Path $convivencia 'tests/run_isolated.py'
$listadoRunner = Join-Path $listado 'tests/run_isolated.py'
$integrationRunner = Join-Path $PSScriptRoot 'run_c03.py'
if ($Task -eq 'Web') {
    $node = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $node) {
        $bundledNode = Get-Process node -ErrorAction SilentlyContinue |
            Where-Object Path -like '*CodexPrimaryRuntime*' | Select-Object -First 1 -ExpandProperty Path
        if (-not $bundledNode) { throw 'Falta Node.js. Instálalo y vuelve a ejecutar el modo Web.' }
        $env:Path = "$(Split-Path -Parent $bundledNode);$env:Path"
    }
    & $python -I -B -X utf8 $integrationRunner --manual-web @pgArgument
    exit $LASTEXITCODE
}
$strictArgument = @()
if ($StrictC06) { $strictArgument = @('--strict-c06') }
$cases = [ordered]@{
    C01 = @($convivenciaRunner, '-k', 'test_incorporaciones or test_http or test_ports')
    C02 = @($listadoRunner, '-k', 'test_contract or test_http_limits or test_images')
    C03 = @($integrationRunner) + $pgArgument
    C04 = @($integrationRunner, '--c04') + $pgArgument
    C05 = @($convivenciaRunner, '-k', 'test_tasks')
    C06 = @($integrationRunner, '--c06') + $pgArgument + $strictArgument
}
$selected = if ($Task -eq 'All') { $cases.Keys } else { $Task.ToUpperInvariant() }
$failed = @()
$c06Pending = $false

try {
    if ($PgBin) { $env:POSTGRES_BIN = $PgBin }
    foreach ($id in $selected) {
        Write-Host "`nS3R-$id"
        $testArguments = $cases[$id]
        & $python -I -B -X utf8 @testArguments
        if ($id -eq 'C06' -and $StrictC06 -and $LASTEXITCODE -eq 2) {
            $c06Pending = $true
        } elseif ($LASTEXITCODE -ne 0) {
            $failed += "$id (codigo $LASTEXITCODE)"
        }
    }
} finally {
    $env:POSTGRES_BIN = $previousPgBin
}

if ($failed.Count) {
    Write-Host "Fallaron $($failed -join ', ')."
    exit 1
}
if ($c06Pending) { exit 2 }
exit 0
