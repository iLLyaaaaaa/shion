# Shion V2.0 阶段 0 最终验证报告

日期：2026-10-26。范围：第二次受控实测及方案修订。**本轮已收尾，阶段 0 的完整客户端验收仍未完成；不得据此进入阶段 1。**

## 1. 结论与证据等级

- **真实验证成功（限定能力）**：Windows 本机 Codex CLI 的七类已配置事件均至少收到一次；同会话多轮、两个 CLI 并行、CLI 新进程继承信任、CLI 与桌面任务并行均获得真实元数据证据。
- **真实验证部分成功**：Codex 桌面本地任务获得 SessionStart、PreToolUse、PostToolUse、PermissionRequest、Stop；通过正式桌面插件创建/继续任务，未通过可视设置页操作。四轮均未收到 UserPromptSubmit。不能宣称桌面完整生命周期或 GUI 提交路径已经通过。
- **仅官方文档支持**：Work 本地编排且本地执行的 Hooks；App Server 状态通知、请求解除、已加载线程查询。未建立本机 Work 独立受控会话或无正文的桌面状态订阅。
- **验证失败**：桌面 UI 观察/恢复入口失败；桌面插件 wait_threads 查询失败。它们是测试入口失败，不是 Hooks 不支持的证据。桌面插件提交路径的 UserPromptSubmit 接收检查未通过，原因未确定。
- **尚未验证**：Work 本地全部事件、人工授权解除与精确待处理数量、显式等待输入、最终轮次失败、跨通道同任务去重、客户端恢复旧会话、无响应超时、多个人工请求并发。缺失项详见矩阵。

不读取聊天历史或用已有任务正文推断身份，不使用 Responses API，不升级客户端。没有修改 Shion 业务代码、动画或依赖，没有提交、推送或移动标签。

## 2. 基线、入口与隐私

本机 CLI：`codex-cli 0.164.0-alpha.11.1`。桌面运行包路径：`OpenAI.Codex_26.1021.3705.0_x64__2p2nqsd0c76g0/app/ChatGPT.exe`。包名与 CLI 均不同于旧报告；进程名 ChatGPT.exe 不能作为 Work 身份证明。

开始时 Git 工作区干净，两个目标文件不存在。使用独占创建原样安装已审查草稿：

| 文件 | SHA-256 |
| --- | --- |
| `.codex/config.toml` | `b46b87bf6a196ded356e32df32dc2e54b96594f239e2c2e77b4a056b812689b4` |
| `.codex/hooks.json` | `8e17b561da936519358202dbd7384817be3c193437b75412baa6e6dc8abaeaeb` |
| 原探针 metadata_probe.py | `d24ae3f8bb3898d200727b44c8b2ec2363cab277bb5d7977ff05da0f9ec78525` |

探针保持原样，标准库、stdio、单个 record_metadata 工具。上游投影仅 event/session_id/turn_id/tool_use_id/agent_id；探针追加观察进程 UUID 和接收时间。没有投影 prompt、response、tool_input、tool_response、路径、密钥或聊天历史。工具 matcher 为 Bash|apply_patch；Hook 2 秒、MCP 启动 10 秒、工具 3 秒。不返回授权决定或附加上下文。

CLI 的正常 `/hooks` 界面逐项核对来源、目标、matcher、超时后，逐项信任七个实际测试 Hook。两个 Subagent Hook 未信任、未测试。没有选择 Trust all。`/mcp` 在同一 CLI 中显示探针 connected、1 tool。

默认工具环境启动 CLI 时无法定位 home；指定真实 CODEX_HOME 后外层沙箱拒绝写入客户端运行目录。通过工具正常权限审批启动，未加任何绕过 Hook 信任或 Codex 沙箱的选项。项目受信任状态为 trusted。用户级 notify 存在，未直接写入或替换。

**范围限制实证**：项目级配置会作用于同项目其他会话，不是只绑定测试任务。继续本次主工作会话后也收到旁观元数据。共 56 条记录中，39 条属于明确登记的受控会话，17 条旁观记录排除在验收统计外。没有据此推断 Work 身份。后续实验应缩短启用窗口，并把同项目并行会话纳入隐私告知。

## 3. 测试登记与真实事件数

| 测试来源 | 会话 ID | 场景 |
| --- | --- | --- |
| CLI A | `01a176b0-cf5a-75d1-b3b9-8981ef86ee8d` | A1 纯文字；A2 合成 shell 输出；A3 exit 7；A4 长工具后 Esc |
| CLI B | `01a176b4-cd03-7393-9980-170ac736a8f0` | B1 与 A4 并行纯文字；B2 正常 require_escalated 合成命令 |
| CLI C | `01a1775c-d1eb-7b70-a598-6e08221c4d0e` | C1 重启后长工具、与 D4 并行；C2 探针断开后纯文字 |
| 桌面 D | `01a176bb-3c6e-7fa3-926c-86928536af34` | D1 纯文字；D2 shell；D3 授权前事件与长工具；D4 与 C1 并行纯文字 |

