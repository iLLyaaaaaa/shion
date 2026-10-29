# 阶段 1：v3 真实安装与客户端验收（截至 2026-10-29）

本轮用户明确授权指定哈希的单次全局安装及阶段 1 验收。结果为部分通过，阶段 1 未完成验收；不 push、合并、发布或进入后续阶段。

2026-10-29 最后针对性验收已另建 [进行中记录](shion-v2-phase1-final-acceptance.md)：保留本报告原始证据，新增只读诊断、41 次正常 Hook 补样及两个现有项目的顺序真实任务；最新包桌面、人工授权与人工中断仍待逐项验收。现有全局安装、信任和 Token 不变，未改产品代码。

## 最新验收结论（2026-10-29 收尾）

本节汇总最新状态；后文保留各时点的原始记录，包括当时尚未验证、后续已经补验的项目，不将早期失败改写为成功。用户已确认最后一次工具执行中 Interrupt 后活动轮次 0、无异常。此次在现有范围内收尾，保留当前安装供继续体验，不宣称全部门槛通过；未额外执行真实卸载或改动全局定义、信任/ACL。

| 项目 | 判定 | 实际证据与边界 |
|---|---|---|
| CLI 基础与 GUI 视觉 | 通过 | 真实 Start/Submit/Pre/Post/Stop；用户反馈进入工作、结束归零并有提示；后续新包重连/开关也已确认 0、无异常 |
| Windows 桌面基础视觉 | 通过，范围有限 | 用户受控桌面样本事件数 19→24、工作 1→0、有提示；发生在 PermissionRequest 修复前，不替代新包桌面全事件重测 |
| 用户级跨目录和多 CLI | 通过，范围有限 | 两个并行 fixture 目录各自独立会话与轮次、完整事件及退出 0；尚非两个现有独立用户项目 |
| 无 matcher：Shell/apply_patch/MCP | 通过 | 三个单工具成功样本有实际执行与前后事件；MCP 根目录复测成功。Windows PowerShell Shell 不等于独立 Bash 工具 |
| 其他工具 | 未验证/不适用 | 当前测试入口未暴露 update_plan；独立 Bash 未验；不将不存在的工具算作 Hook 失败或虚构覆盖 |
| PermissionRequest 修复 | 自动审批路径通过 | 真机权限事件期间保持工作；人工长等待、手动批准/拒绝及附加提示视觉未验证 |
| Interrupt | 观察及视觉通过，工具终止未验证 | 工具实际运行时，官方接口中断轮次、GUI 收到 Interrupt；用户确认归零无异常。不能证明 PowerShell 及时被终止，不等同于桌面按钮验收 |
| Claude/ChatGPT 前台并行 | 通过，单个关键样本 | Codex 结束时 Claude 仍活动，ChatGPT 归零、诗音继续工作，元数据时间线一致；早期后台/拒绝休眠样本无效 |
| GUI 关闭、重启、关闭/开启联动 | 通过 | 离线工具放行；GUI 重启恢复五类事件；关闭停止投递而工具仍完成，重开恢复投递并归零 |
| Observer 异常退出 | 放行通过，同会话恢复未通过该样本 | 后续四 Hook failed 而 Shell 退出 0；同会话所测下一轮未恢复投递；新开 CLI 恢复，GUI 无须重启 |
| 单次 MCP 无响应/超时 | 放行、后续投递及视觉通过 | Submit 1006 ms 后 failed，进程恢复后 Pre/Post/Stop 成功，Shell 退出 0、用户反馈归零无异常；MCP/Hook 均 1 秒，无法区分先触发层 |
| 同步 Hook 性能 | 本机小样本通过 | 五轮 21 次：中位数 9 ms、P95 32 ms、最大 34 ms；每轮四 Hook 累计中位数 54 ms；不是最坏负载或桌面输入延迟上限 |
| 资源 | 部分验证 | Observer 工作集快照 17.70–22.92 MiB、累计 CPU 0.203–1.078 秒；未做峰值/长期泄漏验收 |
| 安装、卸载及恢复 | 安装通过，真实卸载/恢复未验证 | v3 真实安装有事务证据；当前只读卸载预览三项变更通过，不执行真实卸载；隔离崩溃压力不是用户目录恢复验收 |

只读收尾核查（07:53，北京时间）：

- 开发包 228 文件与 dist/Shion 逐文件 SHA-256 一致，EXE 为 `6e64fa0e8a1e3ee828ba42cc0a0fe52a1fd1323f3d512d47c319d9eb43329068`。
- 当前 config SHA-256：`83217ad791819b1fea91be2157fb5d0018ca25c2272716c0d90dc192c62b6a92`；TOML 有效，Shion MCP 与归属定义精确一致，node_repl、notify 存在且未输出字段值。本轮各测试前后哈希相同；与早期信任完成时哈希不同，变化原因没有足够证据确认。不宣称全部无关配置字节与最早记录一致，也不强制还原。
- hooks.json SHA-256：`3e4929662ae33d43fc0d39b861dd1b788378b2da496e37c1d0c0acaf619c1d03`，七个事件均无 matcher，定义与 v3 归属精确一致；14 项信任记录中七项禁用、七项有 trusted_hash 且未禁用。本轮未重写信任，初次信任经官方逐项审核。
- GUI PID 5240 持有 127.0.0.1:47613/47614；日常 Observer PID 8612 存活，测试 Observer 已清理。ChatGPT 通道仍只观察，没有接入 Claude 控制路径；本轮日志/证据仅元数据。
- 独立 Token 文件存在、观察开启；本轮没有创建/轮换 Token，测试前后观察设置字节哈希相同，Token 值未输出或记录。
- 实际保留：用户 config.toml 中 Shion 段、用户 hooks.json、APPDATA/Shion 的 v3 归属记录和独立观察设置、日常 shion.log；开发包备份 `D:\desktop\tools\Shion-dev-before-permission-20261028`，以及忽略目录中的测试脚本、元数据和 fixture 文件。没有自动删除证据或无关文件。
- 安装 WAL、锁和三个预期文件暂存路径均不存在；开发包替换暂存目录也不存在。只读卸载预览通过，仍是预览，不算实际卸载恢复。

