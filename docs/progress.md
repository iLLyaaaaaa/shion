# 进度记录

> 新会话先读本页。历史原文按月保存在 [progress-archive/2026-10.md](progress-archive/2026-10.md)，包括 2026-10-26（含）之前的记录和近期长篇明细。**需要查历史时用 grep 搜归档，不要通读**，例如 `rg -n "关键词" docs/progress-archive/`（也可用 `grep -n`）。归档保留当时状态；旧“下一步”“未安装”“未合并”不代表当前状态。归档原文中的相对链接仍以原 `docs/` 目录为基准，查阅时从该目录解析。规格按需读 `docs/spec.md`。

## 当前状态总览

- 当前分支 `feature/v2-observer-lease-scheduler`；v1.0.1 hook 延迟热修、调度 GUI 审查修复和菜单 Claude Code 标名均已合并。2026-10-30 已替换本机 Shion-dev 开发预览包；未 push、未发布，默认关闭的调度能力不等于已启用或完成人工验收。
- 阶段 1 v3 全局安装已完成，MCP 与七项无 matcher Hook 保留；已安装 Shion-dev 更新为菜单标名开发包（替换记录核验 228 文件）。替换记录确认配置哈希未变，旧包保留为 `Shion-dev-before-menu-label-20261030`；阶段 1 仅部分通过人工验收。旧会话 Observer 异常退出后自动恢复未证明，新开 CLI 会话恢复已有证据。
- 阶段 2 P1～P5 核心、2 秒心跳/10 秒租约及 GUI 适配已完成隔离开发。`v2_scheduler_enabled` 默认 false，没有普通用户菜单开关；ChatGPT 仅观察，无控制入口；Claude 原授权/暂停/继续/中断保留。真实 Claude 缺可靠 turn_id，真实前台缺完整任务绑定，生产端缺可信 coverage；完整身份与仲裁能力仍主要是合成证据。Work 未开发。
- 最近一次全量为 2026-10-30 恢复 `.venv` 后实际执行：`.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/env-recovery`。汇总原文：`1829 passed, 9 skipped, 2 warnings in 602.93s (0:10:02)`，退出码 0；两条均为既有 Pillow `getdata()` 弃用警告。日志在忽略目录 `build/menu-label-replacement-20261030/pytest-env-recovery.log`，`pip check` 同时通过。
- 分支 `feature/menu-claude-label`（从 `4c4db02` 派生，功能提交 `81b8361`，交接提交 `a4edba0`）已快进合并到当前分支，分支保留、未 push；菜单标名已随本次 Shion-dev 开发包替换部署，详见下方 2026-10-30 记录。
- 分支 `feature/menu-parity`（从 `dc9fe3d` 派生）：右键菜单 Claude Code / ChatGPT 连接管理对齐，并新增 Claude 的“临时关闭联动”。未合并、未部署、未 push；本分支全量结果见下方 2026-10-30 记录。
- 分支 `feature/remove-codex-autolaunch`（从 `fad0e3a` 派生）：删除 Codex 新开会话自动拉起诗音，保留 Claude 拉起、单实例互斥锁和 Codex 窗口层级跟随。未合并、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/remove-face`（从 `5062919` 派生）：删除“朝向鼠标”动作并停用 turn 帧，待机动作只剩小跳 : 表情 = 1 : 2。未合并、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/per-session-remote`（从 `5062919` 派生）：工作遥控四个按钮按会话区分，多个会话同时停住时用检查点面板分别继续/结束。未合并、未部署、未 push，详见下方 2026-10-31 记录。
- 公开稳定版为 v1.0.0（`master`）；私有备份仍含旧历史。历史改写后的哈希以当前 Git 为准，旧报告的失效哈希仅作决策记录。

### 本分支提交现状（相对本地 master，按拓扑日期顺序）

