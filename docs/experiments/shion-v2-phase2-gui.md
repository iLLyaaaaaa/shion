# V2.0 控制菜单与调度 GUI 隔离接入

日期：2026-10-29。状态：开发预览接入；**不是正式客户端完整接入或人工验收通过**。只修改开发仓库，不部署、不操作真实 MCP/Hooks/Token/信任、不覆盖 Shion-dev、不 push/merge master/release。

## 整合来源与边界

- 工作分支 `feature/v2-observer-lease-scheduler`，起点 `ce732f2`，包含 `c6889c3` 的 Observer 2 秒心跳、10 秒租约及独立 Scheduler；`ce732f2` 已修复 Windows ACL 继承规范化测试。
- UI 来自独立干净工作树 `feature/ui-menu-refresh`：`d4a7add`（分组菜单）、`aec179f`（tooltip/原生字体渲染）、`b3b40a2`（ChatGPT 状态逐行显示）。共同基点 `c6889c3`。审查实际差异后通过 `git apply --check` / `git apply` 应用这三次提交的净改动；没有 checkout/reset/clean，也没有创建 merge 提交。
- 原有 `docs/progress.md` 的 11 条未提交历史记录和 9 个未跟踪实验文件保留，未纳入本轮提交。UI 原工作树未修改。

## 实现

- `scheduler_gui.SchedulerGUI` 是展示适配层，复用 `Scheduler`、`Observation` 和 `TaskLedger`。连接接收队列与调度器共用同一 ledger，不维护第二份逐轮生命周期。ChatGPT 统计按品牌筛选，关闭 ChatGPT 不修改 Claude 任务。
- `SaveData.v2_scheduler_enabled` **默认 false**，严格布尔校验。开发者可在隔离 Controller 上调用 `set_v2_scheduler_enabled(True)`；没有新增普通用户菜单开关，也没有修改当前用户存档。开关值可以随隔离存档保存；任务、通知、权限、前台绑定不写入存档。
- 关闭时沿用原有 Controller 路径。运行中切换保留去重墓碑，但活动任务转未知，清空展示通知与旧 coverage，不把观察空档当连续工作。重启为空任务表、未知覆盖，不能凭存档恢复工作、授权或成功。去重墓碑只在当前 GUI 生命周期内保留；跨进程持久化去重不是本轮实现。
- P1 使用可靠请求或现有 Claude 权限队列；P2 为失败/失联/未知；P3 为中性结束/中断；P4 工作；P5 仅有明确 coverage。高优先级覆盖不修改底层任务状态；P3 展示约 3 秒后确认移除，排队仍遵循核心原有 30 秒 TTL。相同合并通知 token 不重复弹出。
- 展示复用菜单状态行和双击状态；菜单分组/三语/截断 tooltip 保留，不扩大顶层项目数。权限不依赖折叠菜单：ChatGPT 显示持续只读提示；与 Claude 授权同时存在时，放在原授权面板底部的独立文字区，标题明确标识 Claude；没有 ChatGPT 控制按钮或控制信号。
- Claude 批准/拒绝、暂停/继续、中断、奖励仍走原 RemoteHub/状态机。统一元数据入口不会执行控制或增加奖励。ChatGPT Stop 只给中性结束展示，绝不计成功任务或好感度。静音时不播调度气泡，但权限提示仍可见。

## 两个必须保留的能力缺口

1. **真实 Claude Hook 缺少可靠 turn_id**：现有协议只有 session/tool_id/proc，无法在不扩展协议与客户端证据的情况下证明逐轮身份。没有用本地计数、最近事件、工具参数或内容哈希猜测轮次。真实 Claude 活动/权限以原状态与原请求队列作为展示候选参加仲裁，不进入伪造的逐轮任务表；原完成和奖励语义保留。完整 Claude 轮次去重、跨客户端同轮关联及完整结束队列仅在已规范化的合成事件入口验证，**尚未接到真实 Claude Hook**。
2. **现有前台跟随器没有完整任务绑定**：进程名只能用于窗口层级，不能验证会话/轮次。真实路径不设置 guessed foreground，使用核心的保持/公平轮转降级。完整任务键 `set_foreground(..., verified=True)` 的双向仲裁有自动化 GUI 证据，但没有真实前台窗口到任务的绑定器。

ChatGPT 当前 PermissionRequest 仍不证明人工等待，来源能力默认关闭；可靠 P1 和最终失败测试显式注入合成能力，不代表客户端已具备该能力。Work 未开发。本轮没有为了补齐上述缺口重构 Claude 执行或授权协议，因此不能称为 V2 全面接入完成。

## 验证与复现

所有 pytest 使用既有 `isolated_user` fixture（临时 HOME/USERPROFILE/APPDATA/CODEX_HOME/SHION_DATA_DIR、注册表替身）与仓库内 basetemp。