收尾证据：`build/cli-diagnostic-20261028/final-acceptance-audit-20261029.json`、各 result JSON 和本报告后续原始时间线。本轮没有重新运行完整源码测试，因为续验未改产品代码；已授权修复此前全量 1656 passed、9 skipped，包 97 项自检通过，当前 228 文件一致。本轮文档检查通过；工作区及原有未跟踪文件保留，未 commit/push/merge/release。

问题与下一步建议：优先只读查明整体配置哈希变化来源；选择第二个明确的现有项目补全跨项目证据；再按受控桌面新聊天补新包桌面全事件及可用人工审批路径。Observer 意外退出的已验证降级方式为新开 CLI；是否提供明确断连提示或自动恢复须先审核方案，不擅自改变定义。若要验证工具终止，另以真实进程句柄连续计时；实际卸载/恢复需要解除当前禁止改全局配置的范围限制后再安排。活动任务中途断连及 TTL 过期也仍未实测。本轮到此停止，等待用户审核，不进入阶段 2/3。

## 以下为按时间保留的安装与验收原始记录

## 安装与信任

- 安装前 config SHA-256：fce7048914bdeaae6b9ccc0e9346e7c99235d67169d4254f3313815fb4eafdb1。
- 安装后立即核验：5f5f070efd7e151c909110a40557483fd49b982395723433676c6a918cbc5e76。
- hooks.json：3e4929662ae33d43fc0d39b861dd1b788378b2da496e37c1d0c0acaf619c1d03。
- EXE：884b51d8f582aa72f99c0a1786c7d248bd871807a5a97f9d303a622a0eb1f96d。
- 现有 v3 apply_plan 正常取得独占锁并完成，186.578 ms；原配置字节和 ACL 指纹保留；无事务残留。该时间不是 Hook 延迟。
- PID 11604 pythonw 仍存在但命令行不可见；无活动事务证据。按用户本轮明确许可记录不确定性后继续，未终止该进程。
- CLI 0.165.0-alpha.1.2 官方 Hooks 浏览器逐项审核七项来源、MCP、工具及超时并信任，未 Trust all、未绕过、未直接改信任记录。PreToolUse 在键盘导航中曾被关闭，随后在同一官方界面恢复开启。
- /mcp 显示 shion_lifecycle_v1 connected，1 tool。七项均在 UI 显示 Active。共 14 个 trusted_hash：七项历史 enabled=false；新七项中一项显式 enabled=true，六项省略 enabled。
- 官方信任操作后 config SHA-256：5595559db6ec5965f53bd201adf06b825673413bcb682a176b5275da70ac41a1。此值不同于纯安装后哈希，记录为官方信任操作后的状态。

## 真实测试

使用正式用户级定义、正式打包 MCP 与生产 ObservationServer 类作为受控接收端。测试没有运行桌宠 GUI；不得将接收端测试当成界面验收。CLI 使用 ephemeral，输出直接丢弃；本地证据仅保存事件类型、ID、来源和时间等元数据。

- 初次真实 CLI：退出 0，收到 SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop 各一条，ID 正确对应。总进程时间 32.922 秒。
- 两个独立验收目录并行：两个进程均退出 0、无测试超时，各自创建测试文件；每会话 Start/Submit/Stop 各一条，Pre/Post 各三条，两个不同会话和轮次。共 52.093 秒。目录是项目内两个测试 fixture，不是两个已有用户仓库。
- 无 matcher：实测存在工具事件。但批准的 payload 不含工具名，未读取工具参数或输出，不能将每条事件精确归因于 Bash、apply_patch、MCP 或其他工具。文件创建是执行证据，不等于逐工具事件归因。
- 接收服务离线：CLI 仍创建测试文件，退出 0，无测试超时，32.500 秒。
- 接收服务重启后：再次收到五类事件各一条，退出 0，无测试超时，32.234 秒。证明接收端重连，不代表桌宠 GUI 重启表现。
- 两个实际 Observer 进程瞬时工作集为 22888448 / 24150016 字节；累计 CPU 约 0.234 / 0.219 秒。不是峰值、持续采样或 Hook 附加延迟。

## 未通过验收门槛的项目

未验证：PermissionRequest、Interrupt；Bash/apply_patch/MCP 逐工具归因；两个已有项目；Windows 桌面真实提交与工具事件；Claude 与 ChatGPT 并行界面隔离；桌宠 GUI 关闭/重启、联动开关；人为 MCP 超时/Observer 异常；Hook 附加延迟；实际卸载及故障恢复。

桌面和 Claude 验收已请求用户配合，报告生成时尚无回复。没有读取已有聊天正文或历史。卸载只生成只读计划，三项变更通过归属/语义校验，未实际卸载，不算恢复验收通过。

## 最终状态与建议

保留已安装定义、v3 归属记录、七项新信任及七项旧禁用记录，独立 Token 已由首次接收服务启动创建。Token 内容不记录。本轮测试 CLI 和接收服务已结束，不宣称桌宠已常驻运行。

未观察到持续超时、错误权限或配置异常，未触发紧急禁用条件。安全边界仅证明本轮 CLI 接收端离线时能继续执行；不能推广到所有客户端故障。下一步优先补桌面/Claude 人工配合、精确且不扩展隐私字段的逐工具验收与附加延迟测量，再评估完整验收。