| 事件 | CLI A | CLI B | CLI C | 桌面 D | Work 本地 |
| --- | ---: | ---: | ---: | ---: | --- |
| SessionStart | 1 | 1 | 1 | 1 | 尚未验证 |
| UserPromptSubmit | 4 | 2 | 1 | 0 | 尚未验证 |
| PreToolUse | 3 | 1 | 1 | 3 | 尚未验证 |
| PostToolUse | 2 | 1 | 1 | 3 | 尚未验证 |
| PermissionRequest | 0 | 1 | 0 | 1 | 尚未验证 |
| Stop | 3 | 2 | 1 | 4 | 尚未验证 |
| Interrupt | 1 | 0 | 0 | 0（未触发测试） | 尚未验证 |
| 请求解除 / 显式输入等待 / 整轮失败 | 未建立证据 | 未建立证据 | 未建立证据 | 未建立证据 | 尚未验证 |

C2 时探针已断开，客户端显示 Hook failed，但仍输出合成结果并正常结束；因此 C2 不在接收事件计数内。测试从未要求模型手工调用 record_metadata；可信度来自已知任务 ID、操作顺序、CLI Hook 状态和元数据关联，不是仅凭日志文件存在。

## 4. CLI 结果与语义限制

1. session_id 在同一 CLI 多轮保持不变，turn_id 各轮不同；正常工具前后 tool_use_id 配对。三个 CLI 进程得到不同会话 ID。observer_instance 仅表示探针进程，不能替代会话或运行时身份。
2. A3 的非零退出工具仍收到 PostToolUse，随后收到 Stop。探针未投影错误结果，不能从这两个事件推导整轮失败或成功。
3. A4 按 Esc 后收到 Interrupt；CLI 同时显示后台终端仍在运行。中断回合不等于终止工具进程，不得据此显示“所有进程已停止”。缺失 PostToolUse 不能永久保留 active 状态，应在轮次中断时结束该轮活动、另存工具未确认状态。
4. B2 发出 PermissionRequest 后执行完成，未出现人工确认界面。该事件证明进入授权检查路径，不能证明正在等人。当前投影没有 request_id，也无独立解除事件，不能准确计算未决授权总数。
5. A4 进行时 B1 启动并结束，两个 ID 独立；B1 的 Stop 不会在证据中结束 A4。这里验证的是原始事件可区分，并未实现或验证 Shion 多任务状态机。
6. 第二/第三个 CLI 启动继承已信任七项，只有未信任的两个 Subagent 定义继续提示审核。重启新会话后重新收到事件；未验证 resume 原会话。
7. CLI C 专属探针断开后，C2 约 2 秒完成，前后 Hook 报错。只证明该断连场景 fail-open；未测试死锁、持续无响应、慢磁盘或高负载，不宣称零延迟或全面容错。

## 5. 桌面端与 Work

桌面窗口最初最小化，随后可访问性树仅见框架按钮；捕获未提供可用设置页，Raise 返回 failed to activate captured window。用户通过手机远程，无法补做现场设置操作。因此没有猜测设置菜单、重启整个客户端或绕过信任。

改用已连接的正式 codex-app-tools 插件，在精确项目的 local 环境创建 D，并发送合成后续轮次。创建返回的 threadId 与 Hook session_id 相同。桌面 MCP 探针实例与 CLI 不同；D 收到五类事件，证明此桌面管理的本地任务真实投递，不能归因于 CLI 成功。

CLI 信任后新建 D 无须另一次信任或客户端重启即可收到事件。D 四轮均未收到 UserPromptSubmit：这只限定于插件创建/发送消息路径；普通桌面输入框提交是否相同尚未验证。D1/D4 纯文字只有结束证据，不能及时知道其开始。D3 收到 PermissionRequest 和随后工具完成，但未观察人工授权界面或解除事件。

C1 的 PreToolUse 为 16:39:07（北京时间），D4 Stop 为 16:39:08，C1 PostToolUse 为 16:39:29、Stop 为 16:39:32，形成 CLI/桌面重叠活动证据。D 的 session_id 不变、四个 turn_id 独立。尚未让同一任务经两个事件通道同时上报；没有验证跨通道去重。

**Work 本地未验证**：现有桌面插件创建接口只明确提供本地项目任务和 Work Cloud 目标，没有可独立选取/核实的 Work 本地入口；UI 不可操作。没有使用云端目标替代本地，也没有把当前工作会话、ChatGPT.exe 或共享包身份当作 Work 证据。Work 与 Codex 是否共享同一任务 ID，继续列为门槛。

## 6. 恢复、快照和支持等级

