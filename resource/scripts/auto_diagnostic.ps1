$ErrorActionPreference = 'Stop'
$resourceDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtimeDir = Split-Path -Parent $resourceDir
$projectDir = Split-Path -Parent $runtimeDir
$debugDir = Join-Path $runtimeDir 'debug'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$reportRoot = Join-Path $projectDir ('diagnostic_report_auto_' + $stamp)
$reportZip = $reportRoot + '.zip'
$triggerImage = if ($args.Count -ge 1) { [string]$args[0] } else { '' }

New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null

function Copy-IfExists([string]$source, [string]$destination) {
    if (Test-Path -LiteralPath $source) {
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    }
}

Copy-IfExists $debugDir (Join-Path $reportRoot 'debug')
Copy-IfExists (Join-Path $runtimeDir 'config\maa_option.json') (Join-Path $reportRoot 'config\maa_option.json')
Copy-IfExists (Join-Path $resourceDir 'pipeline\sync_rate.json') (Join-Path $reportRoot 'pipeline\sync_rate.json')
Copy-IfExists (Join-Path $resourceDir 'pipeline\story_demo.json') (Join-Path $reportRoot 'pipeline\story_demo.json')
Copy-IfExists (Join-Path $resourceDir 'default_pipeline.json') (Join-Path $reportRoot 'pipeline\default_pipeline.json')
Copy-IfExists (Join-Path $resourceDir 'image') (Join-Path $reportRoot 'templates')
if ($triggerImage -and (Test-Path -LiteralPath $triggerImage)) {
    $triggerExtension = [System.IO.Path]::GetExtension($triggerImage)
    if (-not $triggerExtension) { $triggerExtension = '.png' }
    Copy-IfExists $triggerImage (Join-Path $reportRoot ('timeout_screen' + $triggerExtension))
}

$frameworkLog = Join-Path $debugDir 'maafw.log'
$failedNode = 'Unknown'
if (Test-Path -LiteralPath $frameworkLog) {
    $failedLine = Select-String -Path $frameworkLog -Pattern 'Node.PipelineNode.Failed' -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($failedLine -and ($failedLine.Line -match '"name":"([^"]+)"')) {
        $failedNode = $Matches[1]
    }
}

$summary = @(
    'Morimens automatic timeout diagnostic report',
    ('Created: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
    ('Timeout/failed node: ' + $failedNode),
    'The task was stopped automatically after this report was exported.',
    'BattleMonitor timeout: 300000 ms (5 minutes).',
    'Other stages use their node-specific 60-180 second timeout.',
    'debug\maafw.log contains recognition results, scores and thresholds.',
    'debug\vision contains annotated recognition screenshots.'
)
[System.IO.File]::WriteAllLines((Join-Path $reportRoot 'README.txt'), $summary, [System.Text.UTF8Encoding]::new($true))

$scoreOutput = Join-Path $reportRoot 'recognition_scores.txt'
if (Test-Path -LiteralPath $frameworkLog) {
    $scoreLines = Select-String -Path $frameworkLog -Pattern 'TemplateMatcher|score|threshold|Recognition.Succeeded|Recognition.Failed' -CaseSensitive:$false -ErrorAction SilentlyContinue |
        Select-Object -Last 8000 |
        ForEach-Object { $_.Line }
    if ($scoreLines) {
        [System.IO.File]::WriteAllLines($scoreOutput, [string[]]$scoreLines, [System.Text.UTF8Encoding]::new($true))
    }
}

Compress-Archive -LiteralPath $reportRoot -DestinationPath $reportZip -CompressionLevel Optimal -Force
if (-not (Test-Path -LiteralPath $debugDir)) { New-Item -ItemType Directory -Path $debugDir -Force | Out-Null }
[System.IO.File]::WriteAllText((Join-Path $debugDir 'auto_diagnostic_latest.txt'), $reportZip, [System.Text.UTF8Encoding]::new($true))
exit 0
