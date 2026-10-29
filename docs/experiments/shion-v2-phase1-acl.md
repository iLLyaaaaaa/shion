> 已废弃，仅作为决策记录保留

# 阶段 1：最小 ACL 安全修订（2026-10-27）

状态：已实现专用私有存储并完成隔离专项；**未安装真实全局配置，桌面 MCP 身份未验证，不能据此重新安装或发布。**

## 方案与允许的权限

应用拟使用 `%APPDATA%\Shion\private-v1`，仅在未来安装/运行获准后创建。Token、配置原文备份、归属记录、事务日志和写入暂存文件集中于此。低层配置 API 的缺省隔离位置为指定配置 home 下的 `.shion-private-v1`；实际应用显式传入上述应用私有目录。不同配置 home 的归属文件以规范路径哈希区分。

创建时通过原生 `CreateDirectoryW` / `CreateFileW` 的 SECURITY_ATTRIBUTES 指定受保护 DACL，拒绝父目录继承。仅允许实际进程用户 SID、SYSTEM（S-1-5-18）及 Administrators（S-1-5-32-544）完全控制。目录 ACE 可向子项继承，但本模块创建的每个文件仍使用显式受保护 DACL。验证对象 owner、每一条 ACE 类型、SID、权限和继承标志；禁止额外 ACE、重解析点和私有文件硬链接。检查失败停止，不修复已有目录或扩大权限。

不改用户主目录、`.codex`、AppData 或原 Shion 目录 ACL；不改 CodexSandboxUsers、沙箱模式、原信任记录，也不复用阶段 0 身份。真正的边界是 Windows 用户令牌；同一用户下的其他非沙箱进程仍可读取，不能把 ACL 当作进程间隔离。管理员/SYSTEM 是此方案明确允许的主体。

## 代码

- `shion/private_store.py`：Windows 私有目录/文件创建、句柄 ACL 验证、安全读写、配置替换及最终权限验证。无新增依赖。
- `shion/observer.py`、`shion/chatgpt.py`、`shion/codex_mcp.py`：Token 创建、读取、开关更新均经过私有存储；MCP 无权限时保持中性、不阻断。发现旧公共位置凭据时停止，未经审核不搬迁或删除。
- `tools/codex_config.py`：备份、归属、锁、journal 移入私有目录；预览记录配置 ACL，写入前检测内容及权限变化。备份先验证权限再保存原文。失败回滚保存的内容和权限；回滚失败保留锁及私有恢复材料，禁止下一次事务覆盖。
- `tests/test_private_store.py` 及现有专项：真实 Windows API 和失败注入。
- `tools/experiments/mcp_identity_probe.py`、`isolated_mcp_acl.py`：仅用于合成数据的客户端身份/传输验证，不输出 Token，不创建 Hook 或模型任务。

## 原子替换、安装和卸载

所有新明文暂存文件先在私有目录建立受限 ACL，验证后才写入。现有配置通过 ReplaceFileW 替换；原配置的 owner、DACL、保护位及各 ACE 最终必须相同。Windows 在跨父目录替换时可能重算继承 ACE，因此替换后的文件必要时恢复其**原始 DACL**并再次比对；这不是收紧或放宽原配置的权限。SE_DACL_AUTO_INHERITED 仅是系统记账位，比较时忽略它，各 ACE 的继承标志仍逐项保持。

文件内容替换与最终 DACL 恢复不是单一系统调用。崩溃可能留下需人工核对的事务，journal 在写入前保存原安全描述符；不得声称跨文件或权限元数据全程事务原子。出现权限恢复/并发冲突时保留恢复材料和锁，不自动覆盖未知内容。私有暂存与目标必须同卷，无跨卷明文复制兜底。

实测遇到 ReplaceFileW 偶发 1175 错误；仅针对共享/占用错误 32、33、1175，在原内容与 ACL 均未变化、临时文件仍存在时最多尝试四次，等待总计最多 120ms。权限拒绝、部分替换或外部变更不重试。最终专项覆盖该分支及外部修改保留。

卸载仍只移除有精确归属证据的片段，保留用户后来新增的配置和客户端信任记录；归属文件被删除，但私有 Token、备份和 journal 留在受限目录供恢复/后续体验。彻底清理这些材料需另行确认。旧公共归属文件不会被静默读取或迁移。

原 `config.toml` 可被当前沙箱读到，属于现有文件的权限情况；本次不修改其访问策略。修改副本只在私有目录落盘，未在 `.codex` 新建明文备份。

## 测试证据与边界