| 提交 | 当前作用与状态 |
| --- | --- |
| `e6e3865` | 全局生命周期观察 MVP；已由后续精简方案、事务修订及租约扩展演进 |
| `fe78a25` | 全局安装审查基线记录，保留历史边界 |
| `5dc9eda` | 精简安装、便携 MCP；替代独立 ACL 存储方案 |
| `c847994` | 安装事务、Hook 信任变化保留及精确卸载加固 |
| `c6889c3` | Observer 租约与独立多任务调度核心，已接开发 GUI |
| `ce732f2` | Windows ACL 继承规范化测试修复，已保留 |
| `a55825f` | 菜单整合与默认关闭的 GUI 接入，后续审查修复已应用 |
| `1f54cb6` | hook 未运行快速退出与连接熔断热修；已由合并提交接入 |
| `ef1149a` | 观察空档恢复、中性待机、Claude 独立连接行、切换与冲突降级修复 |
| `3548f23` | 原阶段 1 待验收记录保存；本次原样转入月度归档 |
| `c0e7482` | 合并热修；隐私扫描冲突和进度记录冲突已解决 |
| `9ba3e66` | 合并验证与逐提交隐私补扫报告，现迁入 experiments |

详见 [核心](experiments/shion-v2-phase2-core.md)、[GUI](experiments/shion-v2-phase2-gui.md)、[审查修复](experiments/shion-v2-scheduler-review-fixes.md)、[热修合并与隐私补扫](experiments/shion-v2-merge-hotfix-report.md)。旧热修提交 `1f54cb6` 的虚构目录测试字面量曾被新扫描规则命中；合并版已修正，未改写历史，不宣称历史每个快照都扫描通过。

## 正在进行的阶段与下一步

- 当前是阶段 2 开发预览、阶段 1 人工验收暂缓；暂缓不阻塞独立开发，也不代表阶段 1 全部验收通过。
- `feature/menu-parity` 待用户审核、真机验收后决定是否合并到当前分支。
- `feature/remove-codex-autolaunch` 待用户审核后合并到当前分支；Codex 自动拉起相关验收项已取消。
- `feature/remove-face` 待用户真机验收后合并到当前分支。
- `feature/per-session-remote` 待用户审核、真机验收后决定是否合并到当前分支。
- 下一步由用户审核开发分支及下方清单，再安排真实客户端适配与 GUI 人工验收；部署、打包、用户开关开放、真实配置写入与发布须有对应授权。本任务不推进这些步骤。
- 普通用户开关开放前，先处理下方全局 `ledger.uncertain` 恢复遗留；不得用心跳、重复包或新 turn 结束推断旧任务成功。真实身份、前台绑定、coverage 和人工权限能力必须各自有证据。

## 未完成的人工验收清单

以下是当前交接清单；历史原文中的 125 条未勾选明细全部留在月度归档（包括后续版本已取代的旧方案/旧计划，不自动改勾）。需要执行某项时用 `rg -n '关键词|\[ \]' docs/progress-archive/2026-10.md` 定位对应小节，并以最新实现为准。

V2 进入日常试用阶段，人工验收以日常使用中的反馈为主；平时碰不到的项目（立即中断后工具进程是否结束、Codex 配置断开再重连、干净环境解压运行）留到发布前专门验收。

