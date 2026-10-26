# Shion V2.0 阶段 1：用户级生命周期观察 MVP

日期：2026-10-27（开发开始于 10 月 26 日）。状态：**已完成本轮开发、自动回归和开发包自检；等待真实全局安装确认，未达到阶段 1 全部验收条件。**

本次授权将此前修订方案中的逐项目安装改为当前 Windows 用户的全局安装，并把阶段 1 范围明确为观察 MVP、全局配置管理与现有界面复用。后续复杂调度、Work 云端和 ChatGPT 远程控制不在本次范围。

## 基线与边界

- 开发分支：`feature/v2-phase1-global-observer`。
- 开发起点：`a71a28d9ab48b862923bcd4e4174ada5f72c93f5`；原发布代码 `5c268e5`。
- 开始时已有 `docs/progress.md` 的阶段 0 记录，以及未跟踪的阶段 0 最终报告和修订方案。保留这些文件；本轮提交不包含那两份既有未跟踪文件。
- 不推送、不合并 master、不改发布标签、不生成正式发布。开发构建放在忽略目录，不覆盖现有 `dist` 发布包。
- 不修改真实 Claude 配置、不启动真实 Claude；Claude 实测行为沿用既有验收边界，自动回归另行记录。

## 模块

| 模块 | 实现 |
| --- | --- |
| `shion/events.py` | 七类事件与严格元数据白名单，ID 长度/字符验证，缺失 ID 不猜测 |
| `shion/tasks.py` | 按来源域、会话、轮次追踪；有界终态记录、幂等、过期/断线待确认 |
| `shion/observer.py` | 独立 127.0.0.1 HTTP 端口与凭据，2048 字节请求限制、每秒 200 请求、512 条队列、250ms 读取超时 |
| `shion/codex_mcp.py`、`hooks/codex_observer.py` | stdio MCP 元数据工具；每次转发最多 150ms 网络等待；离线不返回阻断决定 |
| `tools/codex_config.py` | CODEX_HOME 发现、只读审计、精确差异、备份 SHA-256、事务锁、原子替换、并发检查和失败回退 |
| `shion/chatgpt.py` | 观察开关、安装/卸载预览、客户端信任指引、中性提醒 |
| `app/controller/state`、三语资源 | 现有动画与状态面板接入；独立 ChatGPT 管理菜单；Claude 控制路径保留 |
| `tools/benchmark_observer.py` | 无客户端参与的受控元数据性能测试 |

仅新增已获准依赖 `tomlkit==0.13.3`。Python 3.10 没有内置 tomllib，tomlkit 用于校验配置；写入采用末尾新增独立 MCP 表，原 TOML 的每个字节保持。JSON 用语法位置插入，保留原内容、缩进和键顺序；不接受无效 JSON、重复键或 JSONC 注释，遇到此类配置停止而不重写。

## 观察语义与隔离

- ChatGPT 的任务键为 `(chatgpt, codex-local, session_id, turn_id)`；不读取项目路径，跨项目依赖客户端明确的会话/轮次 ID 分离。未知 ID 进入待确认。
- SessionStart 不创建活动轮次；PreToolUse/提交事件可以确认活动，PostToolUse 仅证明工具返回。PermissionRequest 不显示精确人工授权数量。
- Stop 为结果未知的轮次结束；Interrupt 单独显示中断。均不调用 Claude 完成/好感度路径。
- 同轮重复终态不重复提醒，延迟工具事件不能复活终态。每个进程最多保留 1024 个轮次、每轮最多 2048 个幂等键；达到上限保留待确认而不驱逐终态后误判旧事件。
- 全局/项目来源标记冲突进入待确认；同工具事件重复投递计入诊断重复数但不重复计任务。复制全局定义而仍标记 global 时只能检测重复，不能凭空推断其真实文件来源；磁盘层审计提供辅助证据。
- 无活动快照，启动时不会复原历史工作数。300 秒没有可信活动证据后状态待确认；没有协议心跳，无法即时断言客户端进程已退出。
- Claude 工作会话、RemoteHub、授权按钮、反馈、暂停/中断与 ChatGPT ledger 完全分开。ChatGPT 只贡献展示用活动标志。
- 普通提醒两秒内合并；本阶段没有引入全量 P1～P5 调度，也不提供 ChatGPT 人工请求队列。