本地忽略目录 build/real-install-v3-20261028 保存安装脚本和元数据结果，不保存原配置全文、Token 或客户端正文；测试 fixture 文件留作证据。不 commit，等待用户审核。

## 2026-10-28 PermissionRequest 真机问题与修复（待重测）

用户确认 CLI GUI 视觉联动：事件 12→17，工作姿态正常、活动轮次 1→0、有结束提示；桌面端同类测试 19→24，活动轮次 1→0、有结束提示。以上为用户真机反馈；计数不能证明每条事件类型。

并行场景未完成验收：用户报告 Codex 结束后诗音退出工作，Claude 后台命令结束后再进入工作。只读日志元数据为 17:11:12 working、17:11:14 tool_done、17:11:20 Claude stop、17:11:47 ChatGPT 结束、17:12:15 Claude prompt。支持 Claude 先结束前台轮次的解释，不证明通道覆盖。检查到的当天日志中，17:10 前未见 Claude 事件，因此该时间段不计作 Claude 隔离验收。

用户随后转述 Claude 的 PermissionRequest 首次真机结果：授权期间及批准后掉出工作，PostToolUse 后恢复，判为未通过。源码隔离复现同样为 working 1→0→1→0；与前述后台并行现象分开记录。

经用户明确批准修复并重建替换：PermissionRequest 只设置 permission_unknown，保留已有活动状态；无此前活动时不凭空转 working。接收新事件前先处理 TTL，避免迟到权限事件刷新过期工作；Stop、Interrupt、断连和 300 秒过期保持原语义。三语状态菜单附加“授权结果待确认”，不推测已同意或拒绝。GUI 接收端 INFO 只记录已校验事件类型及会话/轮次 ID 前八位，日志异常不阻断处理；短 ID 仅辅助诊断，不能作为唯一归属证据。

定向状态/观察/UI 回归 110 passed；补充 GUI 权限姿态及提示测试后正在全量回归。新开发包构建和替换状态以本次交付记录为准。未修改全局 MCP、Hooks、信任或 Token；未 push/merge/release。修复后的 PermissionRequest 真机重测仍待用户完成。

### 修复自动验证与替换准备结果

独立后台全量回归：1656 passed、9 skipped、2 个既有 Pillow 弃用警告，540.31 秒。旧中断运行不计通过。新包 228 文件、97 项自检通过；EXE SHA-256 为 6e64fa0e8a1e3ee828ba42cc0a0fe52a1fd1323f3d512d47c319d9eb43329068。

后台替换器已复制并逐文件校验新包，当前 waiting_for_client_exit；报告时仍有 PID 28036、65120 使用旧包，故尚未替换。退出后将再检查路径、旧包哈希、无活动进程及新包完整性，保留旧目录 D:\desktop\tools\Shion-dev-before-permission-20261028 后替换；状态结果位于 build/permission-replacement/status.json。程序最多等待 30 分钟；超时或未知状态停止，不强制结束进程。

### 替换完成后的只读核验

后台替换状态 complete；228 个文件与 dist/Shion 逐文件 SHA-256 清单一致。当前 Shion-dev EXE SHA-256：6e64fa0e8a1e3ee828ba42cc0a0fe52a1fd1323f3d512d47c319d9eb43329068。备份目录存在，旧 EXE SHA-256 与原授权包 884b51d8…1f96d 一致，暂存目录已移走。

MCP 定义与 Hooks 哈希保持预期；14 项信任记录中七项禁用、七项信任且未禁用；Token 文件存在，未读取其值；无安装 WAL/锁。重新打开 Codex 后新路径 Observer PID 33576 已运行；GUI 尚未运行，47613/47614 未监听。PermissionRequest 真机复测待 GUI 启动后进行，自动回归不能替代人工验收。未 commit/push/merge/release。

### 修复后 PermissionRequest 真机重测

用户使用受控 Codex CLI 执行 20 秒等待任务，无人工确认弹窗。新 GUI 元数据日志对应独立 CLI 会话：17:47:45 PreToolUse / PermissionRequest，17:48:07 PostToolUse，17:48:11 Stop。用户明确确认执行期间诗音持续保持工作姿态；反馈中的“1”为手滑，不计作轮次读数。

判定：PermissionRequest 自动审批路径事件覆盖与工作姿态保持通过（日志及用户观察共同支持）。用户级 approvals_reviewer=auto_review；无弹窗与自动审批一致，但未读取内部审批记录。人工长时间等待批准及附加提示视觉仍未验证；用户未提供本次结束后的轮次读数，不能把它计为本轮已实测。后续进入单独 Interrupt 验收。

### Interrupt 真机验收

用户确认 CLI 中断、诗音退出工作姿态、活动轮次归零，无异常或提示。GUI 元数据日志显示测试 CLI 会话短 ID 01a181e8、轮次短 ID 01a181eb：17:51:25 UserPromptSubmit，17:51:37 Interrupt。该轮日志未见 PreToolUse，因此判定轮次中断观察和 GUI 状态收尾通过；未证明工具已启动或其进程被终止。未出现气泡提示不单独判失败（提示受静音及显示策略影响）。

### 无 matcher 工具覆盖：本地 Shell

用户提供固定无敏感命令的一次 Shell 执行截图并确认结束后轮次 0。相同测试 CLI 会话 01a181e8、轮次短 ID 01a181ed 的日志：17:53:27 UserPromptSubmit、17:53:35 PreToolUse、17:53:37 PostToolUse、17:53:40 Stop。判定本地 Shell（PowerShell 命令）真实事件覆盖通过；不能将此扩大为单独 Bash 工具覆盖。归因来自本轮单工具执行截图与时间线，不来自 Hook 中不存在的工具名称字段。

