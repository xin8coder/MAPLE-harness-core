param([switch]$InstallOnly, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$env:PYTHONUTF8 = '1'
$Source = Split-Path -Parent $PSScriptRoot
$Pins = Get-Content -LiteralPath (Join-Path $Source 'runtime\bootstrap.json') -Raw | ConvertFrom-Json
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    throw 'This launcher supports Windows 10/11 x64. ARM64 requires separate validation.'
}
if (-not $env:MAPLE_HOME) { $env:MAPLE_HOME = Join-Path $env:LOCALAPPDATA 'MAPLEHarness' }
$HomePath = [IO.Path]::GetFullPath($env:MAPLE_HOME)
$Tools = Join-Path $HomePath 'bootstrap'
New-Item -ItemType Directory -Force -Path $Tools | Out-Null
$Uv = Join-Path $Tools 'uv.exe'
if (-not (Test-Path -LiteralPath $Uv)) {
    Write-Host '[1/5] Downloading the private Python installer...'
    $Name = 'uv-x86_64-pc-windows-msvc.zip'
    $Archive = Join-Path $Tools $Name
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/download/$($Pins.uv_version)/$Name" -OutFile $Archive
    $Expected = $Pins.uv_sha256.$Name
    if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) {
        throw 'Python installer checksum verification failed.'
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath $Tools -Force
    Remove-Item -LiteralPath $Archive
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $HomePath 'python'
$env:UV_CACHE_DIR = Join-Path $HomePath 'uv-cache'
Write-Host '[1/5] Preparing Python (no administrator access required)...'
& $Uv python install --no-bin --no-registry $Pins.python_version
if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
$Python = (& $Uv python find --managed-python $Pins.python_version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Python)) { throw 'Managed Python was not found.' }
$Arguments = @((Join-Path $Source 'scripts\launcher.py'))
if ($InstallOnly) { $Arguments += '--install-only' }
if ($NoBrowser) { $Arguments += '--no-browser' }
& $Python @Arguments
exit $LASTEXITCODE