## 配置审计与正式安装方案

只读实机检查：当前进程未设置 CODEX_HOME，有效用户目录为 `C:\Users\<user>\.codex`。用户 `config.toml` SHA-256 为 `3f28fe3303bc2c23aa7cafde56ba76c06d50a0dc4d0f392c3ef08b2c68d91ea2`，与阶段 0 清理记录相同。现有 `node_repl` MCP、notify 与七项已禁用信任记录保留；用户 hooks.json 不存在。本项目及祖先可发现磁盘配置层未发现其他 Hooks 文件。

安装前精确差异与无密钥审计保存到本地忽略目录：

- `.venv/preview-run/phase1-review/global-install.diff`
- `.venv/preview-run/phase1-review/audit.json`

拟新增独立 `mcp_servers.shion_lifecycle_v1` 和七个 `observe_lifecycle` Hook。仅投影事件名、来源标记、session_id、turn_id 和适用的 tool_use_id。matcher 暂限定阶段 0 已验证的 `Bash|apply_patch`；不宣称覆盖所有工具类型。MCP 启动 5 秒、Hook/工具超时 1 秒。

用户级配置改动前需要本轮用户明确确认该差异。安装后仍由用户通过正常 `/hooks` 逐项审核新定义，不能复用阶段 0 的身份、Trust all 或绕过信任检查。`hooks.state` 从不直接写入或清理。

安装器另在同一用户目录保存 `.shion-lifecycle-v1.json` 作为归属证据，包含原始/安装后配置和哈希；每次事务在 `.shion-backup-<随机 ID>` 备份受影响文件与 journal。它们可能包含原配置中的敏感字段，只留在当前用户配置目录、不得提交/上传，沿用目录的 Windows ACL。只读核验中，目录允许当前用户、SYSTEM、Administrators 完全控制，现有 CodexSandboxUsers 具有可继承的读取权限；本轮不改变这些访问权限，不宣称备份只有单一用户可读。凭据保存在 Shion 当前用户数据目录，不能放进 Codex 配置或日志。

本轮磁盘审计不证明客户端进程的启动参数、选中 profile、远端托管策略或进程 CODEX_HOME 相同。正式安装前需在目标客户端正常配置/Hook 界面核对有效层及策略；不能以文件不存在推断所有托管配置不存在。

## 关闭、卸载、回退

- “临时关闭”只持久化 Shion 自己的接收开关，丢弃观察队列并保留终态去重记录；不改 Codex Hooks、信任、Claude 状态。
- “卸载”先展示差异，仅移除可用归属清单和精确插入片段证明的内容。用户后续新增的无关配置和信任记录保留。片段被修改、重复或归属无法确认时停止，不猜测删除。
- 备份、归属信息可能含用户配置，仅在用户本机保存。卸载保留备份和客户端信任痕迹，并明确说明。
- 写入前检查预览基线，逐文件再次检查，写入后读回校验；失败只回滚仍等于本次写入值的文件，遇到外部变更保留备份并停止。
- 多文件事务不是文件系统级的同时提交；使用锁防止两个 Shion 安装器并发。外部编辑器不遵守该锁，检查与替换之间仍存在极小竞态窗口。正式安装应关闭配置编辑器，避免同时操作客户端信任页。崩溃留下锁/journal 时停止，不自动删除锁或覆盖用户文件；人工审查备份后恢复。
- 代码回退可切回 `master`；安装后应先经卸载流程移除配置，不能只切分支导致全局 MCP 指向不存在的开发代码。不要 reset/清理原有未提交文档。

## 首次安装和会话影响