### 无 matcher 工具覆盖：apply_patch

用户截图显示一次 apply_patch 新建固定验收文件；自动核验 build/real-install-v3-20261028/tool-coverage/patch-probe.txt 存在，内容仅 SHION_PATCH_COVERAGE。独立 CLI 会话/轮次短 ID 01a181ef：17:55:50 PreToolUse、17:55:51 PermissionRequest、17:55:57 PostToolUse、17:56:00 Stop。判定 apply_patch 前后事件覆盖通过，期间还实际收到权限事件；本轮未单独取得 GUI 轮次读数，不补造视觉结果。

### MCP 单工具测试：事件证据缺口

用户确认 node_repl MCP 单次调用成功、结束后轮次 0。核对当时 GUI 日志，原 CLI 测试会话 01a181ef 在 17:56:00 Stop 后未见新轮次，其他会话为当前验收聊天；因此暂记工具执行用户反馈通过，MCP Hook 事件覆盖未验证。由于连本次 CLI 的 UserPromptSubmit 也未见，不能据此归因于 MCP 工具过滤或宣称不支持。暂停下一工具，先核对执行入口与 MCP 连接。

### MCP 诊断复测的更正

18:03 用户截图明确显示 CLI 回复“当前可用工具中没有 node_repl.js”，未实际调用 MCP。故不把此前“是、是、0”的反馈作为已经发生 MCP 调用的独立证据。当前判定 MCP 工具覆盖未验证；MCP inventory connected/4 tools 与模型可调用工具名称之间存在待核实差异。只查看 /mcp verbose 的工具名称，不调整配置、不安装工具或绕过信任。

### MCP 实际调用失败路径（18:06）

用户截图确认调用 node_repl.js，返回 trusted Node process exited unexpectedly; kernel reset，未产生固定测试输出。CLI 会话短 ID 01a181ef、轮次短 ID 01a181f9 日志：18:06:06 UserPromptSubmit、18:06:19 PreToolUse、18:06:32 Stop；未见 PostToolUse。判定真实失败 MCP 调用的前置事件覆盖通过，成功后置覆盖仍未验证。未见 PostToolUse 的原因尚未确认，不能将失败工具调用直接当成成功事件遗漏或归因于 Shion。暂停 Node 重试，不修改客户端/Node 配置，不扩大已审核 Hook 定义。

### 本地辅助工具可用性边界

用户反馈当前 CLI 可用工具中没有 update_plan，按指令停止，未调用其他工具。该样本记为当前会话不适用，不计作 Shion Hook 失败。至此已实测 Shell、apply_patch 完整前后覆盖；MCP 实际错误调用仅前置覆盖，成功路径未验证；Bash 作为独立工具未验证。后续转入 GUI 关闭时的 fail-open 验收，精确 Hook 附加延迟仍未测定。

### GUI 关闭时的真实故障放行测试：被执行器故障阻断

用户确认 GUI 正常退出、未自行出现；自动检查 47613/47614 均无监听。CLI 单次 Shell 请求返回 Failed to create unified exec process: helper_unknown_error: setup refresh had errors，命令未执行。判定 GUI 退出及不自启通过；本轮离线工具执行验收未通过门槛，不能计为 fail-open 成功，也不能据此确定 Shion 是原因。

当前桌面验收聊天中一次普通沙箱 Shell 对照成功，故不是所有执行环境均失败。正式 Observer 源码离线转发捕获连接异常并返回中性结果，但静态检查不能替代问题 CLI 的现场证明。只读检查默认 .codex/.sandbox/sandbox.log 不存在；未读取认证/会话历史或修改沙箱权限。按官方 Windows sandbox 排查建议，仅重启故障 CLI 做一次同条件对照，若仍失败停止重试，不降级沙箱、不改变 ACL/配置。

### 重开 CLI 对照：启动阶段被阻断，停止后续真实验收

用户截图显示新 CLI 在 TUI bootstrap 阶段退出：account/read failed: workspace routing discovery timed out，code -32603。固定离线测试指令保留为 Unsent draft，尚未提交，未执行 Shell。本次与前一轮 helper_unknown_error 不同，属于客户端启动/账户工作区路由发现阶段的阻断；仅凭截图无法确认具体网络、服务端或客户端原因，也不能建立与 Shion 的因果关系。

按此前约定停止重复尝试及后续故障/延迟测试，不修改认证、全局配置、Hooks、信任、ACL 或沙箱模式，不要求用户重装或重新登录。Shion GUI 用户已正常退出且未自启；上次自动检查接收端口无监听。当前离线执行、GUI 重连、精确 Hook 附加延迟及后续异常恢复仍未完成真机验收。待 CLI 能正常启动并执行一个受控命令后，再从离线放行对照恢复；此前通过的 GUI CLI/桌面视觉、权限自动审批工作保持、轮次 Interrupt、Shell/apply_patch 事件覆盖结果保留。

### Codex CLI 阻断的只读诊断与自动对照

官方 codex doctor 摘要结果：19 ok、1 idle、6 notes、5 warn、0 fail（degraded）。配置/安装可加载、认证已配置、HTTP provider 可达、WebSocket 成功升级、桌面 app-server 可初始化；不能据此证明具体沙箱命令可执行。摘要存在可选 MCP 配置和线程索引元数据警告，未展开会话或读取聊天正文。

