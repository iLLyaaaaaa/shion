# 进度记录

> 新会话先读本页。历史原文按月保存在 [progress-archive/2026-10.md](progress-archive/2026-10.md)，包括 2026-10-26（含）之前的记录和近期长篇明细。**需要查历史时用 grep 搜归档，不要通读**，例如 `rg -n "关键词" docs/progress-archive/`（也可用 `grep -n`）。归档保留当时状态；旧“下一步”“未安装”“未合并”不代表当前状态。归档原文中的相对链接仍以原 `docs/` 目录为基准，查阅时从该目录解析。规格按需读 `docs/spec.md`。

## 当前状态总览

- 当前分支 `feature/v2-observer-lease-scheduler`；v1.0.1 hook 延迟热修、调度 GUI 审查修复、菜单 Claude Code 标名和 v2.0.0 发布前安全修复均已合并。2026-11-01 已替换本机 Shion-dev 开发预览包（安全修复版）；未 push、未发布，默认关闭的调度能力不等于已启用或完成人工验收。
- 阶段 1 v3 全局安装已完成，MCP 与七项无 matcher Hook 保留；已安装 Shion-dev 更新为菜单标名开发包（替换记录核验 228 文件）。替换记录确认配置哈希未变，旧包保留为 `Shion-dev-before-menu-label-20261030`；阶段 1 仅部分通过人工验收。旧会话 Observer 异常退出后自动恢复未证明，新开 CLI 会话恢复已有证据。
- 阶段 2 P1～P5 核心、2 秒心跳/10 秒租约及 GUI 适配已完成隔离开发。`v2_scheduler_enabled` 默认 false，没有普通用户菜单开关；ChatGPT 仅观察，无控制入口；Claude 原授权/暂停/继续/中断保留。真实 Claude 缺可靠 turn_id，真实前台缺完整任务绑定，生产端缺可信 coverage；完整身份与仲裁能力仍主要是合成证据。Work 未开发。
- 最近一次全量为 2026-11-02：`--basetemp=.venv/preview-run/release-prep2`，结果 `1 failed, 2049 passed, 8 skipped, 2 warnings in 603.42s (0:10:03)`。唯一失败是 `test_real_process_tree_is_terminated`，满载时出现（连续 3 次全量都出现），单独跑能通过，详见下方 2026-11-01 记录。更早一次全量通过是 2026-10-30 恢复 `.venv` 后实际执行：`.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/env-recovery`。汇总原文：`1829 passed, 9 skipped, 2 warnings in 602.93s (0:10:02)`，退出码 0；两条均为既有 Pillow `getdata()` 弃用警告。日志在忽略目录 `build/menu-label-replacement-20261030/pytest-env-recovery.log`，`pip check` 同时通过。
- 分支 `feature/menu-claude-label`（从 `4c4db02` 派生，功能提交 `81b8361`，交接提交 `a4edba0`）已快进合并到当前分支，分支保留、未 push；菜单标名已随本次 Shion-dev 开发包替换部署，详见下方 2026-10-30 记录。
- 分支 `feature/menu-parity`（从 `dc9fe3d` 派生）：右键菜单 Claude Code / ChatGPT 连接管理对齐，并新增 Claude 的“临时关闭联动”。未合并、未部署、未 push；本分支全量结果见下方 2026-10-30 记录。
- 分支 `feature/remove-codex-autolaunch`（从 `fad0e3a` 派生）：删除 Codex 新开会话自动拉起诗音，保留 Claude 拉起、单实例互斥锁和 Codex 窗口层级跟随。未合并、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/remove-face`（从 `5062919` 派生）：删除“朝向鼠标”动作并停用 turn 帧，待机动作只剩小跳 : 表情 = 1 : 2。2026-10-31 已快进合并到当前分支并部署到 Shion-dev，分支保留、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/per-session-remote`（从 `5062919` 派生）：工作遥控四个按钮按会话区分，多个会话同时停住时用检查点面板分别继续/结束。2026-10-31 已合并到当前分支（合并提交 `7abd815`）并部署到 Shion-dev，分支保留、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/session-labels`（从 `e5fee12` 派生）：同一项目多个会话时，工作遥控菜单和检查点面板用各会话的第一句话摘要区分。2026-11-01 已快进合并到当前分支（`4ecaaaa`）并部署到 Shion-dev，分支保留、未 push，详见下方 2026-11-01 记录。
- 2026-11-01 本机 Shion-dev 先替换为 `4ecaaaa` 的开发包（旧包 `Shion-dev-before-session-labels-20261101`），同日再替换为 `b016547` 的安全修复开发包（220 文件），旧包保留为 `Shion-dev-before-security-20261101`。
- 分支 `feature/v2-security-fixes`（从 `1500086` 派生）：v2.0.0 发布前审查的 3 条应修 + 2 条小问题和复审第二轮（hook ↔ 服务端令牌、令牌绑定诗音进程、独占绑定、ChatGPT 状态显示时效、按会话中断共用进程保护、prompt_head 读不到存档不发）。2026-11-01 已快进合并到当前分支（`f8ec0a6`），之后追加 bundle_smoke 修正 `b016547`；worktree 已移除，分支保留、未 push，详见下方 2026-11-01 记录。
- 2026-11-01 v2.0.0 发布准备（2026-11-02 已快进合并到本地 `master`、打包、打本地标签；未 push、未发布）：版本号改为 2.0.0；三语 README 补 ChatGPT 只读观察、临时关闭联动、AI 连接菜单新结构、工作遥控选会话、同项目第一句话区分、诗音没开时不拖慢 CC、已知限制和隐私说明；新增 6 张菜单截图；发布说明在忽略目录 `build/release-notes-2.0.0.md`。详见下方 2026-11-01 记录。2026-11-02 追加：ChatGPT 未安装时顶层只显示“ChatGPT：未安装”、子菜单活动显示“—”；6 张菜单图改为原生 Windows 11 风格重新渲染。详见下方 2026-11-02 记录。
- 公开稳定版为 **v2.0.0**（2026-11-02 发布，标签指向 `0034dbb`）；上一版 v1.0.0；私有备份仍含旧历史。历史改写后的哈希以当前 Git 为准，旧报告的失效哈希仅作决策记录。

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

- **2026-11-02 V2.1 第 0 步可行性探测已完成（只做 Claude Code）**：真实 usage 聚合可读；终端 statusLine 已取得 five_hour/seven_day，桌面版原会话与新会话均无记录；hook 两档退路仍只有官方文档候选、未实测。临时配置已按备份恢复，恢复前后哈希核验通过。下一步为第 1 步周报开发，由用户另行安排；本次不开始。spec 的周报、体力和安装器变更仍是规划。
- 当前是阶段 2 开发预览、阶段 1 人工验收暂缓；暂缓不阻塞独立开发，也不代表阶段 1 全部验收通过。
- **v2.0.0 已发布（2026-11-02）**：https://github.com/iLLyaaaaaa/shion/releases/tag/v2.0.0 ，详见下方发布记录。原定的三项发布前人工专测（立即中断后工具进程是否结束、Codex 配置断开再重连、真实干净环境解压运行）没有做，改为**发布后日常使用中验证**；Codex 配置的安装/卸载/冲突已有隔离自动测试，但不代替真实 Codex 客户端里的断开再重连。
- 下一步由用户决定：日常使用中留意上面三项和下方清单；`test_real_process_tree_is_terminated` 满载时失败的根因仍未确认。
- 更正（2026-11-01 核对 `git branch --merged`）：`feature/menu-parity`、`feature/remove-codex-autolaunch` 均已在当前分支历史里，上方“未合并”的描述已过时；`feature/remove-face`、`feature/per-session-remote` 已合并并部署，真机验收按下方清单在日常试用中进行。
- 普通用户开关开放前，先处理下方全局 `ledger.uncertain` 恢复遗留；不得用心跳、重复包或新 turn 结束推断旧任务成功。真实身份、前台绑定、coverage 和人工权限能力必须各自有证据。（更正 2026-11-01：这个粘滞标志原先也让默认配置下的 ChatGPT 菜单“活动”一直显示“待确认”，不只影响调度器；`feature/v2-security-fixes` 已给显示层加时效，调度器语义仍是遗留。）
- `feature/v2-security-fixes` 已合并并部署到 Shion-dev；bundle_smoke（99 项）和隔离实例验证已通过，剩余真机项按下方清单在日常使用中验收。

## 未完成的人工验收清单

以下是当前交接清单；历史原文中的 125 条未勾选明细全部留在月度归档（包括后续版本已取代的旧方案/旧计划，不自动改勾）。需要执行某项时用 `rg -n '关键词|\[ \]' docs/progress-archive/2026-10.md` 定位对应小节，并以最新实现为准。

V2 进入日常试用阶段，人工验收以日常使用中的反馈为主；平时碰不到的项目（立即中断后工具进程是否结束、Codex 配置断开再重连、干净环境解压运行）原定发布前专测，v2.0.0 发布时未做，改为发布后日常使用中验证。

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
- [ ] 会话第一句话区分（`feature/session-labels`）：同一项目开两个 CC 会话并各说一句话，工作遥控子菜单显示“文件夹名 · 第一句话前 12 字…”；只开一个会话时仍只显示文件夹名；诗音启动前就开着、还没说话的会话显示原来的“(2)”编号；开隐私模式后显示“会话 1 / 会话 2”，关掉后不再出现之前的摘要；长名字被截断时鼠标悬停看到全文（高 DPI、多屏）；检查点面板的名字一致。
- [ ] 发布后日常使用中验证（按会话中断，原“发布前专门验收”）：两个会话都在跑长命令时只中断 A，A 的工具进程结束、B 的不受影响；选“全部”时两边都结束。

- 发布前安全修复（`feature/v2-security-fixes`，已部署 Shion-dev `b016547`）：
  - [x] 1. 启动后数据目录出现 `claude-link.json`，正常退出后消失（**隔离实例自动验证**，2026-11-01：打包版隔离实例 + WM_ENDSESSION 正常退出；真实 Shion-dev 启动后也确认文件存在）
  - [ ] 2. CC 里授权面板同意/拒绝、停下/继续、做得好/有问题照常（日常使用验收）
  - [ ] 3. 诗音没开时 CC 不卡、不弹面板（日常使用验收）
  - [x] 4. 诗音被强制结束、`claude-link.json` 留下后，hook 不采用旧令牌、交回 CC 自己处理（**隔离实例自动验证**，2026-11-01：强制结束隔离实例、伪造已不存在进程号的令牌两种情况，hook 均不发请求、占端口 socket 0 连接）；真实 CC 里“再启动诗音后联动恢复”的观感仍在日常使用中留意
  - [x] 5. 47613 被占时诗音不写 `claude-link.json`、日志有警告，hook 不给决定、不连占端口者（**隔离实例自动验证**，2026-11-01）
  - [ ] 6. ChatGPT 菜单“活动”几分钟后不再一直显示“待确认”（日常使用验收）
  - [ ] 7. 两个独立终端各一个 CC 会话，“立即中断”只选其一：只有被选的停下（日常使用验收）
  - [ ] 有条件时：用户目录经 junction 搬过家的机器上联动正常；令牌写不进去时诗音会说“联动凭据写不进数据目录……”（难以手动制造，可跳过）

- [ ] 删除朝向鼠标（`feature/remove-face`）：右键“动作”只剩跳一跳 / 去睡觉 / 趴一会儿（三语）；普通/活泼档待机时不再出现侧身，只有小跳和开心/发呆表情，表情明显多于小跳；旧存档正常加载。

## v1.1 待办
- [x] hook ↔ 服务端令牌认证 + `SO_EXCLUSIVEADDRUSE`（安全审查建议）：`feature/v2-security-fixes` 已实现、合并并部署 Shion-dev（2026-11-01），剩余真机项见验收清单
- [x] hook 耗时：诗音没开时的等待已在 v1.0.1 热修里去掉（见当前状态）。诗音运行时 PreToolUse 仍约 354 ms（源码）/ 435 ms（exe）：主要是进程启动，`find_cc_process` 只占约 26 ms；是否继续降另议
- [ ] 实验：桌面端能否拿到 statusLine 的 `rate_limits.seven_day`（每任务额度上限的前提）
- [ ] 接入 GPT / Codex
- [ ] V2.1 候选：Codex 控制能力。实验结论：授权可行（异常时交回 Codex 自己处理，桌面端未测）；停下只能做到"检查点暂停 → 继续"；中断目前不可行。详见 docs/experiments/shion-v2-codex-control.md。

- [ ] **开关对用户开放之前**：缺身份、来源冲突或容量耗尽导致的全局 `ledger.uncertain` 也要加恢复条件或时效（审查遗留）。ChatGPT 菜单显示已在 `feature/v2-security-fixes` 加 600 秒时效（`TaskLedger.uncertain_at`）；调度器 `scheduler.py` 仍读粘滞标志，这一条仍未完成。
- [ ] ChatGPT 观察端凭据 `chatgpt-observer.json` 的读写仍走 `observer_files.reject_reparse`（检查所有上级目录）：用户目录在 junction 下时 ChatGPT 观察会报错。Claude 联动令牌已在 `feature/v2-security-fixes` 改为只查最后两层；观察端涉及 Codex 配置事务和 ACL 审查，未在该分支改动（范围外发现）。

## 最近几天的记录（摘要，完整原文见月度归档及专项报告）

- **2026-11-02 V2.1 第 0 步可行性探测完成（本地提交，不 push）**：
  - **范围**：只新增标准库工具 `tools/probe_usage.py` 及隔离测试，未修改 `shion/`、正式 hooks 或安装器；真实 statusLine 经用户确认临时修改，现已按字节恢复。已有 spec/progress 规划改动按用户要求纳入本任务；三语 README 补上规划功能的平台限制，不表示功能已经实现。
  - **usage 结果**：真实只读扫描 199 个 jsonl；assistant usage 行 16,154，合格条目去重前 16,154、去重后 7,016；本地日期范围 2026-10-02～2026-11-02。最近 7 天四项逐日合计、模型名列表、客户端字段分布只写在忽略目录 `build/probe-usage.txt`，没有路径、项目名、对话内容或消息标识。`entrypoint` 分布：`claude-desktop` 35,728、`claude-vscode` 165、`cli` 861、`sdk-cli` 272；这是带该字段的顶层记录分布，不等于 usage 条目数，也不证明每条 usage 都能区分客户端。未知客户端值和不符合公开 Claude 模型名格式的值分别合并为 `<other>` / `<other-model>`，不回显自由文本。
  - **统计口径与局限**：完整扫描并按 `(message.id, requestId)` 去重，缺两种标识或日期/数值非法的条目不纳入；本次重复键保留首次遇到的有效记录。坏行及超过 1 MiB 的行在内存计数，不增加规格以外的报告项。第 1 步仍须明确流式重复记录的 usage 是否变化、应采用哪条；本探测不作为账单核验。按本机时区取本地日期，测试同时隔离 HOME / APPDATA / 配置目录，未运行产品全量测试。
  - **hook 调研**（官方文档核对；本机终端 CLI `2.1.289`）：[StopFailure](https://code.claude.com/docs/en/hooks#stopfailure) 的 `error == "rate_limit"` 是限流候选信号；[Notification](https://code.claude.com/docs/en/hooks#notification) 的 `quota_auto_resume_fired` 表示额度等待后自动继续，`quota_auto_resume_stale` / `quota_auto_resume_disabled` 不表示任务已经继续，这三种类型要求 2.1.234+。这些字段不能提供 five_hour/seven_day 百分比；rate_limit 也不保证是订阅窗口耗尽，自动继续不保证已用比例回到 50 以下。未新增真实 hook、未故意撞限额；桌面版支持和实际触发仍未验证，不能把文档信号当作真机验收通过。
  - **statusLine 实测**：已有第三方命令，临时接收器只投影顶层键名和额度数字，并串联原命令（1 秒超时）；未知键名合并为占位。用户在桌面版现有会话发两条并等回复：0 条记录；新开桌面版会话重试两条并等回复：仍为 0。之后终端发两条并等回复：共 6 条调用记录，其中 4 条未带 rate_limits，后续 2 条带 `five_hour.used_percentage=9` / `resets_at=1793627400` 和 `seven_day.used_percentage=8` / `resets_at=1794186000`。调用次数不等于消息数；没有记录只能说明本次未观测到桌面调用，不能推断所有版本都不支持。聚合元数据只在忽略目录 `build/probe-statusline.jsonl`。
  - **恢复核验**：原始备份 SHA-256 `88446db17715def1e3924ca0043a678567d025b2ac5d67eea6b497d6a5b130b5`；临时写入后 SHA-256 `e2706d60e3639e2f800c5df6bd9485a78a9af9ea5b8664a288bc56c78a9a1c51`。恢复前确认当前哈希等于临时写入后哈希，原子替换前再核对原字节未变；原始备份哈希通过后恢复，恢复后 SHA-256 与原始备份完全一致。无并发冲突。备份留在用户配置目录，文件名及阶段记录只在忽略目录 `build/probe-statusline-state.json`；接收器恢复后停止记录，防止会话缓存临时命令继续采样。隔离的安装/备份/并发修改拒绝恢复/原字节恢复测试均通过。
  - **结论与下一步**：token 周报的数据源可行；额度入口目前只有终端获得真机证据，桌面体力暂不承诺支持。StopFailure 和额度自动继续通知值得以后单独验证，但本步未安装它们，也不把普通限流或自动继续等同于五小时窗口耗尽/刷新。第 1 步先做周报；第 2 步若仍无已验证的桌面 hook 退路，体力只对终端开放，未知额度保持隐藏。
  - **验证**：隔离 `tests/test_probe_usage.py` 6 项通过，覆盖跨文件重复、坏行/截断/超长行、非法标识/计数、时区、未知模型和客户端字段的隐私隔离、输入字节不变与固定输出位置。初次测试有一处期望数误写（把 user 行也算入 assistant 行），已修正；收尾重跑仍为 6 项通过。`tools/check_private.py` 暂存区检查与 `git diff --cached --check` 通过；真实聚合输出、临时接收器/控制器和状态记录均忽略、不入库。未运行产品全量测试。

- **2026-11-02 发布 v2.0.0**（证据在忽略目录 `build/release-2.0.0-check/`、`build/release-build-2.0.0-final.log`、`build/release-final-pytest.log`）：
  - **Codex 联动隔离测试**（`codex_isolated.py`，走菜单同一函数 `review_connection`，确认框自动点“是”，观察端命令指向打包版 `Shion.exe`；CODEX_HOME / HOME / USERPROFILE / APPDATA / SHION_DATA_DIR / SHION_INSTANCE_NAME / SHION_PORT 全部指向临时目录和空闲端口）：准备一份带注释、怪格式、末尾无换行、其他 MCP 和其他 hook 的 config.toml / hooks.json。两轮“安装 → 卸载”：安装后只有插入、原有字节逐字保留，MCP 只多 `shion_lifecycle_v1`，hook 多 7 组；按配置命令能启动打包版观察端；卸载后两个文件与原始字节完全一致，无残留。冲突 A（安装后改用户自己的行再卸载）：只移除诗音条目，用户修改保留。冲突 B（改诗音自己的条目再卸载）：拒绝卸载，文件不动。无残留进程，临时目录已删除。
  - **发现并修正的文案问题**：第一次跑时“备份文件存在”4 项不通过——Codex 安装本来就不另存配置副本（只在写入期间有事务记录，内容是哈希和插入位置），但三语菜单提示和 README 写了“写入前备份/保留备份”。用户选择改文案：提交 `0034dbb` 改为“只插入诗音条目、不另存配置副本、断开时按记录精确移除”，卸载提示改为“Codex 里的信任记录保留不动”；该检查项随之改为“只有 1 个所有权记录，且不含用户原文”，最终 **60/60 通过**。
  - **重新打包**：因菜单文案进了程序，从 `0034dbb` 重打；本地标签 `v2.0.0`（未推送过）挪到 `0034dbb`，标签对象 `9f7d867`，标签作者 noreply。zip **45,346,758 字节**，SHA-256 `7b2318fe79ed95cc3a27cf76cc14bd4b3bf2241dd8f6a1b49292bf83ebe08628`；bundle_smoke 99 项、观察端烟测、中文空格路径解压自检（99 项）均通过。上一版 zip（`9dde196a…`，基于 `db5b58a`）作废，挪到 `build/dist-archive-dev-20261102/`。全量 pytest `1 failed, 2049 passed, 8 skipped, 2 warnings in 603.39s (0:10:03)`，唯一失败仍是满载时的 `test_real_process_tree_is_terminated`。
  - **推送前审查**（40 个提交 + 标签）结果同下方记录：`check_private` 只有 `1f54cb6` 的已知虚构测试字面量；USERNAME / COMPUTERNAME 全文 0 命中；邮箱全部 noreply；无 >5 MB 文件，无 raw/build/dist/.venv。
  - **推送**：`git push origin master`、`git push origin v2.0.0` 两条命令。`git ls-remote origin`：`refs/heads/master` = `0034dbb04716…`，`refs/tags/v2.0.0` = `9f7d8677eda3…`（`^{}` = `0034dbb`），均与本地一致；与推送前相比只新增 `v2.0.0`，没有 feature 分支、`refs/codex/*`，没有推 backup。仓库 `iLLyaaaaaa/shion` Public、默认分支 master。
  - **Release**：中途发现本机 `gh` 凭据失效，由用户本人在本机重新登录后创建。`gh release create --verify-tag`，标题 “Shion 2.0.0”，Latest、非 Pre-release，发布时间 2026-11-02T00:16:35Z，正文与 `build/release-notes-2.0.0.md` 一致（只差末尾换行），附件 45,346,758 字节；从 Release 下载后 SHA-256 一致，公开下载地址返回 200。README 引用的 13 张图片/GIF 及 README、LICENSE 链接在 GitHub 上都返回 200，大小与本地一致。
  - **未做**：三项人工专测改为发布后日常使用中验证（见上）。

- **2026-11-02 合并 master、打包 v2.0.0、推送前审查**（只在本地，没有 push、没有创建 Release；证据在忽略目录 `build/release-2.0.0-check/`、`build/release-build-2.0.0.log`）。**注意：本条里的标签位置（`db5b58a`）和 zip（`9dde196a…`）已被上方发布记录取代。**
  - **合并与标签**：起点工作区干净、HEAD 为 `db5b58a`，`master`（`74121dc`，与 `origin/master` 一致）是其祖先；`git merge --ff-only` 快进到 `db5b58a`（38 个提交）。附注标签 `v2.0.0`（标签对象 `093f9c9`）打在发布提交 `db5b58a` 上，标签作者是 noreply 邮箱。**标签位置沿用 v1.0.0 的做法**：v1.0.0 标签指向发布内容提交 `7c34de6`，之后的“记录发布”文档提交（`3cc27ee`）排在标签之后；所以 v2.0.0 指向 `db5b58a`，本条进度记录是标签之后的单独提交，标签不移动。
  - **打包**：`tools/build.py` 从 `master` 正常构建，`dist/Shion` 220 文件 / 104.44 MB（99.6 MiB），bundle_smoke **99 项全部通过**；`dist/Shion-2.0.0-win64.zip` **45,346,513 字节**（222 个条目），SHA-256 `9dde196aeedf267e844053eb643217a8fdafd223a92921c89ad03e4a403a1107`（另用 `sha256sum` 复核一致）。构建前把 `dist` 里旧的开发版残留 `Shion-1.0.0-win64.zip`（46,695,060 字节，SHA-256 `7a1410dc…602ca9`）挪到 `build/dist-archive-dev-20261102/`，没有删除。
  - **烟测**：观察端 stdio 烟测（initialize / tools/list / ping / EOF 正常退出）通过，stderr 为空，响应与上一次替换逐项一致（`serverInfo.version` 仍是协议版本 `1.0.0`，有意保留）。解压自检：zip 解压到路径含中文和空格的临时目录，`testzip` 无错，根目录只有 `Shion/`、`LICENSE`、`assets/LICENSE`，解压出的 220 个文件与 `dist/Shion` 逐文件 SHA-256 一致，没有 `.venv`、`raw`、`build`、令牌或存档文件；对解压目录运行同一套 bundle_smoke 通过 99 项；临时目录已清理。这不等于干净机器验收。
  - **推送前审查**（范围 `origin/master..master`，38 个提交加本条记录）：每个提交运行 `check_private.py --ref`，37 个无命中，`1f54cb6` 命中 1 处（`tests/test_check_private.py` 里虚构用户名的测试字面量，同一文件在后续提交已改写，未改写历史，与 11-01 记录一致）；用 `USERNAME`、`COMPUTERNAME` 的值对完整补丁（含二进制，约 7.1 MB）、全部提交信息、标签和文件路径做不区分大小写全文匹配，均 0 命中；所有提交的作者与提交者邮箱都是 noreply 邮箱，提交信息里唯一的邮箱是 `noreply@anthropic.com`；范围内没有超过 5 MB 的文件（树内最大是 `hero.gif` 1.4 MB），没有 `assets/sprites/raw/`、`build/`、`dist/`、`.venv` 内容，没有音频/字体/字幕类文件，`git ls-files -ci --exclude-standard` 为空。
  - **待推送的引用**：`git push --dry-run origin master v2.0.0` 只显示 `74121dc..db5b58a master -> master`（快进，无需强推）和新标签 `v2.0.0`；`remote.origin.push` 未配置，不使用 `--all`/`--mirror`/`--tags`。本地存在的 `refs/codex/turn-diffs/*`、各 feature 分支、`v1.0.0` 都不会被推送；`backup` 远端不推。

- **2026-11-02 ChatGPT 未安装状态显示 + 原生风格菜单截图**（本地提交，没合并 master、没打包、没 push）：
  - **状态显示**：`ChatGPTConnection.activity()` 在临时关闭**或未安装**时返回“—”（`activity_link_none`），子菜单显示“活动：—”。`build_menu` 的 `status_row` 在 not_installed 时改用新增三语 key `menu_link_status_bare`（“{name}：{state}”），顶层只显示“ChatGPT：未安装”，原来的多行全文仍放在 tooltip。已安装、临时关闭、出错时的显示不变（新增三语×三状态参数化测试）。Claude 未连接时仍显示“未连接 · 空闲”，按用户决定没有改。`test_chatgpt_ui.py` 的辅助函数把连接视为已安装，因为它测的是“待确认”时效。基线 `scheduler_disabled_a55825f.json` 只刷新 `menu_sha256`：21 项中 18 项变化，12 个不同哈希一一对应；不变的 3 项是 ChatGPT 临时关闭阶段，其余字段逐项比对一致。
  - **截图**：`--platform windows` 时 Qt 已经使用 `windows11` 样式（圆角高亮、未勾选项没有方框），但 `QMenu.grab()` 只截客户区，真机上的圆角外框、细边框和阴影是 Windows DWM 加的，所以原图是方角。`render_menu.py` 在原生平台下照样补上外框（圆角 8 逻辑像素、1px 半透明边框、柔和阴影），offscreen 输出不变。`SESSION_SPECS` 改为按语言给虚构的第一句话，项目名都是 `my-app`。6 张图取 scale1.5，大小 48～61 KB，文件名不变。日文和英文的第一句话按程序规则截断到 12 个字。
  - **坑**：曾想把真实菜单弹到屏幕上再截屏来测外框，`grabWindow` 截到的是桌面壁纸（没有菜单），文件已立即删除，之后不再用截屏方式。外框参数按 Windows 11 规范模拟，需要真机对照确认。
  - **其他 README 媒体**：hero.gif（抽 4 帧）、pat、desk、permission 三语、sleep-bed 都只有桌宠和授权面板，没有菜单，不涉及旧菜单结构。
  - **验证**：全量 `--basetemp=.venv/preview-run/release-prep2`，结果 `1 failed, 2049 passed, 8 skipped, 2 warnings in 603.42s (0:10:03)`（日志 `build/release-prep2-pytest.log`）。唯一失败仍是满载时出现的 `test_real_process_tree_is_terminated`（见下方 11-01 记录），根因未确认。

- **2026-11-01 v2.0.0 发布准备**（只改版本号、文档、截图，没改功能代码；没合并 master、没打包、没 push）：
  - **版本号**：`shion/__init__.py` 改为 `2.0.0`。关于页、`QApplication` 版本、snapshot 标题、exe 版本资源（`tools/build.py` → `Shion.spec`）、ZIP 文件名都从这里读取。同步修改了测试里写死的地方（`test_release.py` 的 QApplication 版本、ZIP 名和 `fileVersionMS == 2 << 16`，以及 `test_windowing.py`），还有 spec.md 两处、三语 README 的下载文件名。`shion/codex_mcp.py` 里 `serverInfo.version "1.0.0"` 是 `shion_lifecycle_v1` 协议的版本，有意保留。
  - **README 三语**：结构不变，新增“ChatGPT（Codex）只读观察”“连接 ChatGPT（Codex）”“已知限制”三节。多会话选择、临时关闭联动、诗音没开时不拖慢 CC、Codex 窗口层级跟随写进功能；菜单路径改成“AI 连接 › Claude Code / ChatGPT › …”；隐私节补上一次性令牌与独占端口，以及第一句话摘要只在内存（隐私模式下不发送）。商标声明补上 OpenAI。
  - **截图**：原有 7 张用 `tools/make_media.py` 重新生成后像素完全一致（`permission.en.png` 只差 PNG 编码字节），没有替换。新增 6 张菜单截图 `docs/images/menu-ai.{zh,en,ja}.png`（AI 连接 › Claude Code）和 `menu-sessions.{lang}.png`（工作遥控 › 停下 › 按会话），由 `tools/render_menu.py` 渲染（scale 1.5，20～52 KB）。工具里的合成项目名改为虚构的 `my-app` / `notes`，第一句话改为虚构英文。菜单树 json 已检查，没有路径或用户名。
  - **发布说明**：`build/release-notes-2.0.0.md`（忽略目录、不入库），英中日三语。
  - **坑**：`rg 1\.0\.0` 搜不到 `test_release.py` 里以 `1 << 16` 写死的主版本号，第 1 次全量才暴露（日志 `build/release-prep-pytest-attempt1.log`）。修正后第 2、3 次全量都是 `1 failed, 2040 passed, 8 skipped, 2 warnings`（第 3 次 `in 607.48s (0:10:07)`，日志 `build/release-prep-pytest.log`；第 2 次 `-attempt2.log`），唯一失败是 `test_interrupt.py::test_real_process_tree_is_terminated`：`killed` 里只有 1 个 pid，没有直接子进程。单独跑这个测试 5/5 通过，整个 `test_interrupt.py` 3/3 通过（84 passed）；本次 `shion/` 只改了版本号字符串，没碰中断代码。推测是满载时的时序竞争：`.venv\Scripts\python.exe` 是转发器，子进程（转发器）在真正的 python 被结束后自己退出，`TerminateProcess` 就返回失败，曾孙进程也可能还没创建。**未修复、未确认根因**；这个用例对应发布前专测的“立即中断后工具进程是否结束”，专测时要实机确认。`make_media.py --output-dir` 指到 C 盘会因 `relpath` 跨盘报错，应输出到仓库内的 `build/`。

- **2026-11-01 合并安全修复、隔离验证并替换 Shion-dev**（证据在忽略目录 `build/security-replacement-20261101/`）：
  - **合并**：`git merge --ff-only feature/v2-security-fixes`，HEAD 由 `1500086` 快进到 `f8ec0a6`。worktree `..\shion-security-fixes` 扫描无 reparse point（junction 已在上一任务解除）、无未提交改动（只有被忽略的 `build/` 和缓存），用 `git worktree remove`（未加 `--force`）移除，分支保留；主仓库 `.venv` 与 `assets/sprites/raw`（23 项）完好。
  - **打包**：沿用 `build/session-labels-replacement-20261101/` 的脚本，只改目录名和备份名，不生成 ZIP。
    - 第 1 次：打包成功（220 文件），但 bundle_smoke 失败，`list index out of range`。原因是 `tools/bundle_smoke.py` 的 `MockHooks.link` 只写了 `{"token"}`，没有第二轮新增的 `pid` / `created`；打包版 hook 的 `read_link` 正确地拒绝了它、一个请求都没发，`mock.events` 为空。这是第二轮漏改的测试工具（当时只做了编译检查），不是产品代码问题。
    - 修正：`MockHooks.link` 改用正式的 `shion.loopback.write_token`，单独提交为 `b016547`（只改测试工具）。第 1 次的结果改名保留为 `*-attempt1`。
    - 第 2 次：从 `b016547` 完整重打，220 文件，bundle_smoke **99 项全部通过**（新增 `hook-sends-link-token`、`server-rejects-missing-token`），没有新 ZIP。观察端 stdio 烟测通过，响应与上次替换完全一致。依赖版本 PyInstaller 6.22.3 / pyinstaller-hooks-contrib 2026.9 / PySide6 6.12.0 / numpy 2.2.6，与 `requirements-build.txt` 一致。
  - **隔离验证**（`isolated_verify.py` → `isolated-verify.json`）：打包版在系统临时目录里运行，独立 HOME / APPDATA / CODEX_HOME / SHION_DATA_DIR、空闲端口、唯一实例名，ChatGPT 观察端预置为别的端口并关闭，存档预置 `permission_timeout=10`；隔离实例用原生 windows 平台（正常退出靠 WM_ENDSESSION，等同注销）。**a～d 全部通过**：
    - a. 启动后出现 `claude-link.json`，记录的写入者就是该实例；带令牌 `/health` 返回 200；`--hook PermissionRequest` 登记成功（日志有“有东西要你决定哦”），10 秒超时后撤回，不输出决定，退出码 0；WM_ENDSESSION 正常退出（退出码 0）后令牌文件被删。
    - b. 普通 socket 先占住端口：日志有“HTTP 服务启动失败”，没有令牌文件，实例仍在运行；`--hook PermissionRequest` 不输出决定，占端口 socket 0 连接。
    - c. 伪造进程号已不存在（句柄也已关闭）的令牌文件：PermissionRequest 和 UserPromptSubmit 都不发请求，0 连接；隔离实例被强制结束后令牌文件留下，`read_link` 拒绝，hook 不发请求，0 连接。
    - d. 不带令牌、错误令牌、300 字符畸形令牌请求 `/health`、`/event` 都返回 403。
    - 3 个隔离进程均已结束，4 个临时目录已删除，之后也没有 dist 下的 Shion 进程残留。
  - **替换**：开始时没有任何 Shion.exe 在运行，不需要用户关闭程序。替换器原地替换，两次改名均一次成功；旧包 220 文件逐个核对后保留为 `D:\desktop\tools\Shion-dev-before-security-20261101`，新目录 220 文件逐个核对一致。Codex / CC 配置哈希与任务开始时一致，存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true` 未变，`Shion-1.0.0-win64.zip` 未变，没有强制结束进程。旧 exe `4834ed5a…55f458`，新 exe `b1c65811…278d6a`。
  - **用户启动新版后只读核对**：PID 5780 来自 `Shion-dev\Shion.exe`（exe 哈希与新包一致），同时监听 127.0.0.1:47613 和 47614；19:28:58 启动，19:29:01 真实数据目录出现 `claude-link.json`（只确认存在，没有读取或记录内容）。启动后日志 13 行，没有 WARNING/ERROR，没有端口被占或令牌写入失败；真实 CC hook 发来的 prompt / working / tool_done 都被新服务端接收（新 hook 带令牌和新服务端对上），prompt 行只有 `None` 和会话 ID，没有提示词内容。
  - 验收清单第 1、4、5 项注明“隔离实例自动验证”并打勾，第 2、3、6、7 项留待日常使用验收。未 push、未发布。

- **2026-11-01 安全修复第二轮**（同分支 `feature/v2-security-fixes`，在 `5164056` 之后新提交，不改写历史；本地提交、未合并、未 push）。来源是 reviewer 子代理对 `5164056` 的复审（结论“可以合并”）加我的独立复核。
  - **应修 1：旧令牌被信任。** 诗音被强制结束后令牌文件会留下；命名管道名是整台机器共用的，别的账户能在诗音没开时同时冒充管道和 47613，hook 就会带着旧令牌发出完整命令、采纳伪造的 allow。（子代理原判断只影响设了 `SHION_PORT` 的情况，复核后更正。）修法：令牌文件加 `pid` / `created`（写入者进程号、FILETIME 创建时间），hook 改用 `loopback.read_link`，只有写入者还在运行才采用令牌。新增 `winproc.process_running`，同一句柄上核对创建时间，并要求退出码是 `STILL_ACTIVE`。**踩坑**：最初只比创建时间，测试发现进程被 `kill()` + `wait()` 后，`Popen` 仍握着句柄，内核对象还在，`GetProcessTimes` 照样成功，旧令牌被当成有效。真实环境里任何握着诗音句柄的程序都会造成同样情况，所以加上退出码判断。Windows 上读不到自己的创建时间时，`write_token` 抛 OSError，按写失败处理。
  - **应修 2：junction 回退。** 令牌读写原来复用 `observer_files.reject_reparse`，会检查所有上级目录，用户目录在 junction 下时联动会悄悄失效。改为 `loopback` 自己读写，只检查数据目录本身和令牌文件本身；写入用同目录唯一临时文件 + `os.replace`，失败时删掉临时文件；读取限 4 KB。`start_linked` 改成返回 `ok` / `port_busy` / `token_failed`，`app.link_warning` 在 `token_failed` 时说新台词 `link_token_failed`（三语）。日志只记异常类型，不记路径。
  - **小问题**：hook 的 `request()` 收到 403 时重读令牌，令牌换了才用新令牌重试一次；`_Server.server_bind` 补设 `server_name` / `server_port`；所有选中会话都因共用进程没法结束时说新台词 `interrupt_shared_process`（三语）。
  - **新增测试**：
    - 写入者已退出（握着句柄的情况）、进程号复用两种情况下 `read_link` 拒绝，6 种缺字段或坏字段也拒绝；
    - 上级目录是 junction 时能读写；数据目录本身或令牌文件位置是 junction 时拒绝，且不往别处写；
    - 不留临时文件；`token_failed` 与三种提示文字；
    - 端到端：只靠 `start_linked` 写令牌，用 hook 真实的 `link_token` 读到并 `/health` 返回 200，退出后读不到；
    - 旧令牌 + 冒充者：2 种事件 × 2 种失效方式，hook 一个请求都不发；
    - 403 后令牌换了能重试成功，令牌没变时不重试、也不熔断；共用进程时的提示语。
  - **验证**：全量 pytest（PowerShell `$LASTEXITCODE`，worktree 内临时 junction，`PYTHONUTF8=1`）汇总原文：`2041 passed, 8 skipped, 2 warnings in 618.99s (0:10:18)`，退出码 0；两条警告都是既有的 Pillow `getdata()` 弃用提示。`tools/bundle_smoke.py` 仍未打包运行。
  - **范围外**：ChatGPT 观察端凭据仍会检查所有上级目录（已记入 v1.1 待办）。

- **2026-11-01 v2.0.0 发布前安全修复**（分支 `feature/v2-security-fixes`，从 `1500086` 派生，worktree `..\shion-security-fixes`，本地提交、未合并、未 push）。起因是同日的发布前审查（master `74121dc`..`1500086`，结论“修复后发布”，没有阻塞项）。
  - **令牌（应修 1、3）**：新模块 `shion/loopback.py`（只用标准库）。诗音每次启动生成 `secrets.token_hex(32)`；`server.start_linked` 先删旧的 `claude-link.json`，绑定 47613 成功后才写新令牌（复用 `observer_files.replace_private`，先清掉崩溃残留的暂存文件），端口被占时不写；`stop_linked` 退出时先删令牌再停服务。服务端 `_allowed()` 对所有路由（含 `/health`）核对 `Authorization: Bearer`（`hmac.compare_digest`），不对就 403、不读请求体。hook 读不到令牌就不发任何请求（按诗音没开处理），`probe_health` 重新读令牌。修复前，抢先占住 47613 的进程（包括别的 Windows 账户）能收到完整命令并回 allow，还能注入反馈、解除暂停；`/event` 等接口本机任何进程都能调。
  - **独占绑定**：47613 的 `_Server.server_bind` 和 47614 的 `_ExclusiveHTTPServer` 在 Windows 上设 `SO_EXCLUSIVEADDRUSE`，不设 `SO_REUSEADDR`（47614 原来用标准库默认，会设 `SO_REUSEADDR`）。
  - **ChatGPT 状态（应修 2）**：`TaskLedger.uncertain` 改成带 setter 的属性，并记录 `uncertain_at`，读取时仍是原来的粘滞布尔值（调度器不变）。`ChatGPTConnection` 的 `status()`/`activity()` 只看最近 600 秒（`UNKNOWN_WINDOW`）内的不确定/断开；`_unobserved_start` 只在启动后 `ledger.ttl` 内算；不开调度器时一次降级只断开一次，然后清标记。修复前 `_unobserved_start` 从不清除，菜单“活动”永远显示“待确认”，切换一次开关也会永久卡住。
  - **小问题**：`interrupt_work` 中，选中会话和没选中的工作会话报来同一个 CC 进程（pid + 创建时间）时不结束进程、改为只停下这个会话；hook 新增 `read_save_strict()`，存档读不到或损坏时不发 `prompt_head`。
  - **测试**：`tests/link_support.py` 加 conftest 的 autouse fixture：测试里起的 ShionServer 按端口登记令牌、写进当前 `SHION_DATA_DIR`，`run_hook` 在目标目录没有令牌时补上，hook 模块的令牌缓存每个测试清零。原来 13 个文件共 156 个用例因缺令牌失败，已全部改好。“连不上 / 不回包 / 熔断”这类用例改为先写一个令牌，保证仍真的去连。
  - **新增用例**：8 个路由 × 6 种错误令牌都返回 403；错令牌不转发事件、不取反馈、不能解除暂停；冒充者占着端口回 allow 时 hook 一个请求都不发（PermissionRequest / UserPromptSubmit / PostToolUse）；旧令牌被真服务端拒绝时不给决定；两个端口二次绑定失败；`start_linked` 写/删令牌、端口被占不写；真实 app 子进程不带令牌 403、第二个实例没有令牌文件；ChatGPT 五个时效用例；共用进程中断三个用例；prompt_head 在没有存档、存档损坏时不发。
  - **工具**：`bundle_smoke.py` 的 MockHooks 要求令牌，并新增 `hook-sends-link-token`、`server-rejects-missing-token` 两项；`benchmark_hooks.py` 写令牌。两者只做了编译检查，**没有打包、没有实际运行**。
  - **验证**：全量 pytest（worktree 内，临时 junction 指向主仓库 `.venv` 和 `assets/sprites/raw`，`PYTHONUTF8=1`）。
    - 第 1 次：`1 failed, 2022 passed, 8 skipped, 2 warnings in 623.91s`。唯一失败是 `test_permission.py::test_http_input_validation_and_limits` 发超大请求体时遇到 `ConnectionAbortedError [WinError 10053]`（服务端没读完请求体就回 400 并关连接），和调度审查报告里记过的同类偶发问题一样；单独连跑 15 次都通过。
    - 第 2 次：`2023 passed, 8 skipped, 2 warnings in 630.57s`，但测试全部通过后 Python 进程退出码是 `-1073740791`（0xC0000409，退出阶段崩溃）。
    - 第 3 次（`-X faulthandler`）：`2023 passed, 8 skipped, 2 warnings in 626.86s`，退出码 0，没有崩溃栈。
    - 第 4 次（和第 2 次同样的命令）：`2023 passed, 8 skipped, 2 warnings in 614.04s`，退出码 0。
    - 原代码 `1500086` 在临时 worktree 跑一次：`1955 passed, 8 skipped, 2 warnings in 604.41s`，退出码 0。
    - 退出阶段崩溃只出现过 1 次、没复现、原因未查明，**不能断定和本次改动无关**，后续全量留意。两条警告都是既有的 Pillow `getdata()` 弃用提示。
    - Git Bash 下记到的退出码 127 不可信（审查时原代码也是 127），本次改用 PowerShell 的 `$LASTEXITCODE`。
  - `tools/check_private.py` 检查暂存区通过，`git diff --cached --check` 通过。基线 worktree 已先单独解除 junction、扫描确认无 reparse point 后移除。

- **2026-11-01 合并 session-labels，替换 Shion-dev**：`git merge --ff-only feature/session-labels`，HEAD 由 `e5fee12` 快进到 `4ecaaaa`。worktree `..\shion-session-labels` 扫描无 reparse point（junction 已在上一任务解除）、无未提交改动（只有被忽略的 `build/` 和缓存），用 `git worktree remove`（未加 `--force`）移除，分支保留；主仓库 `.venv` 与 `assets/sprites/raw`（23 项）完好。打包沿用 `build/per-session-replacement-20261031/` 的脚本，只改目录名（证据在忽略目录 `build/session-labels-replacement-20261101/`）：依赖版本一致，不生成 ZIP，bundle_smoke 97 项通过，观察端 stdio 烟测与上次替换响应完全一致；新包 220 文件。替换器等用户退出旧诗音后原地替换，两次改名均一次成功，旧包 220 文件逐个核对后保留为 `D:\desktop\tools\Shion-dev-before-session-labels-20261101`，新目录 220 文件逐个核对一致；Codex/CC 配置哈希与任务开始时一致，存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true` 未变，`Shion-1.0.0-win64.zip` 未变，没有强制结束进程。旧 exe `2c3f163b…81cd38`，新 exe `4834ed5a…55f458`。用户启动新版后只读核对：PID 365416 来自 `Shion-dev\Shion.exe`，同时监听 127.0.0.1:47613 和 47614，09:15:53 启动后日志 19 行、无 WARNING/ERROR；UserPromptSubmit 的日志行只有 `prompt None <会话 ID>`，没有提示词内容。未 push、未发布。

- **2026-11-01 同项目多会话用第一句话区分**（分支 `feature/session-labels`，从 `e5fee12` 派生，worktree `..\shion-session-labels`，本地提交、未合并、未 push）：原来 hook 的 UserPromptSubmit 不发提示词。现在 hook 新增 `prompt_head`（stdin 的 `prompt` 去掉 Cc/Cf 字符、压缩空白、最多 40 字），只在 UserPromptSubmit 且存档 `privacy_mode` 不是 true 时发送；服务端 `clean_prompt_head` 与 `clean_project` 同法清理，非字符串、为空或超过 40 字只忽略该字段（不 400）。控制器只对 `prompt` 事件把它交给 `SessionNames.note`，后者只记每个会话的第一句、截成 12 字 +“…”，存在内存字典里（随会话淘汰、`forget_all` 清除），隐私模式下不记录，打开隐私模式时 `forget_prompts()` 清掉已记的摘要。不写日志（控制器日志只有事件类型/detail/会话 ID，服务端只记请求路径）、不进存档。显示规则：文件夹只有一个会话 → 文件夹名；同文件夹多个 → “文件夹名 · 摘要”，摘要相同再加“(n)”，没有摘要的退回原来的“(n)”编号；隐私或无文件夹名仍是“会话 n”。工作遥控多会话子菜单的会话项按 240 逻辑像素截断、全文放 tooltip；检查点面板由 24 字截断改为同样 240 像素截断（`sessions.LABEL_W`）。`render_menu.py` 新增 `same_project` 场景（新场景在 `--baseline` 对照里跳过）。新测试 `tests/test_session_labels.py` 25 个。验证：全量 pytest（`--basetemp` 在 worktree 内 `build/pytest-tmp`）汇总原文：`10 failed, 1945 passed, 8 skipped, 2 warnings in 584.03s (0:09:44)`；10 个失败全在 `tests/test_process_sheets.py`，原因同前几次：新 worktree 缺 `assets/sprites/raw` junction，补上后单独重跑 `14 passed`。`render_menu.py --platform windows` 三语 `same_project` 子菜单已自查（显示“shion-pet · 把菜单截断的问题修一下，…”“shion-pet · Write the RE…”，不提交截图）。局限：摘要按字符截断，英文 12 字较短；同一会话第一句之后改名不跟随（按需求只记第一句）。

- **2026-10-31 合并 remove-face 与 per-session-remote，替换 Shion-dev**：`git merge --ff-only feature/remove-face`（`242b5bc`），再 `git merge --no-ff feature/per-session-remote`，合并提交 `7abd815`。唯一冲突在 `docs/progress.md`：两边在同样位置各加了状态、下一步和记录行，两边都保留；另外 `242b5bc` 把这个文件存成了 CRLF（`.gitattributes` 是 `* text=auto`），而且 remove-face 记录里的 `..\claude-pet-wt\remove-face` 中 `\r` 被写成了回车字符，合并时已恢复路径，并按 LF 存储。快照 `scheduler_disabled_a55825f.json` 没有冲突（per-session 没改它），合并后快照测试直接通过，`menu_sha256` 不需要重算，文件与 `242b5bc` 一致。全量 pytest（`--basetemp=.venv/preview-run/merge-per-session`）汇总原文：`1 failed, 1929 passed, 8 skipped, 6 warnings in 517.01s (0:08:37)`；唯一失败是已知的 `test_install_hooks.py::test_corrupt_json_not_touched`（GBK 解码），`PYTHONUTF8=1` 单独重跑 `1 passed`。两个 worktree（`remove-face`、`per-session-remote`）扫描无 reparse point、无未提交改动，用 `git worktree remove`（未加 `--force`）移除，分支保留，空的 `claude-pet-wt` 目录已删除。打包沿用 `build/lines-turn-replacement-20261031/` 的脚本（证据在忽略目录 `build/per-session-replacement-20261031/`）：不生成 ZIP，bundle_smoke 97 项通过，观察端 stdio 烟测与上次替换响应完全一致；新包 220 文件，比旧包少的正好是 8 张 `turn_*.png`。替换器等用户退出旧诗音后原地替换，两次改名均一次成功，旧包 228 文件逐个核对后保留为 `D:\desktop\tools\Shion-dev-before-per-session-20261031`，新目录 220 文件逐个核对一致；Codex/CC 配置哈希与任务开始时一致（Codex `config.toml` 相比上次替换后有变化，是本任务开始前就有的），存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true` 未变，`Shion-1.0.0-win64.zip` 未变，没有强制结束进程。旧 exe `f852c131…75fb8d`，新 exe `2c3f163b…81cd38`。用户启动新版后只读核对：PID 342244 来自 `Shion-dev\Shion.exe`，同时监听 127.0.0.1:47613 和 47614，22:48:07 启动后日志事件正常、无 WARNING/ERROR。未 push、未发布。

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