官方文档说明用户级 Hook 在未信任项目仍会加载，但 Hook 自身必须信任；多来源 Hooks 会共同执行；MCP Hook 使用已有连接，缺失/失败不阻断任务。[Hooks](https://learn.chatgpt.com/docs/hooks)、[配置层](https://learn.chatgpt.com/docs/config-file/config-basic)。这些是机制依据，不替代本轮客户端实测。

首次安装预期操作：审核差异 → 写入全局配置 → 正常客户端 `/hooks` 逐项信任 → `/mcp` 核对连接 → 重启目标客户端 → 新建/重新打开受控会话 → 查看 Shion 实际接收事件。这里建议重启是保守操作流程，尚未证明每种客户端都必须重启；已有会话热加载、新会话、resume 和重启的差异都列入真实验收。

不要求逐项目安装，不要求日常手动启用或切换 AI。仅当前 Windows 用户及客户端确实采用该配置的本地运行模式；不扩展到其他 Windows 用户、WSL、Work 云端。

## 验收记录

本轮自动验证：首批单元和界面集成 **40 passed**；完整回归 **1597 passed、9 skipped、2 warnings，523.35 秒**，日志 `.venv/preview-run/phase1-full.log`。跳过项为原生桌面条件及 Claude 进程链；警告为既有 Pillow 弃用提示。不能把这些自动结果解释为本轮真实 Claude 客户端验收。

性能：10 个合成会话、100 事件/秒持续 60 秒，共 **6000** 个事件，失败 **0**、队列峰值 **11/512**、无降级，HTTP 到 50ms 消费周期的 ledger 更新 **p95 78ms，最大 94ms**。日志 `.venv/preview-run/phase1-performance.json`。这是合成 HTTP/ledger 测量，不是实际 Codex Hook 或 Qt 主线程展示延迟。

最终修正专项 **38 passed（6.26 秒）**，覆盖重复安装保留新信任记录、无效归属清单拒绝、观察/界面和打包契约。开发包 stdio MCP 握手、工具列表、离线中性结果及 tomlkit 许可文件通过。第一次构建未使用现有构建环境过滤，截图自检超时；改用 `tools.build.build_environment()` 干净重建后，最终完整复制目录自检 **97 项通过**。开发产物在 `.venv/preview-run/phase1-bundle/`，不覆盖原 dist、不作正式版本交付。

完整日志（本地忽略目录，不进入 Git）：

| 内容 | 路径 |
| --- | --- |
| 全量回归 | `.venv/preview-run/phase1-full.log` |
| 首批集成 | `.venv/preview-run/phase1-integration.log` |
| 最终专项 | `.venv/preview-run/phase1-final-focused.log` |
| 最终构建 | `.venv/preview-run/phase1-build-final.log` |
| 复制目录 97 项自检 | `.venv/preview-run/phase1-bundle-final.log` 和 `phase1-bundle-final/` |
| 最终打包 MCP | `.venv/preview-run/phase1-packed-mcp-final.log` |
| 一分钟性能 | `.venv/preview-run/phase1-performance.json` |
| 安装前差异/审计 | `.venv/preview-run/phase1-review/` |

本轮真实配置残留：**没有新安装的用户级文件或信任记录**。阶段 0 七项已禁用记录继续原样保留。测试残留均位于项目忽略目录；开发包未注册全局 MCP，也没有启动持续运行的真实客户端验收会话。

真实全局安装尚未执行，以下均不得标为通过：

| 场景 | 本轮状态 |
| --- | --- |
| 本项目 / 无关项目 Codex CLI 真实事件 | 等待安装确认及逐项信任 |
| 两个无关项目并发独立会话 | 合成元数据已测；真实 CLI 待验 |
| 未信任项目加载用户级 Hook | 官方文档支持；本轮真实行为待验 |
| 桌面多个项目 | 阶段 0 有限观察证据；新全局适配未验 |
| 全局与项目级 Hook 共存/重复 | 合成去重与来源冲突已测；客户端待验 |
| 安装后新会话、已有会话、客户端重启 | 待验，不承诺热加载 |
| Shion 离线、重启、开关 | 离线协议/开关隔离自动验证；客户端端到端待验 |
| 卸载后 Codex 与 Claude 正常 | 隔离配置恢复已测；真实客户端待验 |
| Work 本地 | 未验证，不宣称支持 |
| 焦点、高 DPI、动画观感 | 未做本轮真实桌面验收 |

阶段 1 在正式安装确认处暂停，不得将本报告当作全阶段验收完成或正式发布说明。