Shion GUI 接收端关闭时，在相同 tool-coverage 目录用 --no-daemon exec --ephemeral --json 做一次固定 Shell 命令自动对照。仅提取 thread/turn 状态、command_execution 状态和退出码，不保留客户端正文、工具参数或工具输出。结果：thread_started=true、turn_completed=true、command_execution failed / exit_code=-1，CLI exit_code=0，无测试超时，22.875 秒。因此启动通路当时可用，但工具执行仍失败；CLI 本身退出 0 不能计作离线放行成功。没有足够证据确认 Shell 失败和早先 Node 内核失败具有同一根因或由 Shion 导致。

暂停后续真实验收。下一步只安排用户正常关闭全部 Codex 客户端/测试 CLI 后重新打开本聊天，保持 Shion GUI 关闭；不改全局配置、沙箱权限、认证或信任，不重装、不强制结束不明进程。

### 完整重启后定位到嵌套验收目录 ACL 刷新阻断，根目录对照通过

完整重启后的同目录自动对照依然 command_execution failed / exit_code=-1；已知错误标签 setup refresh had errors，CLI 可建立并完成轮次。转查实际按日期轮转的 .codex/.sandbox/sandbox.2026-10-28.log（此前仅检查 sandbox.log，不代表没有沙箱日志）。只提取错误类别与验收路径，未输出命令正文或凭据。日志明确显示 tool-coverage 路径 write ACE grant failed，open ACL target for update (READ_CONTROL | WRITE_DAC)，os error 5。

只读 ACL 对比：项目根目录 owner 为当前用户；本助手此前在受限沙箱内创建的 tool-coverage 目录 owner 为 CodexSandboxOffline，两者均未保护继承。由此定位到验收目录准备方式与独立 CLI 刷新 ACL 的兼容问题。未手工修改 ACL、所有者、沙箱模式或用户配置。

仅将固定 Shell 对照的 cwd 改为现有项目根目录，其他正式全局观察配置保留，GUI 接收端仍关闭。结果：thread_started=true、turn_completed=true、一条 command_execution completed / exit_code=0，CLI exit_code=0，无已知错误标签，无超时，38.969 秒。判定项目根目录条件下真实 CLI 离线放行通过；该总时间包含模型/启动/执行，不是 Hook 附加延迟。旧嵌套目录仍保留现场，后续验收统一从项目根目录启动 CLI。Node 内核错误是否同源未确认；单次账户路由启动超时也不归因于目录 ACL。

接下来进入 GUI 重启后重连场景；先请用户启动指定 Shion-dev GUI，再核验端口和真实事件。证据 build/cli-diagnostic-20261028/result-after-restart.json 与 result-project-root.json；未保存客户端正文或工具输出。

### GUI 重启后真实重连：事件链通过，视觉收尾待反馈

用户启动指定 Shion-dev 后，GUI PID 110728 持有 47613/47614，路径正确。项目根目录内的临时 CLI 真实执行固定 Shell 命令，thread_started/turn_completed=true，一条 command_execution completed/exit_code=0，进程退出 0、无超时、无已知错误标签，16.797 秒（不是 Hook 附加延迟）。

自动关联该 CLI 的会话短 ID 01a18225 与 GUI 新增日志：18:53:49 SessionStart、UserPromptSubmit；18:53:53 PreToolUse；18:53:55 PostToolUse；18:53:57 Stop。证明正式全局 MCP/Token 链路在 GUI 关闭并重新启动后可重新送达五类真实事件；未直接调用 observe_lifecycle 或使用合成事件。当前判定重连事件链通过，GUI 菜单轮次与视觉收尾仍待用户确认。证据 build/cli-diagnostic-20261028/result-gui-reconnect.json；仅保存事件元数据与状态/退出码。

### GUI 重启重连视觉收尾确认

用户反馈当前活动轮次 0、无报错或工作姿态卡住。结合前述独立 CLI 五类真实事件链及 Shell exit_code=0，判定本场景 GUI 关闭后重新启动的真实事件重连与界面收尾通过。

后续优先补此前受 Claude 前台 Stop/后台执行影响而未确认的并行隔离；要求 Claude 前台工具保持执行，不能仅根据后台进程仍存在认定前台轮次仍活动。精确 Hook 延迟、MCP 成功路径及其他故障边界保留未验证状态。

### 前台长休眠并行复测：命令被客户端策略拒绝

用户转述 Claude Code 明确拒绝 standalone Start-Sleep 90，命令未运行、不是自动转后台。本轮没有形成预期前台重叠，故并行隔离未验证；不记为 Shion 事件覆盖失败。停止使用长休眠或短休眠拼接、循环等替代等待方式。改以实际有用的前台只读修复审查作为 Claude 工作负载，Codex 执行短固定工具任务；若没有形成重叠则如实保留未验证，不人为绕过工具限制。

### Claude/ChatGPT 前台实质任务并行：关键隔离样本通过

用户反馈两者前台重叠、Codex 结束时 Claude 仍在审查、ChatGPT 轮次 0 且诗音仍工作。元数据日志对应时间线：Claude 19:09:11 prompt，19:09:25/33/56 working 及其 tool_done；ChatGPT 独立会话短 ID 01a18233 于 19:09:34 Submit、19:10:08 PreToolUse、19:10:09 PostToolUse、19:10:13 Stop；Claude 直到 19:10:31 才收到 stop。

判定本样本中 ChatGPT 结束未覆盖仍活动的 Claude 工作状态，前台并行隔离通过（用户视觉及通道时间线一致）。Claude stop 只证明轮次结束，不额外判定代码审查结论或任务成功。此前后台/拒绝长休眠样本仍保留为无效隔离验收，不以本结果改写旧证据。

### 临时关闭联动：真实 CLI 放行与停止投递通过

用户通过 GUI 临时关闭联动；只读检查 enabled=false，GUI PID 110728 仍持有两个端口。正式全局 Hook 定义与 MCP 路径符合预期，七项历史禁用、七项已信任未禁用记录保持该状态。未卸载或修改 Hook 定义。

