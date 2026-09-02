$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$deps = Join-Path $root "deps"
$runtime = Join-Path $root "runtime"
$mfaArchive = Join-Path $deps "MFAAvalonia-v2.16.0-win-x64.zip"
$dotnetInstaller = Join-Path $deps "windowsdesktop-runtime-10-win-x64.exe"
$log = Join-Path $root "startup_win64.log"
$mfaUrl = "https://github.com/MaaXYZ/MFAAvalonia/releases/download/v2.16.0/MFAAvalonia-v2.16.0-win-x64.zip"
$dotnetUrl = "https://aka.ms/dotnet/10.0/windowsdesktop-runtime-win-x64.exe"
$expectedMfaSha256 = "8697117547eb5907414b38b3b381656649e4e951d43fafaa3ce40046c0be790e"
$transcriptStarted = $false

function Get-DotNetExe {
    $systemDotNet = Join-Path $env:ProgramFiles "dotnet\dotnet.exe"
    if (Test-Path $systemDotNet) { return $systemDotNet }
    $command = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

function Test-DesktopRuntime10 {
    $dotnetExe = Get-DotNetExe
    if (-not $dotnetExe) { return $false }
    try {
        $runtimes = & $dotnetExe --list-runtimes 2>$null
        return [bool]($runtimes | Select-String "Microsoft.WindowsDesktop.App 10\.")
    } catch { return $false }
}

function Download-Dependency([string]$Url, [string]$Destination, [string]$DisplayName) {
    Write-Host "Downloading $DisplayName ..." -ForegroundColor Cyan
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    if (-not (Test-Path $Destination)) { throw "Download failed: $DisplayName" }
}

try {
    if (-not (Test-Path $deps)) { New-Item -ItemType Directory -Path $deps | Out-Null }
    Start-Transcript -Path $log -Append | Out-Null
    $transcriptStarted = $true
    Write-Host "Morimens MaaFramework Assistant - Windows x64" -ForegroundColor Cyan
    Write-Host "Project directory: $root"
    Write-Host "Windows: $([Environment]::OSVersion.VersionString)"
    Write-Host "64-bit OS: $([Environment]::Is64BitOperatingSystem); 64-bit process: $([Environment]::Is64BitProcess)"
    if (-not [Environment]::Is64BitOperatingSystem) { throw "Windows x64 is required." }
    if (-not [Environment]::Is64BitProcess) { throw "A 32-bit PowerShell process was started. Run START_WIN64.cmd." }

    if (-not (Test-DesktopRuntime10)) {
        Write-Host ".NET 10 Desktop Runtime x64 was not found." -ForegroundColor Yellow
        if (-not (Test-Path $dotnetInstaller)) {
            Download-Dependency $dotnetUrl $dotnetInstaller ".NET 10 Desktop Runtime x64"
        } else {
            Write-Host "Using bundled .NET installer: $dotnetInstaller"
        }
        $installerProcess = Start-Process -FilePath $dotnetInstaller -ArgumentList "/install", "/quiet", "/norestart" -Wait -PassThru
        if (($installerProcess.ExitCode -ne 0) -and ($installerProcess.ExitCode -ne 3010)) {
            throw ".NET installer failed with exit code $($installerProcess.ExitCode)."
        }
        if (-not (Test-DesktopRuntime10)) {
            throw ".NET was installed but is not available yet. Restart Windows, then run START_WIN64.cmd again."
        }
    }
    Write-Host ".NET 10 Desktop Runtime x64: OK" -ForegroundColor Green

    $exePath = Join-Path $runtime "MFAAvalonia.exe"
    if (-not (Test-Path $exePath)) {
        $archiveOk = $false
        if (Test-Path $mfaArchive) {
            $actualHash = (Get-FileHash -LiteralPath $mfaArchive -Algorithm SHA256).Hash.ToLowerInvariant()
            $archiveOk = ($actualHash -eq $expectedMfaSha256)
            if (-not $archiveOk) {
                Write-Host "The bundled MFAAvalonia archive is incomplete. Downloading it again." -ForegroundColor Yellow
                Remove-Item -LiteralPath $mfaArchive -Force
            } else {
                Write-Host "Using bundled MFAAvalonia archive: $mfaArchive"
            }
        }
        if (-not $archiveOk) {
            Download-Dependency $mfaUrl $mfaArchive "MFAAvalonia v2.16.0 win-x64"
            $actualHash = (Get-FileHash -LiteralPath $mfaArchive -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -ne $expectedMfaSha256) { throw "MFAAvalonia SHA256 verification failed: $actualHash" }
        }
        if (Test-Path $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }
        New-Item -ItemType Directory -Path $runtime | Out-Null
        Expand-Archive -LiteralPath $mfaArchive -DestinationPath $runtime -Force
        $foundExe = Get-ChildItem $runtime -Filter "MFAAvalonia.exe" -File -Recurse | Select-Object -First 1
        if (-not $foundExe) { throw "MFAAvalonia.exe was not found in the x64 archive." }
        if ($foundExe.Directory.FullName -ne $runtime) {
            Copy-Item (Join-Path $foundExe.Directory.FullName "*") $runtime -Recurse -Force
        }
    }
    if (-not (Test-Path $exePath)) { throw "MFAAvalonia installation is incomplete." }
    Copy-Item (Join-Path $root "interface.json") (Join-Path $runtime "interface.json") -Force
    $runtimeResource = Join-Path $runtime "resource"
    if (Test-Path $runtimeResource) { Remove-Item -LiteralPath $runtimeResource -Recurse -Force }
    Copy-Item (Join-Path $root "resource") $runtimeResource -Recurse -Force
    $runtimeConfig = Join-Path $runtime "config"
    if (-not (Test-Path $runtimeConfig)) { New-Item -ItemType Directory -Path $runtimeConfig | Out-Null }
    Copy-Item (Join-Path $root "config\maa_option.json") (Join-Path $runtimeConfig "maa_option.json") -Force
    $debugDir = Join-Path $runtime "debug"
    if (Test-Path $debugDir) {
        try {
            $debugArchive = Join-Path $runtime "debug_archive"
            if (-not (Test-Path $debugArchive)) { New-Item -ItemType Directory -Path $debugArchive | Out-Null }
            $archiveName = "debug_" + (Get-Date -Format "yyyyMMdd_HHmmss")
            Move-Item -LiteralPath $debugDir -Destination (Join-Path $debugArchive $archiveName)
            Write-Host "Previous diagnostic data archived: runtime\debug_archive\$archiveName"
        } catch {
            Write-Host "Previous diagnostic data is in use; continuing without archiving it." -ForegroundColor Yellow
        }
    }
    $uidEnabled = Join-Path $root "uid_mask_enabled.txt"
    if ((Test-Path $uidEnabled) -and ((Get-Content -LiteralPath $uidEnabled -Raw).Trim() -eq "1")) {
        Start-Process -FilePath (Join-Path $root "UID_MASK_ON.cmd") -WindowStyle Hidden
        Write-Host "UID privacy mask: enabled" -ForegroundColor Green
    } else {
        Write-Host "UID privacy mask: disabled" -ForegroundColor Yellow
    }
    Write-Host "Starting MFAAvalonia Windows x64 ..." -ForegroundColor Green
    $process = Start-Process -FilePath $exePath -WorkingDirectory $runtime -PassThru
    Start-Sleep -Seconds 5
    if ($process.HasExited) { throw "MFAAvalonia exited immediately. Exit code: $($process.ExitCode). See startup_win64.log." }
    Write-Host "Started successfully. PID: $($process.Id)" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "STARTUP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log file: $log" -ForegroundColor Yellow
    exit 1
} finally {
    if ($transcriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
}
