#requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ProjectRoot 'dist'
$BuildDir = Join-Path $ProjectRoot 'build'
$PyInstallerVersion = '6.22.2'

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    Write-Host ("[RUN] " + $FilePath + ' ' + ($Arguments -join ' '))
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $FilePath $($Arguments -join ' ')"
    }
}

Set-Location -LiteralPath $ProjectRoot

$python = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { throw 'Python was not found.' }
$prefix = if ($python -eq 'py') { @('-3') } else { @() }

if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
if (Test-Path $DistDir) { Remove-Item $DistDir -Recurse -Force }

Invoke-Checked $python ($prefix + @('-m','py_compile',
    'app\mini_url_converter.py',
    'app\launcher.py',
    'app\main.py',
    'app\runtime.py',
    'app\auto_auth.py',
    'app\browser_auth.py',
    'app\auth_policy.py',
    'app\chrome_bridge.py',
    'app\chrome_native_host.py',
    'app\chrome_bridge_auth.py',
    'app\version.py'
))
Invoke-Checked $python ($prefix + @('app\chrome_bridge_auth.py','--self-test'))

& $python @($prefix + @('-c','import PyInstaller'))
if ($LASTEXITCODE -ne 0) {
    Invoke-Checked $python ($prefix + @('-m','pip','install',("pyinstaller==" + $PyInstallerVersion)))
}

Invoke-Checked $python ($prefix + @('-m','PyInstaller','--noconfirm','--clean','mini_url_converter.spec'))
Invoke-Checked $python ($prefix + @('-m','PyInstaller','--noconfirm','--clean','chrome_native_host.spec'))

$guiExe = Join-Path $DistDir 'mini_url_converter.exe'
$hostExe = Join-Path $DistDir 'chrome_native_host.exe'
if (-not (Test-Path $guiExe -PathType Leaf)) { throw "GUI executable was not built: $guiExe" }
if (-not (Test-Path $hostExe -PathType Leaf)) { throw "Chrome native host was not built: $hostExe" }

Write-Host '[RUN] GUI executable self-test'
$proc = Start-Process -FilePath $guiExe -ArgumentList @('--self-test') -WorkingDirectory $ProjectRoot -Wait -PassThru
if ($proc.ExitCode -ne 0) { throw "GUI self-test failed with exit code $($proc.ExitCode)" }

& (Join-Path $ProjectRoot 'build_installer.ps1') -SkipBuildExe
if ($LASTEXITCODE -ne 0) { throw "Installer build failed with exit code $LASTEXITCODE" }

Write-Host '[OK] Chrome bridge build completed.'
