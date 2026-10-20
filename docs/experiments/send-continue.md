# 实验：不切前台、不模拟键盘，向 CC 会话发送“继续”

日期：2026-10-20 · Windows 11 · CC 2.1.289（终端）/ Claude 桌面端 2.42304.2（Code 标签页）
脚本：`tools/experiments/`（不被诗音正式代码引用）

## 结论

| 方法 | 能送达 | 不抢焦点 | 只进目标会话 | 结论 |
|---|---|---|---|---|
| 终端：AttachConsole + WriteConsoleInputW | ✅ | ✅ | ✅（按 PID 定位） | **可行** |
| 桌面端：UIA ValuePattern + InvokePattern | ✅ | ❌ | ✅（按会话标题定位） | **送得到，但会抢焦点，不满足要求** |

## 1. 终端版（`console_send.py`）

做法：`FreeConsole` → `AttachConsole(CC 的 pid)` → 打开 `CONIN$`/`CONOUT$` → `ReadConsoleOutputCharacterW` 读屏做安全检查 → `WriteConsoleInputW` 写每个字的按下/抬起（`VK_PACKET` + `uChar`），最后写回车（`VK_RETURN`, `'\r'`）→ 再读屏确认 → `FreeConsole`。

实测（测试 CC 在 scratch 目录，haiku，计划模式）：
- 传统 conhost 窗口：`继续` 提交成功，CC 开始回复。
- Windows Terminal（ConPTY）开两个标签：分别往两个标签发，各自只出现在自己那个标签里；被选中的标签和前台窗口都没变。
- 逐字写（字间隔 30ms，回车前 150ms）和一次性写完都能用（中文短句，没被当成粘贴）。
- CC 正忙时发送：消息进入 CC 的排队（“Press up to edit queued messages”），这一轮结束后再处理，不会打断。
- 前台窗口：每次写入前后都一样（中间有一次不一样，查了是用户自己在 ChatGPT/Edge 之间切换，测试控制台从来没到过前台）。
- 读屏本身也有用：能看到 CC 现在是空输入框、在忙、还是在等确认。

限制：
- PID 要选对：`~/.local/bin/claude.exe` 是常驻的 CC 进程；它启动时还会冒出几个马上退出的同名子进程，附着到它们会失败（错误 5）。诗音的 hook 已经能按父进程链拿到 `CLAUDE_PID`，可以直接用这个。
- 只对**终端里的 CC** 有效。桌面端托管的 CC 进程也能附着，但它的控制台是空的、隐藏的，它从管道（stdin）收消息，往控制台里写不会被读到（实验里只读屏，没有往里写）。
- 附着期间，本进程会和目标共用一个控制台：要先忽略 Ctrl+C（`SetConsoleCtrlHandler(None, True)`），用完马上 `FreeConsole`。同一时间只能附着一个控制台。诗音是 GUI 进程（没有自己的控制台），正好适合；放到单独的子进程里做更稳。
- 依赖 CC 现在的输入处理（Bun/libuv 在原始模式下用 ReadConsoleInput 读输入）。以后 CC 改了读输入的方式，这个办法可能就失效了。

风险（实测确认）：
- **回车会替用户点确认对话框**。测试中 CC 正好在问“要不要读 ~/.claude/plans”，第一项是 Yes，脚本读屏发现 `Do you want` / `> 1.`，就中止了。信任文件夹的对话框也一样（“No, exit / Yes, I trust”）。所以发送前**必须读屏**，看到对话框就不发。用 `--mode esc` 发 Esc 等于“拒绝/取消”，这个是安全的。
- **会和用户没发出去的草稿拼在一起**。先注入 `DRAFT-` 不回车，再发一条消息，CC 实际收到的是 `DRAFT-不要用工具…`。正式用的话，要先读屏确认输入行是空的（只有 `>`/`❯` 或提示占位）才发。
- 读屏判断是按文字匹配的，CC 界面改版、换语言后要重新调整；匹配太宽会误判（对话内容里正好有 “Allow” 也会中止，这是故意偏保守）。

## 2. 桌面端 Code 标签页（`uia_dump.ps1`、`uia_send.ps1`）

