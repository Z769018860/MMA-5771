$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root 'uid_mask.pid'
[System.IO.File]::WriteAllText($pidFile, [string]$PID, [System.Text.Encoding]::ASCII)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public static class MorimensWindow {
    public delegate bool EnumProc(IntPtr hwnd, IntPtr param);
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc proc, IntPtr param);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int length);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hwnd, ref POINT point);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();

    public static IntPtr Find() {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hwnd, IntPtr param) {
            if (!IsWindowVisible(hwnd)) return true;
            StringBuilder title = new StringBuilder(512);
            GetWindowText(hwnd, title, title.Capacity);
            if (title.ToString().IndexOf("Morimens", StringComparison.OrdinalIgnoreCase) >= 0) {
                found = hwnd; return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}

public class ClickThroughMask : Form {
    protected override CreateParams CreateParams {
        get {
            const int WS_EX_TRANSPARENT = 0x20;
            const int WS_EX_TOOLWINDOW = 0x80;
            const int WS_EX_NOACTIVATE = 0x08000000;
            CreateParams cp = base.CreateParams;
            cp.ExStyle |= WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
            return cp;
        }
    }
    protected override bool ShowWithoutActivation { get { return true; } }
}
'@

$form = New-Object ClickThroughMask
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.BackColor = [System.Drawing.Color]::Black
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.Width = 240
$form.Height = 38

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 150
$timer.Add_Tick({
    $hwnd = [MorimensWindow]::Find()
    if ($hwnd -eq [IntPtr]::Zero -or [MorimensWindow]::IsIconic($hwnd) -or [MorimensWindow]::GetForegroundWindow() -ne $hwnd) {
        $form.Hide()
        return
    }
    $rect = New-Object MorimensWindow+RECT
    if (-not [MorimensWindow]::GetClientRect($hwnd, [ref]$rect)) { $form.Hide(); return }
    $origin = New-Object MorimensWindow+POINT
    $origin.X = 0; $origin.Y = 0
    [void][MorimensWindow]::ClientToScreen($hwnd, [ref]$origin)
    $scale = [Math]::Max(0.65, ($rect.Bottom - $rect.Top) / 720.0)
    $form.Width = [int](240 * $scale)
    $form.Height = [int](38 * $scale)
    $form.Left = $origin.X + [int](14 * $scale)
    $form.Top = $origin.Y + ($rect.Bottom - $rect.Top) - $form.Height - [int](5 * $scale)
    if (-not $form.Visible) { $form.Show() }
})

$form.Add_FormClosed({ $timer.Stop(); Remove-Item -LiteralPath $pidFile -Force })
$timer.Start()
[System.Windows.Forms.Application]::Run($form)
