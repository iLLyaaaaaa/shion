# 进度记录

> 每个步骤结束时更新这份文件。新会话从这里接手。步骤定义见 `docs/spec.md`「开发步骤」。

## 当前状态
- **2026-10-20 计划确认与完成提醒修正已实现**：ExitPlanMode 不再由诗音接管，只发高优先级三语计划提醒并跳一下；Stop 不再发送/显示回复内容。界面三语文字均不含“Claude”，hooks 备份已忽略。真实 CC 计划确认、三语气泡及跳跃观感 **待用户验收**，见下方本轮清单；用户明确授权先记录待验收再 commit，不 push。
- **v0.2.1 及此前的真机验收已通过**：依据用户 2026-10-19 明确反馈，除本次列出的交互问题外，旧清单均已验收；各历史节已更新标记。下方历史实现记录中的旧戳规则/摸头表扬以本次规则为准。
- **新版行走分帧素材已提交，爱心参数已调整**，验证结果见 2026-10-20 节；行走/跳跃、气泡仲裁与爱心的动态观感和真实桌面点穿仍 **待用户验收**。用户明确授权补测试、更新记录后 commit，不等待本轮真机验收；不 push。
- 上一轮交互打磨的待验收清单继续保留，不能用本轮自动测试和静态截图替代。
- 当前 hooks 仍只装在项目级 `.claude/settings.local.json`（已 gitignore）；用户级 `~/.claude/settings.json` 没动过。本次未安装/卸载 hooks。以后装用户级之前，先卸载项目级那份，避免重复事件。
- **v0.3 两部分都已实现**（暂停/继续 + 反馈队列、同意/否决），自动测试和真实 `claude -p` 联调通过；等待审查和用户真机验收，见下方两节的“待用户验收”。下一步是 v0.4。
- 环境：`.venv`（Python 3.10.11），测试用 `.venv\Scripts\python -m pytest -q`。本仓库提交邮箱为 GitHub noreply。

## v0.3 修正：计划确认交回 CC、完成时只提醒（2026-10-20）
- **计划确认**：PermissionRequest 的 `tool_name == ExitPlanMode` 在描述/截断内容之前直接旁路，只向 `/event` 发 `{"type":"plan_ready"}`；不登记请求、不轮询、不撤回、不输出决定，交回 CC。无计划、短计划、超长计划同样处理；诗音没开或发送失败仍静默退出。普通工具授权的同意/否决规则保留。
- **桌宠反应**：`plan_ready` 结束 working、刷新被理会时间，以高优先级提示并复用原地跳跃一次；不计完成任务、不进入 done、不启动完成后的定时催促。静音只抑制气泡，仍跳；安静档/固定表情不阻止事件小跳；拖动/下落沿用现有跳跃保护。计划不进入最近活动，旧调用方传来的 detail 也不记录到控制器日志。
- **完成提醒**：Stop hook 只发 `{"type":"stop"}`，删除回复第一句提取函数，不读取回复字段、不打开对话文件；控制器和最近活动也忽略旧 hook 发来的 stop detail。气泡只抽取 `claude_done` 提醒，done 3 秒、任务统计、催促、静音及隐私设置保留；最近活动只写“做完了”。
- **三语**：计划提醒为“计划写好啦，去看看吧～” / “The plan's ready! Take a look~” / “計画ができたよ、見てみてね～”；完成提醒为“做完啦！去看看结果吧～”等三语台词。同步替换原有问候、工作/等待/催促、菜单反馈、状态、端口提示和关于页的品牌字样，所有内置 `lines` / `ui` 的显示值都不含“Claude”；内部兼容键名保留。
- **其他**：`.gitignore` 加入 `*.shion-backup-*`；现有项目级 settings 和备份文件均不提交。无新依赖，不改精灵素材，不安装/卸载 hooks；当前配置直接调用本仓库脚本，桌宠重启后加载新事件处理。spec 已同步替换旧的计划接管和回复转述规则。下一开发步骤仍是 v0.4，旧待验收项继续保留。
- **验证**：默认环境完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/plan-stop-20261020/final-temp`，**611 passed，2 条原有 Pillow getdata 弃用警告**。已用 `python -m shion --snapshot` 生成并目视检查计划/完成提醒各三语，共 **6 张原生 Windows Qt 截图**，无裁切、方块字；英文完成提醒正常换行。截图和测试日志保留在已忽略的 `.venv/preview-run/plan-stop-20261020/`，未查看原始 PNG、未提交截图。回归覆盖 hook 子进程→真实本地 HTTP→GUI 事件处理、计划无登记/无决定/不发送正文/服务器不可用、已有授权队列保留、Stop 无内容及旧 hook 兼容、三语、高优先级、静音、跳跃阶段、安静档/固定表情、计数/状态/活动记录。`git diff --check` 通过，备份忽略生效且没有已跟踪备份。
- **测试踩坑**：移除两条已随功能淘汰的回复截句函数测试；首次全量给测试进程设置 `PYTHONIOENCODING=utf-8` 导致旧安装器测试按 Windows 默认 GBK 解码子进程失败，最终使用默认环境重跑。另一个旧暂停常驻测试会被随机闲聊按设计盖掉再恢复，已仅将该测试设为安静档，隔离随机待机行为，没有修改暂停功能。
- **待用户验收**（自动测试/静态截图不能替代真实 CC 与动态观感）：
  - [ ] 重启诗音后，在 **CC 终端版及桌面端 Code 标签页**生成计划：诗音只跳一下并提示去看计划、不弹计划授权面板；由 CC 自己显示确认并处理你的选择。
  - [ ] 中/英/日分别检查计划提醒和完成提醒的文字、气泡排版、打字效果与高优先级打断；计划小跳和落地的观感。静音时只跳不说。
  - [ ] 正常完成后只提示去看结果，气泡和双击最近活动不出现回复第一句；done 表情、任务计数和催促照常。已有普通工具授权面板的同意/否决仍可用。
  - [ ] 菜单、状态、关于页及日常气泡均不出现“Claude”。

## v0.3 审查（reviewer 子代理，2026-10-20）
- 结论：**没找到让 allow 来自诗音界面点击之外的路径**（server 各路由、hook 的 `permission_decision`、`PermissionQueue` 的锁与 id、面板切换瞬间的点击归属、键盘/焦点都核对过）。暂停流程、线程模型、存档迁移、与 spec 的一致性没有问题。
- 已修：① **反馈“取走”和“送达”不原子**：hook 取反馈超时 0.5s 小于 bridge 等 GUI 线程的 2s，GUI 卡顿时 hook 先断开、队列却已被清空而丢反馈。改为 hook 超时 3s（`FEEDBACK_TIMEOUT`）、bridge `TAKE_TIMEOUT` 1.5s，PostToolUse/UserPromptSubmit 总时限 6s；bridge 超时即取消，不会取走队列。② **超长命令被截断仍可点同意**：内容超过 12000 字时 hook 不登记请求、不给决定，交回 CC 自己的授权框（有测试）。③ 新增测试：settings 超时必须大于 hook 最长等待（PreToolUse ≥1895、PermissionRequest ≥180、FEEDBACK_TIMEOUT > TAKE_TIMEOUT）。④ spec 补了威胁模型一句（本机已被攻破的恶意进程不在范围）。
- 没改，记在这里：Edit/Write 只显示文件路径不显示改动内容（符合 spec）；hook 被 CC 杀掉后的“僵尸请求”面板最多停留 25 秒（`PENDING_IDLE`），这期间点按钮无害但没反应；“已经转告啦”在响应写出前就说了（超时修好后窗口极小）；没有专门测“按下旧请求、松开前已换成新请求”的 Qt 事件序列（逻辑上由 `_armed_at` 重置和点击时取 `_rid` 保证）。

## v0.3 第二部分：同意/否决（2026-10-20）
- **硬约束与落实**：allow 只能来自用户在诗音界面上的点击。① `remote.py:PermissionQueue.decide()` 是唯一能写入决定的入口，源码级测试断言整个包里只有 `controller.py` 的按钮回调（`_on_permission_decided`）会调用它、`server.py` 的源码里没有 `decide`；② HTTP 只有 `/permission/open|wait|withdraw`，没有任何字段会被读成决定（测试往所有接口、所有事件类型、各种形状的“同意”字段里灌，请求始终 pending）；③ hook 只有收到 `{"id": 同一个 id, "status": "allow"}`（恰好等于）才输出 allow，大小写不同、`true`、列表、id 对不上、缺字段、超时、连不上、撤回、`gone` 全部不给决定（交回 CC 自己的授权框）；④ 诗音没开：hook 连 `/permission/open` 都失败就立刻退出，无输出。
- **新增/改动**：`remote.py:PermissionQueue`（`secrets.token_hex(16)` 的 id、最多 20 个排队、内容 ≤20000 字、allow/deny 只能取一次、25 秒没人轮询的请求过期、没人取的决定 60 秒后清掉）；`server.py` 三个路由（授权请求体上限 64 KB，其他接口仍 4 KB；`request_queue_size` 调到 64——测试里并发连接偶发 `ConnectionResetError`）；`hooks/shion_hook.py`：`permission_decision` / `describe_permission` / `deny_message`，`ensure_ascii=False` 发请求（中文计划不会膨胀 6 倍）；`hooks_config.py`：新增 PermissionRequest（matcher `*`，超时 180 秒）；`panel.py:PermissionPanel`；`controller.py` 的 `_sync_permission`（tick 里每 100ms 同步，一次显示一条、显示“还有 N 个”）。内容显示规则见 spec「同意/否决的实现要点」。
- **面板**：不抢焦点（`WindowDoesNotAcceptFocus` + `WA_ShowWithoutActivating`），键盘一律不响应（`MouseOnlyButton` 忽略所有按键——测试里直接给按钮发空格/回车也不会同意），每条请求出现 0.6 秒内按钮灰着（防误点，换成下一条同样重新计时），内容区只读、约 6 行，长内容出现“展开/收起”，静音时面板照常弹出（只是不说那句话）。`--snapshot --panel permission|input` 新增，三语/长文本/展开都看过截图，无裁切、无方块字。
- **验证**：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/v03-b/t8`，**581 passed**（521 + `tests/test_permission.py` 60 项）。**真实 `claude -p`（2.1.289，haiku，隔离端口，假桌宠服务器按模式自动“点击”）**：PowerShell 写文件命令 → 请求带着完整命令和描述出现在队列里；点“同意”后文件真的被创建、模型回 RAN；点“否决”后文件没被创建、模型回 DENIED；无人决定（超时 10 秒）后文件没被创建，**没有被默认同意**（`-p` 模式下 CC 没人可问，自己拒绝）。踩坑：①`ExitPlanMode` 在 `-p` 下不会走授权，没法自动实测，留给你；②测试里面板对象被别的线程的垃圾回收销毁会让 Qt 直接 abort（偶发整个 pytest 崩溃），所以 `PetController.dispose()` 在 GUI 线程立刻销毁面板，测试的 `Env.close()` 调用它。③git bash 里用 `
` 写进 Python heredoc 会变成真换行，改文件要用编辑工具。
- **hooks 已重新安装到项目级** `.claude/settings.local.json`（含 PostToolUse、PermissionRequest；备份 `settings.local.json.shion-backup-*` 留在同目录，未提交）；用户级 `~/.claude/settings.json` 仍没动。
- **待用户验收**（我看不到真实桌面和 CC 界面）：
  - [ ] **CC 终端版和桌面端 Code 标签页**：授权请求能否被诗音面板接管；点“同意”“否决”后 CC 的反应；CC 自己的授权框会不会同时弹出（预期：hook 给了决定就不弹）；诗音面板在你同时操作 CC 时不抢键盘焦点。
  - **ExitPlanMode 旧验收项已被替代**：不再验收诗音接管/显示计划全文；按上方“计划确认交回 CC”清单验收。此项不表示旧实现曾通过用户验收。
  - [ ] 面板外观（终端配色、两个大按钮、“还有 N 个”）、0.6 秒防误点的手感、多个请求（子代理并行）排队、你在 CC 里自己答了之后面板是否在约 25 秒内消失。
  - [ ] 120 秒超时后 CC 是否照常弹出自己的授权框（可把存档 `remote.permission_timeout` 临时改成 10 测试）。
  - [ ] 面板与气泡同在诗音头顶时的叠放观感（面板在上层，可能盖住气泡；如果不好看再调）。
