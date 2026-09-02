param(
    [Parameter(Mandatory = $true)][ValidateSet('capture1','capture2','compare')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$ImagePath,
    [Parameter(Mandatory = $true)][string]$Prefix,
    [double]$Threshold = 0.0025
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$stateDir = Join-Path $PSScriptRoot '.motion_state'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$frame1 = Join-Path $stateDir ($Prefix + '_1.png')
$frame2 = Join-Path $stateDir ($Prefix + '_2.png')
$logFile = Join-Path $stateDir ($Prefix + '_motion.log')

function Save-Frame([string]$Source, [string]$Destination) {
    $sourceBitmap = [System.Drawing.Bitmap]::FromFile($Source)
    try {
        # 仅保留战场主体，排除时间、AUTO 按钮、资源计数和调试标注区域。
        $x = [Math]::Min(220, $sourceBitmap.Width - 1)
        $y = [Math]::Min(100, $sourceBitmap.Height - 1)
        $w = [Math]::Min(780, $sourceBitmap.Width - $x)
        $h = [Math]::Min(430, $sourceBitmap.Height - $y)
        $small = New-Object System.Drawing.Bitmap 96, 54
        $graphics = [System.Drawing.Graphics]::FromImage($small)
        try {
            $graphics.DrawImage($sourceBitmap, (New-Object System.Drawing.Rectangle 0,0,96,54), (New-Object System.Drawing.Rectangle $x,$y,$w,$h), [System.Drawing.GraphicsUnit]::Pixel)
            $small.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
        } finally { $graphics.Dispose(); $small.Dispose() }
    } finally { $sourceBitmap.Dispose() }
}

function Get-Difference([string]$Left, [string]$Right) {
    $a = [System.Drawing.Bitmap]::FromFile($Left)
    $b = [System.Drawing.Bitmap]::FromFile($Right)
    try {
        [double]$sum = 0
        for ($y = 0; $y -lt $a.Height; $y += 2) {
            for ($x = 0; $x -lt $a.Width; $x += 2) {
                $pa = $a.GetPixel($x, $y); $pb = $b.GetPixel($x, $y)
                $sum += ([Math]::Abs($pa.R-$pb.R) + [Math]::Abs($pa.G-$pb.G) + [Math]::Abs($pa.B-$pb.B)) / 765.0
            }
        }
        return $sum / (($a.Width / 2) * ($a.Height / 2))
    } finally { $a.Dispose(); $b.Dispose() }
}

switch ($Mode) {
    'capture1' { Save-Frame $ImagePath $frame1; exit 0 }
    'capture2' { Save-Frame $ImagePath $frame2; exit 0 }
    'compare' {
        $frame3 = Join-Path $stateDir ($Prefix + '_3.png')
        Save-Frame $ImagePath $frame3
        if (!(Test-Path $frame1) -or !(Test-Path $frame2)) { throw 'motion frames are incomplete' }
        $d12 = Get-Difference $frame1 $frame2
        $d23 = Get-Difference $frame2 $frame3
        ('{0:o} d12={1:F6} d23={2:F6} threshold={3:F6}' -f (Get-Date),$d12,$d23,$Threshold) | Add-Content -Encoding UTF8 $logFile
        # 三帧两段都几乎不变才判定停住。任何一段有明显动态即进入战斗监控。
        if (($d12 -le $Threshold) -and ($d23 -le $Threshold)) { exit 2 }
        exit 0
    }
}
