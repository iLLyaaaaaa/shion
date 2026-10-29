# 阶段 1 最后一轮针对性验收（2026-10-29，进行中）

阶段 1 暂不宣布完成。本轮仅诊断、自动受控测试与记录，不修改产品代码；保持当前全局安装、信任记录及 Token。不安装、卸载、改 ACL、提交、push、合并、发布或进入阶段 2/3。用户参与的测试一次只安排一个。

本记录补充 [此前续验报告](shion-v2-phase1-real-install.md)，保留其历史结果和失败边界。当前仍等待最新开发包的桌面人工测试，不将 CLI 结果外推到桌面。

## Observer 异常退出诊断

此前受控样本：预热 Stop 后结束测试专属 Observer，原客户端下一轮 Submit/Pre/Post/Stop 四 Hook 均 failed（客户端 durationMs=0），Shell 与轮次仍完成；GUI 没收到该轮事件。保持 GUI 不重启，新建 CLI 会话能恢复投递。

[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks) 明确：MCP Hook 使用既有连接，不启动或重连服务器；服务器缺失、工具不可用或执行错误不阻止原操作。结合上述样本，首要故障点判断为原客户端持有的 stdio MCP 连接没有恢复，而非 GUI 接收端整体不可用。这是文档、故障注入顺序与实际结果共同支持的诊断；没有读取客户端异常正文，不能给出更底层错误码或断言所有客户端版本均不能恢复。

Shion 的 `codex_mcp.forward()` 每次独立建立 HTTP 连接，HTTP 失败也中性返回；`ChatGPTConnection.poll()` 只处理收到的事件和接收队列降级，没有 Observer 进程存活心跳，也不负责重建客户端拥有的 stdio 管道。因此重启 GUI不能据此保证恢复原客户端 MCP 连接。

[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server) 提供 `config/mcpServer/reload`，说明可重新读取配置并为已加载线程排队刷新；本机已有 schema 也包含该方法。本轮没有调用它，也未验证桌面 UI 是否暴露对应操作，不能把它列为已通过的原会话恢复办法。已实测的降级方式仍是新建独立 CLI 会话。

状态风险已用默认生产 `TaskLedger` 和隔离单调时钟验证：最后活动事件后 299.999 秒仍为 working=1；300 秒起 working=0、pending=true、state=uncertain，3600 秒仍不恢复工作。GUI 控制器每次 tick 取该 working 值。故无新事件且 GUI 正常轮询时，逻辑不会无限保持工作，但可能在近五分钟内继续显示先前活动；到期只转待确认，不补造 Stop/Interrupt，也没有专门的断连弹出提示。GUI 卡死、真实活动中断连及真实经过 300 秒的画面仍未验收。

为避免只看源码，本轮只读提取了当前 EXE 内的四个 Python 模块，与当前源码编译后的代码对象比较（仅归一化文件名）：`shion.tasks`、`shion.chatgpt`、`shion.codex_mcp`、`shion.controller` 均一致。隔离时钟仍不是一次真实桌面视觉测试。

候选最小修复方案，仅供审批，未实施：

- 原会话恢复首先应在隔离客户端验证官方 MCP 刷新入口；不改 Hook 定义、信任或 Token，也不声称 Shion 自行重启一个进程就能接回原 stdio 连接。
- 若验收要求及时消除失联后旧“工作中”，需要 Observer 存活租约：只用现有随机 Observer ID 和接收端时间，向独立观察通道发送有界心跳；租约失效将其非终态轮次转为“观察失联，状态待确认”，保留 300 秒兜底。不得据此结束 Codex 任务、宣称任务完成、采集参数/正文或影响 Claude。
- 预计涉及 `codex_mcp.py`、`observer.py`、`tasks.py`、`chatgpt.py`、三语提示及相关测试；覆盖长时间静默工具、单次超时、多个 Observer 隔离、恢复与终态去重，并重测额外开销。仅缩短 TTL 会把正常静默工作误判为失联，不能作为可靠修复。本轮不选择心跳频率、不写代码、不重建替换开发包，等待用户批准。

## 当前安装只读审计