- 已知取舍/风险：本机若有别的程序在诗音没开时占用 47613 端口并冒充服务器，理论上能回 allow；这需要本机已被攻破，本版不处理。PreToolUse/PostToolUse/PermissionRequest 每次多一个 python 进程（约 0.1 秒）。授权面板里的内容不受“只显示状态，不显示内容”隐私开关影响。

## v0.3 第一部分：暂停/继续 + 反馈队列（2026-10-20）
- **新增** `shion/remote.py`（纯 Python）：`RemoteHub`，用 `Condition` 保护暂停标志，`wait_while_paused(秒)` 供服务线程长轮询（单次上限 30 秒）。服务线程只读/只等；开始暂停只能由 GUI 线程调用 `hub.pause()`。
- **服务端**：`POST /feedback/take`（取代 `/praise/take`，返回 `{"text"}`）、`POST /pause/wait`（只读；坏的 wait 值当 0）。收到 `prompt` 事件时服务线程**直接** `hub.resume()`（紧接着的工具调用不会被误挡），再转给 GUI。HTTP 里没有任何能让暂停开始的接口（有测试）。`bridge.py` 的请求对象泛化为 `_TakeRequest`，超时后不会把队列取走。
- **hook**：PreToolUse 先问 `/pause/wait`，暂停中 25 秒一段循环等；诗音没开、请求失败、返回内容不是 `{"paused": true}` 一律放行；等满上限输出 `permissionDecision: deny`（理由“用户暂停了工作，请停下并等待用户指示”）并发 `pause_timeout`，被拒绝的那次不发 `working`。新订阅 PostToolUse：取反馈非空就输出 `additionalContext`。UserPromptSubmit 改为取 `/feedback/take`。总时限：PreToolUse = 暂停上限 + 30 秒，其他事件不变。暂停上限读存档 `remote.pause_timeout`（夹在 60～1880）。`hooks_config.py`：新增 PostToolUse，PreToolUse 超时 1900 秒。**项目级 `.claude/settings.local.json` 里的 hooks 还没重新安装**，要实测前先 `uninstall` 再 `install`（第二部分结束时一起做）。
- **存档 v3**：`pending_praise` 换成 `feedback_queue`（最多 5 条，满了丢最早的；`bad` 的文字单行、最多 200 字）和 `remote`（暂停/授权秒数）。v1 丢弃旧计数，v2 的 `pending_praise` 迁移成等量“做得好”。`PetState.paused`（不存档）：暂停时显示 `stop`，优先级低于拖动/固定/手动/临时表情，高于 working。
- **界面**：右键新增“工作遥控”子菜单（暂停工作⇄继续工作 / 做得好 / 有问题……），原顶层“做得好”并入。暂停时气泡“暂停中”一直挂着（`sticky`：打完字不淡出；`SpeechGate` 按低优先级占位，别的台词可以盖掉它，说完后 tick 里自动恢复；静音时不显示）；超时后文字换成“已经停下了，在 CC 里说一声就能继续”，暂停标记保留，点“继续”只解除标记。“有问题……”弹出新的 `shion/panel.py:InputPanel`（终端配色、一行输入框、Enter 发送/Esc 取消、可留空，这个面板会拿键盘焦点）。送达反馈后说“已经转告啦”。新增 UI 文字不含 “Claude”，三语齐全。
- **验证**：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/v03-a/t12`，**521 passed**（485 基线；改写了旧 praise 测试，新增 `tests/test_remote_control.py` 30 项和 hook 暂停/反馈子进程测试）。**真实 `claude -p`（2.1.289，haiku）联调**（假桌宠服务器 = `ShionServer`+`RemoteHub`，暂停 8 秒）：PreToolUse 被挡住 8 秒、释放后正常开工；PostToolUse 的 `additionalContext` 被模型原样看到；UserPromptSubmit 注入反馈正常。踩坑：`-p` 一开始就会触发 `prompt` 事件，按规则这会解除暂停，所以联调时要在 prompt 之后再暂停。
- **待用户验收**（我看不到真实桌面/CC 界面）：
  - [ ] 暂停时 CC 终端版和桌面端 Code 标签页里看到什么（工具卡住的样子）；点“继续”无缝继续；在 CC 里说话自动解除；暂停挡手造型和“暂停中”气泡观感。
  - [ ] 暂停超时的提示（可临时把存档 `remote.pause_timeout` 改成 60 测试）。
  - [ ] “做得好”/“有问题……”：工作中（PostToolUse）和空闲时（下一条消息）各自送达，Claude 的回应是否自然，“已经转告啦”。
  - [ ] “有问题……”输入面板的外观、焦点和三语文字。
- 已知取舍：并行子代理的多个 PreToolUse 各自计时，超时时每个都 deny；暂停后诗音被关闭，等待中的 hook 会在下一次长轮询失败时放行（最多 25 秒）。

## 2026-10-20：新版走路分帧与爱心密度
- 先按用户指定范围独立提交 **`4b26f44`**：`assets/sprites/raw/walk_sheet.png`、`tools/process_sheets.py` 和重新生成的 `walk_1~4.png`、`jump_1~2.png`，共 8 个文件。本轮未再修改原图、生成图或处理脚本；程序读取验证连通区域能切出走路 4 帧/跳跃 2 帧，6 张生成图均可解码且为 448×512 RGBA，未直接打开原始 PNG。提交前完整基线 **477 passed**。
- `effects.py`：爱心间隔 **0.6 → 0.2 秒**，同时最多 **3 → 6 颗**，基准大小 **18 → 20px**，上飘 **45 → 55px**；原有 1 秒寿命、0.8～1.2 随机大小、分布范围、缓动、鼠标穿透及精确计时保留。
- 沿用相邻摸头间隔 ≤1 秒的连续过程判定。每个新过程的首次有效摸头反馈立即冒 **2 颗**，不受冒出间隔阻挡，仍服从 6 颗总数上限；此后按 0.2 秒间隔冒一颗，超额丢弃、不排队。连续摸头超过 6 秒的第二次台词尝试不重复双爱心；静音或台词被高优先级提示拦截时爱心照常。
- `PatSession` 仅增加当前一次是否开启新过程的标记，由控制器传给粒子层；不改变摸头台词、好感度、统计和仅菜单产生待表扬的规则。规格同步更新，无新依赖；下一开发步骤仍为 **v0.3 Claude Code 遥控**。
- 相关测试 **115 passed**；完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/hearts-20261020/full-temp`，**485 passed**（基线 477＋新增 8 项），仅 2 条原有 Pillow `getdata` 弃用警告。覆盖开始双爱心、0.2 秒/1 秒边界、6 颗上限/剩余容量、过期与不补播、55px 上飘、第二句不重复双爱心、重要台词/静音不抑制爱心及统计保留。日志在已忽略的 `.venv/preview-run/hearts-20261020/`，不提交；`docs/preview.png` 继续忽略。

