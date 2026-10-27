# V2.0 阶段 1 精简修订交付记录

日期：2026-10-28。开发与自动隔离验证已实施；**真实工具 matcher 覆盖与桌面生命周期尚未验收，阶段 1 未完成**。本轮没有写真实 Codex 配置、安装正式 Hooks、push、合并 master 或发布。

## 代码结构与范围

| 文件 | 变更 |
| --- | --- |
| `tools/codex_config.py` | 保留原安装器入口；改为 v2 精确插入归属记录、结构/语义验证、预写日志、保守且可重复的 `recover()`；取消三类工具事件 matcher |
| `shion/observer_files.py` | 标准库用户目录文件读写、重解析点拒绝、独占暂存、flush/fsync、原子替换；已有 Windows 配置通过 ReplaceFileW 保留 DACL |
| `shion/chatgpt.py`、`shion/observer.py` | Token 与归属信息使用 Shion 用户数据目录，不再使用独立 `private-v1` |
| `shion/codex_mcp.py` | 凭据结构、端口与令牌字符校验；异常 JSON 深度中性失败 |
| `Shion.spec` | 仅 Observer 启动跳过 PyInstaller 的 PySide6 运行时钩子，其余模式保留上游钩子 |
| `tests/test_codex_config.py`、`tests/test_codex_observation.py` | 崩溃恢复、硬终止、权限保留、字段安全、速率边界、不加载 GUI 回归 |
| `tools/experiments/observer_acceptance.py` | 打包程序协议、故障与多进程资源验收 |
| `tools/experiments/isolated_observer_client.py` | 独立 CODEX_HOME 下真实 app-server 到打包 MCP 的合成调用验收 |
| `tools/check_private.py` | 提交前检查本地用户路径和常见凭据模式；只输出位置/类别，不打印匹配内容 |

删除上一轮尚未提交的 `shion/private_store.py` 与其独立 ACL 测试；未改动 Claude 控制通道、资源、依赖及三语界面文案。版本源仍为 1.0.0，本产物仅是 V2 阶段 1 开发测试包，不是 2.0 正式发行。

## 安装事务与恢复

归属记录保存每个文件的原长度、前后 SHA-256、插入位置、Shion 插入片段及片段哈希，不保存用户原配置全文。事务日志在任何配置变更前写完并 fsync；成功后删除日志与锁，不留原配置副本。配置替换期间的暂存文件不可避免含目标配置全文，但仅用于原子替换，不作为备份长期保留。

卸载先反向验证精确片段，再解析 TOML / 严格拒绝重复键的 JSON，并比较去除 Shion 定义后的无关配置语义。恢复先检查所有文件、归属和暂存，再逐项执行；文件只能处于事务记录的已知前/后状态。日志或归属证据缺失、外部修改、未知/部分暂存、重复定义或片段不明确时停止，保留现场。不猜测删除，不把相似文本当作归属。

**保守限制**：客户端信任审核也可能修改 `config.toml`。本版不会自动接受这些新字节，随后自动卸载/恢复将停止，需重新人工审核配置差异；没有实现自动合并信任记录。不要手工删日志以绕过这一检查。

测试覆盖安装与卸载各 4 个中断点，恢复时再次中断，再次恢复与重复恢复；另外用子进程 `os._exit(73)` 在安装替换前、恢复替换前真实硬终止。完整已知暂存可恢复清理，部分暂存保持不动。已有配置的受保护 DACL 在安装和卸载后均保持。专项最终结果见下方测试汇总。

日志与证据均位于被忽略的 `build/slim/`、`.venv/preview-run/slim-*`；未读取真实 Claude 设置，未运行 `claude`。

## matcher 真实覆盖边界

当前 CLI 为 `0.164.0-alpha.11.1`。真实隔离 app-server 的 `hooks/list` 识别三类工具事件的 `matcher: null`，但信任状态为 `untrusted`；隔离 `account/read` 未登录。没有复制真实凭据、修改信任数据库或使用 Trust all。

| 场景 | 本轮结果 |
| --- | --- |
| 无 matcher 定义被真实客户端识别 | 已验证；七项 Hook 发现，仍未信任 |
| 本地 shell、apply_patch、其他本地工具的真实 Hook 投递 | 未验证 |
| MCP 工具的真实 Pre/Post/Permission Hook 投递 | 未验证 |
| 连续/并行工具、工具失败、取消与人工授权 | 未验证 |
| 新 matcher 的真实事件覆盖率、重复率、工具调用额外延迟 | 无有效样本，不能给出百分比或延迟承诺 |
| app-server 主动调用打包 Observer MCP | 30/30 合成事件收到，中位数 7.34 ms、p95 31.93 ms；响应仍为中性空对象，属于传输验证，不是 Hook 覆盖 |

[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)说明省略 matcher 匹配受支持事件，MCP Hook 错误/缺失服务不阻止操作；文档支持不替代本轮真实生命周期验收。阶段 0 的旧 matcher 结果也不能作为新定义已验证的证据。

本轮已请求用户完成隔离登录。下一次真实覆盖实验必须仍在隔离 CODEX_HOME 中，通过正常客户端逐项审核信任；不要写入真实用户级配置。桌面端需独立的受控本地任务身份和隔离设置证据，不能用 app-server 的 userAgent 或 CLI 成功冒充桌面验收。阶段 2/3 不在本次工作范围内。

## 打包 MCP 协议验收