用的是 PowerShell 5.1 自带的 .NET `UIAutomationClient`，没装新依赖。

发现：
- **Chromium 一开始不建网页的无障碍树**：导出 UIA 树、用 MSAA 访问 `Chrome_RenderWidgetHostHWND`，网页区都是 0 个元素。注册一个 UIA 焦点事件监听后，几秒内出现约 280 个元素（很可能是 Chromium 看到“有 UIA 客户端在监听”才打开了无障碍）。`uia_send.ps1` 开头会先注册监听再等树建好。
- 输入框：`[Edit] '提示词'`，class `tiptap ProseMirror`，支持 ValuePattern，可写。发送按钮 `[Button] '发送'`，**输入框里有字才出现**；会话在忙时那里是 `'停止'`。
- **只有画面上正在显示的会话才有输入框**。目标会话没显示时找不到，脚本中止（已测）。窗口最小化时，当前显示的会话的输入框仍然在树里。
- 定位：先找会话标题按钮 `'<标题>，重命名会话'`，再往上找“只包含一个输入框”的最小祖先，当作这个会话自己的面板。分屏时两个输入框都在树里，这样能选对：两次发送都只进了测试会话，本会话的输入框一直是空的。
- SetValue 之后 ProseMirror 认这段文字（发送按钮出现并可用），Invoke 后消息发出、输入框清空，测试会话两次都回复了。

**焦点（这是没通过的地方）**：用户把 ChatGPT 放在前台，什么都不碰，分两次单独测：
- 只 `SetValue`：Claude 窗口被拉到前台，键盘焦点进了目标输入框。
- 只 `Invoke`（输入框里已有字）：同样把 Claude 拉到前台，分屏焦点也从原来的会话移到了目标会话。
- 只定位、只读的时候不会抢焦点。

所以桌面端这条路**会抢走前台和输入焦点**：用户正在别的程序里打字时，后面的按键会打进 Claude。这一点脚本这边改不了，是 Chromium 执行这两个操作时自带的聚焦行为。

其他限制和风险：
- 依赖界面文字（“提示词”“发送”“，重命名会话”）和结构，换语言、改版就失效。会话标题可以改，也可能重名（重名时脚本中止）。
- 只能发给正在显示的会话；要发给后台会话，就得先把它切到前面，这本身就是改用户的界面。
- 输入框里有用户草稿时脚本中止（不覆盖）；但从读值到 SetValue 之间，用户还是可能刚好在打字。
- 没测：用系统“屏幕阅读器”开关或 `--force-renderer-accessibility` 打开无障碍。前者是系统设置，会影响所有程序；后者要重启桌面端。而且这两个都不能解决抢焦点的问题。

## 建议

1. 这一轮**还没结束**、只是想让它接着做：用现有 hook，不需要注入。Stop hook 返回 `{"decision": "block", "reason": "继续"}` 就能让 CC 接着干。这条最稳。
2. 终端里的 CC **已经空闲**：可以用 AttachConsole 的办法，但必须同时做到：只用 hook 报上来的 `CLAUDE_PID`，发送前读屏确认是空输入框、不是确认对话框，放在单独的子进程里做，并且要用户在设置里主动打开。
3. 桌面端：不建议用 UIA 注入（会抢焦点、依赖界面文字）。继续让用户自己在 CC 里说话，或者等官方提供能发消息的接口。

## 复现

```
.venv\Scripts\python tools\experiments\console_send.py --list
.venv\Scripts\python tools\experiments\console_send.py --pid <pid> --dry-run --log out.json
.venv\Scripts\python tools\experiments\console_send.py --pid <pid> --text 继续 [--mode paced|burst|esc] [--no-enter]
powershell -NoProfile -ExecutionPolicy Bypass -File tools\experiments\uia_dump.ps1 -Out tree.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools\experiments\uia_send.ps1 -SessionTitle <标题> [-Fill | -Send] -Out out.json
```
`uia_send.ps1` 一定要先只定位、确认标题对应的是测试会话，再加 `-Fill`/`-Send`。不要拿正在用的会话做实验。