**本次待用户验收**：
- [ ] 新版四帧行走、左右镜像及跳跃的观感与对齐。
- [ ] 新摸头过程首次立即冒 2 颗；持续摸头时爱心的密度、20px 大小、55px 上飘距离是否合适。
- [ ] 连续过程与停顿超过 1 秒后重新摸头的反馈，真实桌面上爱心仍不挡鼠标，四档尺寸/高分屏下流畅。
- 自动测试不能替代以上真机视觉和交互验收；用户已授权完成记录后提交，本次不 push。

## 2026-10-19：行走/跳跃帧动画与气泡仲裁
- 按用户要求先独立提交素材准备：`1967da9`，仅包含 `raw/walk_sheet.png`、`raw/jump_sheet.png`、两个处理脚本和生成的 `walk_1~4.png`、`jump_1~2.png`，共 10 个文件；基线 **403 passed**。本轮功能实现没有再改这些素材和脚本。
- 精灵加载增加可选动作帧组：必须整组齐全、可解码且与 idle 同画布才启用；缺图、坏图、画布不匹配时按组回退。两种行走均循环 walk 四帧，原图向右、向左用缓存镜像；80px/s 时每帧 140ms，帧时长随速度反比变化，每两帧一步，附加同步 3px 上下起伏。缺图仍用原状态图及旧的 10px / 0.45 秒起伏。
- 菜单“跳一跳”和待机小跳共用：jump_1 下蹲 0.15 秒 → jump_2 腾空 0.4 秒、程序升高最高 40px → 恢复当前底层表情并落地压扁/回弹 0.25 秒。缺图整组回退 18px / 0.5 秒旧动画。动作帧在显示层覆盖，控制器同步不会重启序列；位移和帧选择都按实际经过时间采样，落地回弹从预定落地时刻算，掉帧不延长动作。保留按下中断、脚底锚点、绘制/遮罩同步与位置保存。
- 新增纯 Python `speech.py`：高优先级（Claude 完成及结果转述、出错、催促、等待确认，预留 permission_request）随时打断，包括另一条高优先级；中优先级（问候/启动/唤醒/回归、菜单反馈、双击状态）只能打断低；低优先级（摸头、戳、拖、自言自语、工作过程提示）不能打断中/高，低之间须当前气泡出现满 2.5 秒、同类已说出台词间隔满 4 秒。工作过程原有 3 秒去重仍保留，并服从低优先级限制。拦截时直接丢弃，不补播、不抽取随机台词；自然结束、静音或切换语言收起后不会残留优先级阻挡。双击状态保留静音豁免，但服从优先级。
- 摸头改为相邻间隔 ≤1 秒的连续过程：开始尝试一句，持续超过 6 秒再尝试一句，每过程最多两句；两次尝试均服从仲裁。爱心、happy、好感度与统计逐次正常处理。戳的普通/挡手/晕共用戳冷却；拖动和落地晃晕共用拖冷却；Claude 出错独立为高优先级。时间集中在 `speech.py`、`behavior.py` 及原有 Animator 常量中，气泡打字/停留/淡出与仲裁共用时间常量。
- 英文菜单精确改为 **Flustered / Teary / Auto expressions / Walk to the other side**。规格同步更新；没有推进 v0.3 授权/遥控功能，没有新依赖。
- 验证：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/frames-full-final`，**477 passed**（403 基线＋74 项；更新了与新冷却规则冲突的旧断言）。覆盖优先级全组合、2.5/4/1/6 秒边界、同类归并、拒绝不补播、不中断爱心/统计、帧循环/步速、跳跃阶段/落地、缺失/坏图/画布不符回退、丢帧、按下中断、四档尺寸的镜像与遮罩。150% Qt 缩放专项 **32 passed**。2 条原有 Pillow getdata 弃用警告，无新增警告。
- 视觉：只通过 `.venv\Scripts\python -m shion --snapshot` 生成并目视检查 **19 张原生 Windows Qt 截图**（左右各四帧、跳跃 8 个时刻、中/英/日腾空气泡各一张），未见裁切、方块字或气泡遮头。新增 `--walk --at ...`，`--jump --at 0.35` 为最高点。截图和日志在已忽略的 `.venv/preview-run/frames-visual/`、`frames-full-final.log`、`frames-dpi-1.log`，不提交。
- 踩坑：40px 跳跃增加顶部留边后，旧截图合成会把气泡放低，已调整气泡利用顶部空白，并按腾空位移留出头顶空间；补截图回归验证气泡不覆盖最高点人物。原始 PNG 未直接打开，只查看 --snapshot 的输出。

**本次待用户验收**：
- [ ] 散步和走到另一边的四帧步频、3px 起伏、左右朝向、结束/按下中断后的恢复与位置保存。
- [ ] 菜单跳跃与待机小跳的下蹲、40px 腾空、落地回弹是否自然，固定/手动表情恢复是否符合预期。
- [ ] 连续摸头开始与超过 6 秒的两句反馈，戳/拖台词冷却是否合适；爱心和表情反馈照常。
- [ ] Claude 完成、出错、等待确认、催促能及时打断；问候/菜单/状态查询及低优先级台词不会盖掉重要提示。
- [ ] 真实桌面中动作帧及跳跃的点穿、四档尺寸/高分屏流畅度，以及四个英文菜单新名称。

## 2026-10-19：交互打磨（7 条反馈＋普通启动台词，历史）
- 用户已确认整体方案及最终概率。连续点击间隔 ≤1.5 秒：1～2 下普通；3～4 下挡手 **60%** / 晕 **20%** / 普通 20%；第 5 下起挡手 **55%** / 晕 **40%** / 普通 5%。单次抽取互斥，挡手/晕后清零，删除固定 5/10 下规则。
- 爱心：统一粒子层限流（≥0.6 秒一颗、同时 ≤3 颗、不排队），18px / 上飘 45px。摸头仅好感/统计/happy/爱心；菜单“做得好”才增加待表扬。hook 按存档语言输出一句 `[诗音] 用户觉得你刚才做得很好。` 的中/英/日版本，无次数、多次合并。
- 存档 `schema_version=2`：旧待表扬无法区分来源，升级仅清空一次旧 `pending_praise`；好感、统计、位置和其他选项保留，新菜单表扬重启保留。
- 拖动晃动：反向摆幅 >40px 才确认转折，过滤抖动；2 秒内至少 3 次反转即记住晃晕，落地才切 dizzy 2.5 秒＋台词。每轮拖动重新计数，下落仍是 drag。
- 表情菜单：九种表情，临时 5 秒；固定选项存档、重启恢复，台词/事件/统计照常，拖动/下落优先 drag、落地恢复固定表情；双击显示“表情已固定”。恢复自动清掉手动表情，不重播固定期间的旧反应。
- 活跃度：安静 / 普通（8～20 秒）/ 活泼（4～10 秒），存档；镜像转身、朝鼠标、原地跳、happy/idle 2 秒、`idle_talk`（10% 抽取、至少间隔 60 秒）。实际 Claude 工作、固定、睡眠、拖动/下落、按住鼠标、打开菜单时暂停；不累积补播、不刷新睡眠/被理会时间。适用的呼吸/眨眼保留；独立 blink 图只用于 idle，不覆盖其他姿势。
- 动作菜单：沿当前屏幕任务栏上沿随机散步 10 秒、走到该屏幕另一侧、跳、转身。行走 80px/s、蹦跳 10px / 0.45 秒，朝向跟随方向；按下鼠标立即中断，再照常戳/摸/拖；结束/中断保存新位置。原地跳 18px / 0.5 秒和镜像转身不改变最终位置。
- 普通非首次启动改为 `startup`，取消随机重复 intro；hook 仅对子进程设置启动来源，非首次拉起交给 session_start 问候。新增台词和 UI 全部中/英/日；相关数值集中在 `state.Config`、`behavior.py`、`effects.py` 常量中。
- 实现沿用原分层，仅新增纯 Python `behavior.py`（晃动、待机调度、按时间采样的行走路径），没有新依赖/精灵素材变更。镜像缓存运行时图像；绘制/遮罩同变换，修正奇数宽度的半像素中心。画布顶部增加原地跳留边。`--snapshot` 新增 `--mirror`、`--jump`。
- 验证：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/feedback-complete`，**403 passed**（原基线 321；更新旧规则测试并补概率边界、晃动/真实手势、表情/存档、待机、路径/中断、三语 hook 等）。150% Qt 缩放下锚点/遮罩/镜像/跳跃专项 **24 passed**。2 条原有 Pillow getdata 弃用警告；无新增弃用警告。原生 Windows Qt `--snapshot` 生成并目视检查 **12 张**镜像/过渡/跳跃/三语大计数固定状态及长 startup/idle_talk 截图，未见裁切、方块字或文字越界；不替代动态真机验收。日志为 `.venv/preview-run/feedback-complete.log`、`feedback-dpi-fixed.log`，截图为 `.venv/preview-run/feedback-visual/`，均已忽略、不提交。
- 踩坑：Qt 的负缩放重采样会让镜像边缘有细小差异，改用缓存镜像；不用已弃用的 QImage.mirrored。概率累加阈值做浮点规整，保证 95% 边界落入普通反应；自动跳被工作状态打断时清理位移。