项目根目录内临时 CLI 自动执行固定 Shell 命令：thread_started/turn_completed=true，唯一 command_execution completed/exit_code=0，CLI exit_code=0，无已知错误标签、无测试超时，45.891 秒（包含启动及模型时间，不是 Hook 附加延迟）。该会话短 ID 01a18238 在 GUI 本轮日志增量中没有观察事件，符合关闭后正式 Observer 停止投递的预期。判定临时关闭场景通过；下一步由用户重新开启自身联动开关，再单独验证恢复投递。

证据 build/cli-diagnostic-20261028/result-observation-disabled.json，仅记录状态与元数据；Token 值未输出或记录。

### 重新开启联动：真实事件恢复通过，界面收尾待确认

用户重新开启自身观察开关；只读确认 enabled=true，GUI PID 110728 仍持有原有两个端口。项目根目录的临时 CLI 自动运行固定 Shell 命令：command_execution completed/exit_code=0，CLI exit_code=0，thread_started/turn_completed=true，无已知错误或测试超时；总用时 39.125 秒，不是 Hook 附加延迟。

会话短 ID 01a1823a 在 GUI 日志新增事件：19:17:43 SessionStart、UserPromptSubmit；19:17:47 PreToolUse；19:17:49 PostToolUse；19:17:52 Stop。与关闭时该测试会话无投递形成直接对照。判定重新开启后的正式事件恢复通过；菜单最终轮次及卡住情况待用户反馈。证据 build/cli-diagnostic-20261028/result-observation-reenabled.json，仅状态与元数据；未修改 Hooks、信任或全局 MCP 定义。

### 临时关闭/重新开启完整场景确认

用户反馈重新开启后活动轮次 0、无异常。结合关闭时正式 CLI 成功但无事件投递、重新开启后正式 CLI 成功并收到五类事件，判定自身观察开关关闭/开启及恢复的完整场景通过。全局 MCP/Hook 定义、信任记录不因开关操作改变。继续进行项目根目录条件下的一次 MCP 成功路径复测；此前嵌套目录 Node 错误保留原始失败证据，不回写为成功。

### 项目根目录 MCP 成功路径：真实覆盖通过

一次根目录临时 CLI 自动复测，元数据确认唯一 mcp_tool_call 为 node_repl/js、status=completed、error_present=false；无 Shell 调用，无已知错误标签，无测试超时，CLI exit_code=0，turn_completed=true，总用时 42.359 秒（不等于 Hook 延迟）。未保留模型正文、工具参数或结果正文。

会话短 ID 01a1823d 的 GUI 真实日志：19:20:52 SessionStart、UserPromptSubmit；19:21:00 PreToolUse；19:21:05 PostToolUse；19:21:08 Stop。判定无 matcher 下该 MCP 成功调用的前后事件覆盖通过。与前期失败 Node 样本分开，不反推早期故障全部由目录 ACL 导致；新会话/目录变化均可能影响结果。证据 build/cli-diagnostic-20261028/result-mcp-project-root.json。

### 同步 Hook 附加耗时：真实运行元数据采样

本机当前 Codex 生成的协议 schema 确认 hook/completed.run.durationMs 为实际同步 Hook 运行时长。通过独立 app-server、新建 ephemeral 线程和五个真实固定 Shell 轮次采集；没有读旧线程/history，没有开启新的遥测配置或修改 Hook。只保存来源为用户级 hooks.json、handlerType=mcpTool 的 Hook 时间、事件与状态，忽略 entries/statusMessage 等正文或结果字段。

21 次 Hook 全部 completed，五个工具命令均 exit_code=0。单次 durationMs：中位数 9 ms、nearest-rank P95 32 ms、最大 34 ms；SessionStart 为 14 ms。每轮 UserPromptSubmit/PreToolUse/PostToolUse/Stop 累计 83、48、42、54、68 ms，中位数 54 ms（不包含该线程首个 SessionStart）。该口径量化了客户端报告的同步 Hook 阻塞时长，不包含模型、Shell 本身、GUI 绘制或整段启动耗时；小样本不代表最坏负载上限或桌面 TUI 输入延迟。

采样时实际 Observer 工作集快照 17.70–22.92 MiB、累计 CPU 0.203–1.078 秒；包含不同生命周期的多个 Observer，既不是峰值也不是长期平均，不据此宣称无资源泄漏。五轮命令无失败或 Hook 超时，本机正常样本性能项通过。

证据 build/cli-diagnostic-20261028/result-hook-timing.json 和生成协议 v2/HookCompletedNotification.json。随后单独进行受控 Observer 异常断连测试，不将其预期失败状态混入正常延迟统计。

### Observer 异常断连：尚未注入及 2026-10-29 续验检查

首个测试器完成一个真实预热轮次和五个 Hook 后，在独占测试进程归属路径检查处停止，原因 Observer executable mismatch；没有终止 Observer。问题来自测试器路径字面量转义，修正版改为 Path 组合，保留唯一后代进程、精确路径和 EXE 哈希检查。修正版上轮执行请求被自动审批系统拒绝：用量上限导致审批未能完成，动作未执行；这不是不安全判定，未通过其他入口绕过。该场景仍为未验证。证据 result-observer-disconnect.json；result-observer-disconnect-final.json 尚不存在。

