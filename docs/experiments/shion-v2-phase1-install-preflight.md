# 阶段 1：真实全局安装前检查（2026-10-27）

用户已批准按最新精确差异安装。本次在写入前检查 Windows ACL 时停止，未执行安装或真实客户端验收。

- 已审核基线与当前 `C:\Users\<user>\.codex\config.toml` SHA-256 一致：`d17efa0d3177e1dbd556a7c9941b119e099418f309972c8f2aa5286d0678bc26`。
- 用户级 `hooks.json` 仍不存在，与预览一致。原配置未写入；node_repl、notify 和七项禁用信任记录保留。
- `.codex` ACL 向 `CodexSandboxUsers` 授予 `ReadAndExecute, Synchronize`，带 `ContainerInherit, ObjectInherit`。Shion 用户数据目录也继承了该组的同类读取权限。
- 现有安装器会在 `.codex` 保存备份与 `.shion-lifecycle-v1.json`，其中包含原配置；凭据写入 `%APPDATA%\Shion\chatgpt-observer.json`。尚无证据保证这些新文件排除上述组的读取权限。因此按用户要求第 5 条停止，不生成敏感文件，不修改任何目录 ACL。

本轮没有新增全局配置、Token、事务备份、归属文件或信任记录，没有启动安装事务，故无需回滚。未执行 CLI、Windows 桌面客户端、Claude/ChatGPT 并行及离线、MCP 故障、超时、多会话性能验收；真实事件和延迟均无本轮结果。此前合成测试不能替代此次验收。

下一步须由用户审核敏感文件的最小 ACL 处理方案；不得默认为允许更改 `.codex` 或其他无关目录权限，也不得将本次停止解释为已批准扩大安装范围。恢复安装前重新核对基线和目标状态，随后经官方流程由用户逐项审核 Hooks。

正式发布前必须迁移到稳定安装路径，消除对当前开发目录和 `.venv` 的依赖。本轮未提交、推送、合并、发布，也未进入阶段 2/3。