**本次待用户验收（旧验收结论不替代以下新行为）**：
- [ ] 爱心的密度、大小和上飘距离。
- [ ] 随机挡手/晕的体验，以及清零后前两下的反馈；精确概率以自动边界测试为准。
- [ ] 拎起晃动的灵敏度；小抖不误判，落地才晕 2.5 秒并说话。
- [ ] 摸头不再传表扬；连续点“做得好”只合并一句，Claude 的自然回应；中/英/日转达。
- [ ] 九种表情、临时 5 秒、固定/恢复自动、拖动恢复固定、重启保持、双击固定提示。
- [ ] 三档活跃度、自言自语频率、朝向鼠标、原地跳；工作/固定/睡眠时安静。
- [ ] 镜像与跳跃中的真实桌面点穿、脚底稳定、不同大小/高分屏下的流畅度。
- [ ] 散步/走到另一边的朝向、边界、按下即中断、新位置重启恢复；跳/转身不改变最终位置。
- [ ] 三语新菜单文字和 startup；普通重启不再说“Claude 来啦”，hook 拉起仍正常问候，静音正常。

## 2026-10-19：此前审查记录（历史）
- reviewer 曾审查动画打磨与自我介绍提交 `39b0316`、`ea6aac3`，没有必须修的问题。当时可选项：端口占用提示覆盖首次介绍；普通启动专用 startup（已在本轮解决）；同状态重播需 `immediate=True`；下落中改大小重置速度；淡化帧的 `toImage` 可在出现卡顿时再缓存。
- 以下各节保留当时的实现与测试记录；当前交互规则以上方本轮记录为准。验收标记依据用户本次确认更新。

## v0.2.1：状态感知（2026-10-19，用户外出，只做自动化验证）
- **hook 命令改成 exec 形式**：`"command": "<.venv>/Scripts/python.exe", "args": ["<项目>/hooks/shion_hook.py", "<事件>"]`，绝对路径、不经过 shell，路径带空格也不用引号，PowerShell/bash 都不受影响，不再依赖 PATH 里的 python。已在 Claude Code 2.1.289 上用真实 `claude -p` 实测可用。`_is_shion` 同时识别旧的引号/`python "…"` 格式，重装会替换、卸载会删。新增订阅 `PostToolUseFailure`。
- **hook 脚本**：PreToolUse 发 `working`，detail 是 JSON `{"tool": 类别, "target": 简短目标}`（文件只取文件名、搜索词/Agent 描述 ≤20 字、网址只取域名、目标最长 60 字，**Bash 不带命令内容**）；Stop 发 `stop`，detail 是回复第一句（≤40 字）；PostToolUseFailure 发 `tool_error`（用户中断的不发）。
- **偏离 spec**：spec 写的是读 `transcript_path`，改用官方文档推荐的 stdin 字段 `last_assistant_message`（官方说 Stop 时 transcript 不保证已含最后一条）。
- **桌宠侧**：新增 `shion/activity.py`（最近 20 条、显示 5 条，内存里，不进存档）；working 带描述时气泡说“在读 x.py……”等（同一句 3 秒内不重复，替代随机的 claude_working）；stop 带第一句时说“做完啦：…”；tool_error → dizzy 2 秒 + 台词；Claude 停下 5 分钟（debug 下 20 秒）没新消息 → 提醒并跳一下（`PetWindow.bounce`），最多 2 次，用户理会/睡醒/Claude 重新开始都会取消；双击状态下面多出“最近：”和 5 条记录；右键新增「只显示状态，不显示内容」（存档 `privacy_mode`，打开后不显示也不记日志文件名/搜索词/回复，切换时清空记录）。三语台词/界面文字都已加。
- 气泡 `\n` 现在真的换行（内部用 U+2028，绘制时去掉），之前换行符会被当成一个字符挤在一行。
- 验证：pytest 321 个通过（新增 hook 纯函数/子进程、状态机、控制器、activity、安装卸载测试）；真实 `claude -p` 端到端（隔离端口和数据目录）日志里依次出现 `working {"tool":"read","target":"progress.md"}`、“在读 progress.md……”、`tool_error 'Read'` → dizzy、`stop '读取失败：…'` → “做完啦：…”、20 秒后催促；用 `--snapshot` 看过长状态气泡（多行、最近 5 条）不越界。
- **已验收（用户真机确认，2026-10-19）**：①工具描述气泡会不会太吵（可调 `ACTIVITY_REPEAT`）；②“做完啦：……”转述是否通顺；③出错时晕一下的观感；④5 分钟后跳一下提醒是否合适；⑤双击看最近记录；⑥隐私开关；⑦桌面端 Code 标签页里是否同样生效（只在终端 `claude -p` 测过）。
- 审查可选项（没做）：隐私模式只控制**显示和日志**，不控制传输——hook 不知道桌宠是否隐私模式，文件名/搜索词/回复第一句仍会发到本机 127.0.0.1；静音时催你回来仍会跳一下但不说话；`server.py` 的 `main()` 调试入口会 print detail（只在调试用）。
- 踩坑：Python 里用 heredoc 写含 `\n`、`\\` 的源码时转义会被二次处理，改这类代码要用编辑工具直接改文件再跑测试。