- `D:\desktop\tools\Shion-dev` 的 228 个文件与 `dist/Shion` 逐文件一致；EXE SHA-256 为 `6e64fa0e8a1e3ee828ba42cc0a0fe52a1fd1323f3d512d47c319d9eb43329068`。GUI PID 5240 保持运行，监听 127.0.0.1:47613/47614。
- 有效 CODEX_HOME 为 `C:\Users\<user>\.codex`。MCP 精确定义、七个各唯一且无 matcher 的 Hook 均符合 v3 归属定义。payload 仍仅事件、来源、会话/轮次/工具调用 ID。
- 14 项信任记录：七项 disabled，七项有 trusted_hash 且未禁用。未独立复算官方信任哈希算法；本轮五类正常 Hook 的实际成功提供执行证据，但不替代其余事件的触发验收。
- 归属记录 v3 结构与定义校验通过；WAL、实际锁路径及三个原子替换暂存路径均不存在。只读卸载预览可生成三项变更，没有应用变更。
- config SHA-256 为 `389242487ef9cab3fabb15d59c5b8b9c7b47860d812b9180edb1efb60f52b811`，与此前 `83217ad7…62b6a92` 再次不同。原因未知；本轮测试前后字节哈希稳定，不推测、不修复、不还原。
- hooks.json SHA-256 仍为 `3e4929662ae33d43fc0d39b861dd1b788378b2da496e37c1d0c0acaf619c1d03`。本轮 config、Hooks、归属及观察设置文件前后哈希均相同；没有创建或轮换 Token，没有输出 Token 值。
- 原 GUI 和检查前已有的三个 Observer（8612、48400、54748）均保留；多个 Observer 本身不等于泄漏，本轮不推测其全部会话归属，也不擅自清理。

证据位于 `build/final-acceptance-20261029/readonly-audit.json`、`post-test-hashes.json`、`runtime-after.json`、`packaged-code-comparison.json`、`stale-clock.json`。这些文件只保留结构、哈希、进程/事件元数据。

## 正常同步 Hook 延迟补样

条件：同一 Windows 用户、现有完整开发包及正式全局配置，GUI 接收端开启。独立 ephemeral app-server 会话，项目根目录，十轮顺序任务；每轮仅一条无文件读写的 `Write-Output`，无故障注入、无人为授权等待。统计正式 `hook/completed.durationMs`，executionMode 均为 sync；不保存客户端正文、工具参数或结果正文。

新会话 `01a184f9-2144-77e3-8304-9f70c4160361`：十轮各一条 Shell，均 completed/exit_code=0；41 次 Hook 全部 completed。P95 使用 nearest-rank，即排序后第 ceil(0.95*n) 项。

| 样本 | 次数 | 中位数 | P95 | 最大值 |
|---|---:|---:|---:|---:|
| 原五轮（保留） | 21 | 9 ms | 32 ms | 34 ms |
| 本次十轮 | 41 | 21 ms | 34 ms | 36 ms |
| 描述性合计 | 62 | 15 ms | 34 ms | 36 ms |

本次分事件：SessionStart 1 次；Submit/Pre/Post/Stop 各 10 次。未包含 PermissionRequest、Interrupt、故障 Hook、模型时间、桌面输入延迟或冷启动整轮时间。两个时段中位数有差异，不能据此断言长期稳定或性能退化。两个现有项目的独立样本不混入此性能组。

首次在受限执行环境尝试启动 app-server 立即退出，未取得任何 Hook，不计正常延迟。随后经正常自动审批运行同一受控测试，未绕过审批。原失败元数据另存。证据为 `result-hook-timing-additional.json`、`timing-summary.json`、`result-hook-timing-sandbox-start-failed.json`。

## 两个现有独立项目

从桌面项目目录取得 `claude pet` 与 `world-execute-me` 两个已有 Git 项目；读取适用规则后，仅在各项目根目录启动一次独立 ephemeral app-server CLI 会话，顺序执行单条安全 Shell，无文件读写或修改。两个项目可发现的 Shion 配置都只有相同用户级 config.toml/hooks.json，没有项目级 Shion 定义。

| 项目 | 完整会话 ID | 完整轮次 ID | 实际结果 |
|---|---|---|---|
| `D:\desktop\work\claude pet` | `01a184fd-1029-7eb1-8e29-0707cdb21c58` | `01a184fd-1228-71a2-b6c0-84e38e195b8e` | 五 Hook completed，唯一 Shell completed/exit 0 |
| `D:\desktop\work\world-execute-me` | `01a184fd-4087-7b23-84a7-53a7c62357d1` | `01a184fd-428a-7350-814f-856f8113d89e` | 五 Hook completed，唯一 Shell completed/exit 0 |