- 初次定向回归：218 passed。
- 全量：**1738 passed、9 skipped、2 个既有 Pillow 弃用警告，638.28 秒**。包括 Claude 控制、观察链路、租约、安装事务、ACL、持久化等既有回归。
- 全量进程启动后补充了切换时清空旧 coverage 的一行边界修正和七项测试；最终定向 **196 passed、1 skipped，86.90 秒** 验证最终适配代码、调度核心、ChatGPT UI、权限、远控和暂停标签。没有把先启动的全量测试宣称为最终字节版本的全量重跑。
- `git diff --check` 与暂存差异检查通过；`tools/check_private.py` 在新增文件暂存后扫描通过。Author/Committer 邮箱均核对为 `201329225+iLLyaaaaaa@users.noreply.github.com`。
- 三语原生 Qt 截图实际 DPR **1.0 / 1.5 / 2.0**，字体库 341 项；权限面板宽 400、提示宽 300 逻辑像素，自动换行高度和菜单边界断言通过，截图人工查看无明显裁切/重叠。100% 预览通过独立子进程校准 Qt 缩放因子，未修改 Windows 显示设置。
- 日志在 `.venv/v2-gui-full.log`、`.venv/v2-gui-final-focused.log`；最终截图在 `.venv/preview-run/v2-dpi-100-verified/`、`v2-dpi-150/`、`v2-dpi-200/`。早期缩放探测产物保留但不计入验证。

```powershell
.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/v2-gui-full
.venv\Scripts\python -m pytest tests/test_scheduler_gui.py tests/test_scheduler.py tests/test_chatgpt_ui.py tests/test_permission.py tests/test_remote_control.py tests/test_pause_badge.py -q --basetemp=.venv/preview-run/v2-gui-final-focused
.venv\Scripts\python tools/preview_scheduler.py --out .venv/preview-run/v2-dpi-150 --scale 1.5
.venv\Scripts\python tools/check_private.py
```

`preview_scheduler.py` 采用原生 Windows Qt 字体、`SnapshotScene` 和直接 QWidget 渲染，所有窗口设置 `WA_DontShowOnScreen`；不打开接收端口、不执行真实客户端、不读写真实配置、不访问真实自启注册表。支持三语、1/1.5/2 缩放，输出 `scheduler-snapshot.png` 与记录实际 DPR、面板尺寸、字体数量的 `checks.json`。截图是合成场景，布局断言不是焦点、实际客户端或多屏验收。

| 场景 | 自动化范围 |
| --- | --- |
| 单 Claude/ChatGPT、双品牌、双 Codex 会话 | Qt Controller、状态文字和动画；完整身份为合成元数据 |
| 双向前台、前台结束转后台 | 经明确验证标记的合成任务键；另测无验证时不猜测、5 秒轮转 |
| 多权限、权限与结束并发 | 原 Claude 请求队列、合成可靠 P1、ChatGPT 未确认提示；批准/拒绝只影响 Claude |
| 重复、延迟、缺失与冲突身份 | 事件/通知去重、终态不复活、缺失 ID 降级、品牌隔离 |
| Observer A 失联、B 健康 | 确定性时钟与真实 ledger；心跳恢复不复活旧工作，健康长静默保持活动 |
| 关闭/重开开关、GUI 重建 | 持久化开关、内存墓碑、空档未知、无旧任务自动恢复 |
| P2/P3 覆盖、恢复工作、P5 | 可信失败、只读结束、权限队列先行、明确 coverage 才空闲 |
| 三语、菜单密度、不同桌宠尺寸 | 新菜单回归、120/200/600 像素桌宠、300 像素只读提示、权限区不藏在折叠内容中 |

## 人工验收与回退

仍待审核：实际 Claude/Codex 客户端同时工作、真正人工长授权、实际中断及底层工具终止、窗口焦点/遮挡/跨屏/高 DPI 视觉体验、GUI 原生启动/退出与长期运行。此前阶段 1 未通过的项目不因本次模拟通过而变为通过。

最小停用方法是在**隔离开发环境**调用 `set_v2_scheduler_enabled(False)`，当前安装包没有部署本轮代码，无需回滚安装。源码提交后可在保留个人未提交修改的前提下 `git revert <本轮提交SHA>`；不要使用 reset --hard/clean。单次提交同时包含 UI 净改动和适配层，revert 会一起撤回；原 UI 分支与原核心提交仍保留。

## 文件范围

- 新增适配与提示：`shion/scheduler_gui.py`、`shion/observation_hint.py`。
- 连接/展示/存档：`shion/controller.py`、`chatgpt.py`、`panel.py`、`scheduler.py`、`state.py`、`tasks.py`；三语 `assets/lines/{zh,en,ja}.json`。
- 测试：新增 `tests/test_scheduler_gui.py`、引入 Claude 的 `tests/test_menu_layout.py`；调整 `test_scheduler.py`、`test_chatgpt_ui.py`、`test_controller.py`、`test_dialogue.py`、`test_hover_passive.py`。
- 工具：新增 `tools/preview_scheduler.py`，引入 Claude 的 `tools/render_menu.py`。
- 文档：本报告、`docs/spec.md` 和 `docs/progress.md` 本轮新增的一条记录。共 23 个文件；既有未提交实验材料不在提交范围。
