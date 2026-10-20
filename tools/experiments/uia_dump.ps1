# 实验（只读）：把 Claude 桌面端窗口的 UI Automation 树导出到文本文件。
# 用 Windows PowerShell 5.1 自带的 UIAutomationClient，不装新依赖。
#   powershell -NoProfile -File tools\experiments\uia_dump.ps1 -Out <文件> [-MaxDepth 40] [-Filter Edit,Button,Document]
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$MaxDepth = 60,
    [string[]]$Filter = @()   # 只输出这些控件类型（为空则全部）；层级照样遍历
)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TW = [System.Windows.Automation.TreeWalker]::RawViewWalker

$procs = Get-Process -Name claude -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq 'Claude' }
if (-not $procs) { Write-Error '找不到 Claude 桌面端窗口'; exit 1 }
$root = $AE::FromHandle($procs[0].MainWindowHandle)

$sb = New-Object System.Text.StringBuilder
function Patterns($el) {
    ($el.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers.Pattern', '' }) -join ','
}
function Walk($el, [int]$depth) {
    if ($depth -gt $MaxDepth) { return }
    try {
        $c = $el.Current
        $type = $c.ControlType.ProgrammaticName -replace 'ControlType.', ''
        if ($Filter.Count -eq 0 -or $Filter -contains $type) {
            $name = $c.Name; if ($name.Length -gt 80) { $name = $name.Substring(0, 80) + '…' }
            $name = $name -replace "`r|`n", ' '
            $pats = Patterns $el
            $extra = ''
            if ($pats -match 'Value') {
                try { $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); $extra = " ro=$($vp.Current.IsReadOnly) val='$($vp.Current.Value)'" } catch {}
            }
            [void]$sb.AppendLine(('  ' * $depth) + "[$type] '$name' id='$($c.AutomationId)' cls='$($c.ClassName)' focus=$($c.HasKeyboardFocus) en=$($c.IsEnabled) off=$($c.IsOffscreen) pats=$pats$extra")
        }
    } catch { return }
    $child = $TW.GetFirstChild($el)
    while ($child -ne $null) {
        Walk $child ($depth + 1)
        $child = $TW.GetNextSibling($child)
    }
}
Walk $root 0
[System.IO.File]::WriteAllText($Out, $sb.ToString(), [System.Text.Encoding]::UTF8)
"已写入 $Out，共 $(($sb.ToString() -split "`n").Count) 行"