- [ ] 阶段 1：修复后桌面普通任务的完整生命周期、真实故障画面、活动中断连；原会话自动恢复或明确的恢复边界。
- [ ] 人工权限长等待、实际 PermissionRequest 语义；工具执行中 Interrupt 后工具进程及时终止。现有视觉“轮次 0、无异常”和官方 turn interrupted 不等于工具被及时终止。
- [ ] 两个现有项目真正并发、GUI 会话辨别（顺序 CLI 已通过，但短 ID 曾碰撞）；Claude/ChatGPT 并行隔离及桌面重连/观察开关的完整链路。
- [ ] 真实卸载/恢复、安装事务完整用户流程与长期附加延迟；62 次正常 Hook 样本不足以代表长期性能。
- [ ] 阶段 2：完整真实身份、前台任务绑定、可靠人工请求及 coverage；当前合成 GUI/Qt 截图不代替真实客户端、焦点、多屏或动态观感验收。
- [ ] 热修真机：诗音关闭时 hook 等待改善、运行时无回退、自定义端口分支；`find_cc_process` 和服务端协议进一步优化未做。
- [ ] v1 系列遗留：图标/README 媒体观感、ZIP 解压启动、干净无 Python Windows、杀毒表现；本任务不打包。
- [ ] v1 桌面交互：Win+D 恢复、置顶与附属面板避让、透明区点穿、不抢焦点、多屏/高 DPI、四档尺寸、动态动作及爱心/Z/睡眠观感。
- [ ] v1 Claude 实际联动：授权自动收起、暂停/继续、中断文字与工具分支、超时/静音、终端草稿与确认框保护、桌面复制“继续”、连接迁移不重复事件和登录自启。
- [ ] 三语菜单/台词/气泡、对话数字键与焦点、每日额度/时段问候/等级与存档迁移；逐项条件见归档，自动化通过不能替代用户观感。
- [ ] 菜单对齐与临时关闭联动（`feature/menu-parity`）：真机右键看两个子菜单的结构、截断与 tooltip；Claude 临时关闭后真实 CC 的授权框、停下中的 hook、反馈注入与重新开启的表现；离屏渲染和合成测试不代替真机。
- [x] Claude 临时关闭联动（2026-10-31 真机通过）：关闭时不弹面板、交回 CC 授权框；重新开启后授权面板同意/拒绝生效。
- [ ] 菜单标名（`feature/menu-claude-label`）：真机右键看顶层“Claude Code：…”状态行，以及“AI 连接 › Claude Code › / ChatGPT ›”两个子菜单的展开位置、宽度和 tooltip（高 DPI、多屏）；离屏渲染截图不代替真机观感。
- [x] ~~Codex 自动拉起（`feature/codex-autolaunch`）~~ **已取消（2026-10-31）**：功能已在 `feature/remove-codex-autolaunch` 删除，不再验收；Codex 用户改用“开机自启”。原因（Codex 的 KILL_ON_JOB_CLOSE Job）见下方记录和 spec.md 末节。
- [x] Codex 不再自动拉起（2026-10-31 真机通过）：诗音没开时新开 Codex 对话，诗音不出现，Codex 正常工作。
- [ ] Codex 窗口层级跟随（`feature/codex-autolaunch`）：关闭“置于最上层”后，Codex 桌面端窗口在前台时诗音浮在其上方且不抢焦点；在 Codex 里临时关闭 ChatGPT 联动或未安装联动时不再跟随；终端窗口（Windows Terminal 等）前台时不跟随；Claude 桌面端跟随不变；高 DPI/多屏观感。
- [x] Codex 桌面端窗口层级跟随（2026-10-31 真机通过）：未置顶时诗音浮在 Codex 窗口上方，其他程序照常遮挡。
- [ ] 单实例互斥锁（`feature/codex-autolaunch`）：多个 Claude 会话同时新开只剩一个诗音；Claude 临时关闭联动后新开 CC 会话不拉起诗音（源码版与打包版各验一次；原属上面已取消的条目，Claude 侧保留）；旧版诗音（无互斥锁）运行时新版不会重复启动；诗音被强制结束后能正常重新启动；退出后再启动正常。
- [x] 单实例互斥锁（2026-10-31 真机通过）：同时新开两个 CC 会话只出现一个诗音。
- [ ] 工作遥控按会话区分（`feature/per-session-remote`），日常试用时留意：只开一个 CC 会话时右键菜单和以前一样；开两个项目同时工作时，“停下 / 立即中断 / 做得好 / 有问题……”展开成子菜单，名称是项目文件夹名（同名带“(2)”，隐私模式显示“会话 1 / 会话 2”）；停下 A 时 B 继续干活；A 停住时暂停标签写“暂停中：A 的文件夹名”，在 A 的 CC 里说话只放开 A；两个都停住时出现检查点面板，可分别“继续 / 结束这一轮”，面板不抢焦点、出现后 0.6 秒内点击无效；“做得好 / 有问题……”只在选中的会话下一次工具调用时注入，选“全部”时每个会话各收到一份、好感度只加一次。
- [ ] 发布前专门验收（按会话中断）：两个会话都在跑长命令时只中断 A，A 的工具进程结束、B 的不受影响；选“全部”时两边都结束。

- [ ] 删除朝向鼠标（`feature/remove-face`）：右键“动作”只剩跳一跳 / 去睡觉 / 趴一会儿（三语）；普通/活泼档待机时不再出现侧身，只有小跳和开心/发呆表情，表情明显多于小跳；旧存档正常加载。