GUI 实收两组 Start/Submit/Pre/Post/Stop：08:09:03–08:09:11 和 08:09:15–08:09:23（北京时间）。两个完整会话和轮次 ID 均不同，但 GUI 现有前八位显示均为 `01a184fd`。归因采用受控客户端完整 ID、执行顺序及接收时间线，不靠短 ID 单独证明隔离。

以这两个实际完整 ID 向隔离生产 TaskLedger 回放 Submit A、Submit B、Stop A、Stop B，活动数为 1→2→1→0；Stop A 后 B 保持 working。此为独立逻辑核验，不冒充已读取真实 GUI 内存中的任务表。当前通过两个真实项目的顺序全局投递；两个现有项目同时运行时的界面辨别仍需补验。

证据为 `existing-project-layers.json`、两个 `result-existing-*.json`、`existing-project-summary.json`。

## 当前验收矩阵

| 项目 | 当前判定 | 对正式验收的影响 |
|---|---|---|
| CLI 五类基础事件、已有 GUI/Claude 隔离 | 保留此前通过；本轮正常样本也通过 | 不重复扩大结论 |
| 最新完整开发包、MCP/七 Hook/v3 归属 | 只读一致性通过，信任哈希算法未独立复算 | 未触发事件仍要实测 |
| 原会话 Observer 退出后观察恢复 | 已知限制；此前下一轮未恢复 | 仍阻止声称自动恢复通过 |
| 活动中失联后的错误工作状态 | 隔离逻辑有界于 300 秒；真实故障视觉待验 | 五分钟残留窗口、即时失联提示仍待决定 |
| 最新包 Windows 桌面真实生命周期 | 待本轮人工验收 | 阻止桌面完整验收 |
| 两个现有项目用户级全局投递 | 顺序真实任务通过 | 并发 GUI 辨别仍未补；短 ID 碰撞是显示限制 |
| 人工授权等待、批准/拒绝、恢复提示 | 未验证 | 阻止人工等待体验验收；自动审批不能代替 |
| 人工桌面中断 | 未验证 | 不能用此前协议 Interrupt 代替按钮验收 |
| 工具进程是否被及时终止 | 此前证据不足 | 与 Shion 是否收到 Interrupt 分开判断 |
| 正常 Hook 延迟 | 增至 62 次，分组保留 | 本机小样本，不宣布长期性能完成 |
| 无 matcher 工具覆盖 | 保留 Shell/apply_patch/MCP 的受控证据 | 不增采参数；未暴露/未触发的工具不伪造覆盖 |
| 配置整体哈希历史变化 | 原因未知，本轮前后稳定 | 保留未知，不自动还原配置 |
| 真实卸载/用户目录恢复 | 本轮禁止执行，保持未验证 | 如原门槛仍要求此项，须另获授权，不能以预览代替 |

## 唯一待用户参与的测试：最新包桌面普通任务

保持当前 GUI 和全局安装不动。待本聊天回复结束、没有其他 Codex/Claude 任务活动时，在 Windows Codex 桌面端选择 `claude pet` 项目，新建一个本地聊天，用输入框提交下面这一个安全任务：

> 这是 Shion 桌面生命周期验收。不要读写文件，不修改配置，不额外调用工具或 observe_lifecycle。只调用一次本地 Shell 执行 `Start-Sleep -Seconds 12; Write-Output SHION_DESKTOP_FINAL_1`，完成后简短结束。

预期：实际收到 Submit 或 Pre 后应进入工作；12 秒等待期间保持工作；收到 Stop 后该轮归零。是否在文字提交时立即进入工作需以实际收到的 Submit 判断，不能提前假定桌面支持或发出了该事件。此任务不主动请求人工授权，也不触发 Interrupt；这两项记为本场景未触发。SessionStart/Submit/Pre/Post/Stop 的接收情况随后从元数据逐项核对。单次缺失事件先记未收到、原因未定，不直接标为客户端不支持。

需要反馈：开始与结束时间（尽量到秒）；等待期间是否持续工作；结束后活动轮次数；是否出现结束提示/卡住。若可取得新聊天链接或完整 ID，一并提供；不提供聊天正文、工具参数、Token 或授权敏感内容。若完整 ID 无法取得，结合时间线归因，并保留不能证明的边界。

本场景反馈完成前不安排下一个人工场景。产品修复方案与其批准也不和本场景混为同一请求。
