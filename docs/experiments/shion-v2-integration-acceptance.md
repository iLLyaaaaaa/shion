# Shion V2.0 集成回归与独立测试包

日期：2026-10-29。结论：最终源码自动化回归通过，可以进入用户审核后的隔离桌面体验验收；真实客户端完整接入、精确前台仲裁和正式发布尚未验收。本轮未增加产品功能、未修改产品源码、未创建新提交。

## 基线与保护

- 分支：`feature/v2-observer-lease-scheduler`。
- HEAD：`a55825f11d2fa0697b8f9393a1153a1d3d5cd5a8`。Author/Committer 均为 `201329225+iLLyaaaaaa@users.noreply.github.com`，仓库邮箱设置相同，未修改身份配置。
- 阅读 `CLAUDE.md`、`AGENTS.md`、当前进度、规格相关章节、阶段 2 核心/GUI 报告及阶段 1 事务记录；旧修订方案仅作历史背景，当前授权以本轮任务和最新代码为准。
- 既有 `docs/progress.md` 改动和九个未跟踪文件全部保留，十个文件前后 SHA-256 相同。没有 reset、clean、stash 或覆盖其他开发成果。
- 原 Shion-dev 的 228 个文件逐个比较，文件集合及内容哈希不变。全局 MCP/Hooks 所在配置、观察凭据与归属文件仅取哈希核对，采集的七个路径均未变化；不输出配置内容或 Token。信任位于既有配置中，配置字节未变。本轮未操作真实客户端、真实 ACL、注册表写入或全局安装。

## 集成代码核查

| 项目 | 结论 |
| --- | --- |
| Claude 菜单优化 | 已保留；菜单测试与渲染工具和 UI 来源 `b3b40a2` 一致，新菜单布局 33 项通过 |
| Observer 与 GUI | 新 Observer 2 秒心跳、10 秒独立租约已进入接收端与共用任务表；GUI 轮询失联转未知，B 的心跳不续 A 的租约 |
| P1～P5 GUI | `SchedulerGUI` 复用 `Scheduler` / `TaskLedger`，Controller 按显式开关接入；默认 `v2_scheduler_enabled=False` |
| 旧 GUI | 默认关闭路径的 Claude 事件、权限、暂停/继续、中断和原完成统计保留；合成观察事件不叠加成功计数或奖励 |
| 重复状态与 UI | 未发现第二套逐轮生命周期表；旧 Claude 状态是无可靠轮次时的展示补充，不伪造 TaskKey；权限提示复用菜单及原授权面板，一次只显示一份 ChatGPT 只读提示 |
| Claude 权限归属 | 操作绑定原 PermissionQueue 的随机请求 ID，不绑定当前调度显示候选；撤回后的旧按钮不能批准下一会话请求，切到下一请求重新执行防误触延迟 |
| ChatGPT 能力 | 冻结 MCP 仅公开一个只读元数据工具，权限提醒没有批准/拒绝按钮，不接 RemoteHub 控制或奖励 |

前台验收必须区分：

1. **品牌级候选与安全轮转：模拟通过。** 两个真实协议形态的 Claude 会话只形成 Claude 品牌候选；与 ChatGPT 的候选轮转不生成伪造轮次。
2. **品牌级真实前台优先：未验收。** 当前窗口跟随器管理层级，没有向调度器提供经过验证的品牌前台绑定；不能将品牌轮转称为前台优先已接通。
3. **会话级精确前台优先：仅完整 TaskKey、`verified=True` 的合成测试通过。** 真实窗口到会话/轮次的可靠绑定未实现/未验证，不能宣称真实精确仲裁通过。

真实 Claude Hook 缺少可靠 turn_id 的边界完整保留；没有用时间戳、最近事件、本地递增号或工具内容拼造身份。真实多个 Claude 会话的视觉辨识、请求来源及进程归属还须人工客户端验收。

## 最终测试结果

最终源码启动全量测试后未发生产品代码或项目测试文件修改，本次结果覆盖 `a55825f` 的最终字节版本。

| 检查 | 最终结果 |
| --- | --- |
| 全量 pytest | **1745 passed，9 skipped，2 warnings，647.08 秒** |
| 最终专项（含三项补充验收） | **325 passed，1 skipped，126.82 秒** |
| P1～P5 核心 | 13 passed，包含优先级、前台迟滞、轮转、多请求、未知、容量和去重 |
| Scheduler GUI | 26 passed，包含双品牌/多会话、抢占恢复、独立租约、开关及重建 |
| Observer / MCP 与租约 | `test_codex_observation` 20 passed，`test_observer_lease` 16 passed |
| Claude 权限与远控 | `test_permission` 94 passed，`test_remote_control` 26 passed；暂停标签亦在全量和专项内 |
| Windows 文件 ACL / 事务 / 信任保护 | `test_observer_files` 16 passed，`test_codex_config` 23 passed，`test_codex_trust` 18 passed；只用隔离目录和合成配置 |
| 菜单布局 | 33 passed |
| 补充权限竞态、无身份品牌轮转 | 3 passed；已包含在最终专项中 |
| 隐私与差异 | `tools/check_private.py`、`git diff --check`、已跟踪但被忽略文件检查通过 |

九项跳过：对话框非激活焦点 1、前台窗口层级/隐藏恢复 3、暂停标签焦点 1、睡眠 Z 输入样式/非激活 2、窗口置顶与提醒层级 1，合计八项需要原生桌面窗口交互；另有真实 Claude 祖先进程链 1 项需要在 Claude Code 中运行。本轮 pytest 使用 offscreen，不把原生字体截图当作这些测试通过。两个警告均为既有 Pillow `Image.getdata` 弃用提示。