## v1.1 待办
- [ ] hook ↔ 服务端令牌认证 + `SO_EXCLUSIVEADDRUSE`（安全审查建议）
- [x] hook 耗时：诗音没开时的等待已在 v1.0.1 热修里去掉（见当前状态）。诗音运行时 PreToolUse 仍约 354 ms（源码）/ 435 ms（exe）：主要是进程启动，`find_cc_process` 只占约 26 ms；是否继续降另议
- [ ] 实验：桌面端能否拿到 statusLine 的 `rate_limits.seven_day`（每任务额度上限的前提）
- [ ] 接入 GPT / Codex
- [ ] V2.1 候选：Codex 控制能力。实验结论：授权可行（异常时交回 Codex 自己处理，桌面端未测）；停下只能做到"检查点暂停 → 继续"；中断目前不可行。详见 docs/experiments/shion-v2-codex-control.md。

- [ ] **开关对用户开放之前**：缺身份、来源冲突或容量耗尽导致的全局 `ledger.uncertain` 也要加恢复条件或时效（审查遗留）。

## 最近几天的记录（摘要，完整原文见月度归档及专项报告）

- **2026-10-31 删除朝向鼠标（face）并停用 turn 帧**（分支 `feature/remove-face`，从 `5062919` 派生，worktree `..\claude-pet-wt\remove-face`，本地提交、未合并、未 push）：face 借用 turn_2 / turn_8 侧身，看起来仍像转身，一并删除。删去 `behavior.FACE_SECONDS`、`PetWindow.face()` 及只为它服务的 `_automatic_pose`（`idle_motion_active` 现只看自动跳跃）、controller 待机与菜单两处分支、三语 `action_face`、截图 `--face` 参数（现在传入会被 argparse 拒绝）；`SEQUENCE_GROUPS` / `EXACT_SEQUENCES` 去掉 turn，`assets/sprites/turn_1～8.png` 已删除，旧目录残留的 turn_*.png 会被忽略；`tools/process_sheets.py` 的 `SHEETS` / `EXPECTED` 去掉 `turn_sheet`（raw 里的 turn_sheet.png 保留不动，脚本不再读取也不再生成 turn 帧，`--only turn` 不再是合法选项；`process_sprites.py` 本就跳过 `*_sheet`）。待机动作 `IDLE_ACTIONS = ("jump", "expression")`，权重 1 : 2：自言自语可抽时 talk 10% / jump 30% / expression 60%（原 face/jump/expression 各 30%），冷却中 jump 33.3% / expression 66.7%（原各 33.3%）。存档从未有 face/turn 字段，新增测试确认带陌生字段的旧档照常加载。原来以 face 为载体的淡化/遮罩/中断测试改用跳跃或静止的捏脸松手姿势。`scheduler_disabled_a55825f.json` 只刷新 21 个 `menu_sha256`，其余字段逐项比对一致。验证：全量 pytest（`--basetemp=build\pytest-tmp-face`，在 worktree 内，`PYTHONUTF8=1`）汇总原文：`1877 passed, 8 skipped, 2 warnings in 517.70s (0:08:37)`，退出码 0；两条为既有 Pillow `getdata()` 弃用警告。截图 `--snapshot --jump --at .24` 正常。
- **2026-10-31 工作遥控按会话区分**（分支 `feature/per-session-remote`，从 `5062919` 派生，worktree `..\claude-pet-wt\per-session-remote`，本地提交、未合并、未 push）：hook 所有事件多带 `project`（只是 `cwd` 的文件夹名，不带完整路径），`/feedback/take` 也带 `session`；服务端 `clean_project` 去掉 Unicode Cc/Cf 字符和首尾空白，非字符串、含 `/` `\`、为空或超过 64 字时只丢掉这个字段，事件照常，旧格式事件不受影响。`RemoteHub` 新增按会话暂停、按会话放行（全局暂停中被单独放行的会话）和按会话的一次性“结束这一轮”代数；`wait_gate` 在全局或自己会话暂停时等待，不带会话的旧请求只看全局。UserPromptSubmit 只放开自己会话；为了单会话时与原来一致，放行某会话后如果没有别的会话单独停着或在等，就整个解除全局暂停；多会话选“全部”停下时会同时给每个会话单独打标记，所以 A 说话不会放掉 B。新文件 `shion/sessions.py` 负责菜单名称（首次出现顺序、同名 “(2)”、隐私或无名时“会话 n”）。菜单：0/1 个会话时走原代码路径，三语菜单树与 `5062919` 逐项一致；≥2 个时四个按钮变成子菜单（各会话 + “全部”），“继续”在多个目标时也是子菜单，“有问题……”选完会话再弹输入框。立即中断只结束选中会话的工具进程，收尾只解除这些会话的暂停。反馈队列项带可选 `session`，每个归属各最多 5 条；带 session 的取走“自己的 + 无归属的”，旧请求只取无归属的；“全部”给每个相关会话各放一份，好感度、表情、台词只算一次。检查点：1 个会话停住仍是暂停标签，文字为“暂停中：{名称}”；≥2 个停住时换成 `badge.CheckpointPanel`，每个会话一行“继续 / 结束这一轮”，不抢焦点、只响应鼠标、出现或会话集合变化后 0.6 秒才生效、键盘无效。新增三语 key：`pause_label_named`、`session_n`、`menu_all`、`checkpoint_title`、`checkpoint_resume`、`checkpoint_end`、`checkpoint_ended`。新测试 `tests/test_per_session_remote.py` 53 个。`render_menu.py` 增加 `one_session`、`two_sessions` 场景；基线快照 `scheduler_disabled_a55825f.json` 未改动（单会话菜单不变，快照测试直接通过）。验证：全量 pytest（`--basetemp=build\pytest-tmp\full`，在 worktree 内）汇总原文：`1 failed, 1951 passed, 8 skipped, 6 warnings in 494.08s (0:08:14)`；唯一失败是已知的 `tests/test_install_hooks.py::test_corrupt_json_not_touched`（子进程 stderr 按 GBK 解码失败），设 `PYTHONUTF8=1` 单独重跑 `1 passed`，与本次改动无关。三语单/双会话菜单截图和双会话停住的面板截图已自查（在忽略目录 `build/menu-shots/`、`build/checkpoint-shots/`，不提交）；面板最初因字体回退把标题裁掉一半，已改用台词字体并设最小行高。范围外发现（未实现）：单会话时没有“结束这一轮”的界面按钮（只有多会话面板有）；“继续（这一轮已结束）”只记最近一个会话；授权面板不显示项目名。
- **2026-10-31 删除 Codex 新开会话自动拉起**（分支 `feature/remove-codex-autolaunch`，从 `fad0e3a` 派生，worktree `..\claude-pet-wt\remove-codex-autolaunch`，本地提交、未合并、未 push）：诊断结论是 Codex 把 MCP 观察端放进 `KILL_ON_JOB_CLOSE` 且不允许脱离的 Job，观察端拉起的诗音会随 Codex 退出或关闭 MCP 一起被结束，所以决定不再由 Codex 拉起，Codex 用户改用“开机自启”。删除 `codex_mcp.py` 的 `autolaunch()`、`codex_link_enabled()`、`_AUTOLAUNCH`、`dispatch()` 中的调用及相关 import，`git diff d907e33 -- shion/codex_mcp.py` 为空（观察端转发、心跳、租约与 668962c 之前一致）；`launcher.py` 删除 `AutoLaunch`、`AUTOLAUNCH_COOLDOWN` 及不再用的 `logging`/`time`，保留 `shion_running()`、`launch_shion()`、`INSTANCE_NAME`；`tests/test_autolaunch.py` 删掉 Codex 观察端拉起的全部用例，Claude 拉起、公共函数、Claude 联动开关、单实例竞争用例保留；三语 README 常见问题各加一条“用 Codex 时诗音不会被自动拉起，建议右键 → 设置 → 开启开机自启”；spec.md 末节记录决定与原因。Claude hook 的 `claude_link_enabled` 判断、单实例互斥锁（`fad0e3a`）、Codex 窗口层级跟随（`4a6e9eb`）均未改动。验证：全量 pytest（`--basetemp=build/pytest-tmp4`，在 worktree 内）汇总原文：`1913 passed, 8 skipped, 2 warnings in 648.08s (0:10:48)`，退出码 0。首轮为 `11 failed, 1902 passed, 8 skipped, 6 warnings in 628.37s (0:10:28)`：其中 10 个是 `tests/test_process_sheets.py`，原因是新 worktree 没有 `assets/sprites/raw` junction（补上后通过）；另 1 个 `tests/test_install_hooks.py::test_corrupt_json_not_touched` 是子进程 stderr 按本机 GBK 解码失败，主仓库未改动的 `fad0e3a` 上同样失败，设 `PYTHONUTF8=1` 后通过，与本次改动无关。`tools/check_private.py` 暂存区通过，作者与提交者邮箱均为 noreply 邮箱。
- **2026-10-30 单实例改用命名互斥锁**（分支 `feature/codex-autolaunch`，本地提交、未合并、未 push）：`SingleInstance.acquire()` 在 Windows 上先 `CreateMutexW("Local\\" + 实例名)`（原子，实例名仍支持 `SHION_INSTANCE_NAME` 覆盖），返回 `ERROR_ALREADY_EXISTS` 就关掉本次句柄、照原样连一下已有实例的管道后返回 False；拿到锁的实例在整个生命周期内持有句柄，`release()` 才关闭，崩溃由系统回收。拿到锁后仍做原来的管道连接检查（兼容没有互斥锁的旧版诗音），再 `listen`，listen 失败会释放锁。命名管道服务保留，`launcher.shion_running()` 和 hook/观察端接口不变；非 Windows、创建锁失败时行为与原来一致。上一条的 xfail 竞态用例改为必须只剩一个：4 个进程对齐到同一时刻、一个测试里连跑 3 轮，另独立连续跑 5 次全部通过；另有 `tests/test_single_instance.py` 覆盖锁语义。
- **2026-10-30 Codex 桌面端窗口层级跟随**（分支 `feature/codex-autolaunch`，本地提交、未合并、未 push）：未开“置于最上层”时，`shion/foreground.py` 原来只在 `claude.exe` 前台时让诗音紧邻其上，Codex 桌面端窗口会盖住诗音。跟随目标改成常量集合 `CLAUDE_IMAGES={"claude.exe"}`、`CODEX_IMAGES={"chatgpt.exe"}`；Codex 只在控制器的 `_follow_codex_window()` 为真时才跟随（ChatGPT 联动 `connection_state()=="installed"`，即已安装且未临时关闭；关闭/未安装/读失败都不跟随，判断在每次前台事件时动态进行）。不加任何终端程序；重验、不激活、不绑定 owner、置顶时不跟随都不变，日志与注释改为中性说法。Codex 桌面端实际映像：已装包 `OpenAI.Codex_26.1027.3384.0_x64__2p2nqsd0c76g0`，主窗口（Chrome_WidgetWin_1，标题 ChatGPT）属于该包 `app\ChatGPT.exe`，只读枚举进程与可见窗口确认。局限：按映像名匹配，另一个同名 `ChatGPT.exe`（独立 ChatGPT 桌面应用）也会命中。
- **2026-10-30 Codex 新开会话自动拉起诗音（已于 2026-10-31 删除，见上方记录；`shion/launcher.py` 的公共函数和 Claude 侧改动保留）**（分支 `feature/codex-autolaunch`，从 `d907e33` 派生，worktree `..\claude-pet-wt\codex-autolaunch`，本地提交、未合并、未 push）：新增公共模块 `shion/launcher.py`（仅标准库）——`shion_running()`（命名管道检查，从 hook 挪来）、`launch_shion()`（DETACHED/NEW_PROCESS_GROUP/优先 BREAKAWAY、标准流 DEVNULL、`SHION_LAUNCHED_BY_HOOK`，只 Popen 不等待）、`AutoLaunch`（30 秒冷却，异常只记日志）和 `INSTANCE_NAME`（`shion/app.py` 改为从这里取）。Claude hook 改为薄包装调用它，行为不变；唯一新增：存档 `claude_link_enabled` 为 false 时 SessionStart 不拉起（读失败/缺字段按默认开启）。Codex 观察端 `dispatch()` 在转发 SessionStart 之后调用 `AutoLaunch.attempt`，管道返回 False 才拉（True/None 都不拉），任何异常只记日志、`observe_lifecycle` 返回不变；Codex 的“临时关闭”开关实际在 `chatgpt-observer.json` 的 `enabled`（不在 state.json），只有明确为 false 才不拉。conftest 新增 autouse 保护，所有测试都不能真的拉起诗音。**发现（已在后续提交修复，见下一条）**：Qt 6.12 在 Windows 上允许两个 `QLocalServer` 同时 listen 同名管道，`SingleInstance.acquire()` 先连后 listen，多个进程在同一毫秒内都通过“连接失败”检查时会同时成为赢家（实测 3～4 个对齐启动的进程全部 WON）；先后相隔几百毫秒则只有一个。另：刚拉起时那条 SessionStart 会丢（1 秒预算内不等 /health）。
- **2026-10-30 菜单连接管理对齐 + Claude 临时关闭联动**（分支 `feature/menu-parity`，worktree `..\claude-pet-menu-parity`）：两个子菜单统一为“连接：… / 活动：… / ─ / 连接 / 查看配置 / 临时关闭联动（重新开启联动）/ 断开并移除配置”，三语文案两边一致；顶层每个提供方一行“{名称}：{连接} · {活动}”，截断 240 挂 tooltip。Claude 新增临时关闭：`RemoteHub.set_link_enabled` 关闭授权队列（撤回全部请求，含已决定未取走的）、清暂停和中断并唤醒检查点等待；服务端 `/event` 忽略、`/pause/wait` 放行、`/permission/open` 不给 id、`/permission/wait` 一律 gone、`/feedback/take` 返回空且不取走队列；hook 脚本未改。开关存 `state.json` 的 `claude_link_enabled`，旧档默认开启。删除不再使用的 `menu_connect/menu_reconnect/menu_disconnect/menu_connection_status/chatgpt_install/disable/enable/uninstall`，`test_lines.py` 白名单缩小为 `connection_explain`、`menu_claude`。`scheduler_disabled_a55825f.json` 只刷新 21 个 `menu_sha256`，其余字段逐项比对一致。全量（`--basetemp=build\pytest-tmp\full2`）：`1870 passed, 8 skipped, 2 warnings in 607.21s (0:10:07)`，两条为既有 Pillow `getdata()` 弃用警告。第一次全量有 2 个失败：`test_menu_contents` 是旧断言没跟上，已改；`test_install_hooks.py::test_corrupt_json_not_touched` 是环境问题：当前会话设了 `PYTHONIOENCODING=utf-8`，子进程按 UTF-8 写 stderr，测试用 `text=True` 按 GBK 解码；去掉该变量后通过，与本改动无关。`render_menu.py --platform windows --baseline dc9fe3d` 三语无未挂 tooltip 的截断，ChatGPT 子菜单比旧版窄，英文 Claude 子菜单约宽 70 逻辑像素（“Disconnect and remove configuration”）。范围外发现：`ChatGPTConnection._unobserved_start` 从未被清除，所以 ChatGPT 活动总显示“待确认”；工作遥控置灰时好评/差评也无法入队（按要求整体置灰）。未合并、未打包、未部署、未 push。

- **2026-10-30 Codex 控制能力隔离实验**：仅临时 CODEX_HOME、临时项目、独立 CLI/TUI/app-server 和固定回环响应器，不改产品代码、真实 Codex/CC 配置或 Shion-dev。同步 Pre/Post 每次 125 秒等待可用；Pre deny 只挡当前调用，Post continue:false 的 stopped 状态仍未阻止下一工具。官方 turn/interrupt 可结束轮次，但两组测试父子工具进程八秒后仍运行。PermissionRequest allow/deny 有效；超时/崩溃回原审批，自动审批仍可能放行；事件输入无可靠人工等待标志且缺 tool_use_id/request_id。桌面独立实例隔离未证实，GUI 六项均未验证。详见 [控制实验报告](experiments/shion-v2-codex-control.md)，不开放 ChatGPT 控制能力；后续须先解决失败关闭、进程归属和桌面隔离。本地提交，不 push。
- **2026-10-30 `.venv` 事故恢复与替换收尾**：移除菜单 worktree 时漏解除指向主 `.venv` 的 junction，误删共享依赖；已单独解除链接、清理残留并重装运行、测试、构建依赖及 pip。本次 `pip check` 和全量 pytest 通过（汇总见上）；旧环境无完整版本清单，不保证所有开发依赖逐版本还原。`CLAUDE.md` 已加入 junction 单独解除及 worktree 移除前 reparse point 扫描规矩。替换状态 `complete`；只读核对新 exe 哈希与记录一致、47613/47614 均归新 Shion-dev（PID 30104）、08:39:40 最新启动以来日志正常、存档 `v2_scheduler_enabled=false`。证据在忽略目录 `build/menu-label-replacement-20261030/`；本次仅改规则与进度文档，本地提交、不 push。
- **2026-10-30 菜单给 Claude Code 标名**（分支 `feature/menu-claude-label`，`81b8361`）：顶层状态行改为“Claude Code：{状态}”；“AI 连接”拆成并列的“Claude Code ›”（禁用状态行 + 连接/重连/断开，tooltip 不变）和“ChatGPT ›”（原子菜单迁入，未启用 ChatGPT 时只剩前者）。新增 `menu_connection_status`、`menu_claude`、`menu_chatgpt` 三个 key，没有改 `connection_status`（双击状态气泡仍用）和 `chatgpt_manage`（ChatGPT 面板窗口标题），所以气泡和面板标题仍不出现 Claude。spec 品牌规则改为只有连接类标签可写“Claude Code”，`test_lines.py` 按新边界断言，其余文案仍不含 Claude。`scheduler_disabled_a55825f.json` 只刷新了 `menu_sha256`（菜单形状变了），其余字段未动。验证：全量 1820 passed、8 skipped、10 failed；10 个失败都在 `test_process_sheets.py`，原因是 worktree 缺被忽略的 `assets/sprites/raw/`，链接后 14 项全过，主仓库同样通过，不是本次改动造成；`render_menu.py --platform windows` 三语截图无截断或过宽（最宽为 en 路径失效状态行，约 450px）。未打包、未 push、未部署。
- **2026-10-29 文档整理**：8 份原未跟踪实验文档和 2 个脚本纳入本地版本管理；加上迁移的合并报告共 9 份文档。ACL 报告与探针标记废弃；先暂存扫描再脱敏。进度历史原文按月归档，首页改为当前交接摘要；没有修改产品代码、测试或实验脚本运行逻辑，没有打包、部署或 push。
- **2026-10-29 合并与审查**：热修和 V2 已合并；GUI 空档恢复审查修复已保留，最新验证及历史扫描限制见合并报告。早先热修 worktree 的失败记录留在归档，不覆盖本次合并全量结果。
- **2026-10-29 阶段 2**：租约与 P1～P5 核心、菜单及 GUI 隔离接入完成；真实能力缺口和默认关闭边界继续保留。
- **2026-10-29 阶段 1 续验**：工具离线放行、新会话恢复、单次 MCP 无响应后恢复、Interrupt 观察与视觉收尾有证据；进程及时终止、原会话自动恢复等仍未证明。新 41 次 Hook 与旧 21 次分组保留；两个现有项目仅顺序任务通过。
- **2026-10-28**：v3 真实安装和 PermissionRequest 修复部署；阶段 1 部分验收。事务/精简方案隔离验证通过；CLI 嵌套目录 ACL 阻断后根目录离线命令通过，未手工改 ACL。
- **2026-10-27**：全局观察 MVP 开发，后续已完成真实安装；公开历史用户名清理和隐私扫描工具落地，私有备份未清理。旧独立 ACL 方案已废弃，仅保留决策记录。

原条目核对（不计本页新增摘要）：原状态记录 58 条 + 历史小节 58 个 + v1.1 待办 4 条 = 120 条；归档保留 116 条，本页原样保留 4 条，合计 120 条，缺失 0。逐条原文及重复次数核对通过；包括嵌套清单在内的原列表项 780 条 → 780 条。归档原文加回本页原 v1.1 待办后，可逐字节重建整理前的 progress.md。人工明细的历史勾选状态未改写。