2026-10-29 用户要求继续后，先只读核查。当前仅发现指定开发包的 Observer PID 8612，没有 GUI 进程，47613/47614 无监听，因此未启动故障注入。开发包 EXE SHA-256 为 6e64fa0e8a1e3ee828ba42cc0a0fe52a1fd1323f3d512d47c319d9eb43329068；hooks.json 为 3e4929662ae33d43fc0d39b861dd1b788378b2da496e37c1d0c0acaf619c1d03。TOML 解析成功，MCP 及七个无 matcher Hook 与 v3 归属记录定义精确一致；14 项信任记录中七项 enabled=false，七项有 trusted_hash 且未禁用。node_repl 和 notify 存在，未输出其字段值。归属 v3 有效，WAL、锁与预期暂存路径均不存在；Token 文件存在，不输出其内容。

当前 config SHA-256 为 83217ad791819b1fea91be2157fb5d0018ca25c2272716c0d90dc192c62b6a92，与最初信任完成时记录不同；本轮未写该文件，也没有足够证据定位变化原因。定义及信任摘要符合上述检查，但不据此宣称所有其他配置字节未变化。不安装、不强制恢复、不变更配置或信任。下一步仅请用户启动 GUI 并保持观察开启，再按正常审批执行测试专属 Observer 断连；现有日常 Observer 不处理。

### 2026-10-29 Observer 受控异常退出：工具放行通过，视觉待确认

用户启动 GUI 后，只读确认 PID 5240 运行指定开发包，持有 127.0.0.1:47613/47614，观察开启；日常 Observer PID 8612。修正版测试器本次经过正常自动审批后运行，未绕过上次审批用量限制。通过独立 app-server 新建 ephemeral 线程，先完成一轮真实固定 Shell 预热，再核对唯一后代 Observer、指定路径及当前 EXE SHA-256，结束的仅为测试 PID 42824。

该线程完整 ID 为 01a184dc-88af-7b92-9e4f-2f81d589ad56。预热轮次末尾 8a55-7ec3-9f19-a2fc81a5bbe5 与故障轮次末尾 ba27-7433-92ed-2fcfdbf4995e 的前八位相同，短 ID 不能区分这两个轮次；归因使用 app-server 完整 ID 和测试顺序，而非 GUI 短 ID 单独判断。预热 GUI 日志为 07:33:30 SessionStart/Submit、07:33:33 Pre、07:33:35 Post、07:33:38 Stop，五个正式 Hook completed；Shell completed/exit_code=0。

Observer 退出后，同一线程下一轮 Submit、Pre、Post、Stop 四个 Hook 均 failed，客户端 durationMs 均为 0（仅说明客户端测量精度下立即失败，不代表没有任何开销）。该轮唯一 Shell 仍 completed/exit_code=0，turn completed，没有触发测试器 90 秒轮次超时。GUI 对该会话未收到第二轮事件；不把事件缺失填成成功，也不把预期 Hook 错误计作正常性能样本。

测试器结束后再次只读确认：仅原日常 Observer PID 8612 和 GUI PID 5240 在运行，两个端口仍由 GUI 持有；config SHA-256 83217ad7…62b6a92、Hooks SHA-256 3e492966…19c1d03 及观察设置文件字节哈希与测试前一致，未创建/轮换 Token，未修改信任。证据 build/cli-diagnostic-20261028/result-observer-disconnect-final.json，仅保存事件、状态、ID、时长和退出码元数据，无聊天/工具参数/结果正文。

判定：本样本 Observer 异常退出后的工具放行通过，其他进程存活及配置未被改写的自动核验通过；同一会话没有在该后续轮次恢复观察，因此不宣称自动重连通过。本次在预热 Stop 后才断连，不证明活动工具执行中断连的状态清理；MCP 持续超时也未测试。GUI 视觉及最终轮次待用户反馈，完成该反馈前不开始下一场景。

用户随后明确反馈“0、无异常”，该场景视觉收尾通过。下一项只验证新建独立 CLI 会话能否恢复事件投递，继续保持原 GUI、全局定义、信任与 Token，不将新会话成功等同于旧会话自动重连。

### 2026-10-29 新建 CLI 会话后的恢复投递：自动核验通过

保持原 GUI 和现有日常 Observer，不重启、不改正式全局定义/信任或 Token；独立执行一次 --no-daemon exec --ephemeral 的真实 CLI 固定 Shell 任务。线程完整 ID 01a184e0-1049-7060-93c5-28509f8a096c，一条 command_execution completed/exit_code=0，turn_completed=true，CLI exit_code=0，无测试超时和已知错误标签。总用时 18.454 秒包含启动、模型和工具时间，不作为 Hook 附加延迟。

GUI 日志在本次增量中收到该独立短 ID：07:37:23 SessionStart/UserPromptSubmit、07:37:26 PreToolUse、07:37:28 PostToolUse、07:37:30 Stop。config、Hooks、观察设置文件字节哈希前后相同。判定新 CLI 会话可恢复正式事件投递，自动核验通过；GUI 最终轮次/视觉卡住情况待用户确认。证据 build/cli-diagnostic-20261028/result-observer-new-session-recovery.json，只保留元数据，没有模型正文、工具参数或结果正文。

可安全降级边界：测试专属 Observer 意外退出时，该客户端后续轮次的工具仍能执行，但在所测后续轮次内观察没有恢复；新开独立 CLI 会话能恢复投递，GUI 无须重启。本样本不证明原客户端自动重连，也不证明跨断连补发历史事件。MCP 超时及活动任务执行中断连仍保留未验证。

用户随后反馈“0、无异常”，新建 CLI 会话恢复投递与视觉收尾完整场景通过。接下来只验证测试专属 Observer 一次有界无响应；正式 Hook 和 MCP tool_timeout_sec 均为 1 秒，不修改定义来区分这两层超时。使用已验证归属、路径、哈希和创建时间的进程/线程句柄，首次故障 Hook 完成即恢复，另有 3 秒恢复看门狗和 finally 清理。仅调用 Windows 已记录的线程暂停/恢复 API，不安装新依赖，不触碰日常 Observer。