首次专项中的两个失败来自新增临时验收脚本：假时钟推进后未手动刷新真实 QTimer 所控制的按钮 enabled 状态。修正测试脚本后，三项补充验收与完整专项均重新通过，未因此改产品逻辑。初次启动脚本验收另出现启动等待超时和 HTTP 202 空响应被误当 JSON 的脚本问题；最终验收修正等待和空响应处理后通过，旧失败日志保留，未计入通过。

## 构建与隔离运行

- 使用既有 `tools/build.py` / `Shion.spec`，锁定的 PyInstaller 6.22.3、hooks-contrib 2026.9 已存在，没有安装新依赖。
- 完整原始运行目录 **228 文件、105,787,179 字节**；资源、Qt、Python 运行时和依赖完整复制，不依赖系统 Python。
- 原生 EXE 版本资源仍为项目现有 `1.0.0`；交付名称及 `INTEGRATION-TEST.json` 标明 V2 集成测试用途，不代表正式 V2 发布。
- 既有迁移目录自检 97 项通过。发现原自检没有独立 Observer 端口后，复用同一工具，再以隔离 CODEX_HOME、独立 Token、随机 Observer 端口和关闭观察重跑 **97 项通过**；最终交付依据后者。
- 冻结 EXE stdio MCP 自检：4 个协议版本、14 个请求、七种生命周期、认证心跳、只读工具声明、禁止内容字段/伪造租约、离线放行通过。42 个包内项目模块与当前源码编译对象逐项相同。
- 隔离启动脚本验收 **21 项通过**：默认/显式开启两轮、独立数据/配置/双端口、脚本锁和 EXE 单实例锁、冻结 GUI 合成事件轮询、不创建 MCP 或 Claude Hooks。结束时仅终止该测试路径下的进程；原生正常退出仍待人工。

独立交付目录：`D:\desktop\tools\Shion-v2-integration-test`。完整运行时、隔离启动脚本、注入脚本、许可、验收报告和截图一并交付。静态文件清单/大小/哈希以 `SHA256SUMS.json` 为准，ZIP 的大小与哈希另见仓库 `build/integration-delivery-report.json`。

**必须通过 `Start-Isolated.cmd` 启动。** 裸 `Shion.exe` 保留项目原有启动语义，会使用默认配置路径和端口，因此不应直接双击。启动脚本只在包内 `.isolated-profile` 创建新 HOME、CODEX_HOME、Claude 配置目录、数据与本地随机 Token，排除生产端口 47613/47614，并使用独立单实例名称。交付不包含运行时 profile 或 Token。

默认启动同时关闭调度和 ChatGPT 观察。只有用户显式传入 `-EnableScheduler -SyntheticObservation` 时才在隔离 profile 开启模拟测试，脚本不会连接 Codex、安装 Hooks、修改全局配置或迁移信任。隔离注入脚本只访问该 profile 的回环端口。不要在测试包里操作全局连接/开机启动管理；这些用户触发的管理功能未被改写为新的沙箱功能。

## GUI 可视证据

- `evidence/panel-100.png`、`panel-150.png`、`panel-200.png`：中文/英文/日文，实际 DPR 1.0 / 1.5 / 2.0，原生 Windows Qt 字体库 341 项，窗口全部设置为不显示到桌面。
- 菜单约 285～287 × 265 逻辑像素，权限面板 400 × 242～262。布局断言和截图查看未见明显文字裁切/控件重叠；长菜单状态按设计省略并有 tooltip。ChatGPT 提示自动换行且位于 Claude 按钮下方的独立文本区。
- `evidence/synthetic-scenarios.png`：12 个原生 Qt 合成场景，包含单品牌、双品牌、多会话、P1、P2、P3、失联、仅心跳恢复待确认、新活动恢复 P4、显式 coverage 的 P5 和开关关闭。
- 截图使用当前源码 Controller 与 SnapshotScene/窗口直接渲染；冻结包有单独启动、协议和旧 snapshot 模式验证。未声称这些 P1～P5 截图来自真实客户端或冻结 EXE 的新截图命令。

仍待人工：真实 Claude/Codex 同时工作及多个项目会话、真正长授权和正确请求辨识、真实中断与底层进程终止、真实失联/重连与客户端会话恢复、正常原生启动退出、输入焦点/点穿/遮挡、高 DPI 观感、多屏和长期运行。真实 ChatGPT 可靠人工等待/解除/最终失败能力未验证，Work 本地未验收。

可以审核后进入**隔离测试包的桌面体验验收**；不具备据此宣称真实客户端全部通过或正式发布的条件。本轮没有 push、merge master、发布、替换原安装、全局部署或自动连接真实客户端。交付后停止，等待用户审核。

## 本地证据与复现

日志与验收脚本保留在 `.venv/preview-run/v2-integration-20261029/`（忽略目录，不纳入 Git）：`full.log/full.xml`、`focused-final.log/focused-final.xml`、`extra-final.log`、`strict-bundle/report.json`、`frozen-protocol.json`、`launcher-check.json`、`scenario-checks.json` 和三组 DPI `checks.json`。

```powershell
.venv\Scripts\python -m pytest -q -ra --junitxml=.venv/preview-run/v2-integration-20261029/full.xml --basetemp=.venv/preview-run/v2-integration-20261029/full-temp
.venv\Scripts\python tools/check_private.py
.venv\Scripts\python .venv/preview-run/v2-integration-20261029/strict_bundle_check.py
.venv\Scripts\python .venv/preview-run/v2-integration-20261029/frozen_protocol_check.py
.venv\Scripts\python tools/preview_scheduler.py --out .venv/preview-run/v2-integration-20261029/dpi-150 --scale 1.5
```