## v0.2：Claude Code hooks（2026-10-19，用户外出，只做自动化验证）
- 新增 `hooks/shion_hook.py`（只用标准库）：5 个事件映射到 session_start/prompt/working/stop/notification；UserPromptSubmit 调 `/praise/take`，count>0 且存档 `inject_praise` 不为 false 时用 UTF-8 字节写出那句表扬；SessionStart 在 `/health` 不通时用 `.venv\Scripts\pythonw.exe -m shion` 脱离父进程拉起桌宠并最多等 3 秒。任何情况返回 0、stderr 为空；请求不走系统代理、单次超时 0.5 秒，另有总时限兜底（普通事件 2.5 秒、SessionStart 12 秒）。
- 新增 `tools/install_hooks.py`、`uninstall_hooks.py`、`hooks_config.py`：`--settings PATH`（默认用户级 `~/.claude/settings.json`）；写前备份为 `*.shion-backup-时间戳`，合并不覆盖、可重复安装、卸载只删 Shion 条目；坏 JSON 不改文件；文件不存在/没有变化时卸载不写盘。
- 桌宠侧只加日志：`收到事件：…`、`取走夸奖：N`，用日志验证事件有没有到。
- **开发阶段只装在项目级** `.claude/settings.local.json`（已 gitignore，含本机绝对路径）；**没有动用户级 `~/.claude/settings.json`**。
- 验证：pytest 287 个通过（新增 hook 子进程测试、服务卡死/关闭/大 stdin、安装卸载往返等）；手动冒烟（隔离端口和数据目录）逐个事件日志正确；**真实 `claude -p` 端到端**：桌宠关闭时 SessionStart 自动拉起，日志依次出现 session_start / prompt / working / stop。
- **踩坑**：Claude Code 在这台机器上用 **PowerShell** 执行 hook，命令以带引号的路径开头（`"D:/…/python.exe" …`）会解析失败（hook 报错但不阻塞）。所以命令改成以不带引号的 `python` 开头：`python "D:/…/hooks/shion_hook.py" Stop`，bash 和 PowerShell 都能解析。代价：要求 PATH 里有真 python（install 脚本会检查，Microsoft Store 占位程序会被拒）；项目路径含 `$`、反引号、引号时拒绝安装。
- **已验收（用户真机确认，2026-10-19）**：①桌面端 Code 标签页和终端里开会话时桌宠自动出现、没有控制台窗口一闪；②用工具时 working、结束 done 的观感；③原摸头/夸夸联动（本次改为仅“做得好”）的下一条消息里 Claude 是否自然回应表扬；④关掉桌宠时 CC 完全无感（PreToolUse 每次多一个 python 进程，约 0.1 秒）；⑤桌面端 Code 标签页是否也读到项目级 `.claude/settings.local.json`（只在终端测过）。
- 审查可选项（没做）：用户级和项目级同时装会让每个事件触发两次（claude_tasks +2）——**装用户级之前先对项目级运行 `uninstall_hooks.py --settings .claude/settings.local.json`**；`inject_praise` 是 hook 读磁盘存档的，右键切换后若还没落盘会读到旧值（目前菜单里没有这个开关，影响小）；`launch_shion` 无自动测试；PowerShell 下解析命令没有自动测试；拉起桌宠超过 3 秒才就绪时那次 session_start 会丢。
- 已知取舍：被 SessionStart 拉起时，桌宠自己的启动介绍会被随后的 session_start 问候盖掉。

