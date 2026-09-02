$ErrorActionPreference = 'Stop'

$mode = if ($args.Count -ge 1) { [string]$args[0] } else { '' }
$imagePath = if ($args.Count -ge 2) { [string]$args[1] } else { '' }
$prefix = if ($args.Count -ge 3) { [string]$args[2] } else { 'sync' }
$threshold = if ($args.Count -ge 4) { [double]$args[3] } else { 0.0025 }

$resourceDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtimeDir = Split-Path -Parent $resourceDir
$stateDir = Join-Path $runtimeDir 'debug\motion'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

if (-not $imagePath -or -not (Test-Path -LiteralPath $imagePath)) {
    throw 'Current Maa screenshot is unavailable.'
}

$frame1 = Join-Path $stateDir ($prefix + '_frame1.png')
$frame2 = Join-Path $stateDir ($prefix + '_frame2.png')
$frame3 = Join-Path $stateDir ($prefix + '_frame3.png')
$resultFile = Join-Path $stateDir ($prefix + '_result.txt')

if ($mode -eq 'capture1') {
    Copy-Item -LiteralPath $imagePath -Destination $frame1 -Force
    exit 0
}
if ($mode -eq 'capture2') {
    Copy-Item -LiteralPath $imagePath -Destination $frame2 -Force
    exit 0
}
if ($mode -ne 'compare') {
    throw ('Unknown frame-motion mode: ' + $mode)
}

Copy-Item -LiteralPath $imagePath -Destination $frame3 -Force
if (-not (Test-Path -LiteralPath $frame1) -or -not (Test-Path -LiteralPath $frame2)) {
    throw 'The first two motion frames are missing.'
}

Add-Type -AssemblyName System.Drawing

function Get-Samples([string]$path) {
    $source = [System.Drawing.Bitmap]::new($path)
    try {
        $cropX = [int]($source.Width * 0.12)
        $cropY = [int]($source.Height * 0.10)
        $cropW = [int]($source.Width * 0.76)
        $cropH = [int]($source.Height * 0.62)
        $small = [System.Drawing.Bitmap]::new(64, 36)
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($small)
            try {
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBilinear
                $graphics.DrawImage($source, [System.Drawing.Rectangle]::new(0, 0, 64, 36), [System.Drawing.Rectangle]::new($cropX, $cropY, $cropW, $cropH), [System.Drawing.GraphicsUnit]::Pixel)
            }
            finally { $graphics.Dispose() }

            $values = [double[]]::new(64 * 36)
            $index = 0
            for ($y = 0; $y -lt 36; $y++) {
                for ($x = 0; $x -lt 64; $x++) {
                    $pixel = $small.GetPixel($x, $y)
                    $values[$index] = (0.2126 * $pixel.R + 0.7152 * $pixel.G + 0.0722 * $pixel.B) / 255.0
                    $index++
                }
            }
            return $values
        }
        finally { $small.Dispose() }
    }
    finally { $source.Dispose() }
}

function Get-MeanDifference([double[]]$left, [double[]]$right) {
    $sum = 0.0
    for ($i = 0; $i -lt $left.Length; $i++) {
        $sum += [Math]::Abs($left[$i] - $right[$i])
    }
    return $sum / $left.Length
}

$samples1 = Get-Samples $frame1
$samples2 = Get-Samples $frame2
$samples3 = Get-Samples $frame3
$difference12 = Get-MeanDifference $samples1 $samples2
$difference23 = Get-MeanDifference $samples2 $samples3
$isStatic = ($difference12 -lt $threshold -and $difference23 -lt $threshold)

$lines = @(
    ('time=' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
    ('difference_1_2=' + $difference12.ToString('F6', [Globalization.CultureInfo]::InvariantCulture)),
    ('difference_2_3=' + $difference23.ToString('F6', [Globalization.CultureInfo]::InvariantCulture)),
    ('static_threshold=' + $threshold.ToString('F6', [Globalization.CultureInfo]::InvariantCulture)),
    ('result=' + $(if ($isStatic) { 'STATIC' } else { 'MOVING' }))
)
[System.IO.File]::WriteAllLines($resultFile, $lines, [System.Text.UTF8Encoding]::new($true))

if ($isStatic) { exit 2 }
exit 0
