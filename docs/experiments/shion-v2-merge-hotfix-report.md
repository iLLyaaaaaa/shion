# 热修合并与隐私补扫报告

日期：2026-10-29。分支：`feature/v2-observer-lease-scheduler`。未 abort、未 push、未打包，未改动 Shion-dev 或未跟踪实验材料。

## 提交及原有记录

- 原 `docs/progress.md` 的 11 行先原样保存为 `3548f23`，父提交 `ef1149a`。提交前全文匹配环境变量实际值，`USERNAME`、`COMPUTERNAME` 均无命中；报告不记录实际值。旧隐私扫描也通过。开工文件 SHA-256 为 `2F022316946EDA712756B9EA776D074C6534A7F8DEF276F12C6A9DC7C95EFE96`，与上一任务完全一致。
- 保留原合并现场继续处理；合并提交为 **`c0e748284eb9092b5e0adad8d2e1187e91a63a97`**，父提交为 `3548f23`、`1f54cb6`。
- 仅解决检查工具和进度两处冲突。进度冲突区的我方 17 条、对方 2 条全部保留，按日期倒序（沿用文档既有顺序）排列；同日热修记录在较早的 V2 GUI 记录前。原 11 行逐行验证仍各出现一次，内容不变；保留热修对待办复选框的更新。
- `hooks/shion_hook.py`、`tests/test_hook.py`、`tests/test_hook_latency.py`、`AGENTS.md`、`CLAUDE.md` 与 `1f54cb6` 完全一致；没有额外修改 V2 产品代码。

## check_private.py 合并方案

以 `74121dc` 的实现为基础：环境变量运行时读取，名字大小写不敏感匹配，路径和内容均检查；默认读 Git 索引 blob，`--ref` 读指定提交完整树。保留 CLI 参数、`main` 调用接口和退出码 0/1/2，保留原名字检查函数供原测试使用。`AGENTS.md`、`CLAUDE.md` 按原接口调用，本地 pre-commit hook 未修改，并在合并提交时实际调用成功。

新增共享的 `scan_files()`，在两种输入模式上同时检查个人 Windows 用户目录、私钥头和 API 凭据三类 V2 模式。二进制 blob 也不跳过。所有 CLI 命中输出只包含脱敏位置、行号和类别，不输出内容摘录；名字用 `<USERNAME>` / `<COMPUTERNAME>`，路径本身若含凭据也先脱敏，避免名字命中行或文件名顺带泄露密钥。

`tests/test_check_private.py` 保留原五项测试的断言，新增二十项用例，覆盖三类附加检查的暂存区/历史快照、索引与工作区差异、路径/二进制、V2 各凭据前缀、占位目录和输出脱敏。原测试的虚构个人目录改为等价字节拼接，避免源码自己命中附加扫描；“非仓库”用例使用 Git discovery ceiling，避免仓库内 basetemp 被识别成父仓库，仍真实调用 Git 验证退出码 2。

## 逐提交补扫

本地 `master` 为 `74121dc`。合并提交完成后，使用合并好的脚本，按 `git rev-list --reverse master..HEAD` 枚举，下表每个提交都单独执行 `python tools/check_private.py --ref <完整提交哈希>`。扫描的是每个提交的完整文件树，不是只扫补丁或最后一个提交。

| 提交 | 退出码 | 结果 |
| --- | --- | --- |
| `e6e3865` | 0 | 未命中 |
| `fe78a25` | 0 | 未命中 |
| `5dc9eda` | 0 | 未命中 |
| `c847994` | 0 | 未命中 |
| `c6889c3` | 0 | 未命中 |
| `ce732f2` | 0 | 未命中 |
| `a55825f` | 0 | 未命中 |
| `1f54cb6` | 1 | 虚构目录测试字面量，见下文 |
| `ef1149a` | 0 | 未命中 |
| `3548f23` | 0 | 未命中 |
| `c0e7482` | 0 | 未命中 |

合计 11 个提交：10 个退出码 0，1 个退出码 1，没有执行错误（退出码 2）。`1f54cb6` 唯一命中位于 `tests/test_check_private.py:25`，类别为 `personal Windows profile`，对应原 master 测试中的虚构 Windows 用户目录字面量；不是本机用户名/机器名命中，也没有私钥/API 凭据命中。当前合并版已改为等价字节拼接，测试输入不变，合并提交退出码 0。历史快照的退出码 1 如实保留，没有豁免规则，也没有改写历史。

同一范围 Author/Committer 均为 `201329225+iLLyaaaaaa@users.noreply.github.com`；提交消息额外检查本机名字及凭据类别，没有命中，署名邮箱均为 noreply 类地址。实际名字、匹配内容或密钥均不写入报告。

本报告的后续文档提交会再用 `--ref HEAD` 补扫；交付时的最终完整范围、完整提交哈希、退出码和脱敏输出保存在 `.venv/merge-hotfix-ref-audit.json`，文档提交自身的结果另在交付消息汇报。

## 测试和收尾检查

- 隐私专项原文：`25 passed in 11.74s`。
- 三组定向原文：`86 passed in 44.37s`，包含 `tests/test_check_private.py`、`tests/test_hook.py`、`tests/test_hook_latency.py`。
- 最终全量原文：`1829 passed, 9 skipped, 2 warnings in 583.31s (0:09:43)`，退出码 0，basetemp 为 `.venv/preview-run/merge-hotfix`；两条警告均为既有 Pillow `Image.getdata()` 弃用提示。
- 合并提交前默认暂存区扫描通过；本地 pre-commit 扫描通过；`git diff --check` 和暂存白名单检查通过，合并提交仅包含八个预期文件。

```powershell
.venv\Scripts\python -m pytest tests/test_check_private.py tests/test_hook.py tests/test_hook_latency.py -q --basetemp=.venv/preview-run/merge-hotfix-focused
.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/merge-hotfix
```

日志在 `.venv/merge-hotfix-private-focused.log`、`.venv/merge-hotfix-focused.log`、`.venv/merge-hotfix-full.log`。全量启动前记录代码、资源和测试哈希，全量后逐项核对通过；测试启动后仅回填本报告，没有修改产品代码、工具、资源或测试。没有用合并前的全量结果替代本轮测试。

原 `docs/experiments/`、`tools/experiments/` 下十个未跟踪文件不编辑、不暂存、不提交。本报告单独位于 `docs/`。自动化通过不代替已有的真实客户端/桌面人工验收。