## 2026-10-19：动画打磨与启动自我介绍
- 按用户要求先提交此前遗留：截图验收记录/忽略规则、诗音更名和三语 `intro` 台词（`39b0316`）；基线 237 项测试通过。此次实现不新增或修改图片素材，不引入新依赖。
- 全部 QTimer 改用 `Qt.PreciseTimer`。桌宠、爱心、气泡的动画时钟为 `time.perf_counter()`；下落按起点和实际经过时间解析计算重力位置，去掉 50ms 的截断，错过落地后的压扁也会按真实时间结束。
- 精灵切换约 120ms ease-out 交叉淡化，3% 轻微压扁后回弹，脚底固定；快速切换从当前混合画面和姿态继续。眨眼同样淡化，但不额外压扁。粒子位移改三次 ease-out，倾斜保留指数 ease-out，缩放使用平滑压扁/回弹曲线。
- idle 每隔 6～15 秒随机轻微歪头或左右晃约 1.2 秒，幅度 ≤1.8°。眨眼、小动作各用独立随机序列并按预定时刻推进，掉帧不会把后续动作整体推迟。鼠标拖动仍直接跟手，下落保留重力加速。
- 遮罩覆盖淡化中所有可见精灵，按姿态缓存；不随权重重复生成。把重画 13 遍改为绘制一遍后平移合并区域；保留非透明轮廓像素，透明角落仍点穿。180 帧 dizzy 的原生 Qt 本机采样：320px 档位刷新逻辑（含遮罩）P95 约 **4.6ms → 1.5ms**，绘制 P95 约 0.7ms；这是函数计时，不能替代真实桌面帧率，暂不降遮罩更新频率。
- 没有存档文件时启动说当前语言的 `intro`；已有存档时 `<10%` 说 `intro`，其余 `greeting`；遵守静音，Claude session_start 逻辑保留。自动测试覆盖首次、概率边界、静音和真实子进程首次启动日志。
- `--snapshot` 增加 `--from-state`，例如 `--from-state idle --state working --at 0.06` 检查淡化中间帧；原有不带该参数的截图仍直接显示目标状态。
- 验证：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/animation-full-1`，**263 passed**（新增 26 项）；150% Qt 缩放下交叉淡化/遮罩专项 **7 passed**；2 条原有 Pillow `getdata` 弃用警告。日志、性能数据及检查图放在已忽略的 `.venv/preview-run/`；`docs/preview.png` 仍不提交。
- 已看过原生 Qt 过渡截图（0/30/60/90/120/240ms）和固定种子的 idle 小动作截图：未见裁切或脚底跳位。修过淡化叠加导致身体短暂闪透的问题，以及遮罩阈值遗漏半透明轮廓的问题，均有回归测试。
- **已验收（用户真机确认，2026-10-19）**：实时淡化/回弹是否自然；连续快速摸头、拖动、松手的跟手感；idle 小动作频率和幅度；淡化中和动画后的真实桌面点击穿透；高分屏下的实际流畅度；中/英/日首次介绍、重启问候及静音体验。自动化和静态截图不算这些项目的人工验收。
- 用户已明确授权本次验收清单标待验收后提交。下一开发步骤仍是 **v0.2 Claude Code hooks**；本次不 push。

## 2026-10-19：截图视觉检查（用户外出，代查静态画面）
- 使用 `.venv\Scripts\python -m shion --snapshot`，原生 Windows Qt 平台生成 **12 张状态截图 + 中/英/日各 4 张气泡截图**：每种语言按字数挑最长的两条台词、使用大计数的状态文字（9999 天 / 99999 次 / 好感度 999999）和端口占用提示，共 24 张。
- 总览：`docs/preview.png`（1280×2449），已加入 `.gitignore`，**不提交**。单图、三语细节图、生成脚本、检查结果和测试日志在已忽略的 `.venv/preview-run/`。
- 已目视检查总览和三语原尺寸细节：12 张状态内容正常；未见方块字、气泡文字越界、遮挡人物或位置异常。另对 90 条文本实例检查 Qt 字形缺失和折行绘制边界，均通过，未改程序或素材。
- 测试：`.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/pytest-temp-20261019`，**237 passed**；2 条现有 Pillow `getdata` 弃用警告。默认 pytest 临时目录访问被拒（WinError 5），改用项目内独立临时目录后通过。
- 此次只完成静态画面检查；上面的拖动、点穿、焦点、高分屏、打字机/淡出等交互已于 2026-10-19 由用户真机验收。下一开发步骤仍是 v0.2 Claude Code hooks。本次未 commit。

## 换 2.3 头身 Q 版精灵图（v0.1 之后的素材更新）
- 精灵图 448x512（人物高约 480，头约 45%），`tools/process_sprites.py` 已重写；旧图备份在 `old_4.3heads/`（已 gitignore）
- 摸头判定区 35% → 45%（`pet_window.HEAD_FRAC`）；默认高度 240 → 200；大小档位 160/200/260/320
- **存档里如果已是旧高度（如 240）不会自动变**，右键 → 大小 → 200 选一次即可
- 测试：`test_anchor_dizzy_sway...` 的脚水平漂移容差 3 → 12px（新图脚更宽，最低 8 行在倾斜时只剩一只脚，是度量方式的问题，不是脚真的在滑）；新增摸头区测试，pytest 共 211 个通过
- 已验收（用户真机确认，2026-10-19）：200 高度下观感、头部 45% 的悬停/摸头手感

## 多语言（中/英/日）
- `shion/lines.py` 重写：`Lines(lang, rng, directory)`、`set_language`、`ui(key, **kw)`、`font_fallback`、`available_languages()`（扫描 `assets/lines/*.json`）、`resolve_language(saved, locale, codes)`；缺 key 回退中文
- 存档新增 `language`（None=还没选）；首次启动跟随系统语言（zh→中、ja→日、其他→英）并写入存档
- 控制器/app 的界面文字全部走 `lines.ui()`；右键菜单新增「语言」子菜单，切换立即生效并存档；气泡 `set_font_fallback` 追加备选字体；`--snapshot --lang ja` 可看日文气泡
- pytest 共 237 个通过；日文气泡截图正常（不是方块）
- 已验收（用户真机确认，2026-10-19）：右键 → 语言 切换三种语言的观感；删掉存档里的 `language` 后按系统语言启动；日文字体在你机器上显示正常
- 注意：`zh.json` 必须完整（它是回退的底）；以后新增台词类别/界面 key 要先加到 zh

## 已完成
- [x] 美术素材：12 张精灵图已处理好（`tools/process_sprites.py`）
- [x] 规格文档
- [x] v0.1-3 状态机 + 持久化（`shion/state.py`，pytest 全部通过）
- [x] v0.1-6 本地 HTTP 服务（`shion/server.py`，回调式，不依赖窗口；pytest 共 72 个通过）
- [x] v0.1-1 骨架 / 透明置顶窗口 / 拖动下落 / `--snapshot`（pytest 共 94 个通过；**真机已验收（2026-10-19）**）
- [x] v0.1-2 程序动画（`shion/animator.py`；pytest 共 121 个通过；**真机已验收（2026-10-19）**）
- [x] v0.1-4 交互接入状态机（`shion/controller.py`、`effects.py`、`lines.py`、`assets/lines/zh.json`；pytest 共 151 个通过；**真机已验收（2026-10-19）**）
- [x] v0.1-5 气泡与台词（`shion/bubble.py`；pytest 共 173 个通过；**真机已验收（2026-10-19）**）
- [x] 把 server 回调接到 Qt 信号上（`shion/bridge.py`、`app.run()` 启动服务；pytest 共 189 个通过；真机 curl 已验收（2026-10-19））
- [x] v0.1 审查（独立子代理，只读）+ 修复（pytest 共 210 个通过）
- [x] v0.2 Claude Code hooks（pytest 共 287 个通过；**真机已验收（2026-10-19）**）
- [x] v0.2.1 状态感知（pytest 共 321 个通过；**真机已验收（2026-10-19）**）
- [x] v0.3 Claude Code 遥控（pytest 共 583 个通过；**真机验收待用户确认**）
- [ ] v0.4 诗音的对话菜单（零食、预设对话，不调用模型）
- [ ] v0.5 内容包
- [ ] v1.0 发布

## 第 1 步：已验收（用户真机确认，2026-10-19）
自动验证过：pytest（拖动阈值、拖动切 drag、松手落到底边、屏幕外拉回、落地回 idle、透明角落不在 mask 里、单实例、`--snapshot` 输出透明 RGBA 120x240）；真实第二个进程启动会直接退出（exit 0）；idle 截图目视正常。
**用户已在真机完成以下清单**（运行 `.venv\Scripts\python -m shion`，右键 → 退出可关闭）：
- [x] 启动后桌宠出现在主屏右下角，脚贴任务栏上沿，置顶、任务栏不显示图标
- [x] 按住身体拖动 → 变成 drag 图，窗口跟着鼠标；松手 → 下落贴底，回到 idle；拖到屏幕外松手会被拉回
- [x] **透明区域点穿**：点人物两侧的空白处，能点到下面的窗口；点人物身体不穿透
- [x] 再开第二个 `python -m shion` 会直接退出，不出现第二只
- [x] 高分屏（缩放 150%）下清晰度、窗口大小正常
历史自动验证限制（点穿现已由用户真机验收）：当时电脑处于锁屏状态（`WindowFromPoint` 返回 LockScreenBackstopFrame）。实现用的是 `setMask`（按精灵 alpha 生成遮罩），不依赖 Windows 分层窗口的自动穿透。

## v0.1 审查结论与修复
审查（项目里的 `reviewer` 子代理本会话没注册，改用 general-purpose 子代理加载同样的审查要求）逐项核对了 spec 的数值、判定、状态机、协议和线程模型，**没发现规格错误，线程模型没问题**。修掉的问题：
- 写存档失败（目录只读/被占用）不再抛异常：`SaveScheduler.flush` 记日志、保持 dirty、30 秒退避重试；`controller.quit()` 保证一定能退出；`setup_logging` 目录不可写时只输出到 stderr、不影响启动；日志改为 1 MB 轮转
- 副屏恢复：之前存档在副屏的桌宠每次启动都跳回主屏。现在用存档的 x、y 选屏（`pick_screen_rect`），`PetWindow.place_on` 直接按那块屏的可用区域贴底；拔掉副屏/改分辨率/任务栏变化时 `relocate()` 会把桌宠放回屏内
- 单击/拖动阈值改成欧氏距离（对角 4+4=5.7px 仍是单击）
- 存档里的高度限制在 120～600
- `/praise/take` 超时后不会再丢计数（请求对象带取消标志）
- 服务端加固：拒绝带 `Origin` 头的请求（网页脚本无法伪造事件）和 `Host` 不是本机的请求（防 DNS 重绑定），读请求有 5 秒超时。**hook 脚本必须是普通 HTTP 客户端、不带 Origin，Host 用 127.0.0.1 或 localhost**
- 气泡折行后每一行都有 `> ` 前缀；`take_praise(now)` 用传入时间做防抖；`lines.py` 容错；一个近乎恒真的测试改写
**已知遗留（没修，影响很小）**：气泡停留期间仍每 16ms 刷新（画面不变，CPU 极小）；下落过程中改大小，落地位置会偏一点（不到 1 秒的窗口）；混合 DPI 的副屏上精灵只按主屏 DPR 缩放，可能略糊；子进程冒烟测试依赖真实时间（最长约 20 秒超时）。修完后没有再跑一遍审查，每处修复都有针对性测试。

## 服务接入 Qt：已验收（用户真机确认，2026-10-19）
自动验证过：控制器 `handle_event`（working 续期与 2 分钟超时、stop→done+计数+台词、greeting、notification、react、未知类型/表情忽略、静音时仍改状态）；真 HTTP 服务 + 假时钟控制器（处理函数确实在主线程执行、20 个并发事件全部处理、非法请求 400 且不改状态、`/praise/take` 计数正确且 20 个并发请求总数恰好等于待夸奖数、GUI 不泵事件时超时返回 500）；子进程冒烟：真的启动 `python -m shion`，HTTP 发 working/stop 后日志出现状态变化，第二个实例抢同一端口时不崩溃并记录“HTTP 服务启动失败”。
**用户已在真机确认**（先 `.venv\Scripts\python -m shion` 启动桌宠，另开终端；PowerShell 里用 `curl.exe`，不要用 `curl` 别名）：
- [x] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"working\"}"` → 桌宠变成抱电脑的 working，气泡说「Claude 在努力中」之类
- [x] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"stop\"}"` → done 3 秒 + 气泡「做完啦！」，双击看“Claude 完成了 1 个任务”
- [x] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"notification\"}"` → 气泡「Claude 在等你回话呢」
- [x] 旧版摸头后 `curl.exe -X POST http://127.0.0.1:47613/praise/take -d "{}"` → 返回 `{"count":N}`，再发一次返回 0（旧行为验收记录；新版仅菜单表扬，见本次待验收清单）
- [x] 桌宠没开时这些 curl 会连接失败（符合预期：关了桌宠不影响 Claude）
- [x] 如果端口被别的程序占着，桌宠启动后会说「本地端口 47613 被占用了…」且其他功能正常

## 服务接入 Qt 留给后面步骤的接口
- `ServerBridge(controller, take_timeout=2.0)`：`on_event`/`on_take_praise` 给 `ShionServer` 用；事件用排队信号切到 GUI 线程，夸奖用请求对象 + `threading.Event` 等结果，超时抛 `TimeoutError`（server 回 500）。**ShionServer 的回调都在服务线程，PetState 和界面只在 GUI 线程动**
- `PetController.handle_event(type, detail)`、`take_praise()`
- 环境变量：`SHION_PORT`（覆盖端口）、`SHION_INSTANCE_NAME`（覆盖单实例名，自动测试用）、`SHION_DATA_DIR`、`SHION_DEBUG`
- v0.2 的 hook 脚本只需要往 `http://127.0.0.1:47613/event` POST JSON，超时要短（桌宠没开时不能拖慢 Claude Code）

## 第 5 步：已验收（用户真机确认，2026-10-19）
自动验证过：时间线（30ms/字、打完停留 4s、0.3s 淡出、新台词替换）、`place_bubble`（头顶居中、顶部放不下翻到脚下、左右夹进屏幕）、窗口（不抢焦点/不挡鼠标的窗口标志、打字全程大小不变、字数随时间单调增加、背景 #0A0A0A / 边框 #F58236 / 圆角 / 米白文字、到时自动隐藏）、控制器（默认出口走气泡、静音收起并不再弹、桌宠移动时气泡跟随）；`--snapshot --bubble` 截图目视检查过（中文折行、`> ` 前缀、位置）；真实运行 1.5 秒：单击后气泡出现在桌宠头顶，字体选到 Cascadia Mono。
**用户已在真机确认**：
- [x] 打字机速度（30ms/字）和停留（4 秒）观感合适，淡出自然
- [x] 气泡不抢焦点（点桌宠时别的窗口的输入焦点不丢）、不挡鼠标（气泡所在位置能点到下面的窗口）
- [x] 拖动桌宠时气泡跟着走；把桌宠拖到屏幕最上方，气泡翻到脚下；靠左右边缘时不出屏
- [x] 静音后不再弹，已显示的立刻消失；双击的状态提示不受静音影响
- [x] 字体显示正常（Cascadia Mono，中文回退到系统字体）

## 第 5 步留给后面步骤的接口（`shion/bubble.py`）
- `BubbleWindow(clock, autostart)`：`say(text)`、`follow(body_rect)`、`dismiss()`、`render_image(now)`、`font_family`、`timeline`、`line_count`；纯逻辑 `BubbleTimeline`、`place_bubble`、`pick_font_family`
- `PetController(..., bubble=BubbleWindow)`：默认说话出口就是气泡；`PetWindow.body_rect()`、信号 `moved`
- `--snapshot` 不再强制 offscreen（offscreen 平台没有任何字体，中文会变方块），用原生平台离屏渲染；`--bubble 文字` 把气泡画在头顶，`--at` 是打字进度

## 第 4 步：已验收（用户真机确认，2026-10-19）
自动验证过：窗口手势（头部悬停是张开的手、头部左右移动每 40px 一次 patted 且不会拖动、身体拖动发 drag_started/落地发 drag_finished、单击、双击顺序 clicked→double_clicked、右键发菜单信号、抓住下落中的桌宠再松手会继续落、改大小保持脚底不动）；控制器（摸头→happy+爱心+好感度、5 连戳→stop、10 连戳→dizzy、拖动含下落全程是 drag、菜单各项、静音、双击等待间隔后才显示状态、存档防抖/退出 flush/重启恢复大小、位置恢复与越界回退、睡眠唤醒台词、冷落回归台词）；真实运行 4 秒：存档和日志写到了数据目录，正常退出；爱心粒子截图看过。
**用户已在真机逐项上手确认**（`.venv\Scripts\python -m shion`；`SHION_DEBUG=1` 会缩短冷落/睡眠阈值并在控制台打日志）：
- [x] 头部按住左右摩挲：happy + 摇头 + 爱心，手感合适；头部按住不会把桌宠拖走
- [x] 身体单击压扁；原固定 5/10 下规则由本次随机戳替代（新观感见本次待验收清单）
- [x] 身体拖动→drag 图，松手落地回 idle；重启后位置（x）和大小恢复
- [x] 双击：约半秒后出现「已陪伴… 今天被摸… 好感度…」提示
- [x] 右键菜单：夸夸 Claude（proud）、大小四档（切换后仍贴任务栏）、静音气泡、开机自启灰色、关于、退出
- [x] 台词已在第 5 步换成真气泡（不再用 QToolTip）
- [x] 爱心窗口完全点不到（不挡鼠标）
- [x] 睡着（15 分钟无操作，或 `SHION_DEBUG=1` 下 1 分钟）后悬停会唤醒并说起床台词
- [x] 存档位置：`%APPDATA%\Shion\state.json`，日志：`%APPDATA%\Shion\shion.log`

## 第 4 步留给后面步骤的接口
- `PetController(window, state, scheduler, lines=None, overlay=None, now_fn=datetime.now, say=None, autostart=True)`：信号 `quit_requested`；`react(reactions)`、`say_key(key)`、`say(text)`、`sync()`、`tick()`、`set_size/set_muted/praise/quit`、`restore_position()`、`build_menu()`、`status_text()`
- **第 5 步只需把 `say` 的出口换成气泡**：控制器的 `_tooltip_say` 是暂代；构造时传 `say=` 回调即可覆盖；静音在 `say_key` 里已处理，双击状态不受静音影响
- **接 server（下一步之后）**：`controller.state.claude_event(...)` 的返回值交给 `controller.react(...)`，再 `controller.sync()`；注意要在 GUI 线程调用（用信号切线程），`take_praise` 要同步返回
- `PetWindow` 不再自己决定精灵：新增信号 `hovered/patted/clicked/double_clicked/drag_started/drag_finished/menu_requested`，`set_height()`、`snap_to_floor()`、`head_anchor()`；状态机的 `current()` 由控制器同步给 `set_state`
- `app.run()` 已接好存档（`SaveScheduler`）、日志、`SHION_DEBUG`、`SHION_DATA_DIR`（环境变量，覆盖数据目录，测试用）

## 第 2 步：已验收（用户真机确认，2026-10-19）
自动验证过：animator 纯逻辑 14 个 pytest（呼吸 1.000~1.012 / 周期 3s、眨眼只在 idle、间隔 3~6s、连眨约 15%、压扁结束精确回 1、倾斜限幅 ±12° 且松手回 0、晃动幅度）；窗口层用离屏渲染检查锚点（呼吸、压扁时最低行 ±1px、水平不滑；dizzy 晃动时脚不滑、不被画布裁掉）、遮罩覆盖所有可见像素；`--snapshot` 看过 idle / dizzy 最大角度 / land 压扁的截图；真实运行 8 秒 CPU 约 1.6%（单核）。
**用户已在真机确认**：
- [x] 呼吸、眨眼看着自然，不跳位、不抖
- [x] 点一下身体有压扁弹回；松手落地有压扁
- [x] 拖动时向左右拖会随速度倾斜，松手后回正，头没被裁掉
- [x] 动画状态下透明区域仍然点穿（遮罩现在随角度/缩放更新，向外扩 4px，边缘点击略宽松）
- [x] 高分屏下画面清晰
（dizzy / happy 的晃动已实现，要等第 4 步接上摸头、连戳后才能在真机看到）

## 第 2 步留给后面步骤的接口（`shion/animator.py`、`pet_window.py`）
- `Animator(rng)`：`set_state(name, now)`、`squash(now, "click"|"land")`、`set_drag(bool)`、`feed_velocity(vx, now)`、`frame(now) -> Frame(sprite, sx, sy, angle)`；时间都是传入的秒数，纯 Python
- `PetWindow(height, clock, autostart)`：`set_state(name)`（取代第 1 步的 `set_sprite`，第 4 步接状态机时用它）、`advance_to(now)`、`render_frame()`、`displayed_sprite`、`frame`、`sprite_size`
- **窗口现在是画布**：精灵左右各留 64px、上 8px、下 6px（`MARGIN_X/TOP/BOTTOM`），脚底中心在画布底边上方 6px。第 4 步的“头部 35%”命中区要用精灵坐标（减去 `MARGIN_X`、`MARGIN_TOP`）；`landing_geometry` 带了留边参数
- 单击已触发 click 压扁，第 4 步接单击/连戳时不用再做；拖动时 Animator 自己切 drag 状态，松手后回 `_base_state`（第 4 步改成状态机的 `current()`）
- `--snapshot` 新增 `--at 秒数`、`--squash click|land`

## 第 1 步留给后面步骤的接口（`shion/pet_window.py`、`app.py`）
- `PetWindow(height=240)`：`set_sprite(name)`、`place_default()`、`start_fall()`、信号 `quit_requested`；落地后回到 `_base_sprite`（第 4 步接状态机后改成 `state.current()`）
- 拖动/下落没有接状态机（`drag_start/drag_end` 还没调用），第 4 步接；右键菜单目前只有「退出」，第 4 步补全
- 窗口位置/大小还没存档，第 4 步一起做（`state.py` 的 `window.x/y/height`）
- `app.run()` 只建窗口，没接 server 和 `SaveScheduler`，留到“把 server 接到 Qt 信号”那步
- `app.snapshot(out, state, bubble)`：离屏渲染；`--bubble` 第 5 步才生效

## 第 3 步留给后面步骤的接口（`shion/state.py`）
- `PetState(data, now, config=None, on_change=None)`；`current(now)` 返回精灵名；`tick(now)` 清理到期状态
- 输入方法都返回 `list[Reaction]`，`Reaction("say", key)` 的 key 对应台词分类：
  `poke / stop / dizzy / drag / wake / neglect_return / praise_menu / claude_working / claude_done`（已在 spec 的 zh.json 里），
  另外有 **`greeting`（session_start）和 `claude_waiting`（notification）两个新 key，第 5 步写台词库时要补上**
- 界面层调用：`pat`（累计移动 40px 一次）、`click`、`drag_start/drag_end`、`interact`（悬停、双击、右键，只唤醒；拖动除外，拖动算被理会）、`praise_claude`、`take_praise`、`claude_event(type, detail, now)`
- 存档：`load(path)` / `save(path, data)` / `SaveScheduler(path, data)`（`mark_dirty`、`poll(now)` 给 QTimer、退出时 `flush()`）。路径用 `QStandardPaths.AppDataLocation` 取，第 1 步的 app 负责
- `Config.debug()` 给 `SHION_DEBUG=1` 用

## 第 6 步留给后面步骤的接口（`shion/server.py`）
- `ShionServer(on_event, on_take_praise, host="127.0.0.1", port=47613)`；`start()`（端口被占用抛 `OSError`）、`stop()`、`port`
- 回调在**服务线程**里调用：`on_event(type, detail)`、`on_take_praise() -> int`（server 内部加锁串行）。事件类型不在 server 校验，交给 `PetState.claude_event`
- 接 Qt 时：`on_event` 只发信号；`on_take_praise` 要同步拿返回值，打算 `BlockingQueuedConnection` 或共享锁，到时再定
- 调试：`.venv\Scripts\python -m shion.server` 起一个无窗口的内存版，用 curl 发 `/event`、`/praise/take`、`/health` 看打印

## 设计决定（第 3 步时定的，spec 没写死的部分）
- 摸头、单击、拖动（开始和松手）、Claude 事件算“被理会”；悬停、双击、右键只唤醒不算。唤醒和冷落回归同时发生时只说 `neglect_return`
- 夜间（0:30～6:30）默认睡；被叫醒后当晚不再强制睡，要再空闲 15 分钟才睡
- “做得好”菜单让待表扬 +1；摸头不再产生表扬（2026-10-19 本轮更新）
- 存档里 `window.x/y` 默认是 `null`（表示用默认的右下角），spec 里写的是 0
- `working` 事件每来一次就续期 2 分钟，但已在 working 时不重复说话
- `stop` 事件无论是否在 working 都会算一次任务完成

## 踩坑记录
- `QT_QPA_PLATFORM=offscreen` 下没有任何字体（`QFontDatabase.families()` 为空），文字渲染成方块；要看中文截图必须用原生平台
- 隐藏（没 show）的 QWidget 不会收到 move 事件，`moved` 信号相关测试要先 `show()`
- `QTest.mouseDClick` 在 offscreen 下只发一个双击事件，没有按下/松开；测试里要手动补 `mouseRelease`
- 测试里 `QMenu` 临时对象一旦被回收，里面的 `QAction` 就失效（RuntimeError），要留引用
- `QWidget.grab()` 会被 `setMask` 裁剪，遮罩外的像素是未初始化内存（测试偶发角落有像素）；截图和测试改用 `render_frame()`
- numpy 用 `frombuffer` 读 `QImage.constBits()` 时，QImage 一释放数据就悬空，必须 `.copy()`
- 遮罩要覆盖实际绘制：角度取整 1° 在 250px 处有约 2px 误差，所以遮罩向外扩 4px
- 呼吸每帧都变会让 60fps 重绘（CPU 约 8.6%）；把帧量化到 0.001 / 0.01° 后降到约 1.6%
- `QRegion(QPixmap.mask().scaled(...))` 会报错，要先 `QBitmap.fromPixmap(...)`
- Windows 下 Qt 窗口坐标是逻辑像素，用 `WindowFromPoint` 等 Win32 API 检查时要乘 `devicePixelRatio`；锁屏时它返回 LockScreenBackstopFrame，测不了
- Git Bash 的长 heredoc 里夹中文/引号容易解析失败，写大文件用 Write 工具
- 本机只有 Python 3.10，spec 已从 3.11+ 改成 3.10+
- Windows 下 git 会提示 LF 将转 CRLF，只是警告
