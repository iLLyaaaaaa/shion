# 实验：用 UI Automation 往 Claude 桌面端 Code 标签页里“指定标题”的会话输入框写字，可选点发送。
# 不发键盘、不调 SetForegroundWindow。只是可行性实验，诗音正式代码不用它。
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\experiments\uia_send.ps1 -SessionTitle send-continue-test            # 只定位
#   ... -SessionTitle send-continue-test -Text 继续 -Fill                                                                    # 只填字
#   ... -SessionTitle send-continue-test -Text 继续 -Send                                                                    # 填字并点发送
# 结果写 -Out（JSON）。找不到 / 不唯一 / 输入框里有草稿时都中止。
param(
    [Parameter(Mandatory = $true)][string]$SessionTitle,
    [string]$Text = '继续',
    [switch]$Fill,
    [switch]$Send,
    [string]$Out = '',
    [int]$WarmupSeconds = 12
)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class Fg { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }'
$A = [System.Windows.Automation.Automation]
$AE = [System.Windows.Automation.AutomationElement]
$TW = [System.Windows.Automation.TreeWalker]::RawViewWalker
$Scope = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
$result = [ordered]@{ session = $SessionTitle; text = $Text; fill = [bool]($Fill -or $Send); send = [bool]$Send }

function Finish($code) {
    if ($Out) { [System.IO.File]::WriteAllText($Out, ($result | ConvertTo-Json -Depth 4), [System.Text.Encoding]::UTF8) }
    ($result | ConvertTo-Json -Compress -Depth 4)
    $A::RemoveAllEventHandlers()
    exit $code
}
function FocusDesc() {
    try { $f = $AE::FocusedElement; return "$($f.Current.ControlType.ProgrammaticName)|$($f.Current.Name)|$(($f.GetRuntimeId()) -join '.')" } catch { return '?' }
}
function Prop($cond1, $cond2) { New-Object System.Windows.Automation.AndCondition($cond1, $cond2) }

$proc = Get-Process -Name claude -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'Claude' } | Select-Object -First 1
if (-not $proc) { $result.error = '找不到 Claude 桌面端窗口'; Finish 1 }
$root = $AE::FromHandle($proc.MainWindowHandle)
$result.foreground_before = [Fg]::GetForegroundWindow().ToInt64()
$result.focus_before = FocusDesc

# Chromium 平时不建网页的无障碍树；注册一个 UIA 事件监听后它才会建（实验发现），等它出现
$handler = [System.Windows.Automation.AutomationFocusChangedEventHandler]{ param($s, $e) }
$A::AddAutomationFocusChangedEventHandler($handler)
$editCond = Prop (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Edit)) (New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, '提示词'))
$renameName = "$SessionTitle，重命名会话"
$renameCond = New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, $renameName)
$deadline = (Get-Date).AddSeconds($WarmupSeconds)
do {
    $edits = $root.FindAll($Scope::Descendants, $editCond)
    $titles = $root.FindAll($Scope::Descendants, $renameCond)
    if ($edits.Count -gt 0 -and $titles.Count -gt 0) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
$result.composers_in_window = $edits.Count
$result.title_matches = $titles.Count
if ($edits.Count -eq 0) { $result.error = '没有任何输入框（无障碍树没建起来，或窗口最小化/没显示 Code 标签页）'; Finish 1 }
if ($titles.Count -ne 1) { $result.error = "标题为 '$SessionTitle' 的会话不在画面上，或不唯一（$($titles.Count) 个）——只有正在显示的会话才有输入框"; Finish 1 }

# 从会话标题往上找，找到“只包含一个输入框”的最小祖先 = 这个会话自己的面板（分屏时防止发到隔壁）
$pane = $TW.GetParent($titles[0]); $composer = $null
while ($pane -ne $null) {
    $inPane = $pane.FindAll($Scope::Descendants, $editCond)
    if ($inPane.Count -eq 1) { $composer = $inPane[0]; break }
    if ($inPane.Count -gt 1) { break }
    $pane = $TW.GetParent($pane)
}
if (-not $composer) { $result.error = '会话标题和输入框对应不上（同一面板里有 0 个或多个输入框）'; Finish 1 }

$vp = $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
$result.readonly = $vp.Current.IsReadOnly
$result.value_before = $vp.Current.Value
$buttons = $pane.FindAll($Scope::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Button)))
$result.pane_buttons = @($buttons | ForEach-Object { "$($_.Current.Name)|en=$($_.Current.IsEnabled)" } | Where-Object { $_ -notmatch '^\|' })

if ($Fill -or $Send) {
    $existing = $vp.Current.Value.Trim()
    if ($existing -ne '' -and $existing -ne $Text) { $result.error = '输入框里已有草稿，中止（不覆盖用户的字）'; Finish 1 }
    if ($vp.Current.IsReadOnly) { $result.error = '输入框只读'; Finish 1 }
    if ($existing -eq '') { $vp.SetValue($Text) }
    Start-Sleep -Milliseconds 400
    $result.value_after_fill = $vp.Current.Value
    $result.focus_after_fill = FocusDesc
    $result.foreground_after_fill = [Fg]::GetForegroundWindow().ToInt64()
}
if ($Send) {
    # 发送按钮要输入框有字后才出现，重新取一遍
    $buttons = $pane.FindAll($Scope::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Button)))
    $sendBtn = @($buttons | Where-Object { $_.Current.Name -in @('发送', '发送消息', 'Send', 'Send message', '提交') })
    if ($sendBtn.Count -ne 1) { $result.error = "发送按钮找到 $($sendBtn.Count) 个"; Finish 1 }
    $result.send_enabled = $sendBtn[0].Current.IsEnabled
    if (-not $sendBtn[0].Current.IsEnabled) { $result.error = '发送按钮是灰的（编辑器可能没认 SetValue 的内容）'; Finish 1 }
    $sendBtn[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Start-Sleep -Milliseconds 1500
    $result.value_after_send = $vp.Current.Value
}
$result.focus_after = FocusDesc
$result.foreground_after = [Fg]::GetForegroundWindow().ToInt64()
$result.foreground_unchanged = $result.foreground_before -eq $result.foreground_after
$result.focus_unchanged = $result.focus_before -eq $result.focus_after
Finish 0
