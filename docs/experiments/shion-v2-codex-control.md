# Codex 控制能力实验：停下、中断、授权

实验日期：2026-10-30（Asia/Shanghai）。状态：隔离实验完成；桌面 GUI 控制未验证；不据此开放诗音的 Codex 控制功能。

## 结论

1. **停下**：同步 Pre/Post hook 能等待超过两分钟。PreToolUse `deny` 能挡住当前调用，但模型仍可继续调用工具；本机 PostToolUse `continue:false` 虽被记成 `stopped`，随后仍执行了下一次工具。不能据此保证整轮停止，长期暂停还存在 hook 故障后继续执行的缺口。
2. **中断**：有官方 `turn/interrupt`，可结束受控 app-server 的轮次；**不保证结束工具进程**。本次前台、转后台两组测试中，轮次 interrupted 后父子进程均继续存活至少八秒，心跳持续增加。只结束已登记且核对身份的测试进程可以清理这些工作负载，不能推广成任意 Codex 会话的可靠进程树控制。
3. **授权**：PermissionRequest allow/deny 有实际作用，但无输出、超时、崩溃会交回原审批流程。原流程若使用自动审批，仍可能无人点击就执行。**hook 单独不能提供“任何异常都不会默认放行”的保证**；必须限制为可验证的人工审批配置，或增加独立、默认拒绝的执行边界。尚不建议接入现有诗音授权面板。

上述是本机版本、固定 Bash/exec_command 工作负载的结论；不是所有工具、托管环境或未来版本的保证。既有阶段 0/1 的观察结论继续保留，产品仍为“ChatGPT 只观察和提醒”。

## 环境、官方依据与隔离

| 项目 | 本次记录 |
| --- | --- |
| Codex CLI | `codex-cli 0.165.0-alpha.1.2`，由 `codex --version` 获取 |
| 桌面安装包 | 当前运行进程路径中的包标识 `OpenAI.Codex_26.1023.6621.0_x64__2p2nqsd0c76g0`；包版本 `26.1023.6621.0`。这是桌面包版本，不能冒充其内部服务的独立版本 |
| 文档 | 2026-10-30 实际打开官方页面；页面无明确修订版本号，以检索日期标识。未采用第三方转述作结论依据 |
| CLI 接口 | 真正启动本机 CLI 的非交互 `exec`、交互 TUI、独立 `app-server --stdio`；三者分别标注 |
| 模型与自动审查 | 本机 `127.0.0.1` 确定性 Responses/SSE 响应器，发送固定工具调用或固定审查 allow/deny。没有调用外部模型，没有读取、复制登录凭据；验证的是实际 Codex 执行/审批路由，不是线上模型的判断质量 |
| 临时位置 | `build/codex-control-20261030/`，Git 忽略。每个用例有独立 `home/`、`profile/`、`appdata/`、`project/`；后续用例的临时项目初始化独立 Git 根，避免继承本仓库配置 |
| 运行环境 | 仅对子进程设置 CODEX_HOME、HOME、USERPROFILE、APPDATA、LOCALAPPDATA，并去掉继承的 CODEX_/OPENAI_ 路由变量；不修改父进程及用户真实环境 |
| Hook 信任 | CLI 仅使用官方一次性 `--dangerously-bypass-hook-trust`，脚本为本次自行编写审核的固定探针。独立 app-server 通过 `hooks/list` 审核临时来源和 currentHash，再用 `config/value/write` 写入**临时 home** 的精确 hooks.state，重启并确认 trusted；不伪造真实用户的信任记录 |
| 沙箱 | 临时配置分别为 read-only、workspace-write、danger-full-access；完整访问下也只执行固定输出或有登记的临时心跳进程。TUI 使用临时 `[windows] sandbox="unelevated"`；没有进行管理员沙箱安装或更改全机安全设置 |
| 产品边界 | 没有运行诗音实验接收服务，没有连接 Shion-dev，没有运行 Claude Code，没有修改产品代码、真实全局配置或本仓库 `.codex` 配置 |