| 检查 | 结果 |
| --- | --- |
| 最终专项 | 38 passed，5.80 秒；`security-final3.log` |
| 全量回归 | 修正前启动的全量：1608 passed、9 skipped、1 failed、2 warnings，559.44 秒；唯一失败为备份/卸载专项的 WinError 1175。该失败已由有界重试修正并包含在最终 38 项通过结果中；未重复整套全量，不能标为全量全绿 |
| 替换稳定性复核 | 最终代码连续 40 次隔离安装/卸载全部通过，原内容与 ACL 均保留、无暂存文件残留，10.13 秒；`replacement-stress.json` |
| 正常用户 | 私有文件创建/读取/更新、Token 替换及子进程重启通过；owner 和三个允许 SID 已核验 |
| 实际沙箱账户 | CodexSandboxOffline 对 8 个已知文件路径均读取失败（errno 13），包括 Token、备份、归属、journal、临时文件；`sandbox-access.json` |
| 其他身份 | 未以 CodexSandboxOnline、SYSTEM 或提升的管理员实际登录访问；不把 ACL 条目当作这些身份的实际测试 |
| 失败路径 | 目录/文件权限验证失败先于 payload；拒绝扩大 ACL、硬链接、旧凭据；替换失败清理临时文件；安装失败恢复内容及 ACL；回滚失败保留私有备份与锁 |
| CLI MCP | 真正 `codex app-server` 启动观察进程，实际 TokenUser 为桌面用户 SID、Medium 完整性、Administrators 为 deny-only；受保护测试凭据可读，状态 connected |
| MCP 传输 | 20/20 个明确标记的合成元数据经 Codex MCP 通道送达；中位数 16.00ms、p95 31.53ms、最大 34.15ms |
| 桌面 MCP | 未取得运行令牌证据。官方 `app-server proxy` 连接控制套接字失败（Windows 10050），initialize 未完成；不修改桌面配置来绕过 |

CLI 证据是官方 app-server MCP 通道，**不是交互 CLI 全任务验收，不是全局 Hook 延迟，不是桌面 UI 验收**。真实全局 Hook、信任启用和 Claude/ChatGPT 并行验收留待安装重新获准后进行。桌面尚未验证，不应宣称其兼容性通过；若以后实际 MCP 使用不同 SID，应停止并评估受控本地代理/命名管道等替代方案，不给沙箱账户开放 Token。

日志均在项目忽略目录 `.venv/preview-run/phase1-acl/`。测试生成的 Token、配置和事务数据均为隔离合成数据；真实用户目录中没有新增私有目录、凭据、Hooks 或归属记录。失败注入的恢复材料和被故意扩大权限的假数据仍留在该测试目录。未触碰真实 Claude 配置。

## 修订后的全局安装精确差异

仅生成预览，未应用：

- `.venv/preview-run/phase1-acl/global-install-revised.diff`
- `.venv/preview-run/phase1-acl/global-install-revised-audit.json`

最新只读基线 SHA-256：`740fa9b1c6dcb0964fd23bbe04d89fc19779b678e9218b2f079a6b3178cd85e5`。它已不同于先前审核的 `d17efa0d…678bc26`，本轮未写入真实配置，不推断外部变化原因。`hooks.json` 仍不存在，node_repl、notify、七项已禁用信任记录仍在。后续安装必须重新审核这份差异并再次核对基线。

与上次方案相比，MCP 的 `--data-dir` 指向 `Shion\private-v1`；MCP 名称、七个事件、matcher、超时和元数据投影均不变。新增敏感存储文件不出现在 config/hooks 差异中，具体位置和内容在本报告前文列明；归属记录包含原配置，禁止上传。

**安装后全局配置仍将指向开发目录与 `.venv`。卸载前不能切换到缺少实现的分支、移动或清理开发目录。正式发布前必须迁移到稳定安装路径。**

## 与“不保留原配置副本”方案的比较

参考本地新增审查意见，评估但未擅自切换设计：

| 方案 | 代码及风险 | 能力取舍 |
| --- | --- | --- |
| 本次私有 ACL + 原文备份 | 新增约 300 行 Windows 安全存储实现；需要持续维护原生 API、SID、继承、原子替换与权限恢复测试 | 保留完整原文和权限恢复证据；仍需防崩溃/并发修改；明文副本虽受限但存在 |
| 归属只存哈希、长度及插入片段 | 可删掉备份/归属中的原文；配置算法及迁移须另行设计、审核，不能直接假设任意 Hooks 合并只需截尾 | 减少持久明文；仅截尾会与后来追加的信任/用户设置冲突；崩溃后的复杂恢复能力降低 |

后者仍须保护 Token；将 Token 留在原有宽权限目录不符合本次用户要求，不作为默认替代。Token 外泄在当前阶段可能伪造观察状态/提醒，不会直接进入 Claude 控制或奖励，但这并不构成放宽权限的授权。

本轮不提交 Git、不推送、不合并、不发布，不进入阶段 2/3。等待用户审核代码、桌面验证缺口和新的安装基线。

机制参考：[Microsoft 文件安全与访问权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)、[OpenAI MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp)。文档机制不替代上文实际访问及客户端测试。
