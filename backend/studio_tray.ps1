param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$studioRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$pythonPath = Join-Path $studioRoot '.venv\Scripts\python.exe'
$launchPath = Join-Path $studioRoot 'backend\launch.py'
if (!(Test-Path -LiteralPath $pythonPath) -or !(Test-Path -LiteralPath $launchPath)) { throw 'Run SETUP_STUDIO.bat before starting the tray.' }
if ($CheckOnly) { Write-Output 'Tray assemblies and installation paths verified.'; exit 0 }
$mutex = New-Object Threading.Mutex($false, 'Local\SceneFlowStudioTray')
if (!$mutex.WaitOne(0)) { $mutex.Dispose(); exit 0 }
$icon = New-Object Windows.Forms.NotifyIcon
$menu = New-Object Windows.Forms.ContextMenuStrip
$open = $menu.Items.Add('Open SceneFlow')
$stop = $menu.Items.Add('Stop Studio Agent')
$exit = $menu.Items.Add('Exit tray')
$startStudio = { Start-Process -FilePath $pythonPath -ArgumentList @(('"'+$launchPath+'"'), '--quiet') -WorkingDirectory $studioRoot -WindowStyle Hidden }
$open.add_Click($startStudio)
$icon.add_DoubleClick($startStudio)
$stop.add_Click({ Start-Process -FilePath $pythonPath -ArgumentList @(('"'+$launchPath+'"'), '--stop') -WorkingDirectory $studioRoot -WindowStyle Hidden })
$exit.add_Click({ [Windows.Forms.Application]::ExitThread() })
$icon.Icon = [Drawing.SystemIcons]::Application
$icon.Text = 'SceneFlow Studio'
$icon.ContextMenuStrip = $menu
$icon.Visible = $true
$noticePath = Join-Path $studioRoot 'logs\desktop-notice.json'
$script:lastNotice = ''
if (Test-Path -LiteralPath $noticePath) { try { $script:lastNotice = (Get-Content -LiteralPath $noticePath -Raw | ConvertFrom-Json).id } catch {} }
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 3000
$timer.add_Tick({
    if (Test-Path -LiteralPath $noticePath) {
        try {
            $notice = Get-Content -LiteralPath $noticePath -Raw | ConvertFrom-Json
            if ($notice.id -and $notice.id -ne $script:lastNotice) {
                $script:lastNotice = $notice.id
                $icon.ShowBalloonTip(5000, [string]$notice.title, [string]$notice.message, [Windows.Forms.ToolTipIcon]::Info)
            }
        } catch {}
    }
})
try { $timer.Start(); [Windows.Forms.Application]::Run() }
finally { $timer.Stop(); $timer.Dispose(); $icon.Visible = $false; $icon.Dispose(); $menu.Dispose(); $mutex.ReleaseMutex(); $mutex.Dispose() }
