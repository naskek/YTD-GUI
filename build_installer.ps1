#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipBuildExe,
    [switch]$SkipSmokeTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildDir = Join-Path $ProjectRoot 'build'
$DistDir = Join-Path $ProjectRoot 'dist'
$ToolsDir = Join-Path $ProjectRoot 'tools'
$InstallerScript = Join-Path $ProjectRoot 'installer\mini_url_converter.iss'
$InnoDir = Join-Path $ProjectRoot 'tools\inno'
$IsccExe = Join-Path $InnoDir 'ISCC.exe'
$PyInstallerVersion = '6.22.2'

function Get-PythonLauncher {
    # Prefer the active PATH Python. GitHub Actions setup-python puts the
    # requested interpreter first, while the Windows py launcher may select
    # a different globally installed version.
    if (Get-Command -Name python -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{ FilePath = 'python'; PrefixArgs = @() }
    }
    if (Get-Command -Name py -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{ FilePath = 'py'; PrefixArgs = @('-3') }
    }
    throw 'Python was not found in PATH.'
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory = $ProjectRoot
    )
    Write-Host ("[RUN] " + $FilePath + ' ' + ($Arguments -join ' '))
    $exitCode = -1
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')"
    }
    Write-Host "[OK] Exit code: $exitCode"
}

function Write-Stage {
    param([Parameter(Mandatory = $true)][string]$Name)
    Write-Host ""
    Write-Host ("===== " + $Name + " =====") -ForegroundColor Cyan
}

function Clear-BuildArtifacts {
    $rootFullPath = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    foreach ($target in @($BuildDir, $DistDir)) {
        $targetFullPath = [System.IO.Path]::GetFullPath($target).TrimEnd('\')
        if ([System.IO.Path]::GetDirectoryName($targetFullPath) -ne $rootFullPath) {
            throw "Refusing to clean a path outside the project root: $targetFullPath"
        }
        if (Test-Path -LiteralPath $targetFullPath) {
            Write-Host "[INFO] Removing old build output: $targetFullPath"
            Remove-Item -LiteralPath $targetFullPath -Recurse -Force
        }
    }
}

function Invoke-WindowedSelfTest {
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [string]$DataDirectory
    )
    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "Self-test executable was not found: $ExePath"
    }

    $oldDataDirectory = [Environment]::GetEnvironmentVariable('MINI_URL_CONVERTER_DATA_DIR', 'Process')
    try {
        if ($DataDirectory) {
            [Environment]::SetEnvironmentVariable('MINI_URL_CONVERTER_DATA_DIR', $DataDirectory, 'Process')
        }
        Write-Host "[RUN] $ExePath --self-test"
        $process = Start-Process -FilePath $ExePath -ArgumentList @('--self-test') -WorkingDirectory $ProjectRoot -Wait -PassThru
        Write-Host "[INFO] Self-test exit code: $($process.ExitCode)"
        if ($process.ExitCode -ne 0) {
            throw "Self-test failed with exit code $($process.ExitCode): $ExePath"
        }
    } finally {
        [Environment]::SetEnvironmentVariable('MINI_URL_CONVERTER_DATA_DIR', $oldDataDirectory, 'Process')
    }
}

function Install-LocalInnoSetup {
    New-Item -ItemType Directory -Path $InnoDir -Force | Out-Null

    # Developer-machine fallback. CI installs Inno Setup explicitly and uses
    # the system compiler instead of depending on this download redirect.
    $installerUrl = 'https://jrsoftware.org/download.php/is.exe'
    $installerPath = Join-Path $InnoDir 'innosetup-installer.exe'
    Write-Host "[INFO] Downloading Inno Setup installer..."
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Write-Host "[INFO] Installing Inno Setup (silent)..."
    $args = @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/SP-',
        ('/DIR=' + $InnoDir)
    )
    $proc = Start-Process -FilePath $installerPath -ArgumentList $args -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Inno Setup installer failed with exit code $($proc.ExitCode)"
    }

    if (-not (Test-Path -LiteralPath $IsccExe -PathType Leaf)) {
        throw "ISCC.exe was not found after installation: $IsccExe"
    }
}

function Resolve-InnoCompiler {
    $override = [Environment]::GetEnvironmentVariable('INNO_SETUP_ISCC', 'Process')
    if (-not [string]::IsNullOrWhiteSpace($override)) {
        if (Test-Path -LiteralPath $override -PathType Leaf) {
            return $override
        }
        throw "INNO_SETUP_ISCC points to a missing file: $override"
    }

    if (Test-Path -LiteralPath $IsccExe -PathType Leaf) {
        return $IsccExe
    }

    $candidates = @()
    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $candidates += (Join-Path $programFilesX86 'Inno Setup 6\ISCC.exe')
        $candidates += (Join-Path $programFilesX86 'Inno Setup 7\ISCC.exe')
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates += (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        $candidates += (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe')
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            Write-Host "[INFO] Using installed Inno Setup compiler: $candidate"
            return $candidate
        }
    }

    Install-LocalInnoSetup
    return $IsccExe
}

