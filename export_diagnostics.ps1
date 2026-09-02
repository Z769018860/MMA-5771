$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$reportRoot = Join-Path $root ('diagnostic_report_' + $stamp)
$reportZip = $reportRoot + '.zip'
New-Item -ItemType Directory -Path $reportRoot | Out-Null

function Copy-IfExists([string]$source, [string]$destination) {
    if (Test-Path -LiteralPath $source) {
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    }
}

Copy-IfExists (Join-Path $root 'runtime\debug') (Join-Path $reportRoot 'debug')
Copy-IfExists (Join-Path $root 'runtime\config\maa_option.json') (Join-Path $reportRoot 'config\maa_option.json')
Copy-IfExists (Join-Path $root 'resource\pipeline\sync_rate.json') (Join-Path $reportRoot 'pipeline\sync_rate.json')
Copy-IfExists (Join-Path $root 'resource\image') (Join-Path $reportRoot 'templates')
Copy-IfExists (Join-Path $root 'startup_win64.log') (Join-Path $reportRoot 'startup_win64.log')

$summary = Join-Path $reportRoot 'recognition_scores.txt'
$debugDir = Join-Path $root 'runtime\debug'
$logFiles = Get-ChildItem $debugDir -Filter '*.log' -File -ErrorAction SilentlyContinue
$matches = foreach ($logFile in $logFiles) {
    Select-String -Path $logFile.FullName -Pattern 'score|threshold|confidence|TemplateMatch|recognition|reco' -CaseSensitive:$false -ErrorAction SilentlyContinue |
        Select-Object -Last 5000 |
        ForEach-Object { '[' + $logFile.Name + ':' + $_.LineNumber + '] ' + $_.Line }
}
if ($matches) {
    [System.IO.File]::WriteAllLines($summary, [string[]]$matches, [System.Text.UTF8Encoding]::new($true))
} else {
    [System.IO.File]::WriteAllText($summary, 'No recognition-score lines were found. Check debug\vision images for annotated match scores.', [System.Text.UTF8Encoding]::new($true))
}

$manifest = @(
    'Morimens MaaFramework diagnostic report',
    ('Created: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
    'debug\maafw.log: complete framework log',
    'debug\vision: annotated ROI, hit box, template score and threshold',
    'debug\on_error: screenshot captured when a node fails',
    'recognition_scores.txt: extracted recognition-score related log lines',
    'pipeline and templates: exact resources used by this run'
)
[System.IO.File]::WriteAllLines((Join-Path $reportRoot 'README.txt'), $manifest, [System.Text.UTF8Encoding]::new($true))

Compress-Archive -LiteralPath $reportRoot -DestinationPath $reportZip -CompressionLevel Optimal -Force
Write-Host ('Diagnostic report created: ' + $reportZip) -ForegroundColor Green