正式测试命令为 `D:\desktop\tools\Shion-dev\Shion.exe --codex-observer --data-dir <隔离数据目录>`。完整目录运行，无仓库 `.venv` 路径依赖。测试驱动使用 Python 不代表被测 Observer 依赖 Python。原有 bundle smoke 97 项通过，包括搬移后的程序与 Claude hook 回归入口。最终 EXE SHA-256：`8e80618b274d7145786b7b87b928591df6714ce70cb289112d1f92fa15c78413`；指定开发目录与构建产物逐字节一致。

13 组验收覆盖：七类事件逐项在凭据缺失、损坏、类型错误、关闭、无效端口、接收端离线时的中性输出；正常 initialize/通知/ping/list；未知请求、非法元数据、伪造 observer、未展开变量、坏 JSON、超长帧；正常重复事件 14/14；接收端关闭；队列/速率压力；HTTP 200/400/403/429/500/503 的恶意响应体以及慢响应超时。

所有工具成功输出严格等于 `content=[{"type":"text","text":"{}"}], isError=false`；非法请求仅产生 JSON-RPC 错误，超长帧直接正常结束。接收端试图返回 block/allow/updatedInput/additionalContext 时内容被丢弃。不存在批准/拒绝、阻止执行、工具输入改写、上下文注入或 Claude 控制请求输出。协议层结果成立；实际客户端异常 Hook 的工具继续执行仍需上述真实覆盖实验。

保留 Bearer Token、元数据白名单、200 次/秒限流、512 条队列上限、150 ms 转发超时、1 秒 Hook/MCP 工具超时。Token 被本机有读取权限的进程获得后的影响限于伪造显示事件，不是授权凭证；不再声称独立 ACL 隔离。

## 多 Observer 资源测量

同机同时启动到 initialize 响应；每进程随后 100 次 ping；工作集不等于独占物理内存。空闲采样 2 秒，Windows CPU 计时粒度有限，0 增量不表示绝对零开销。结果会受负载/缓存影响。

| 并发进程数 | 启动中位数 ms | 单进程工作集 MiB | 空闲 CPU 增量 | 100 ping/进程总 CPU 秒 | ping p95 ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 233.38 | 21.94–21.94 | 0 | 0.000000 | 0.202 |
| 4 | 358.66 | 21.80–22.08 | 0 | 0.031250 | 0.829 |
| 8 | 502.77 | 21.75–22.04 | 0 | 0.000000 | 1.587 |

三个场景均枚举加载 DLL 并确认没有 Qt/PySide 模块。源码入口另有不导入 `PySide6` / `shion.pet_window` 的测试。单 EXE 方案可运行，无需增加 Observer EXE。这里是启动/空闲/协议负载测量，不是模型工具端到端延迟。

## 全局安装精确差异（只读）

最新完整机器路径差异与元数据仅存本地：`build/slim/global-install.diff`、`global-install-audit.json`、`global-ownership-proposed.json`。没有应用。

| 目标 | 当前 → 提议 |
| --- | --- |
| 有效 CODEX_HOME/config.toml | 4923 → 5141 字节；只追加独立 MCP 表 |
| 有效 CODEX_HOME/hooks.json | 不存在 → 1724 字节；七类元数据 Hook，三个工具事件无 matcher |
| 用户 Shion 数据目录的归属文件 | 不存在 → 3022 字节；v2 插入证据，无原配置全文 |

config 基线 SHA-256：`0040c496f869baea01df291c8caf503fa9b42d2c11eb21fdd0a41a240a8b6271`。
config 提议 SHA-256：`c6c91800a3ade6614894d6de05598761bf79bf035278dc6928c835a57d246bd1`。
hooks 提议 SHA-256：`3e4929662ae33d43fc0d39b861dd1b788378b2da496e37c1d0c0acaf619c1d03`。

目标命令固定为开发目录 EXE；数据目录为用户 `%APPDATA%\Shion`，Token 不写入 Codex 配置。原七条禁用信任记录和 notify 保留。首次真实安装前必须重新核对这些基线哈希并由用户单独批准；哈希不同则重新生成差异。

## 测试汇总、回退与剩余风险

首轮全量：1609 passed、9 skipped、2 条既有 Pillow 警告。第二轮全量：1618 passed、9 skipped、2 条既有 Pillow 警告（561.67 秒，日志 `build/slim/full-final.log`）。第二轮全量在最后的 Windows 替换/DACL 修订前启动；该最终修订随后单独通过 43 项专项（`build/slim/target5.log`），并重打包通过 97 项自检、13 组 EXE 验收及 30/30 app-server 传输复测。没有把早一轮测试声称为最终修订后的整套重跑。

Claude 自动回归包含原全量测试及 97 项 bundle smoke；没有执行真实 Claude 登录、授权、桌面交互，焦点/高 DPI/真实 Claude 联动不能由自动结果代替。人工桌面验收和无 Python 干净机器验收仍未完成。

未提交生成物、真实配置、Token、事务日志或构建证据。提交前执行 `tools/check_private.py`、对应测试与 `git diff --check`；该脚本是有限模式检查，不等于专用秘密扫描器或发布范围审计。

本轮仅本地提交，最终提交哈希见交付回复。源码回退使用 `git revert <本轮提交哈希>`，不改写历史。回退前先确保没有活动隔离事务；已安装的测试配置应由当前版本卸载/恢复，不要用旧代码猜测清理。真实全局配置没有安装，无需真实全局卸载。开发 EXE 目录可保留作证据，回退提交不会自动更换该目录。