function Build-Exe {
    $python = Get-PythonLauncher
    & $python.FilePath @($python.PrefixArgs + @('-c', 'import PyInstaller'))
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[INFO] PyInstaller is missing; installing version $PyInstallerVersion..."
        Invoke-ExternalCommand -FilePath $python.FilePath -Arguments ($python.PrefixArgs + @('-m','pip','install',("pyinstaller==" + $PyInstallerVersion)))
    }
    Invoke-ExternalCommand -FilePath $python.FilePath -Arguments ($python.PrefixArgs + @('-m','PyInstaller','--noconfirm','--clean','mini_url_converter.spec'))
    if (-not (Test-Path -LiteralPath (Join-Path $DistDir 'mini_url_converter.exe') -PathType Leaf)) {
        throw "Built exe not found in dist: $DistDir"
    }
}

function Build-Installer {
    $compiler = Resolve-InnoCompiler
    Invoke-ExternalCommand -FilePath $compiler -Arguments @($InstallerScript) -WorkingDirectory $ProjectRoot
}

function Build-SmokeInstaller {
    $compiler = Resolve-InnoCompiler
    Invoke-ExternalCommand -FilePath $compiler -Arguments @('/DSmokeBuild=1', $InstallerScript) -WorkingDirectory $ProjectRoot
}

function Smoke-Test {
    Build-SmokeInstaller
    $setupExe = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'installer\\Output') -File -Filter 'MiniURLConverterSetup-smoke*.exe' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $setupExe) {
        throw "Smoke installer exe was not found in installer\\Output."
    }

    $testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("mini-url-converter-install-" + [guid]::NewGuid().ToString('N'))
    $testAppDir = Join-Path $testRoot 'app'
    try {
        New-Item -ItemType Directory -Path $testAppDir -Force | Out-Null

        Write-Host "[INFO] Installing into: $testAppDir"
        $installArgs = @(
            '/VERYSILENT',
            '/SUPPRESSMSGBOXES',
            '/NORESTART',
            '/NOICONS',
            '/SP-',
            ('/DIR=' + $testAppDir)
        )
        $proc = Start-Process -FilePath $setupExe.FullName -ArgumentList $installArgs -Wait -PassThru
        Write-Host "[INFO] Installer exit code: $($proc.ExitCode)"
        if ($proc.ExitCode -ne 0) {
            throw "Silent install failed (exit code $($proc.ExitCode))."
        }

        $installedExe = Join-Path $testAppDir 'mini_url_converter.exe'
        $smokeDataDir = [Environment]::GetEnvironmentVariable('MINI_URL_CONVERTER_DATA_DIR', 'Process')
        if ([string]::IsNullOrWhiteSpace($smokeDataDir)) {
            $smokeDataDir = $testAppDir
        } else {
            Write-Host "[INFO] Reusing pre-seeded self-test data dir: $smokeDataDir"
        }
        Invoke-WindowedSelfTest -ExePath $installedExe -DataDirectory $smokeDataDir
        Write-Host "[OK] Installed application smoke test passed."
    } finally {
        if (Test-Path -LiteralPath $testRoot) {
            Write-Host "[INFO] Removing smoke installation: $testRoot"
            Remove-Item -LiteralPath $testRoot -Recurse -Force
        }
    }
}

try {
    Set-Location -LiteralPath $ProjectRoot

    if (-not $SkipBuildExe) {
        Write-Stage 'Clean old build and dist'
        Clear-BuildArtifacts

        $python = Get-PythonLauncher
        Write-Stage 'Python syntax check'
        Invoke-ExternalCommand -FilePath $python.FilePath -Arguments ($python.PrefixArgs + @('-m','py_compile','app\mini_url_converter.py'))

        Write-Stage 'Source self-test'
        Invoke-ExternalCommand -FilePath $python.FilePath -Arguments ($python.PrefixArgs + @('app\mini_url_converter.py','--self-test'))

        Write-Stage 'Build PyInstaller EXE'
        Build-Exe

        Write-Stage 'Built EXE self-test'
        Invoke-WindowedSelfTest -ExePath (Join-Path $DistDir 'mini_url_converter.exe')
    }

    Write-Stage 'Build release installer'
    Build-Installer

    if (-not $SkipSmokeTest) {
        Write-Stage 'Build, install, and test smoke installer'
        Smoke-Test
    }

    Write-Stage 'Build completed successfully'
    Write-Host "[OK] EXE: $(Join-Path $DistDir 'mini_url_converter.exe')"
    Write-Host "[OK] Installer: $(Join-Path $ProjectRoot 'installer\Output\MiniURLConverterSetup.exe')"
    exit 0
} catch {
    Write-Host ""
    Write-Host ("[FAILED] " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
