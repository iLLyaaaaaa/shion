# a55825f 调度 GUI 独立审查修复

日期：2026-10-29。分支：`feature/v2-observer-lease-scheduler`，起点：`a55825f`。本轮仅修复用户列出的调度问题；没有打包、运行集成包、改动 Shion-dev、合并 hotfix 或 push。开工时只读检查运行路径，只有 Shion-dev 的两个 Shion.exe，没有 `build/integration-package` 下的实例，无需结束进程。

## 修改与恢复语义

1. **没有 coverage 的中性待机**：空候选返回 P5 `idle_unconfirmed`，三语说明观察覆盖未确认，允许原 idle 精灵和正常待机动作。只有显式 `confirm_coverage()` 才显示“空闲已确认”，生产路径仍不伪造 coverage。`test_idle_requires_explicit_coverage_and_is_not_persisted` 改名为 `test_idle_without_coverage_is_neutral_and_coverage_is_not_persisted`，验证初始状态、Claude 停止后、待机动作许可及切换后的 coverage 清空。改变原因是旧测试把“不能证明全局空闲”等同于“发生了故障”，而生产代码没有完整活动快照能力，导致正常待机一直报警。未知身份/能力仍显示待确认，P2 的未知展示使用中性 idle；原 P1 人工请求和 P3 中断的停止表情保持其原用途，失联/可信失败仍用 stop。

2. **ChatGPT 空档不再永久压住 Claude**：v2 使用按 provider 选择任务的 `observation_gap()`，不调用会永久置全局 `ledger.uncertain` 的旧 `disconnect()`。旧活动转 `uncertain`，保留去重墓碑、不伪造终态或成功；这种已知空档是 P5 待确认候选，可被其他来源的 P4 健康工作覆盖，无工作时仍显示待确认。停用/重开只暂停旧任务的观察契约，不把人为暂停当作租约故障。新的非重复有效活动恢复该任务，心跳和重复包只证明连接；切换前接收的延迟包不能跨过空档。新的完整 turn 结束后，旧未知任务也不会复活。队列降级标记在 v2 中被消费；当前批次和缺包之间顺序不明，保守丢弃该批次，后续批次可正常接入。队列空档仍保留原租约监测：10 秒确实没有心跳就是 P2 失联，恢复心跳后旧任务仍未知。该方案不靠超时猜测任务完成，也不靠清空所有任务掩盖断连。

3. **Claude 连接行独立保留**：删除对原 `status_action` 的 `setText()`，该行的文字/禁用状态保持 `b3b40a2` 的逻辑；v2 状态新增独立禁用行，同样按 240 逻辑像素截断并提供完整 tooltip。测试覆盖三语和 connected/disconnected/stale/error 四种 Claude 状态。

4. **切换不制造失联提醒**：切换 v2 时活动任务转待确认，清空 coverage、展示通知和旧选择/前台绑定，保留去重信息。测试分别覆盖有/无租约的任务、关闭时继续 tick、超过旧租约时长后重开，以及不弹出 ChatGPT 失联提示。

5. **attach 冲突降级**：两个不同 ledger 已经有 GUI 活动时，记录 WARNING，返回失败并停用当前 v2 展示，继续旧 ChatGPT poll/Claude 展示，不合并或重建不明任务。测试覆盖 tick、显式启用和 observe 三个入口。tick/observe 的运行期降级不改存档中的开发者偏好，下一次启动仍可重试；显式启用失败则保存实际未启用状态。没有引入新的异常来打断 tick。

6. **心跳进入 core**：v2 启用时，真实 inbox poll 将心跳送到 `Scheduler.heartbeat()`，让 ledger 租约和 core 请求失效维护一起执行。测试直接调用 poll 后检查请求已转未知，避免后面的 GUI select 掩盖漏维护。关闭时仍走原 ledger 路径，心跳不计作生命周期事件。

## 先复现再修复

写完测试后、修改任何产品代码之前，在 HEAD `a55825f` 执行：

```powershell
.venv\Scripts\python -m pytest tests/test_scheduler_review.py tests/test_scheduler_gui.py -k 'test_scheduler_review or idle_without_coverage' -q --basetemp=.venv/preview-run/scheduler-review-red
```