[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)提供 thread/status/changed、thread/loaded/list、serverRequest/resolved。loaded 不是 active；resolved 不是批准。尚未找到并验证可在严格元数据边界内附着到这些实际客户端的恢复通道。未调用广泛的 thread/list/read 或读取会话日志补状态。一次对精确合成任务的 wait_threads 调用失败，不能作为快照能力验证。

| 目标能力 | CLI | 桌面本地（插件路径） | Work 本地 |
| --- | --- | --- | --- |
| 任务开始、工作中、工具调用 | 部分：提交/工具可观察，无持续心跳 | 部分：工具可观察，纯文字开始缺失 | 未验证 |
| 人工授权提醒、等待输入 | 部分：授权前事件；人工状态未证明 | 同左 | 未验证 |
| 回合结束 | Stop 已验证，结果语义有限 | Stop 已验证，结果语义有限 | 未验证 |
| 失败 / 中断 | 中断事件已验证；整轮失败未验证 | 均未完成验证 | 未验证 |
| 多会话、新任务自动接收 | CLI 并行与新进程已验证 | 新任务、跨 CLI 并行已验证 | 未验证 |
| Shion 中途启动、历史任务恢复 | 无可靠快照，不承诺完整恢复 | 同左 | 未验证 |

39 条受控记录的事件语义键没有重复；这不是重复投递容错测试。主动重复 Hook、多个人工授权、Work 并发、同任务多通道、无响应测试及客户端恢复旧任务仍未验证。没有用合成回放冒充真实客户端成功。

## 7. 清理与剩余风险

已通过正常 `/hooks` 逐项关闭七个已信任 Hook，界面 Active 均为 0；用户级配置中对应七项均为 enabled=false。两项 Subagent 从未信任。CLI C 用 `/quit` 正常退出；A/B 工具终端会话在中途暂停后已失效，后续未发现其探针，不宣称观察到了它们的正常退出事件。D 已通过正式插件归档，未删除测试会话历史；归档不等于立即卸载内存线程。随后只终止精确脚本路径匹配的探针进程，未结束桌面客户端或无关任务。

两个项目配置删除前 SHA-256 与安装清单一致，已经删除。`codex mcp get shion_phase0_probe --json` 返回 No MCP server named。信任痕迹仍存在：七项来源定位键、trusted_hash 和 enabled=false 留在用户级 config.toml。它们当前禁用且源文件不存在；若将来重新安装相同定义，仍应检查启用/信任状态。**这不是彻底删除所有信任痕迹。**

最终进程核验：精确探针脚本路径匹配的 Python 进程为 0；清理后的两次元数据核对均为 56 条，没有继续增长，所有记录字段均在允许列表内。新 CLI 配置查询已不发现探针；没有声称已逐个检查所有桌面内存缓存列表。`git diff --check` 和新增文档空白检查通过。

用户级 config.toml 基线 SHA-256：`4ac849c02957ceb3753d78f7781a4028f3c9c15aa4638fb0d5cf406d66cdcb2c`；清理时：`3f28fe3303bc2c23aa7cafde56ba76c06d50a0dc4d0f392c3ef08b2c68d91ea2`。文件由正常信任/禁用流程更新，未直接编辑。基线只保存整体哈希和少量结构信息，没有保存原文或各键语义哈希，故不能独立证明 notify/所有第三方条目逐键等价；不能声称用户配置整体恢复原样。未发现需要覆盖配置的理由，保留现场而不回滚整个用户文件。

用户级 hooks.json 的不存在状态，以及用户级 Claude settings.json、项目 Claude settings.json/settings.local.json 的哈希与基线一致。收尾写文档前全部 Git 跟踪文件哈希相同、工作区干净；最终仅本报告、修订方案和 progress 文档变更。未运行全量业务测试：本轮没有业务代码变更，CLI 实测不等于 Shion 回归验收。

## 8. 证据与后续门槛

本地、不入库的元数据证据：`.venv/preview-run/phase0-round2-20261026/` 下 baseline.json、installation.json、controlled-events.json、evidence-summary.json、cleanup.json、final-verification.json；原探针事件保存在上轮目录 evidence/，报告统计严格限定登记 ID。原 READOUT.md 与 CONTROLLED-REPORT.md 保留作为历史记录。

官方机制依据：[Hooks](https://learn.chatgpt.com/docs/hooks)、[App Server](https://learn.chatgpt.com/docs/app-server)、[Work 本地与云端边界](https://learn.chatgpt.com/docs/enterprise/cloud-local-access)。这些文档不替代本次客户端证据。

下一次阶段 0 补测应优先解决：普通桌面输入路径、Work 本地入口、明确人工请求与解除、精确快照、同任务双通道去重。若无法取得这些能力，可以审批“部分观察支持”方案，但必须明确降级，不能把完整验收门槛自动取消。当前停止，不进入阶段 1。