沿用现有 [阶段 0 报告](shion-v2-phase0-final.md) 和 [阶段 1 隔离客户端](../../tools/experiments/isolated_observer_client.py) 的独立 home、独立子进程、固定任务做法。本次不复用其会话身份、MCP 或已安装 hook。

官方依据：

- [Hooks](https://learn.chatgpt.com/docs/hooks)：同步 hook 的决策形状、信任、默认超时及事件字段。PreToolUse 不支持 continue:false；PostToolUse 支持该字段，但应区分“hook run stopped”和整轮是否停止。PermissionRequest 没有决定时继续正常审批。
- [App Server](https://learn.chatgpt.com/docs/app-server)：turn/interrupt、审批 RPC、serverRequest/resolved、itemId/turnId/threadId。它们描述服务协议，不能证明任意已运行桌面窗口可被外部程序接管。
- 本机 `--help`、`app-server generate-json-schema` 交叉核验；生成内容保存在实验目录 `schema/`。不从旧版本文档推断本机支持程度。

## 能力矩阵

“已证实”可以是明确的否定结果；“部分”表示只覆盖所列条件。“桌面未验证”不等于功能不存在。独立 app-server 成功不计为桌面 GUI 成功。

| 实验 | CLI | 桌面 | 证据及缺口 |
| --- | --- | --- | --- |
| E1 授权决定 | **部分** | **未验证** | TUI 实见原生授权框、单次人工批准、hook deny、hook allow 后执行；exec 强制 never。策略/read-only/workspace-write/自动审批的完整对照来自独立 app-server，见下表；非 Bash 工具未测 |
| E2 等待与超时 | **部分** | **未验证** | TUI 等待 10 秒时先显示 Running hook，随后出现原生框；CLI Pre/Post 每次实际等待 125 秒。故障回退和配置极值主要由独立 app-server 验证；没有在 TUI 重跑每种崩溃 |
| E3 撤回 | **部分** | **未验证** | TUI 等待 30 秒的授权 hook 期间按 Esc，hook PID 结束、收到 Interrupt，之后可继续新轮。app-server turn/interrupt 同样取消等待 hook；等待时还没有原生审批请求，无法测试两边同时回答的竞态 |
| E4 停下 | **已证实**（所测工具） | **未验证** | CLI 两个并发会话各做两次 125 秒等待；Pre deny 两次均挡住工具但轮次继续；Post continue:false 后第二条工具仍执行。app-server hook 状态复核一致 |
| E5 中断 | **部分** | **未验证** | CLI TUI Esc 的轮次中断、等待 hook 取消有证据；正在执行/后台工具的进程存活检查来自独立 app-server，两组均未自动终止。没有把该结果外推成 TUI Esc 的工具树实测 |
| E6 对号 | **部分** | **未验证** | CLI Pre/Post tool_use_id 配对、并发两会话 ID 分离；PermissionRequest 实际没有 tool_use_id/request_id。app-server 原生请求可用 itemId/requestId 对号；两连接的 requestId 同为 0，必须加来源实例作用域 |

桌面限制：现有桌面进程使用用户真实服务环境，复用其会话会加载已安装的全局观察 hook，违反本任务“不碰 Shion-dev”的条件。已检查本机 `codex app --help`：提供工作区路径和普通配置选项，没有证实可建立独立 GUI profile、独立 CODEX_HOME 与独立服务实例的入口。没有尝试通过重启用户桌面、修改全局设置或向现有桌面线程注入实验来补齐。故六项均保留未验证；后续需先验证独立桌面实例的隔离边界，再进行 GUI 验收。

## E1：何时触发、返回值与人工等待

统一工具参数：`exec_command`，命令 `Write-Output CONTROL_LAB_OK`。升级请求另带 `sandbox_permissions=require_escalated`、固定 justification；普通调用省略升级参数。用 hook 日志、审批 RPC、commandExecution 退出码及 PostToolUse 联合判断，不能只看 CLI exit 0。

以下是**独立 app-server** 的真实执行结果，审批决定由实验客户端明确回复；自动审批的判断内容是确定性夹具。

| 策略 / 沙箱 / 调用 | PermissionRequest | 后续结果 | 用例 |
| --- | --- | --- | --- |
| on-request / danger-full-access / 请求升级 | 不触发 | allow/deny/无输出三种临时定义均不会被调用；命令 exit 0 | `a-full-{allow,deny,none}` |
| on-request / workspace-write / 请求升级 | 触发 | hook allow → 无客户端审批请求，exit 0，有 Post；hook deny → blocked、不执行、无 Post | `a-write-{allow,deny}` |
| on-request / workspace-write / 请求升级 / hook 无输出 | 触发 | 一个原生 requestApproval；accept → exit 0，有 Post；decline → declined，无 Post | `a-none-accept2`、`a-write-none-decline` |
| on-request / read-only / 请求升级 | 触发 | hook allow → exit 0；无输出 → 原生请求，客户端 decline 后未执行 | `a-read-{allow,none}` |
| on-request / workspace-write / 普通固定命令 | 触发 | 本机对此 PowerShell 命令仍要求审批；客户端 decline 后未执行 | `a-normal-write` |
| never / danger-full-access 或 workspace-write / 显式请求升级 | 不触发 | 在工具校验处立即拒绝升级参数，无 Post | `a-never-{full,write}` |
| on-request + auto_review / workspace-write / 请求升级 / hook 无输出 | 触发 | 不发送人工 requestApproval；确定性审查 allow → exit 0，deny → declined | `a-auto-{allow,deny}` |
| on-request + auto_review / workspace-write / hook deny | 触发 | blocked，未交自动审查放行 | `a-auto-hook-deny` |
| untrusted | 未建立会话 | 本机启动明确报 `approval_policy = "untrusted" is no longer supported; remove this setting` | `a-untrusted2/rpc-stderr.log` |

`codex exec` 即便临时 config.toml 写 on-request，显式升级仍返回 `approval policy is Never`；因此 `request-*` 初始 exec 组不能当人工审批测试，也不能说 allow/deny 被忽略。never 不代表所有命令都被拒绝：普通完整访问命令的 `smoke` 用例成功，只是显式升级参数被拒绝。

TUI `tui-two` 中，使用临时 workspace-write / unelevated 配置：先等授权 hook 10 秒，再显示 `Would you like to run the following command?`；只选择本次 Yes，实际输出固定标记。之后改临时探针行为为 deny，界面显示 `Blocked by hook`；再改为 allow，命令执行且没有再次人工确认。没有选择“don't ask again”。同一 TUI 后续用户消息可继续提交。

**不能从 PermissionRequest 输入认定正在等人。** 人工与自动审查路径都含 `permission_mode:"default"`，字段集合相同：

```json
{
  "hook_event_name": "PermissionRequest",
  "session_id": "<session>", "turn_id": "<turn>",
  "transcript_path": null, "cwd": "<temporary-project>",
  "model": "control-fixture", "permission_mode": "default",
  "tool_name": "Bash",
  "tool_input": {
    "command": "Write-Output CONTROL_LAB_OK",
    "description": "CONTROL_LAB_ONLY"
  }
}
```

没有 reviewer、审批来源、人工框是否可见、tool_use_id 或 request_id。原生 app-server requestApproval 才表示已向客户端提出具体审批请求；还需确认该客户端确实呈现人工界面。所有输入都只是本次版本/工具的样本，不承诺未来字段不增加。

## E2：等待、超时与异常

### 超时取值

- 官方一般 hook 默认 600 秒；SessionEnd/Interrupt 默认 1 秒，上限 3 秒。本机 hooks/list 复核一般事件省略 timeout 时为 600；将 Interrupt/SessionEnd 写成 600 后均归一为 3。
- PermissionRequest 的 `timeout=0` 在本机归一为 1 秒；600、1900、86400 均被 hooks/list 原样接受。
- 本机配置发现可接受的整数上界测至 `9223372036854775807`（2^63−1）；2^63 及 2^64−1 在 hook discovery 的 TOML identity 序列化处触发内部 panic，RPC 返回 -32603；2^64、负数没有发现对应 PermissionRequest 定义。**这是配置边界测试，不是这么长的等待已被运行验证。**
- 因而“字段 schema 写 uint64”不能解释成整个 uint64 范围都可用。本次只证明 125 秒实际可等待；不承诺极大值的调度、时钟和资源行为。产品若以后使用，建议数分钟的有限超时并留退出余量，不使用极值或无限等待。

原始证据：`timeout-bounds.json`、`bound-*/hooks-list.json`、`large-*/`、`defaults-caps/result.json`。大整数 panic 只发生在独立实验服务，没有作用于用户桌面服务。

### 等待和回退

`a-permission-wait` 中 hook 开始时间 `1793324359.973`，结束 `1793324369.987`；原生 `item/commandExecution/requestApproval` 收到时间 `1793324370.095`。即先等 hook，后请求客户端；等待期间没有原生审批 RPC。TUI 的 10 秒样本也先显示 Running hook，再出现授权框。

| hook 行为 | app-server hook 状态 | 人工 reviewer 下的后续 | 证据 |
| --- | --- | --- | --- |
| exit 0、无输出 | completed | 回到原生审批 | `a-write-none-decline` |
| sleep 10、timeout 1 | failed | 回到原生审批；decline 不执行 | `a-permission-timeout` |
| exit 7（崩溃替身） | failed | 回到原生审批 | `a-permission-crash` |
| exit 2、stderr 原因 | failed | 回到原生审批；不是 PermissionRequest deny | `a-permission-exit2` |
| 坏 JSON | failed | 回到原生审批 | `a-permission-badjson` |
| 超时 / exit 7，随后客户端明确 accept | failed | exit 0、有 Post；执行来自新的客户端决定 | `a-timeout-accept`、`a-crash-accept` |
| 超时 / exit 7，auto_review 的夹具返回 allow | failed | 无人工请求，exit 0、有 Post | `a-auto-timeout-allow`、`a-auto-crash-allow` |

最后一行直接否定“hook 出错就一定拒绝”。它证明回退路由允许自动审查决定，并不证明线上审查模型会批准任意命令。hook deny 在所测场景阻止执行，hook 不存在/未信任/异常则不能提供相同保证。

## E3：撤回和等待中的原生操作

所测同步流程没有“两边同时存在的授权框”：hook 等待时尚无原生 requestApproval，不能在原生框里抢先批准/拒绝。因此**原生批准/拒绝会不会终止等待 hook 的竞态未验证**，不能沿用 Claude Code 的双界面假设。

另测实际可行的取消动作：

- TUI `tui-two`：授权探针 sleep 30 秒。等待中记录 PID `154800` 及创建时间，按 Esc 后界面出现 `Conversation interrupted`，同一 PID 的进程句柄查询变为非运行，hook 无正常 finish，日志收到 Interrupt。随后提交 `CONTROL_LAB_CONTINUE` 可进入新轮。
- 独立 app-server `cancel-permission-hook`：同样 sleep 30。中断前 hook PID `151452` 正在运行，尚无审批请求；turn/interrupt 返回 `{}`，四秒窗口内确认 hook 已退出、收到 Interrupt 和 turn/completed interrupted。没有收到这次 PermissionRequest 的 hook/completed，也没有 serverRequest/resolved（因为尚无原生请求）。**缺少 hook/completed 不能被当成 hook 仍在等人。**

原生请求已经出现后的 accept/decline，则在 `a-none-accept2`、`parallel-B` 等用例中观察到 serverRequest/resolved。resolved 同时可能表示清除，不能单独解读为批准；必须结合已知响应和最终 item 状态。

## E4：检查点等待与整轮结束

两个 CLI exec 进程并发运行，各自由确定性响应器发两次工具调用，hook timeout 160 秒，每次实际等待 125 秒：

| 用例 | 实际经过 | 工具结果 | 后续 |
| --- | --- | --- | --- |
| `long-PreToolUse` | 总计 256.355 秒，两次等待均 ≥125 秒 | 两次 deny 均未执行 | 模型仍收到第一次拒绝后发出第二次调用，之后正常结束 |
| `long-PostToolUse` | 总计 259.969 秒，两次等待均 ≥125 秒 | 两个工具均 exit 0 | 第一次 continue:false 没有阻止第二个工具；之后正常结束 |

短对照 `pre-stop` / `a-pre-stop`：PreToolUse 输出 continue:false 被判 failed，固定命令仍 exit 0，符合官方“不支持该字段”的说明。`pre-deny` / `a-pre-deny`：当前调用被 blocked，但模型仍可继续尝试。

`a-post-stop/rpc.jsonl` 的实际序列是：

```text
preToolUse completed → 第一个 commandExecution completed / exitCode 0
postToolUse stopped / CONTROL_LAB_STOP
preToolUse completed → 第二个 commandExecution completed / exitCode 0
postToolUse stopped / CONTROL_LAB_STOP → turn completed
```

因此在此版本把 Post hook 的 stopped 当作整轮中断是不安全的。用户可在 TUI 的拒绝/中断后继续发消息；阻止工具不等于锁死会话。等待期间的模型/网络/其他并行工具未被全局冻结，两个检查点也不能形成覆盖所有执行路径的强制暂停边界。

## E5：官方中断与实际进程存活

官方入口由本机 schema 和实测共同确认：

```json
{"id":31,"method":"turn/interrupt","params":{"threadId":"<thread>","turnId":"<turn>"}}
```

返回 `{}` 后，独立服务发 turn/completed `status:"interrupted"` 和 Interrupt hook。实验工具为临时 Python 心跳父进程，额外启动一个子进程；每秒在实验目录更新计数。通过 Windows OpenProcess / GetProcessTimes / GetExitCodeProcess / QueryFullProcessImageName 查询**登记 PID 与创建时间**，同时检查心跳，避免用轮次状态猜进程是否停止。

| 场景 | 中断前 | 中断后 1 / 3 / 8 秒 | 清理后 |
| --- | --- | --- | --- |
| `interrupt-active`：工具仍在首次 exec 等待中，yield 10000ms | 父 `150776`、子 `150680` 均运行，心跳 0 | 均运行；心跳约 1 / 3 / 8 | 仅终止两个已核对身份的测试 PID；均非运行 |
| `interrupt-background`：yield 1000ms 后转后台，模型响应暂缓保持轮次活动 | 父 `115652`、子 `153592` 均运行，心跳 2 | 均运行；父心跳 3 / 5 / 10，子 3 / 5 / 9 | 同上，均非运行 |

创建时间与可执行文件保存在各用例 `result.json`；PID 只用于本次证据，不能作为以后清理命令。全系统 WMI 进程查询在当前沙箱拒绝访问，改用上述精确进程句柄查询，无需修改权限或安装依赖。

本次证实“对已知归属进程执行终止并复核”可清理测试工作负载；没有证实能从任意 hook 的祖先进程可靠找全 Codex 的工具树，也没有证明能阻止任务脱离进程树、服务化或远程执行。不得按进程名结束 Codex、共享 code-mode host、全局 sandbox service 或用户其他 Python 进程。

## E6：标识符能否一一对应

- CLI 与 app-server 样本中，PreToolUse/PostToolUse 的 `session_id + turn_id + tool_use_id` 一致；例如 `a-write-allow` 的两端均为 `call_a-write-allow_0`。
- **PermissionRequest 缺少 tool_use_id 与 request_id**，只有 session/turn 和工具输入。一个 turn 内多次相同命令、重试、并发工具无法只靠它精确对号；命令/参数哈希也不能消除重复。
- 原生 app-server 审批包含 `threadId`、`turnId`、`itemId` 和 JSON-RPC 顶层 `id`；`itemId` 与对应 Pre/Post 的 call id 一致。serverRequest/resolved 给出 threadId/requestId，可用于撤销未决 UI；不等于 hook 自带了这些字段。
- `parallel-A` 和 `parallel-B` 真正并发，每个服务独立 home、项目和连接。A 回复 accept，只有 A 执行并有 Post；B 回复 decline，B 未执行。两个连接都使用 requestId `0`，没有串到另一会话。两个长等待 CLI 会话也有各自不同 session/turn，事件未混入另一文件。
- 此证据覆盖两个独立客户端连接，不覆盖一个桌面服务多窗口、多审批客户端同时回答或断线重连后旧请求重放。

建议将客户端实例/连接代次、thread、turn、item、requestId 一起作为授权键；没有准确身份就拒绝接管。不能用“最近一次 PermissionRequest”配“下一个 Post”维持精确人工等待数。hook 自己生成的 nonce 可对应自己的 IPC 等待，但不能冒充原生 requestId。

## 建议设计：停下 → 中断 → 授权

### 停下

可做实验性“到达下一检查点后暂缓”：仅同步 hook、有限等待，显示“已在此调用前等待”，释放后继续本调用。超时应显式 deny；故障和强制杀死 hook 仍可能让 Codex 继续，因此不能把这套方案标成可靠暂停或安全隔离。

若需要结束整轮，优先使用拥有会话控制连接的 app-server turn/interrupt，并等待对应轮次回执。本机不能依赖 Pre continue:false 或 Post stopped。要对现有 CLI/桌面提供这个按钮，须先验证连接归属和中断权限，不能启动一个新服务就假装控制了原服务。

### 中断

分开保存“轮次已 interrupted”和“工具进程已停止/尚未确认”。优先正式中断；只有对自己启动并持续登记的执行器，才考虑进程终止作为补充。应在启动时记录 PID、创建时间、会话归属，并用 Job Object 等受控执行边界管理后代；退出后复核存活和心跳，无法确认就显示未确认。

对现有 Codex 工具进程做事后祖先扫描，没有足够证据保证准确；目前不建议复制 Claude 的实现。完整访问、本地后台和未来远程执行需要分别验收。

### 授权与“异常不默认放行”

**直接复制现有 Claude 的“异常无输出”策略到 Codex 自动审批环境不合格。** 本次超时/崩溃后自动审查 allow 的两个成功执行样本就是反例。

可供后续验证的两级方案：

1. **有限的便利授权**：仅接管原生本来就需要人工审批的操作，确认 `approvals_reviewer="user"`、有限沙箱、无适用的已有批准规则/会话授权、无其他匹配 hook 返回 allow。诗音自身的超时、IPC 失败、异常 JSON、ID 不符、过期、服务重启全部显式返回 deny；只有来自当前有效请求、一次性消费的用户 allow 才返回 allow。hook 外层超时或进程崩溃来不及输出时，必须回到**尚未回答的原生人工框**，用户可以在原生界面重新明确批准。该保证依赖经验证的配置前提，不能宣称对所有 Codex 运行模式成立。
2. **严格授权边界**：若要求自动审批、其他 hook、hook 被跳过或客户端配置漂移等任意异常也不能放行，必须由独立执行器/沙箱或可强制的管理策略在执行前默认拒绝，并由唯一可信审批客户端控制请求；丢连接、校验失败、超时均拒绝且不能切回自动 reviewer。这是新的架构课题，本实验没有实现或证明。靠普通用户 hook 的 try/finally、Pre deny、调大 timeout 或不断轮询，均不能提供这个保证。

正常命令可能根本不进 PermissionRequest；客户端审批缓存、完整访问或被跳过的工具路径也不能靠此 hook 统一拦截。外部 UI 若无法证明上述配置与精确原生请求身份，应继续只观察，不显示可点击的授权控制。禁止自动修改用户审批策略来“帮忙”满足前提。

## 将来可能需要的配置与回滚

**本次没有改真实配置，也没有执行以下安装建议。** 一般 Pre/Post/PermissionRequest 默认 600 秒，已经足够本次 125 秒实验；要等待两分钟不需要额外的全局 timeout 开关。

| 未来需求 | 需审核的实际变更 | 回滚方式 |
| --- | --- | --- |
| 安装控制 hook | 有效 CODEX_HOME 的 hooks.json 中增加精确归属的同步 PreToolUse/PostToolUse/PermissionRequest 定义；只为自己的条目设置 timeout（例如 180），保留其他定义 | 保存原有布局和条目归属；卸载只删除自己的定义并恢复自己改过的 timeout，不覆盖整个文件 |
| hook 定义/timeout 改变 | 定义 hash 会改变，按官方入口重新审核信任 | 恢复原定义；不删除、伪造或覆盖用户其他信任记录 |
| 限制便利授权为人工审批 | 显式审核有效 config.toml 的 `approval_policy`、`approvals_reviewer`、`sandbox_mode` 及适用的 `.rules`/已有会话授权；会改变用户日常操作体验 | 逐字段恢复安装前值/缺省状态；已有运行服务可能仍持有旧配置，需在无活动任务时验证重载，不能假设磁盘回滚已改变活动会话 |
| 严格失败关闭 | 可能需要 admin requirements/执行器等新的边界 | 必须另行设计和授权；本报告不提供未经验证的全局策略配方 |

配置写入仍应采用现有阶段 1 事务、差异展示和用户确认流程；不得把实验的一次性 hook-trust 标志用于正式安装。CLI 临时 unelevated 配置及其信任全部留在实验 home，不需要用户真实环境回滚。

## 证据、失败尝试和交付检查

本地证据集中于 Git 忽略目录 `build/codex-control-20261030/`：

- `lab.py` / `run.py` / `extra.py` / `winproc.py` / `limits.py`：独立探针、回环响应器、实验编排与 Windows 进程句柄检查；没有导入诗音。
- 每用例 `spec.json`、`hook.jsonl`、`model-*.json`、`rpc.jsonl` 或 `stdout.jsonl`、`result.json`：只有固定合成任务；日志中可能含临时绝对路径，不纳入提交。
- `summary.json`、`parallel.json`、`timeout-bounds.json`：结构化汇总；TUI 转录另存 `tui-transcript.txt`。转录存在 ANSI、终端截断，故标识/进程证据同时依据 hook 文件，不能仅依赖画面文本。
- `protected-before.json` / `protected-after.json`：只保存真实配置哈希，不复制内容。核验对象为真实 Codex config/hooks、Claude 用户配置及仓库 `.codex/config.toml`、`.codex/hooks.json`。
- `verification.json`：**62 项证据一致性检查通过**，包括执行退出码、拒绝、Pre/Post 配对、两个长等待、并发请求作用域、取消及中断后的进程存活/清理。上述六个配置对象前后哈希/不存在状态全部一致。收尾进程表仅余实验前已有的两个 Codex 进程，没有实验 Python 或额外 Codex 服务；两个回环响应器已结束。`evidence-manifest.json` 保存本地证据文件 SHA-256，未提交运行日志。

失败尝试未算通过：第一次 app-server 信任 key 被 API 路径的点拆分，临时 hooks 被跳过；改为单次精确 hooks.state 写入、重启并核对 trusted 后才进入正式组。一次临时配置原子保存失败，后续成功样本另名保留，没有覆盖失败现场。untrusted 启动错误已单列；初次全系统 WMI 查询被拒绝，后改精确句柄检查。短暂尝试 import 未安装的 psutil 失败后，改用标准库 ctypes，没有安装新依赖。TUI 会请求标题等额外模型调用，固定响应器可能在同轮产生多次固定命令；不把模型请求总数当工具数或人工请求数。

没有重跑产品全量测试：本次只新增实验报告并更新进度，产品代码未改；运行真实隔离用例、核对命令退出状态/进程表，并执行暂存区隐私检查与 git diff 检查。桌面 GUI、同一服务多客户端竞态、非 Bash 工具覆盖、长期暂停故障恢复继续列为待验收，不阻塞本报告的本地提交。
