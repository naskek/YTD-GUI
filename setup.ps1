#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$BuildExe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
}

$ProjectRoot = 'D:\yt-conv-GUI'
$ToolsDir = Join-Path $ProjectRoot 'tools'
$DownloadsDir = Join-Path $ProjectRoot 'downloads'
$DistDir = Join-Path $ProjectRoot 'dist'
$AppDir = Join-Path $ProjectRoot 'app'
$AppScript = Join-Path $AppDir 'launcher.py'

$YtDlpDownloadUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
$FfmpegZipUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'

$YtDlpPath = Join-Path $ToolsDir 'yt-dlp.exe'
$FfmpegPath = Join-Path $ToolsDir 'ffmpeg.exe'
$FfprobePath = Join-Path $ToolsDir 'ffprobe.exe'

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("yt-conv-gui-setup-" + [guid]::NewGuid().ToString('N'))
$YtDlpTempPath = Join-Path $TempRoot 'yt-dlp.exe'
$FfmpegZipPath = Join-Path $TempRoot 'ffmpeg.zip'
$FfmpegExtractDir = Join-Path $TempRoot 'ffmpeg'

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ""
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}

function Write-Info {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Gray
}

function Write-Success {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Failure {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
        Write-Info "Created directory: $Path"
        return
    }

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Path exists but is not a directory: $Path"
    }

    Write-Info "Directory exists: $Path"
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$DestinationPath
    )

    $destinationDir = Split-Path -Parent $DestinationPath
    if ($destinationDir) {
        Ensure-Directory -Path $destinationDir
    }

    Write-Info "Downloading: $Url"
    $client = New-Object System.Net.WebClient
    try {
        $client.Headers['User-Agent'] = 'yt-conv-GUI setup.ps1'
        $client.DownloadFile($Url, $DestinationPath)
    } catch {
        throw "Failed to download $Url. $($_.Exception.Message)"
    } finally {
        $client.Dispose()
    }

    if (-not (Test-Path -LiteralPath $DestinationPath -PathType Leaf)) {
        throw "Downloaded file was not created: $DestinationPath"
    }

    Write-Success "Downloaded to: $DestinationPath"
}

function Install-YtDlp {
    Write-Section 'Installing yt-dlp'

    Invoke-Download -Url $YtDlpDownloadUrl -DestinationPath $YtDlpTempPath
    Copy-Item -LiteralPath $YtDlpTempPath -Destination $YtDlpPath -Force
    Write-Success "Installed yt-dlp: $YtDlpPath"
}

function Install-FfmpegTools {
    Write-Section 'Installing ffmpeg and ffprobe'

    Invoke-Download -Url $FfmpegZipUrl -DestinationPath $FfmpegZipPath

    if (Test-Path -LiteralPath $FfmpegExtractDir) {
        Remove-Item -LiteralPath $FfmpegExtractDir -Recurse -Force
    }

    Expand-Archive -LiteralPath $FfmpegZipPath -DestinationPath $FfmpegExtractDir -Force

    $ffmpegSource = Get-ChildItem -LiteralPath $FfmpegExtractDir -Recurse -File -Filter 'ffmpeg.exe' | Select-Object -First 1
    $ffprobeSource = Get-ChildItem -LiteralPath $FfmpegExtractDir -Recurse -File -Filter 'ffprobe.exe' | Select-Object -First 1

    if (-not $ffmpegSource) {
        throw "ffmpeg.exe was not found inside the archive: $FfmpegZipPath"
    }

    if (-not $ffprobeSource) {
        throw "ffprobe.exe was not found inside the archive: $FfmpegZipPath"
    }

    Copy-Item -LiteralPath $ffmpegSource.FullName -Destination $FfmpegPath -Force
    Copy-Item -LiteralPath $ffprobeSource.FullName -Destination $FfprobePath -Force

    Write-Success "Installed ffmpeg: $FfmpegPath"
    Write-Success "Installed ffprobe: $FfprobePath"
}

function Get-CommandFirstLine {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "Executable not found: $FilePath"
    }

    $output = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $outputLines = @($output | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ })

    if ($exitCode -ne 0) {
        $details = $outputLines -join [Environment]::NewLine
        throw "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')`n$details"
    }

    if ($outputLines.Count -eq 0) {
        return '(no output)'
    }

    return $outputLines[0]
}

function Show-InstalledVersions {
    Write-Section 'Installed versions'

    $ytDlpVersion = Get-CommandFirstLine -FilePath $YtDlpPath -Arguments @('--version')
    $ffmpegVersion = Get-CommandFirstLine -FilePath $FfmpegPath -Arguments @('-version')
    $ffprobeVersion = Get-CommandFirstLine -FilePath $FfprobePath -Arguments @('-version')

    Write-Host "yt-dlp  : $ytDlpVersion"
    Write-Host "ffmpeg  : $ffmpegVersion"
    Write-Host "ffprobe : $ffprobeVersion"
}

function Get-PythonLauncher {
    if (Get-Command -Name python -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{
            FilePath = 'python'
            PrefixArgs = @()
        }
    }

    if (Get-Command -Name py -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{
            FilePath = 'py'
            PrefixArgs = @('-3')
        }
    }

    throw 'Python was not found in PATH.'
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $false)][string]$WorkingDirectory = $ProjectRoot
    )

    Write-Info ("Running: " + $FilePath + ' ' + ($Arguments -join ' '))

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
}

function Build-GuiExecutable {
    Write-Section 'Building GUI executable'

    if (-not (Test-Path -LiteralPath $AppScript -PathType Leaf)) {
        throw "GUI entry file not found: $AppScript"
    }

    $python = Get-PythonLauncher

    Invoke-ExternalCommand -FilePath $python.FilePath -Arguments ($python.PrefixArgs + @('-m', 'pip', 'install', '--upgrade', 'pyinstaller'))
    Invoke-ExternalCommand -FilePath $python.FilePath -Arguments ($python.PrefixArgs + @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed', 'app\launcher.py'))

    Write-Success "Build finished. Output folder: $DistDir"
}

try {
    Write-Section 'Preparing directories'
    Ensure-Directory -Path $ProjectRoot
    Ensure-Directory -Path $ToolsDir
    Ensure-Directory -Path $DownloadsDir
    Ensure-Directory -Path $DistDir
    Ensure-Directory -Path $TempRoot

    Install-YtDlp
    Install-FfmpegTools
    Show-InstalledVersions

    if ($BuildExe) {
        Build-GuiExecutable
    }

    Write-Section 'Done'
    Write-Success 'Setup completed successfully.'
    exit 0
} catch {
    Write-Section 'Failed'
    Write-Failure $_.Exception.Message
    exit 1
} finally {
    if (Test-Path -LiteralPath $TempRoot) {
        try {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force
        } catch {
            Write-Info "Temporary files were left in: $TempRoot"
        }
    }
}