### 2026-10-29 单次 MCP 无响应/超时：工具放行及后续事件恢复通过

独立 ephemeral 线程 01a184e5-e88d-7473-bc0e-a11bd115d342，预热轮次 01a184e5-e952-7511-833c-08981e7fbb8d 的五个 Hook 全 completed，固定 Shell exit_code=0。完成预热后，唯一测试后代 Observer PID 612 通过指定路径、EXE 哈希、创建时间及线程归属核验；持有进程与线程句柄，仅暂停该进程的五个线程。使用 Windows 文档中的 [SuspendThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-suspendthread) 和 [ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread)，没有安装依赖或改正式程序。

故障轮次 01a184e6-173e-7ef2-ab84-b32d34f67db5 的 UserPromptSubmit Hook failed，durationMs=1006；收到该完成通知立即恢复进程，暂停累计 1110 ms，五个 ResumeThread 返回值均为 1，无恢复错误，未使用终止兜底、未触发 3 秒看门狗。随后同轮 PreToolUse、PostToolUse、Stop 均 completed，durationMs 分别 9、30、10；唯一真实 Shell completed/exit_code=0，turn completed。仅制造该一次有界无响应，没有循环重试或持续超时。

GUI 预热五类事件完整；故障轮次于 07:43:55 收到延迟的 Submit，随后 07:43:58 Pre、07:44:00 Post、07:44:02 Stop。说明失败 Hook 对应的请求仍可能在恢复后到达接收端，不能把 failed 状态改写为 Hook 成功；事件实际收到和客户端 Hook 结果分别记录。正式 MCP tool_timeout_sec 与 Hook timeout 都是 1 秒；未读取异常正文，本样本无法精确区分由哪一层先触发，结论限定为一秒无响应边界后的工具放行和后续事件恢复。

测试后仅原日常 Observer PID 8612 和原 GUI PID 5240 存活，GUI 两个接收端口仍正常；测试 Observer 已清理，config、Hooks、观察设置字节哈希与测试前相同。证据 build/cli-diagnostic-20261028/result-observer-timeout.json，仅状态/事件/ID/时长元数据，无聊天、工具参数/结果正文。判定本次有界无响应后的工具放行和后续投递恢复自动核验通过；GUI 最终活动轮次与卡住情况待用户反馈。该样本不证明任意负载、持续故障或活动工具中途断连均可恢复。

用户随后反馈“0、无异常”，单次无响应场景的视觉收尾通过。下一项仅补工具实际运行时的中断证据：[官方 app-server 文档](https://learn.chatgpt.com/docs/app-server#interrupt-a-turn) 与本机 schema 均提供 turn/interrupt。测试先确认独立会话 commandExecution/inProgress 及其新建 Shell 进程归属，再通过该端点请求取消；不把协议中断等同于人工 TUI 按键或桌面按钮验收，也不把被中断命令记为成功完成。

### 2026-10-29 工具执行期间 Interrupt：事件观察通过，工具终止证据不足

独立 ephemeral 线程 01a184ea-4c28-78b2-a6de-9fca7b1c7742、轮次 01a184ea-5098-7f90-9493-721bd3960f59。实际 commandExecution 进入 inProgress；其 PTY 标识为 33518，仅视为协议 ID，不当作 OS PID。通过进程树和创建时间确认本次新建实际 Shell 为 pwsh.exe PID 44876，创建时间 FILETIME 134377049188424080，未读取命令行或正文。命令执行中约 3719 ms、进程仍活着且没有 item/completed 时，通过官方 turn/interrupt 请求取消，收到成功应答，187 ms 内轮次状态变为 interrupted。

正式 Hook 状态：SessionStart 12 ms、Submit 6 ms、Pre 27 ms、Interrupt 16 ms，均 completed。GUI 实际时间线为 07:48:33 SessionStart/Submit、07:48:37 Pre、07:48:42 Interrupt；未收到 PostToolUse 或 Stop，不补造。该结果补足“工具已经活动时收到真实中断事件”的观察证据；不是由 Shion 控制 ChatGPT，也没有直接发送 observe_lifecycle。

工具退出的判定独立保留：轮次结束后等待 0.5 秒再作一次 CIM 查询时，PID 和创建时间仍匹配、进程存活，且未取得 commandExecution item/completed；查询本身耗时未单独测量。随后停止其他测试，只读复查：2026-10-29 07:49:21（UTC 2026-10-28T23:49:21.6800315Z）该进程已不存在。但该时点已晚于固定 20 秒休眠的自然结束上限，不能证明由中断终止，也不能断言一直运行到自然终点。未擅自杀进程；普通进程元数据不能确定 PowerShell 内部命令是否早已取消。

测试后原 GUI PID 5240 和日常 Observer PID 8612 保留，测试 Observer 已退出，config/Hook/观察设置哈希前后相同。证据 build/cli-diagnostic-20261028/result-tool-active-interrupt.json，仅元数据。当前判定工具执行中 Interrupt 事件观察通过，工具进程及时退出未验证，GUI 最终轮次/视觉收尾待用户反馈；不是 Shion 控制失败的结论。若需进一步证明工具是否被终止，建议另作持有真实进程句柄的连续退出计时测试，不改变 Shion、Hooks、信任或配置；本轮先报告证据边界，不自动重复。

用户随后反馈“0、无异常”，该场景观察与视觉收尾通过。进程退出原因及及时性继续保持未验证；补充只读复查和用户反馈元数据位于 result-tool-active-interrupt-followup.json。之后只做上述收尾审计，没有开始新的故障样本或修改产品代码。