汇总原文：`24 failed, 3 passed, 25 deselected in 10.57s`。六项问题都有失败用例；当时 `git diff --stat -- shion assets` 为空。日志：`.venv/scheduler-review-red.log`。

关闭开关的三语基线在未改产品代码的 `a55825f` 上采集并通过。`tests/fixtures/scheduler_disabled_a55825f.json` 固定七个阶段：idle、工作、权限请求、结束、inbox 降级、ChatGPT 停用、重开。逐阶段比较双击状态全文、ChatGPT 状态全文、事件/工作计数、精灵，以及递归菜单结构/文字/禁用/勾选/tooltip 的 SHA-256。菜单摘要由规范 JSON 计算，不依赖截图或字节码；完整文本采集日志保留在 `.venv/preview-run/scheduler-review-baseline/`。测试无自动更新基线分支。

## 最终验证

- 定向回归：`121 passed in 34.02s`；此后只隔离了一处测试的随机待机动作，产品代码未变。新增回归、核心、GUI、租约、ChatGPT 与三语菜单均覆盖。
- 首次最终全量：`1 failed, 1773 passed, 9 skipped, 2 warnings in 519.37s (0:08:39)`。唯一失败为原 `tests/test_permission.py::test_no_http_route_can_set_a_decision[extra4]` 发 HTTP 请求时遇到 `ConnectionAbortedError [WinError 10053]`，未到业务断言；本轮未改该测试或 server。未改任何产品/测试代码，单独重跑整个权限模块：`94 passed in 44.15s`。原因未确定，记录为本次出现后未在定向重跑复现的传输异常，不推断为某一组件故障，也不加重试或改范围外代码。
- 最终全量 pytest（相同最终代码重新完整运行，退出码 0）：`1774 passed, 9 skipped, 2 warnings in 512.05s (0:08:32)`。两条警告均为原 Pillow `Image.getdata()` 弃用提示。日志：`.venv/scheduler-review-full-recheck.log`；首次完整运行保留在 `.venv/scheduler-review-full.log`，权限模块重跑在 `.venv/scheduler-review-permission-recheck.log`。没有把首次失败结果、定向结果或修改前启动的全量当作最终通过结果。
- `tools/check_private.py`：`PASS: tracked files privacy patterns`（14 个修复文件已逐文件暂存后扫描，包含新增测试、基线和报告）；`git diff --check` / `git diff --cached --check` 通过。Author/Committer 均为 `201329225+iLLyaaaaaa@users.noreply.github.com`，仓库邮箱原本正确，无需改配置。
- 开工时的 11 个未提交/未跟踪文件逐一 SHA-256 核对通过；暂存中只有本轮的 14 个文件。最终全量启动前记录产品代码、资源和测试哈希，全量后再次核对通过；测试启动后只回填本报告的验证结果，没有修改产品代码、资源或测试。

全量命令：

```powershell
.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/scheduler-review-full
.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/scheduler-review-full-recheck
```

用户原有 `docs/progress.md`、八份未跟踪实验文档和两个实验脚本均不修改、不暂存。结果另写本报告。测试仅使用隔离用户 fixture、Qt 离屏、假时钟和合成元数据；不声称实际客户端、多屏、焦点或视觉手感已人工验收。

## 范围外与限制

- `hotfix/v1.0.1-hook-latency` / `1f54cb6` 保留，未合并。
- 真实 Claude 仍缺可靠 turn_id、真实前台缺完整任务绑定，生产端仍没有可信 coverage 快照；本轮没有扩展协议或补造能力。
- 缺身份、来源冲突或容量耗尽设置的旧全局不确定标志，不属于本轮断连/开关恢复路径，仍保守保留；本轮没有增加容量回收或跨进程去重。
- 关闭 v2 的旧 disconnect/degraded 行为刻意保留，以满足与 `a55825f` 相同的菜单、状态及计数合同；本轮不顺带改旧路径。
- 原有 ChatGPT 状态仍注明仅本次观察、没有历史快照。旧未知任务不会因新 turn 完成而被猜成成功；它们可在无更高优先级工作时重新显示待确认。
- 原打包/隔离集成验收停止，没有续跑，也没有以此前全量结果替代本轮最终全量。
