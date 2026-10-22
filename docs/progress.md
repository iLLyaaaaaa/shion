# 进度记录

> 每个步骤结束时更新这份文件。新会话从这里接手。步骤定义见 `docs/spec.md`「开发步骤」。

## 当前状态
- **2026-10-22 Win+D 后跟随修复与分段中断提示**：前台/恢复双事件、150ms/500ms 有限补查和非激活显示恢复；中断点击与 `work_stopped` 分开提示、三语 stop 表情，连接面板/spec 补充源码迁移限制。全量 **1552 passed、9 skipped、2 warnings**，原生 Windows 150% 专项 **64 passed**，修正版 exe 复制目录自检 **78 项通过**。PreToolUse 启动到退出各 20 次中位数：**exe 392.562ms / .venv 329.602ms**，未做启动优化。真实桌面与实际 CC 联动 **待用户验收**。本轮仅本地 commit，不 push；三份既有 README 草稿保留、不纳入提交。
- **2026-10-22 v1.0 第 2 步：Windows onedir 打包**：已生成 `dist/Shion/Shion.exe`，完整目录 **105,519,736 字节（105.52 MB / 100.63 MiB，221 文件）**。复制到无 `.venv` 的中文/空格临时路径后，exe 内 HookConnection、九张截图、八类 hook、自启动和存档日志落点等 **78 项自检通过**；全量 **1531 passed、7 skipped、2 warnings**，最终修正回归 **31 passed**。真实桌面、干净机器、杀毒及 Claude Code 实际联动 **待用户验收**。只做本步，本地 commit，不 push。
- **2026-10-22 v1.0 第 1 步：连接管理、首次引导与开机自启**：已实现共用 hooks 服务的用户级连接/断开、项目级迁移及失败恢复，三语状态和不激活引导面板，HKCU 自启与源码/打包分支。最终全量 **1519 passed、7 skipped、2 warnings**；修正回归 **105 passed**，原生 Windows 专项 **23 passed**，三语截图已自查。只完成本步，不推进打包/发布；真实桌面与实际联动 **待用户验收**。本轮按用户要求本地 commit，不 push。
- **2026-10-22 Claude 前台窗口层级跟随**：关闭「置于最上层」时，原生 Windows 用前台 hook 将诗音与可见附属窗口紧邻放到任一 Claude.exe 窗口之上；其他程序前台不调整。不激活、不移动缩放、不绑定 Claude owner；延迟创建/句柄重建补同步，开启置顶及退出注销。全量 **1473 passed、6 skipped、2 warnings**；最终专项与独立暂存副本均 **81 passed、2 skipped**，原生 hook 两轮注册/注销、真实受控窗口组 Z 序 **1 passed**。真实焦点、遮挡、最小化和高分屏 **待用户验收**。只提交本轮改动，不 push。
- **2026-10-21 三语台词扩充、时段问候与等级混合抽样**：按确认方案追加三语各 24 句现有类别台词、五类各三句时段台词；原文全部保留。时段成功显示才记入兼容 v5 的每日存档，跨天清零、重启/换语言不重置；工作/静音/睡眠/气泡阻挡不消耗机会。等级池按当前 60%、较低各级及通用池平分 40% 抽样。专项 **315 passed、1 skipped**，修正回归 **201 passed**；恢复后核对包含本轮改动的后续全量 **1473 passed、6 skipped、2 warnings**。真实桌面台词节奏与三语观感 **待用户验收**。草稿核对迁入 JSON 后删除；本地 commit，不 push。
- **2026-10-21 动态睡眠 Z、趴桌双眨与轻姿态**：用户确认方案后完成 sleep/bed 去除原图漂浮 Z、单独导出 fx_z、四档大小动态 Z、趴桌 1.5～3.5 秒眨眼与 20% 双眨、working 轻点头及 neglect2 慢摇。素材四张图已单独提交 `24d72cd`；其他 PNG（含 raw）哈希未变。专项 **224 passed、3 skipped**；原生 Windows 150% 新专项 **42 passed、1 skipped**（没有有效前台窗口，未证明焦点保持）。56 张 `--snapshot` 已自查；最终全量 **1340 passed、6 skipped、2 warnings（406.34 秒）**。动态观感、真实桌面点穿/焦点与高分屏表现 **待用户验收**。用户已授权素材与代码分两次本地 commit，不 push。
- **2026-10-21 置顶开关、面板避让与版本统一**：用户确认方案后实现三语「置于最上层」（默认开、兼容存档、即时生效），附属气泡/特效/暂停标签同步；授权、计划、有效完成、首次到达暂停检查点前移一次，使用不激活 API。所有对话框独立置顶并放在身体旁；关于与 QApplication 从唯一 `__version__` 读取 **0.4.1**。原生 Windows 150% 专项 **48 passed**，面板相关回归 **281 passed、3 skipped**，最终全量 **1297 passed、4 skipped、2 warnings（402.39 秒）**；三语 `--snapshot` 已自查。当前取不到有效前台窗口，真实焦点未验证；真实桌面遮挡、焦点和多屏表现 **待用户验收**。用户已授权本地 commit，不 push。
- **2026-10-21 抱胸待机与动作衔接**：用户换好的 idle / blink 与两张 raw 原图、忽略旧备份规则已单独提交 `348b498`，素材未改。确认方案后，新增 idle 与转身、侧身、跳跃、捏脸/挠痒动作层进出各 0.10 秒透明度混合，mask 取完整轮廓并集；表情、拖动和眨眼保持原行为。最终全量 **1250 passed、3 skipped、2 warnings（377.53 秒）**；原生 Windows 150% 最终专项 **16 passed**，`--snapshot` 已自查。动态观感、真实桌面点穿和高分屏表现 **待用户验收**；用户已授权测试与记录后独立本地 commit，不 push。完整验证见下方同名记录。
- **2026-10-21 待机“活着感”**：仅代码实现 idle / neglect1 的 2.5% 呼吸、working 的 0.8% 轻呼吸、idle ±1.5° 慢摇摆和 0.6 秒随机换重心；动作/状态互斥、独立随机时间线和有界 LRU 轮廓缓存。全量 **1210 passed、3 skipped、2 warnings（366.42 秒）**；原生 Windows 150% 专项 **17 passed**，离屏 150% / 200% 专项通过，`--snapshot` 已自查。动态观感、真实桌面点穿和高分屏表现 **待用户验收**。用户已确认方案，授权记录待验收后本地 commit，不 push。
- **2026-10-21 问题 A、C 与授权面板及时收起**：诗音结束的这一轮（立即中断 / 停下拿到 stop / 停太久）紧接着的 Stop 不再算完成；Notification `idle_prompt` 清掉该会话的工作中；工作中点“做得好/有问题”改说“马上转告”；用户在 CC 里自己答了授权后，诗音面板马上收起。B 不修、改预期；桌面端 statusMessage 不显示记为已知限制。用户已验收的桌面端项已打勾。全量 **1172 passed、2 skipped、2 warnings（335 秒；跳过项和 Pillow 警告同前）**。没开嵌套 CC、没重装 hooks（事件列表没变）。本地 commit，不 push。
- **2026-10-21 终端版 CC 自动验收**：嵌套终端版 CC（haiku）+ 隔离端口/数据目录的测试诗音，逐项跑完终端版待验收项，自动通过的已打勾并标“CC 自动验收”，详见同名一节。发现 3 个问题（中断后又说任务完成、授权框和诗音面板同时显示、Esc 取消工具后一直工作中），只报告未修；锁屏导致焦点项不能完全证明。用户级 `~/.claude/settings.json` 的 model 被 `/model haiku` 改成 haiku，原值未知，待用户决定。测试后 `PYTHONUTF8=1`、offscreen 全量 **1132 passed、2 skipped、2 warnings**（日志 `.venv/preview-run/cc-auto/pytest.log`；本轮在 CC 内运行，进程链用例不再跳过）。只改了本文件，不 push。
- **2026-10-21 称呼中性化**：仅调整三语台词、对话/零食与好感配置中的用户称呼，共 49 处；独立呼语直接省略，其余按语境使用“你 / you / あなた”，保持原有语气和内容。spec 已明确诗音不使用性别化称呼。指定资源中的三种旧称呼均检索为 0；代码、测试、JSON 结构及数值未改。`PYTHONUTF8=1`、`QT_QPA_PLATFORM=offscreen`，`.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/neutral-address-full` → **1131 passed、3 skipped、2 warnings**（314.98 秒；跳过项和既有 Pillow 警告同上一轮），`git diff --check` 通过，日志在已忽略的 `.venv/preview-run/neutral-address-full.log`。此前动态验收清单继续保留。本轮按用户要求本地 commit，不 push。
- **2026-10-21 v0.4.1 好感度系统已实现**：五级配置、统一每日额度、v5 存档迁移、升级高优先级气泡和独立爱心圈、状态进度/剩余额度、等级解锁和中英日分级台词。完整测试 **1131 passed、3 skipped**，原生 Windows 150% 专项 **102 passed**。用户本轮明确要求并确认方案后开始本步；之前保留的真机验收项不视为已通过。动态和桌面表现 **待用户验收**；用户已授权记录待验收后 commit，不 push。
- **2026-10-21 悬停不再算交互**：移除 hovered → interact 及其唤醒路径；进入、无按键移动、离开仅处理光标和 Qt 提示，不改变状态、动作或交互计时。仅打开/浏览/取消右键菜单也不唤醒、不打断动作，实际手势和菜单动作沿用原优先级。完整测试 **974 passed、3 skipped**；原生 Windows 150% 专项 **53 passed**。桌面表现 **待用户验收**。用户明确要求补测试、更新记录后 commit，不等待本轮亲眼验收；不 push。
- **2026-10-21 这一轮结束后的“继续”已实现**：立即中断 / 停太久结束这一轮后，工作遥控菜单多一项：终端版“继续（发送“继续”）”（子进程 AttachConsole + WriteConsoleInputW，先读屏，有草稿或确认框不发并说明原因），桌面端“继续”（复制到剪贴板）。桌面端立即中断本身不变。完整测试 **922 passed、2 skipped**；conhost 和 Windows Terminal 真机读屏/发送通过；完整链路 **待用户验收**，见本轮记录。不 push。
- **2026-10-20 可行性实验：替用户发“继续”**（没改正式代码）：终端版 AttachConsole + WriteConsoleInputW **可行**（conhost 和 WT 后台标签都能送达，不抢焦点；要先读屏，避开确认对话框和用户草稿）；桌面端 UIA SetValue/Invoke **送得到，也能选对会话，但会把 Claude 拉到前台、抢走焦点**，不建议用。详见 `docs/experiments/send-continue.md`，脚本在 `tools/experiments/`。
- **2026-10-20 暂停文字标签已实现**：小 ⏸ 已换成终端风格“暂停中 / Paused / 一時停止中”，带三语悬停提示；真正停在检查点后才显示，左键点击复用“继续”，0.6 秒防误点，不接键盘、不抢焦点。原生 Windows 150% 专项 **34 passed**；最终完整测试 **889 passed、3 skipped、2 warnings**。真实桌面穿透、悬停提示和 CC 点击续跑 **待用户验收**。第 1～4 项提交 `ddb5b1b`，本轮仍不 push。
- **2026-10-20 床睡、趴桌与原地停放已实现**：新增宽画布按脚底中心切换、三语道具动作、慢放悬空/甩出下落与默认关闭的“松手后落到任务栏”存档开关。素材先提交 `61fe43d`。专项 **95 passed、1 skipped**；原生 Windows 150% 专项 **69 passed**。本轮动态桌面表现 **待用户验收**，见下方记录；用户确认方案并授权分步 commit，不 push。暂停文字标签见上一条。
- **2026-10-20 暂停可见性已实现**：检查点 hook 带 `statusMessage`（CC 转圈处显示“诗音在看着～（一直停在这里就是暂停了，右键诗音点继续）”，三语按存档语言安装）；诗音真的在检查点停住后头顶右侧一直显示小 ⏸。项目级 hooks **已重装**。完整测试 **836 passed、1 skipped**，真实 `claude -p` 两个场景通过；CC 里文字的观感/闪烁、⏸ 的位置与出现/消失时机 **待用户验收**，见本轮记录。用户已授权记录待验收后 commit，不 push。
- **2026-10-20 停下简化、立即中断、工作状态与多会话已实现**：删掉检查点面板，停下只说两句；新增“立即中断”（结束工具子进程 + 下个检查点结束这一轮）；工具执行中一直 working；按 session_id 区分会话。完整测试 **814 passed、1 skipped**，真实 `claude -p` / 终端版 CC 六个场景通过；**终端版没有用 Ctrl+C**（实测会让 CC 整个退出，见本轮记录，需要你决定）。桌面端 Code 的立即中断和界面观感 **待用户验收**。用户已授权记录待验收后 commit，不 push。
- **2026-10-20 停下与暂停合并已实现**：菜单只留“停下”，到下一个检查点原地等待，诗音弹出“继续 / 结束这一轮”面板；30 分钟没选按结束处理。挠痒放慢（200ms/帧、±2.5°、0.6 秒）已单独提交 `e15de5c`。完整测试 **763 passed、1 skipped**，真实 `claude -p` 两个场景通过；面板观感与真实 CC 界面 **待用户验收**，见下方本轮记录。用户已授权记录待验收后 commit，不 push。
- **2026-10-20 转身、捏脸与挠痒已实现**：新增三组动作帧，移除行走入口与全部镜像；区域、时间和距离已集中为常量，三语台词齐全。完整测试 **759 passed、1 skipped**，原生 Windows 150% 专项 **119 passed**；动态交互 **待用户验收**。用户本轮明确授权素材先提交、功能测试和文档完成后再提交，不等待亲眼验收，不 push。
- **2026-10-20 工作遥控改进已实现**：暂停检查点从 PreToolUse 扩到 PreToolUse + PostToolUse；新增“停下”（`continue: false`，只生效一次）。完整测试 **723 passed、1 skipped**，真实 `claude -p` 四个场景通过；菜单、气泡和真实 CC 界面表现 **待用户验收**，见下方本轮记录。用户已授权记录待验收后 commit，不 push。
- **2026-10-20 动作更新已实现**：可变帧数组、八帧走路（60px/s、110ms/帧）、四阶段跳跃（最高 45px）、拖动变速循环和 SHION_DEBUG 实际绘制 FPS，见下方本轮记录。完整测试 **702 passed、1 skipped**，原生 Windows 150% 专项 **70 passed**；动态观感、真实桌面点穿与 FPS 显示 **待用户验收**。用户已授权记录待验收后 commit，不等待亲眼验收，不 push；不推进好感度或内容包开发。
- **2026-10-20 v0.4 对话菜单已实现**：三语 JSON 零食与预设、点击后数字键选择、每日五次喂食额度、happy + 碎屑、晚安睡眠，见本轮记录。真实桌面焦点和动态观感 **待用户验收**；用户已授权记录后 commit，不等待亲眼验收、不 push。下一开发步骤：**先由用户集中真机验收 v0.2.1～v0.4**，然后 v0.4.1 好感度系统，再 v0.5 内容包。
- **2026-10-20 计划确认与完成提醒修正已实现**：ExitPlanMode 不再由诗音接管，只发高优先级三语计划提醒并跳一下；Stop 不再发送/显示回复内容。界面三语文字均不含“Claude”，hooks 备份已忽略。真实 CC 计划确认、三语气泡及跳跃观感 **待用户验收**，见下方本轮清单；用户明确授权先记录待验收再 commit，不 push。
- **v0.2.1 及此前的真机验收已通过**：依据用户 2026-10-19 明确反馈，除本次列出的交互问题外，旧清单均已验收；各历史节已更新标记。下方历史实现记录中的旧戳规则/摸头表扬以本次规则为准。
- **新版行走分帧素材已提交，爱心参数已调整**，验证结果见 2026-10-20 节；行走/跳跃、气泡仲裁与爱心的动态观感和真实桌面点穿仍 **待用户验收**。用户明确授权补测试、更新记录后 commit，不等待本轮真机验收；不 push。
- 上一轮交互打磨的待验收清单继续保留，不能用本轮自动测试和静态截图替代。
- 当前 hooks 仍只装在项目级 `.claude/settings.local.json`（已 gitignore）；用户级 `~/.claude/settings.json` 没动过。2026-10-20 暂停可见性一轮**重装了项目级**（加 statusMessage，自动备份）。以后装用户级之前，先卸载项目级那份，避免重复事件。
- **v0.3 两部分都已实现**（暂停/继续 + 反馈队列、同意/否决），自动测试和真实 `claude -p` 联调通过；等待审查和用户真机验收，见下方两节的“待用户验收”。v0.4 实现见本轮记录。
- 环境：`.venv`（Python 3.10.11），测试用 `.venv\Scripts\python -m pytest -q`。本仓库提交邮箱为 GitHub noreply。

## 2026-10-22：Win+D 后跟随修复、分段中断与 hook 耗时（待用户验收）
- **范围**：已读 AGENTS/CLAUDE、相关进度与规格。开始时 master 无已跟踪改动、无暂存内容，但有三份未跟踪的 `docs/drafts/README*.md`；用户确认保留草稿后实施本轮四项。草稿不修改、不暂存。无新依赖、版本或素材改动，不 push。
- **做了什么**：
  - 跟随同时注册前台切换与最小化恢复事件；回调只投递合并请求。前台识别为 Claude 后，即使此刻仍最小化，也安排约 150ms、500ms 各一次补查，同一轮重复事件不延长补查，无常驻轮询；每次重新核对前台，切走、开启置顶、退出时取消。两个 hook 部分注册失败会清理；注销失败保留回调并可重试。
  - 跟随时将 Qt 仍认为可见、但被系统隐藏/最小化的诗音窗口用 `ShowWindow(SW_SHOWNOACTIVATE)` 恢复，再同步层级。显式隐藏的气泡/特效不恢复，不改变置顶选择、不主动激活。Win+D 的完整桌面行为仍须用户验收。
  - 立即中断实际结束至少一个进程时说“命令停掉了，等它说完这句就停～”；没有结束进程时说“等它说完这句就停～”，均用 stop 表情。只有对应待确认会话收到 `work_stopped` 后才说“已经中断啦，在 CC 里说一声就能继续”，每会话一次，三语同步、两段分别遵守当前静音设置。Stop/新 prompt 清除待确认提示；延续中断工具失败不报错、结束后“继续”、不计完成任务的规则。
  - 连接确认面板三语与 spec 明确：迁移旧项目 hooks 只在源码运行时有效，且只处理该源码项目；用 exe 连接时，请在旧项目运行 `tools\uninstall_hooks.py`，避免与用户级 hooks 双发。不扫描或修改用户其他项目配置。
  - 新增可复跑的 `tools/benchmark_hooks.py`：两种入口各 20 次，相同合成 Read 输入、独立随机端口的本机 HTTP mock（未暂停）、隔离 HOME/APPDATA/存档；交替先后顺序，不预热、不丢弃首轮。`perf_counter_ns` 从创建子进程前计到退出并收完管道，包含启动、hook 标准路径与退出，不含脚本整体初始化。不优化启动。
- **验证**：
  - 新增“前台事件早于恢复完成”在 150ms / 500ms 补查后恢复、补查有界且不轮询、恢复事件合并且不延后定时、切走/退出取消、双 hook 部分注册及注销失败清理、系统隐藏与显式隐藏区分的回归；原生用例覆盖 SW_HIDE / SW_MINIMIZE 后显示、geometry/mask 与普通层级保持。
  - 新增三语两段中断、实际结束进程/无工具/结束失败、会话隔离、重复事件、各阶段静音、新 prompt/Stop 作废等测试；更新旧桌面中断即时完成的假设，保留实际结束后“继续”的断言。三语面板测试检查迁移提示和正文高度。
  - 全量 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/restore-interrupt/full-tmp` → **1552 passed、9 skipped、2 warnings（451.29 秒）**，日志 `full.log`。本轮新增的两个原生恢复用例在全量 offscreen 中跳过，已在下列原生专项执行；两条警告均为既有 Pillow getdata 弃用。
  - `QT_QPA_PLATFORM=windows`、`QT_SCALE_FACTOR=1.5`，前台跟随/连接面板最终专项 → **64 passed（11.38 秒）**，日志 `native-final.log`。初轮离屏相关专项修正后 **200 passed、5 skipped（45.83 秒）**，最终代码由全量与原生专项覆盖。
  - 重建 `.venv\Scripts\python tools\build.py`，`dist/Shion` **105,521,442 字节（105.52 MB / 100.63 MiB，221 文件）**；复制到独立临时目录后的 **78 项自检通过**。三语连接面板 `--snapshot` 已逐张自查，新增说明、脚本路径与按钮显示完整；截图仅为静态证据。构建日志 `.venv/preview-run/restore-interrupt/build.log`，包内自检和截图 `build/bundle-check/`。
- **PreToolUse 耗时，仅测量、未优化**：在以上全量/构建/原生专项全部退出后运行 `.venv\Scripts\python tools\benchmark_hooks.py`；两种入口均正常退出、无 stdout/stderr，40 次均由 mock 收到对应 working 事件。

  | 入口（相对仓库根目录） | 次数 | 启动到退出中位数 |
  | --- | ---: | ---: |
  | `dist\Shion\Shion.exe --hook PreToolUse` | 20 | **392.562 ms** |
  | `.venv\Scripts\python.exe hooks\shion_hook.py PreToolUse` | 20 | **329.602 ms** |

  - 测量条件见上方脚本说明；数字为本机本轮结果，非冷启动/其他机器的保证。原始 40 次样本、完整命令、版本及 exe/hook SHA-256 在已忽略的 `build/hook-benchmark.json`；终端记录 `.venv/preview-run/restore-interrupt/benchmark.log`。未修改 `hooks/shion_hook.py`、构建入口或依赖。
- **踩过的坑与验证边界**：初轮专项发现双 hook 部分注册失败时空句柄需统一为 None，以及旧桌面中断测试还断言点击即完成；已修正并补回归。当前原生平台 `windows`、实际 DPR=1.5，但 `GetForegroundWindow()` 返回空句柄，所以即使原生隐藏/恢复和 Z 序用例通过，也不能据此宣称真实焦点通过。
- **待用户验收**（重启修正版源码或 `dist/Shion/Shion.exe`）：
  - [ ] 关闭置顶 → Win+D → 恢复 Claude 桌面端为最大化/全屏，诗音及当时可见附属提示恢复到其上；多次切换、另一个 Claude 窗口、换到其他程序均正常，不抢焦点、不改位置或置顶设置。
  - [ ] Win+D 若隐藏/最小化诗音，恢复 Claude 后诗音重现；已主动消失的气泡/特效不复活。开启置顶、退出后没有迟到补查。
  - [ ] 三语立即中断：有命令被结束/只有文字两种即时提示准确、表情为 stop；真正 `work_stopped` 后才显示完成中断，不重复说、不冒充任务完成，静音及“继续”菜单正常。
  - [ ] 三语连接面板正文完整可读，明确源码迁移限制；按提示卸载旧项目 hooks 后，exe 用户级连接没有重复事件。
- **下一步**：用户验收本轮及此前保留清单。本轮测试与记录已完成，仅本地提交明确文件清单，不 push；提交 Author/Committer 均核对为 GitHub noreply 邮箱，三份既有 README 草稿继续保留。

## 2026-10-22：v1.0 第 2 步——Windows onedir 打包（待用户验收）
- **范围**：开始时已读取 AGENTS/CLAUDE、相关规格，master 工作区干净、提交邮箱正确。用户确认方案后实现本步；按用户选择不生成自定义图标、版本资源或 zip，不改版本、不推进许可/发布，不修改素材原图或精灵。
- **构建与使用**：
  - `.venv\Scripts\python tools\build.py` 一条命令检查/安装构建依赖、清洁构建、统计体积并执行复制目录自检；`.venv\Scripts\python tools\build.py --check-only` 可复查现有产物。构建/检查失败返回非零，详细日志和证据在已忽略的 `build/`。
  - 新增 `Shion.spec` 和独立 `requirements-build.txt`，固定 **PyInstaller 6.22.3 / hooks-contrib 2026.9**；本机运行库为 Python 3.10.11、PySide6 6.12.0、NumPy 2.2.6。输出为 GUI 子系统的 onedir：`dist/Shion/Shion.exe` 与 `_internal/`，最终用户复制整个 Shion 文件夹即可，不需要 Python。build/、dist/ 已加入忽略。
  - 收集运行 JSON、sprites 顶层运行图和冻结的 hook/连接模块；raw、旧备份、reference、测试/开发工具不进包。Qt 仅保留 Core/Gui/Widgets/Network，以及 qwindows、qoffscreen、qmodernwindowsstyle；不用的 WebEngine、QML/Quick、多媒体、PDF、3D、OpenGL 软件渲染器及 Qt TLS 附带库排除。NumPy 与标准库自身需要的 DLL 保留。
  - `--hook <事件>` 在业务 GUI 导入前复用原标准库 hook；缺失的标准流从继承的 Windows 管道/文件句柄副本恢复，无句柄用空设备，不创建/附着控制台。冻结文本流统一 UTF-8，hook 的中文输入、反馈和授权 JSON 均实测。PyInstaller 自带运行时 hook 会加载 QtCore 注册资源，内部自检断言不加载 QtGui/QtWidgets。
  - 冻结的“继续”子进程改走当前 exe 的内部 `--console-send`；中断候选排除当前 exe，避免误杀 hook。SessionStart 拉起当前 exe 时设置 `PYINSTALLER_RESET_ENVIRONMENT=1`。源码路径保持原 Python 模块命令。
  - 存档/日志默认显式取 `%APPDATA%\Shion`，保留 SHION_DATA_DIR 测试覆盖与无 APPDATA 时的原 Qt 后备；正常用户落点不变。复制程序目录前后逐文件 SHA-256 清单一致，没有新增状态、日志、缓存或连接配置。
- **自检与验证**：
  - host 自检只用标准库，复制产物到系统临时目录下的 `诗音 with spaces/Shion`，工作目录另设；移除 Python/虚拟环境/外部 Qt 搜索变量，PATH 只留系统目录。子进程所有 HOME/USERPROFILE/HOMEDRIVE/HOMEPATH/APPDATA 隔离，SHION_DATA_DIR 不设置，从而验证真正的默认 APPDATA 落点。随机端口、唯一实例名；结束时按临时 exe 完整路径核对并清理自己启动的进程。
  - exe 内 `--self-check-connection` 仅允许系统临时目录下且与隔离 HOME 一致的全新目录；直接使用包内 HookConnection，验证三语连接、迁移、备份、幂等、旧路径失效/修复、断开和第三方配置保留。验证包内模块路径与 sys.path 均不依赖源码；不匹配 HOME 的调用拒绝读写。
  - 八类 hook 通过临时 HTTP mock 检查事件与中文会话信息；额外验证 allow/deny/gone、中文反馈、检查点 continue=false、ExitPlanMode 只提醒、Stop 无回复内容、服务不可达静默，以及无效目标的 console-send JSON。另用 SessionStart 启动真实复制版 GUI 服务、发送 working/stop 并核对日志与存档。
  - 最终复制目录 **78 项检查通过**，证据 `build/bundle-check/report.json`、`subprocess.log`、临时存档/日志副本；九张 `--snapshot` 包含 Windows 原生平台的 idle/working、bed/desk、日文零食与三语连接面板，另有一张 offscreen idle。已自查生成截图，文字和布局完整。截图是静态渲染证据，不代表真实桌面焦点或动态观感验收。
  - 首轮相关专项 **65 passed（13.92 秒）**；扩展 hook/中断/连接/自启回归 **158 passed、1 skipped（68.33 秒）**；最终打包/连接修正回归 **31 passed（7.26 秒）**，日志 `.venv/preview-run/v1-packaging-final-targeted.log`。
  - 完整 `.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/v1-packaging-full` → **1531 passed、7 skipped、2 warnings（436.10 秒）**，日志 `.venv/preview-run/v1-packaging-full.log`。六项原生 Qt/焦点条件和一项 CC 父进程链环境限制跳过；两条为既有 Pillow getdata 弃用警告。最终一条命令构建与 **78 项自检**同样通过，日志 `.venv/preview-run/v1-packaging-build-final.log`；`git diff --check` 通过。
- **体积与踩坑**：
  - 首包 **173.24 MB**，最大项为误收的 `icudt78.dll` **33.13 MB**、OpenGL 软件渲染器 **20.64 MB**、NumPy OpenBLAS **20.39 MB**、QtCore **10.47 MB**、QtGui **9.68 MB**、Qt TLS OpenSSL crypto **7.45 MB**。初始明细在 `build/size-report-initial.json`。
  - PyInstaller 从本机 PATH 中误收了 Poppler 的 ICU（版本化导出），遮住 Qt 需要的 Windows 系统 ICU（非版本化导出），造成 QtCore 导入失败和无控制台错误框；用 PE 导入/导出检查定位后，构建子进程改用仅含当前 Python 与系统目录的 PATH，不再携带外部 ICU 和其他应用库。OpenGL 软件渲染器、Qt TLS 插件配套 OpenSSL 3 也无需携带；保留标准库 OpenSSL 1.1。最终 **105.52 MB**，无需进一步删除 Qt 模块。完整大小/前十项/目录汇总与依赖版本在 `build/size-report.json`。
  - 不仅要处理 None 标准流：本机冻结 exe 的已有文本流可能还是 GBK；已统一 UTF-8 并覆盖恢复管道和编码两条路径。构建依赖文件使用 ASCII 注释，避免本机 pip 按 GBK 读取 UTF-8 注释失败。
  - offscreen 的日文字体回退与 Windows 原生不同，不能用它判断发布版文字；面板与零食截图用 windows 平台，offscreen 仅做资源/后台链路验证。
- **待用户验收**：
  - [ ] 双击整个复制后的 Shion 文件夹中的 exe：启动耗时、无控制台闪窗、动画、交互、透明区域、高分屏和多屏观感。
  - [ ] 从 exe 的菜单连接后，实际 Claude Code 事件、授权、暂停/继续与“继续”完整链路；本轮不运行 claude，也不访问真实 `~/.claude`。
  - [ ] 无 Python 的干净 Windows 机器启动、系统安全软件表现。当前证据是本机复制路径与环境隔离自检，不冒充干净虚拟机或实际联动结果。
- **下一步**：用户集中验收；后续另做图标、版本资源、zip、README/许可与发布准备。本轮只本地 commit，不 push。

## 2026-10-22：v1.0 第 1 步——连接管理、首次引导与开机自启（待用户验收）
- **范围**：开始前读取 AGENTS/CLAUDE 和相关规格，`git status` 为 master 干净。用户确认完整方案，明确旧存档不补弹引导；只做连接、迁移、引导、自启和状态，不引入依赖、不改素材、不推进 exe 打包/许可/发布。
- **做了什么**：
  - 扩展原 `tools/hooks_config.py`，GUI 与原安装/卸载工具共用识别、合并、校验、备份及写入。保持八个事件、command + args、matcher、timeout 和检查点 statusMessage；收紧为明确的诗音脚本/打包命令，保留旧 shell 命令兼容，不按子串误删其他条目。
  - 用户级配置合并保留 statusLine、modelSettings、未知键和第三方 hooks，包括混合分组；无变化不写盘。空文件、损坏 JSON、非法结构拒绝写入。连接前同时校验两份配置，所有变更文件先备份原始字节/暂存，再先清项目旧诗音 hooks、后写用户级；中途失败恢复已改文件，并发变化拒绝覆盖，恢复失败明确列出备份位置。断开只删用户级诗音条目，不重新启用旧项目 hooks。
  - 菜单与双击状态每次读取实际用户级配置，显示已连接/未连接/路径失效或不完整/读取失败，支持重新连接；已连接表示配置完整且当前路径有效，不等同于已验证实际联动。三语仅在连接与兼容性说明中提 Claude Code，名称/标题仍用诗音/Shion；原有台词和 meta 完全保留。
  - 全新首次启动在介绍及当前气泡结束、无授权/输入面板时弹“连接 / 以后再说”；不抢焦点，按钮只接受鼠标，随身体定位，语言切换立即更新。授权请求优先隐藏连接面板，结束后恢复待选择。兼容 v5 的可选 connection_prompt 记录 pending/connect/later/skipped：旧档跳过，未选退出可重试，选后立即写盘，连接失败也不再自动问。
  - HKCU Run 只管理 Shion 值，不自动开启；菜单读实际命令及目标文件，有效时勾选、失效时点击修复，关闭仅删自己的值。源码使用绝对 pythonw.exe + 可直接运行的现有入口，不依赖工作目录；冻结分支直接运行当前 exe。hook 预留当前 exe --hook 事件，在加载 GUI 前复用原标准库入口，SessionStart 冻结分支拉起当前 exe。
- **测试与自查**：
  - 全局 autouse fixture 隔离 HOME/USERPROFILE/HOMEDRIVE/HOMEPATH/APPDATA/SHION_DATA_DIR，子进程继承；所有测试的 Startup 注册表接口使用替身。新增连接/迁移、第三方配置保留、相似命令不误删、备份失败、写入失败恢复、恢复失败提示、并发修改、三语 UI、引导时序/存档/失败/旧档、自启修复与关闭、源码/frozen 分支测试。
  - 配置/CLI/自启首轮专项 **38 passed**；三语与连接专项 **79 passed（6.10 秒）**，日志 `.venv/preview-run/v1-connection-targeted.log`。全量首轮发现两处输出目录断言受新隔离 fixture 影响，修正后相关回归 **105 passed（18.64 秒）**，日志 `v1-connection-regression.log`。
  - 最终 `.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/v1-connection-full-final` → **1519 passed、7 skipped、2 warnings（420.94 秒）**，日志 `.venv/preview-run/v1-connection-full-final.log`。跳过为六项原生 Qt/焦点条件及一项 CC 父进程链环境限制；两条为既有 Pillow getdata 弃用警告。`git diff --check` 通过。
  - 补充实际 pythonw 自启命令从无关工作目录启动的隔离冒烟 **1 passed（2.17 秒）**：随机端口、唯一实例名、临时存档，HTTP /health 成功，不创建真实自启项。
  - 原生 Windows 三语 `--snapshot --panel connection --with-pet` 已自查，正文与按钮完整、面板在身体旁；HOME 等同样隔离。截图 `.venv/preview-run/v1-connection-{zh,en,ja}.png`。原始台词和 meta 与 HEAD 逐项相等；只新增 UI 键及修改自启占位文字。
  - 原生 Windows 新增 UI/自启专项 **23 passed（7.32 秒）**，日志 `.venv/preview-run/v1-connection-native.log`。通过的是界面路径、窗口标志与受控输入等自动断言，真实前台焦点和登录行为仍待用户验收。
  - 本轮未读取或修改真实 `~/.claude`，未运行 claude 命令，未修改真实 HKCU 自启项，也未实际迁移当前项目 hooks；真实连接需用户重启诗音后从右键操作。
- **踩过的坑**：Qt 在首次显示前低估长正文的 word-wrap sizeHint，三语初稿截图出现裁切；按面板实际内容宽度计算标签高度后重新截图通过。连接状态会从旧控制器测试的菜单/双击路径读取配置，因此隔离必须覆盖全部测试，不能只隔离新增用例；隔离 HOME 也不能放在业务 tmp_path 中，否则会干扰素材工具精确检查输出目录的旧断言，现改为独立的 tmp_path_factory 目录。打包分支只是预留，标准流、资源路径和启动耗时留给实际打包步骤验证。
- **待用户验收**（重启诗音）：
  - [ ] 三语右键连接说明、确认/取消和双击状态显示自然；长路径和高分屏无裁切、不遮住身体
  - [ ] 自动引导与点击按钮不会抢走其他程序的输入焦点；全新存档介绍后只问一次，已有存档不补问
  - [ ] 实际点击连接后备份存在，用户原配置保持，项目旧诗音条目移除，Claude Code 每个事件只触发一次；断开保留其他配置
  - [ ] 开启自启后重新登录 Windows，诗音可正常出现且无控制台；关闭后不再随登录启动
  - [ ] 迁移后的终端与桌面端联动、授权/暂停/完成提醒表现正常；此前真机待验收项继续保留
- **下一步**：完成本步测试与本地提交后，由用户验收；exe 打包及发布另开后续步骤，不 push。

## 2026-10-21：三语台词扩充、时段问候与等级混合抽样（待用户验收）
- **范围**：先读 AGENTS/CLAUDE、进度和相关规格，用户确认完整方案后实现；原有待验收项继续保留。没有新依赖、素材或 hooks 改动，不 push。
- **做了什么**：
  - 草稿第一部分逐语言追加到八个已有类别，各 24 句；第二部分五类各三句，共各 39 句。逐项与草稿及提交前 JSON 比较，三语原有台词、等级台词、meta/UI 均保留。`docs/lines_draft.md` 原为未跟踪文件，核对后删除，不进入提交。
  - 本地时段边界集中在 `TIME_SPEECH_PERIODS`，左闭右开：05–10、11:30–13:30、17:30–19:30、23–次日02、02–05；空档不触发。可选存档 `time_speech={date,spoken}` 兼容 v5，旧档缺失/非法值回退、类别去重过滤，重启和语言切换不清零，本地自然日跨天清零（午夜前后的 late 分属两天）。
  - 状态层分开查询和成功标记；控制器在启动/实际交互完成后及原有闲聊机会尝试，只有实际显示成功才记账。先处理原介绍/启动/唤醒/交互/升级提醒，遵守低优先级仲裁；真实工作会话、静音、睡眠及暂停时不说，不抽取、不消耗资格。阻挡解除后只等后续实际交互或闲聊机会，不逐 tick 补播；已过时段不补说。悬停、浏览/取消菜单和普通工作事件不新增机会；双击等状态回应后再试。
  - `Lines.pick_for_level()` 对 pat / neglect_return / idle_talk 先按池抽样、池内等概率：当前池 60%，更低各级及通用池平分 40%，权重集中为常量；排除基础类别上次台词后空池重新归一，只有一句时允许重复。配置失效仍用通用池；满级感谢保留原概率和冷却。
- **测试与自查**：
  - 新增时段边界、跨午夜/跨天、同日一次及读写重启、坏存档回退、成功脏标记/换语言、工作状态被表情遮住、静音/睡眠/气泡阻挡不抽句与不消耗、原回应优先、不逐 tick 补说、后续交互/闲聊重试、空档/悬停/取消菜单不触发、缺台词不记账测试。
  - 新增五等级三语候选范围、禁止越级、连续去重、空池/单句回退；固定随机种子每级 30000 次验证 60/40 分池权重与池大小无关。保留稀有感谢回归，调整旧的仅当前池、固定句子和无时段台词假设。
  - offscreen 专项 **315 passed、1 skipped（49.17 秒）**；跳过为既有原生焦点用例。日志 `.venv/preview-run/lines/targeted-final.log`。
  - 首轮全量暴露旧测试对闲聊/连续交互期间没有时段问候的假设，以及一处抽取测试替身未接收 level 参数；相关专项修正后 **201 passed（42.38 秒）**，日志 `regression.log`。旧冷却/手势用例预先标记当天时段已说，保留原断言；新增专项独立验证时段行为。
  - **2026-10-22 恢复核验**：本任务的 `full-final.log` 随中断停在 29%，不作为通过证据。后续窗口层级跟随任务在包含本轮未提交台词改动的同一工作区完成全量：**1473 passed、6 skipped、2 warnings（413.52 秒）**，日志 `.venv/preview-run/foreground/full.log`。恢复时逐个核对本轮代码、测试和三语资源文件修改时间均早于该完整运行开始，且其后仅更新本轮文档；因此采用该全量结果，不重复运行。六项跳过为既有原生窗口/焦点及 CC 环境限制，两条为既有 Pillow getdata 弃用警告；新增原生层级测试的独立验证见其对应记录。`git diff --check` 通过。
  - 三语资源逐项核对通过，原台词保留，各新增 24+15 句与草稿逐字相同，meta/UI 未改；不打开素材 PNG。
- **踩过的坑**：受限环境默认系统临时目录无权限，pytest 改用仓库内已忽略的 `.venv/preview-run/lines/`，先建父目录。设置语言/隐私/解除静音等真实菜单动作现在也会尝试时段问候，旧测试需要明确等气泡结束或隔离当天已说记录；工作提示测试从硬编码两句改为断言当前资源池。
- **待用户验收**（重启加载代码与三语 JSON）：
  - [ ] 三语新增台词显示自然，原台词仍会出现；高等级能偶尔说通用及低等级句子，当前等级最常见
  - [ ] 启动/唤醒/交互回应优先；工作、静音、睡眠及重要提醒期间不插入时段问候，之后交互/闲聊仍可说
  - [ ] 同一时段同一天只说一次，重启/换语言不重复；进入新时段及次日可再次触发，空档不补说旧时段
- **下一步**：用户验收本轮及此前保留的桌面清单；本轮完成本地 commit，不 push。

## 2026-10-22：Claude 前台窗口层级跟随（待用户验收）
- **范围**：先读 AGENTS/CLAUDE 与相关规格，本机已确认桌面端映像为 `Claude.exe`；用户确认方案后实现。保留已有未提交的三语台词/时段问候改动，共享文件只暂存本轮片段；无依赖、素材、存档 schema、语言资源或 hooks 脚本改动，不 push。
- **做了什么**：
  - 新增独立 `ForegroundFollower` 与窄 Win32 接口，关闭置顶时注册 `EVENT_SYSTEM_FOREGROUND` / `WINEVENT_OUTOFCONTEXT`。Qt GUI 线程接收回调，只启动单次零延时合并请求；进程查询、Z 序调整均延后执行，不轮询。
  - 现取当前前台 HWND → PID → 映像名，大小写无关匹配 Claude.exe，不固定标题、PID、版本目录；查询后和逐窗调整前重验前台，失效/隐藏/最小化/查询失败跳过。其他程序前台不调整窗口。
  - 本体、气泡、爱心/升级圈、碎屑、Z、暂停标签及 FPS 用控制器现有窗口提供器获取，只处理可见窗口，不创建隐藏窗口 HWND、不主动显示。按既有前后层级插入 Claude 上方，跳过本组邻居，避免把 Claude HWND 直接用作 insert-after 而排到其后；无普通邻居用 HWND_TOP，避免继承 topmost。全部操作带 NOACTIVATE / NOMOVE / NOSIZE / NOOWNERZORDER，不改变前台，不设置 Claude owner。
  - 启动/关闭置顶立即排队检查；Qt Show / WinIdChange 补齐后来创建或重建的窗口。开启置顶先停跟随，quit / dispose / aboutToQuit 清理；注销失败保留 ctypes 回调并允许下次清理重试。非 Windows/offscreen 不加载 Win32 接口，API 失败写日志且不阻止退出。
- **测试与自查**：
  - mock Win32/Z 序覆盖多 PID/大小写、前台换程序/过期事件/查询中切换、无效/隐藏/最小化/进程查询失败、准确相邻排序/跳过本组/无邻居/topmost 邻居、全部附属窗口/隐藏不出现/延迟显示/句柄重建、回调无查询/100 次事件合并、注册/注销失败、清理重试、开关/退出与跨平台。Qt Show 使用真实事件验证，ctypes 绑定校验 64 位 HWND 参数及精确 flags。
  - 最终专项 `.venv\Scripts\python -m pytest -q tests/test_foreground.py tests/test_windowing.py --basetemp=.venv/preview-run/foreground/targeted-final-tmp` → **81 passed、2 skipped（9.88 秒）**；跳过既有 offscreen 原生焦点/层级及新增受控原生 Z 序测试。日志 `.venv/preview-run/foreground/targeted-final.log`。
  - 原生 Windows 无窗口 smoke：两次真实注册、处理消息和注销通过，未移动窗口。原生受控测试只替换目标窗口和进程识别，真实 SetWindowPos / GetWindow 校验本体及全部六类附属窗口紧邻目标上方且无 TOPMOST → **1 passed（2.42 秒）**，日志 `native.log`。环境没有有效前台 HWND，不能证明真实焦点保持；Claude 多窗口切换仍待用户验收。
  - 从暂存索引导出独立副本（排除原有台词/时段改动），相同专项 **81 passed、2 skipped（9.22 秒）**，日志 `staged.log`；确认本次提交不依赖未提交功能。
  - 全量 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/foreground/full-tmp` → **1473 passed、6 skipped、2 warnings（413.52 秒）**，日志 `full.log`；警告为既有 Pillow getdata 弃用。原生受控用例在全量收集后追加，已独立在原生平台通过、最终离屏专项跳过；其他代码未再修改。`git diff --check` 通过。
- **踩过的坑**：`SetWindowPos` 的 insert-after 指定的是待调整窗口前面的窗口，直接传 Claude 会排到其后；用 topmost 窗口作邻居还可能让普通窗口继承置顶。必须跳过本组邻居并对 topmost 边界使用 HWND_TOP。ctypes 回调必须保留到注销成功，不能在失败时清空引用。
- **待用户验收**（重启加载新代码）：
  - [ ] 关闭置顶，切换 Claude 的多个窗口，诗音及可见气泡/爱心/Z/暂停标签均位于对应窗口上方，键盘焦点仍在 Claude
  - [ ] 切到其他程序后正常遮挡诗音；Claude 最小化后诗音不跟随隐藏
  - [ ] 保持 Claude 前台时，后来出现的附属窗口仍排在上方；开关置顶反复切换正常
  - [ ] 高分屏/多屏下位置、尺寸、点穿与焦点保持正常，退出无残留窗口
- **下一步**：用户验收本轮与此前保留清单；本轮仅本地 commit，不 push。

## 2026-10-21：动态睡眠 Z、趴桌双眨与轻姿态（待用户验收）
- **范围与素材提交**：开始时完整读取 AGENTS/CLAUDE、核对 Git 干净；用户先确认方案再实现本步。按白名单仅提交 `assets/sprites/sleep.png`、`bed_1.png`、`bed_2.png`、新增 `fx_z.png`，提交 `24d72cd`（`assets: separate sleep Z from character sprites`）。raw、reference 未修改；所有其余 PNG 逐个 SHA-256 核对未变。无新依赖、无 hooks/台词/存档变更、不 push。
- **做了什么**：
  - `process_sprites.py --only sleep`：alpha 清理后人物只留最大连通块，取人物外面积最大的 Z，原像素透明底裁边单独导出（149×147）；sleep 重新按无 Z 的头部/人物边界缩放对齐。`process_sheets.py --only bed`：先分帧，再各留最大连通块，计算缩放并生成 bed_1/2。两入口仅写指定结果。
  - `effects.py` 增加纯逻辑 SleepZParticles 和独立点穿、不接焦点的 SleepZOverlay，由 PetWindow 帧时钟驱动。进入 sleep/bed 立即一个，此后 0.9 秒一个，最多 3 个，寿命 2.4 秒；右上匀速漂移总路程 40px、0.5→1 倍放大、±8°/1.2 秒摆动，最后 1/3 淡出。醒来/动作覆盖/拖动时立即停止发射并在 0.15 秒内淡出，重复同步不重启淡出，快速再睡不复活旧粒子。sleep/bed 独立锚点、床缺图使用 sleep 锚点，位置/距离/尺寸/特效窗口按本体高 200 的基准同比缩放；不扩大身体 mask，移动/改大小/置顶即时跟随，隐藏关闭清理。参数集中为 Z_* 常量。
  - 趴桌眨眼间隔改为 1.5～3.5 秒，20% 在闭眼结束后间隔 0.25 秒再眨 0.15 秒；叹气优先，取消待播第二眨，掉帧不延长。参数集中在 behavior.py。
  - working 每 3～5 秒一次 0.4 秒 sin² 点头，叠加原呼吸，sy 最多额外压缩 1.5%、前倾 1°；随机流独立，工作默认 calm/安静档仍点头。动作层、按住、拖动/下落时取消，恢复后重新等待，离开状态清空事件。neglect2 ±1.2°/3.5 秒慢摇，固定/calm、安静或动作覆盖时关闭，全部沿用脚底中心/现有姿态淡化；参数集中在 animator.py。
  - 截图默认合成睡眠 Z，并按假时钟重建粒子发射时刻（正式运行掉帧仍不补发）；增加互斥的 `--nod`、`--desk-blink single|double` 检查入口。规格同步更新。
- **测试与自查**：
  - 新增 `tests/test_sleep_motion.py` 43 项，覆盖发射上限/间隔/掉帧、漂移/增长/摆动/淡出、唤醒与快速再睡、四档缩放/位置跟随/透明窗口属性/置顶/隐藏关闭、身体 mask 与裁切、床缺帧、活动中改大小、叹气与双眨冲突/概率边界及采样、点头时间/幅度/独立随机流/状态清理、慢摇互斥和截图入口。素材处理新增 2 项：面积排序及定向生成白名单、Z 像素和当前输出可复现。既有桌子间隔断言与两处静止基准同步调整。
  - 相关专项：offscreen，**224 passed、3 skipped（78.05 秒）**；随后仅将 Z 的末端减速改为匀速并补相邻间距断言，避免多枚挤在漂移末端，纳入最终全量。
  - 原生 Windows 150%（DPR=1.5，可用区 1707×1019）：新增专项 **42 passed、1 skipped（16.85 秒）**，包括四档大小、WS_EX_TRANSPARENT / WS_EX_NOACTIVATE / WS_EX_TOPMOST 原生属性。当前 `GetForegroundWindow()` 为 0，焦点测试按证据不足跳过，不能声称真实输入焦点已通过。
  - 最终全量回归：`QT_QPA_PLATFORM=offscreen`、`PYTHONUTF8=1`，`.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/sleep-motion/full-tmp` → **1340 passed、6 skipped、2 warnings（406.34 秒）**。跳过为既有两项原生非激活显示、一项需要在 CC 内的进程链、既有原生层级检查，以及本轮两项原生 Z 属性/焦点检查；本轮属性已在上述 Windows 专项通过，真实焦点证据不足仍保留待验收。两条警告为既有 Pillow getdata 弃用。日志 `full.log`，`git diff --check` 通过。
  - 通过 `python -m shion --snapshot` 生成 56 张最终关键帧：sleep/bed 四档大小各 0/.9/1.8/2.2 秒，working 四档 0/.2/.4 秒，neglect2 四档左右峰值，desk 双眨 0/.15/.4/.55 秒。仅查看这些截图及其拼图，确认 Z 位置、比例、轨迹间距、眨眼开闭和身体无明显裁切。原素材 PNG 未打开。截图、拼图和日志全部在已忽略的 `.venv/preview-run/sleep-motion/`，不提交。
- **踩过的坑**：bed 换呼吸帧时身体 mask 本来就变，需逐帧验证而非把整段当静止图；切离 working 时要清理下一次点头，不能只改 enabled；眨眼/叹气结束比较加微小容差，避免浮点边界多留一帧。
- **待用户验收**（重启加载本次代码/素材）：
  - [ ] sleep / bed 无固定残留 Z，动态 Z 从头部右上冒出，大小、摆动、间距、淡出自然；起床立即收尾，没有遗留或突然重新变亮
  - [ ] 四档大小与原生高分屏下 Z 比例正常，切大小/移动/床与坐睡切换不偏位，床呼吸与 Z 同时自然
  - [ ] Z 所在区域完全点穿，正在输入的其他窗口不丢焦点；置顶关闭可被普通窗口盖住，隐藏/退出无遗留窗口
  - [ ] 趴桌约 1.5～3.5 秒眨眼，偶尔双眨且不打断叹气；工作点头与冷落慢摇轻微自然，动作/拖动切换不跳位
- **下一步**：用户验收本轮及此前保留的真实桌面清单；本轮代码/测试/规格/进度单独本地 commit，不 push。

## 2026-10-21：置顶开关、面板避让与版本统一（待用户验收）
- **范围**：本次会话开始时已完整读 AGENTS/CLAUDE，`git status` 确认干净；先给方案，用户回复「确认」后实现。只改程序、三语菜单、测试和规格/进度；无新依赖，不改素材或 hooks，不 push。
- **做了什么**：
  - 新增兼容 v5 的可选存档字段 `always_on_top`，默认 true；缺失、非布尔值均默认开启。三语右键菜单即时生效并经既有存档调度写盘。同步本体、气泡、摸头/升级爱心、吃零食碎屑、暂停文字标签和调试 FPS；延迟创建的窗口继承当前开关。
  - 新增 `windowing.py` 统一处理 Qt flags 切换：原可见窗口重新 show，保留位置、大小、mask、其他 flags 和透明/不抢焦点属性；原隐藏窗口不出现。诗音明确设置 `WA_ShowWithoutActivating` 与 `WindowDoesNotAcceptFocus`。
  - 授权新队首、plan_ready、有效 Stop，以及 stop_work 后首次真正到达检查点时，只前移一次；静音也生效，定时同步不反复前移，被诗音结束的一轮的后续 Stop 不前移。Windows 调用 `SetWindowPos(HWND_TOP, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)`，不调用激活/切前台 API，不改变置顶开关；对话框最后前移，保持在本体/特效之前。
  - 关于、反馈输入、对话选择、授权面板各自始终置顶；按身体中心选当前显示器，优先右侧，不足换左侧，再不足尝试上下。使用可用区域和实际面板/原生边框尺寸；授权展开与对话换页重新定位。主动输入/关于仍可用键盘，自动授权和对话选择继续沿用原焦点安全规则。
  - 将旧 `controller.VERSION = "0.1"` 替换为唯一 `shion.__version__ = "0.4.1"`，关于和 QApplication 从这里读取。排查 shion/assets/tools 后没有其他运行时应用版本常量；存档/内容 schema、HTTP 协议版本和未来菜单 v1.0 标记不是当前应用版本，保留。
  - `--snapshot --panel about` 新增关于截图，`--with-pet` 可把面板与诗音按真实定位结果合成，供避让自查。
- **测试与验证**：
  - 新增 `tests/test_windowing.py` **48 项**：布尔校验/旧档默认与持久化、启动恢复、三语勾选菜单、反复切换几何/mask/flags/可见性、延迟附属窗口、独立面板置顶、有效/被抑制的完成、授权排队、检查点只前移一次、层级顺序、三种显示器坐标与五个边缘位置、空间不足时上下避让、授权展开、关于版本/避让和合成截图。既有菜单断言与气泡替身同步更新。
  - 面板相关专项（新测试 + controller/permission/dialogue/pause_badge）：**281 passed、3 skipped（90.13 秒）**，offscreen；跳过两项原生焦点检查及新增 Windows 层级检查。
  - 原生 Windows，`DPR=1.5`、可用区 1707×1019：新增专项 **48 passed（12.14 秒）**；补强后再次检查本体/气泡/爱心/标签能被普通窗口遮挡、提醒前移后整组位于覆盖窗口前、实际 WS_EX_TOPMOST 正确、几何和 mask 不变，以及关于开着时来回切换仍始终置顶：**1 passed（2.33 秒）**。**焦点证据限制**：当前会话 `GetForegroundWindow()` 为 0，比对句柄未变化不足以证明有实际前台窗口时的键盘焦点；未把焦点标为通过，需用户在正常桌面输入时验收。这些自动检查也不代替用户真实桌面验收。
  - 最终完整回归：`QT_QPA_PLATFORM=offscreen`、`PYTHONUTF8=1`，`.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/windowing/full-tmp` → **1297 passed、4 skipped、2 warnings（402.39 秒）**。跳过为既有两项原生非激活显示、一项需要在 CC 内运行的进程链，以及新增原生 Windows 层级检查（已另跑）；警告为既有 Pillow getdata 弃用。日志 `full.log`，`git diff --check` 通过。
  - 原生 Windows 下通过 `python -m shion --snapshot` 生成中/英/日五类面板合成图共 15 张，另生成暂停气泡/标签图；检查合成对照图，文字可读、版本正确、身体与面板无重叠或明显裁切。首次 offscreen 截图出现字体方框，已改用原生 Windows 重新生成和检查；没有据此修改产品字体。截图/日志/临时文件均位于已忽略的 `.venv/preview-run/windowing/`，不提交。
- **待用户验收**（先重启加载本次修改，此后切开关无需重启）：
  - [ ] 三语置顶勾选显示正常；关闭后诗音、气泡、爱心和暂停标签可被其他窗口盖住，重新开启立即置顶；重启记住选择
  - [ ] 授权面板始终置顶；四类提醒各前移一次，正在输入的窗口与键盘焦点不变，未重新开启置顶开关
  - [ ] 关于、反馈输入、对话/零食和授权面板在身体旁，不被诗音遮挡；贴左右边缘换侧、多屏/高分屏、展开授权详情显示完整
  - [ ] 切换开关无位置跳动/轮廓损坏，透明区仍点穿；关于显示 0.4.1
- **下一步**：用户验收本轮及之前保留的真实桌面清单；不 push。

## 2026-10-21：抱胸待机与动作衔接（待用户验收）
- **素材先提交**：按用户白名单仅提交 `.gitignore`、`assets/sprites/idle.png`、`blink.png` 和 `raw/idle.png`、`raw/blink.png`，提交 `348b498`（`assets: switch idle/blink to crossed-arms pose`）；旧张手图仍在被忽略的 `raw/old_arms_open/`。本轮没有修改或重新生成素材，没有打开原始 PNG。
- **做了什么**：
  - `pet_window.py` 新增统一常量 `ACTION_FADE_SECONDS = 0.100`，仅在底层 idle（含 blink）进出转身、侧身、有效跳跃帧、捏脸与挠痒动作层时线性混合透明度；复用现有预乘 RGBA 加权绘制，重叠的不透明部分不因 SourceOver 闪透。
  - 动作内部继续按原时间直接取帧，不增加压扁、不延长动作；自然结束从预定结束时刻采样末帧开始淡出，长掉帧后直接到达应有的混合或完成状态。中断和连续触发从当前混合接续，结束后不残留旧层。
  - 淡化层共用脚底锚点和原宽绘制；目标图在透明度为 0 的起点就预留宽画布，退出淡化结束才收窄，避免第一帧之后才改窗口宽度。复用现有多层 mask 的完整轮廓并集与扩边/LRU 缓存，仅透明度变化时复用。切到其他底层表情、开始拖动或下落会清掉本层淡化；无有效动作帧的旧跳跃回退不增加淡化。
  - 表情之间的原有过渡、拖动/下落、眨眼均保持原行为；不改素材、依赖、hooks、台词、存档格式或动作调度。`--snapshot` 捏脸入口接入同一边界，无新增参数；规格补充边界规则与截图时刻。
- **测试**：新增 `tests/test_action_fade.py` **40 项**，覆盖两侧起点/中点/终点与时长、序列内部不重启、自然结束与掉帧末帧、中断及快速重触发、从当前 blink 混合接续、表情/其他底层状态/真实拖动/无帧跳跃排除、真实捏脸方向与松手、挠痒循环、四档大小的 mask 完整并集与所有可见像素覆盖、透明角点、脚底稳定、缓存复用、不透明重叠及 CLI 截图两侧中间帧。旧截图唯一性测试改用进入后的不同动作时刻：现在转身和跳跃的 0 秒都应显示待机，不能再断言不同。
- **验证**：
  - 新增测试 + 原有帧序列/动作/待机活着感/活跃度专项 **147 passed（68.00 秒）**。
  - 宽画布起点修正后，窗口/道具与宽画布/新增淡化专项 **134 passed、2 warnings（55.07 秒；既有 Pillow 弃用警告）**。既有宽动作测试补上淡化起点/退出中点/收窄后的脚底检查；静态身体取点改为新抱胸图的躯干中心，不再使用已经透明的旧左腿外侧。
  - 原生 Windows `DPR=1.5` 的完整轮廓/透明度/真实拖动/宽画布/透明角点最终专项 **16 passed（15.03 秒）**；只证明自动检查，未进行用户桌面动态点穿验收。
  - 最终完整回归：`PYTHONUTF8=1`、`QT_QPA_PLATFORM=offscreen`，`.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/action-fade/final-tmp` → **1250 passed、3 skipped、2 warnings（377.53 秒）**，日志 `final.log`。跳过为两项 offscreen 非激活显示与一项需在 CC 内运行的进程链检查；警告为既有 Pillow `getdata` 弃用。`git diff --check` 通过。
  - 通过 `.venv\Scripts\python -m shion --snapshot` 生成转身、跳跃、左右侧身与捏脸松手的 30 张起点/中点/完成截图，查看生成的对照图，无明显裁切或脚底错位。静态混合图有预期的双轮廓，实际 0.10 秒动态观感仍需用户验收。截图/日志均在已忽略的 `.venv/preview-run/action-fade/`，不提交。
- **踩坑**：首轮全量发现两项：旧身体点位已变透明、宽动作在 alpha=0 时未预留目标宽度。前者只更新对应测试的躯干取点，后者修正目标画布预留并补强既有宽图测试；未修改素材或放松 mask 覆盖要求。
- **待用户验收**（先重启诗音）：
  - [ ] 抱胸待机切入转身、跳跃、左右侧身，以及动作结束/中断回待机时，手部过渡自然；快速连续触发无残影积累，动作节奏正常
  - [ ] 捏脸和挠痒进出自然；动作内部、眨眼、表情切换与拖动维持原表现，抓住/拖动立即响应
  - [ ] 160 / 200 / 260 / 320 与高分屏下无裁切或脚底抖动，淡化期间轮廓点选和透明区点穿正常
- **下一步**：用户真机验收本轮及之前保留的清单；不 push。

## 2026-10-21：待机“活着感”（待用户验收）
- **范围**：用户确认方案后实现；只改程序、测试和规格/进度，无新增素材、依赖，不改 hooks、台词、存档格式或既有待机转身/小跳调度。截图、日志和测试临时文件均在已忽略的 `.venv/preview-run/idle-life/`，不提交。
- **做了什么**：
  - `animator.py`：idle / neglect1 呼吸改为 sy=1.000～1.025、3 秒；working 独立使用 sy=1.000～1.008、4 秒，即使没有 controller 的 calm 也生效。其他 calm 表情保留原来的轻呼吸，道具帧保持原样。
  - 仅 idle（含眨眼）增加脚底中心 ±1.5°、4.5 秒正弦摇摆，恢复后 0.3 秒平滑进入。随机换重心普通每 8～15 秒、活泼每 5～10 秒，持续 0.6 秒：2% 下蹲 + 0.6% 轻回弹，或随机左右歪 3°；歪身平滑接管慢摇摆，不叠成 4.5°。
  - 新增姿态在拖动、下落、按住鼠标、跳跃（含缺图回退）、转身、侧身、捏脸/挠痒、道具、非 idle、calm、固定表情和安静档期间取消，恢复重新等待、不补播。微动作使用独立随机流，按真实时间计算，不改变状态、好感或交互/睡眠计时。
  - `pet_window.py`：保留画面细粒度动画与脚底锚点，mask 使用 1° / 0.01 缩放量化与 4px 扩边，64 项 LRU 逐项淘汰，避免满后整批清空；量化和绘制精度也集中成常量。
  - `--snapshot`：新增 `--weight-shift crouch|left|right`、`--height 160|200|260|320`、`--activity quiet|normal|lively`，确定性查看新姿态；未打开原始素材。
- **测试**：新增 `tests/test_idle_life.py` 39 项，覆盖轻呼吸、摇摆边界与平滑进入、微动作曲线/峰值/频率、禁用和重排、掉帧一致性、动作互斥、四档大小的扩大画布检查、所有非透明像素的 mask 覆盖、透明角点、锚点/位置稳定、缓存复用/逐项淘汰和截图入口。另更新原有呼吸断言；原先使用 working 当静止基准的下落/跳跃像素测试改用 neglect2，工作状态的跳跃恢复测试改验实际工作呼吸。
- **验证**：
  - 针对调整后的跳跃/下落及全部新增测试 **74 passed**（35.93 秒）；此前专项其余用例通过。
  - 离屏 `QT_SCALE_FACTOR=1.5` 的新增测试 + 帧序列测试 **73 passed**（44.71 秒）；`QT_SCALE_FACTOR=2` 的几何/缓存/截图专项 **8 passed**（17.61 秒）。原生 Windows `DPR=1.5` 的几何/动作互斥/活跃度/缓存专项 **17 passed**（19.36 秒）。均使用仓库 `.venv\Scripts\python` 和项目内 `--basetemp`。
  - 原生 Windows 150%、320 大小、固定随机种子 42，模拟推进 60 秒 / 3600 帧（含眨眼与随机微动作），mask 只重建 **32 次**、最终缓存 33 项（上限 64）；推进过程约 0.172 秒。仅衡量时间线/遮罩开销，没有显示窗口/实际呈现，不作为桌面 FPS 或实际占用验收。
  - `PYTHONUTF8=1`、`QT_QPA_PLATFORM=offscreen`，`.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/idle-life/final-tmp` → **1210 passed、3 skipped、2 warnings（366.42 秒）**。跳过：对话/暂停标签两项 offscreen 非激活显示，及一项需在 CC 内运行的进程链测试；警告为既有 Pillow `getdata` 弃用。日志 `final.log`；`git diff --check` 通过。首次全量仅发现旧 working 静止像素断言，修正后反馈 UI 模块 **20 passed**，再完整重跑得到上述结果。
  - `--snapshot` 已生成呼吸峰值、working、左右慢摇摆、下蹲/回弹、左右歪身、安静档和四档大小截图；已查看生成的对照图，无明显裁切或错位。静态截图及自动检查不能证明真实桌面动态感和点穿。
- **踩坑**：默认系统 `pytest-of-<user>` 临时目录访问受限，改用项目内已忽略的 `--basetemp`；未改权限。working 新增呼吸后，旧“恢复后 sy=1 / 像素完全相同”断言不再适用，按新曲线验证恢复，不削弱位移/落地检查。
- **待用户验收**（先重启诗音）：
  - [ ] 普通 idle 呼吸和慢摇摆自然，偶尔下蹲回弹或左右换重心；活泼更频繁，安静无摇摆/换重心
  - [ ] working 只有轻呼吸；neglect1 呼吸更明显；固定表情、睡觉、趴桌、拖动、跳跃、转身/侧身、捏脸/挠痒不叠新待机姿态；恢复无补播或突跳
  - [ ] 160 / 200 / 260 / 320 与高分屏下无裁切、脚底/窗口抖动，动态轮廓与透明区点穿正常；帧率和占用可接受
- **下一步**：用户真机验收上述项目及之前保留的清单；不 push。

## 2026-10-21：问题 A、C 与授权面板及时收起
- **官方文档查证**（code.claude.com/docs/en/hooks）：Notification 的类型字段是 `notification_type`，`idle_prompt` 是 CC 回复完约 60 秒用户没输入时触发；`PermissionDenied` **只在 auto 模式触发**，手动否决授权框时不触发，所以没接；PermissionRequest 输入没有 `tool_use_id`，只能按工具名 + 参数和 PostToolUse 配对；取消正在运行的工具不触发 PostToolUseFailure（C 的根因）。
- **做了什么**：
  - A（`shion/controller.py`）：新增 `_end_pending`，立即中断成功、`work_stopped`、`pause_timeout` 的会话加进去；该会话紧接着的 Stop 按 work_stopped 处理：不加 claude_tasks、不 done、不说完成台词、不催、最近活动不记“做完了”，菜单“继续”照常；只吞一次，`prompt` 时作废。
  - C：hook 的 Notification 把 `notification_type` 作为 detail 发出（不转发 message）；`PetState.claude_event` 收到 `idle_prompt` 时去掉这个会话（含执行中的工具），controller 同时清 `_tool_wall`。台词照旧。
  - 授权面板：`PermissionQueue` 记 session 和 key（sha256(工具名+参数) 前 32 位），新增 `settle(session, key)` 只删除未决请求（hook 下次轮询得到 gone，不给决定，安全约定不变）。新接口 `/permission/settle`；hook 的 PostToolUse / PostToolUseFailure 一进来（检查点等待之前）就调它；`/event` 的 prompt / stop / idle_prompt 带 session 时撤掉该会话全部请求。界面靠原来 100 毫秒的 `_sync_permission` 收起或换下一条；25 秒过期保留作兜底。
  - 措辞：`praise_menu_working`（收到！马上转告～ / Got it! Passing it on right away~ / 了解！すぐ伝えるね～）、`feedback_bad_working`（收到！这就去转告～ / Got it! Passing that on right now~ / わかった！すぐ伝えてくるね～），工作中用；空闲时不变。
  - 文档：spec 事件表 stop / notification、hooks 节、授权排队、B 的新预期、转圈文字只在终端版显示；progress 的问题 A/B/C 标注处理结果，用户已验收的桌面端项打勾并标“用户验收 2026-10-21”。
- **测试**：`tests/test_interrupt.py`（中断 / work_stopped / pause_timeout 之后的 Stop 不计、不催、只吞一次、prompt 作废、别的会话照常；idle_prompt 只清该会话、其他 notification_type 不清）、`tests/test_permission.py`（settle 按会话 / key、不碰已决定的和旧 hook 的请求、字段校验、各事件触发与不触发、key 与参数顺序无关、子进程 hook：PermissionRequest 带 session/key，PostToolUse / PostToolUseFailure（含 Esc 中断）后还在等的 hook 不给任何决定、面板收起换下一条；伪造“同意”测试覆盖新接口）、`tests/test_hook.py`（Notification 带类型）、`tests/test_state.py`、`tests/test_remote_control.py`（三语新台词、空闲台词不变）。
- **验证**：`PYTHONUTF8=1`、`QT_QPA_PLATFORM=offscreen` 全量 **1172 passed、2 skipped、2 warnings（335 秒；跳过项和 Pillow 警告同前）**（日志 `.venv/preview-run/fix-ac/pytest.log`）；`git diff --check` 通过。按用户要求没开嵌套 CC 实测。
- **踩坑**：权限测试的 server 夹具回调只收两个参数，带 session 的 `/event` 会回 500；撤请求发生在回调之前，所以测试只看请求是否被撤掉。
- **待用户验收**（先重启诗音；hook 脚本改动对已装配置直接生效）：
  - [ ] 诗音面板等待时，在 CC 自己的授权框里点同意：工具一跑完诗音面板马上收起；点否决 / 按 Esc：在 CC 里再说话或约 60 秒后收起（不再等 25 秒）
  - [ ] 立即中断（或停太久）后诗音不再说“任务完成”、不催；菜单“继续”照常；再说一句话后下一次完成正常提醒
  - [ ] 在提问框上按 Esc 后，约 1 分钟内诗音退出工作中
  - [ ] 工作中点“做得好/有问题”说“马上转告”，空闲时说原来的话；切英/日语同样
- **下一步**：真机验收上面几项和之前保留的清单；用户级 model 设置待决定；不 push。

## 2026-10-21：终端版 CC 自动验收（CC 自动验收）
- **方式**：没改 `shion/`、`hooks/`、`tests/`。测试诗音照用 `start-debug.bat` 启动，但带隔离环境变量（`SHION_PORT=47699`、`SHION_DATA_DIR=.venv/preview-run/cc-auto/data`（真实存档副本）、`SHION_INSTANCE_NAME`），并用会话 scratchpad 里的 `sitecustomize.py` 挂命令通道，直接调用 `stop_work / resume_work / interrupt_work / continue_ended / feedback_good / feedback_bad / _on_permission_decided` 和暂停标签的 `activated` 信号；截图用 Qt `grab()`。嵌套 CC 2.1.289 `claude --model haiku`，工作目录为本项目（项目级 hooks 生效），清掉了桌面端继承的 `CLAUDE*` 等环境变量；会话 A 在 Windows Terminal，会话 B 在 conhost。输入用 `WriteConsoleInputW`，读屏用 `ReadConsoleOutputCharacterW`。
- **为什么隔离**：桌面端这个会话的工作目录也是本项目，自己的工具调用也会发 hooks。若和真实诗音共用，立即中断会把桌面端会话也中断。真实诗音全程没动；真实存档只多了正常运行的 `claude_tasks` 2→4 和 `last_attended`（来自桌面端会话自己的事件，不是测试造成），备份在 `.venv/preview-run/cc-auto/backup/`，未覆盖。
- **结果**（屏幕文字 `.venv/preview-run/cc-auto/screens/*.txt`，截图 `.venv/preview-run/cc-auto/shots/*.png`，均已忽略、不提交）：
  1. **授权**：CC 把 `echo` 当只读命令直接放行，所以改用 `.venv\Scripts\python -c ...`。诗音面板出现（`1-perm-allow-perm.png`：“要不要同意？ [PowerShell]”、命令全文、否决/同意），同意后 CC 显示“Allowed by PermissionRequest hook”并执行；否决后显示“Denied by PermissionRequest hook”，回复 “The operation was denied by you via Shion.”，要写的文件没生成。**但面板等待期间 CC 自己的授权框同时显示**（`screens/1-perm-pending.txt`），诗音决定后才收起，见问题 B。等待中诗音还会多说一句“它好像有话想问你”（Notification）。
  2. **停下/继续**：停下 2 秒内在 PreToolUse 停住，说一次“已经停下啦～”，菜单第一项变“继续”，标签“暂停中”出现（`2-held-badge-*.png`）；CC 转圈处一直显示“诗音在看着～（一直停在这里就是暂停了，右键诗音点继续）”。停 8 秒确认确实不动；点标签、点菜单“继续”、在 CC 里说“继续吧，把剩下的做完”三种方式都无缝继续，标签消失，诗音说“继续干活啦”。点停下但还没停住时标签不显示。
  3. **立即中断 `Start-Sleep 120`**（CC 这台机器只有 PowerShell 工具）：点击后约 0.9 秒命令结束，CC 回复 “Sleep interrupted. Waiting for your signal to continue.”，这一轮结束；菜单第一项变“继续（发送“继续”）”。点了以后 CC 输入框收到“继续”，执行 `echo resumed-ok` 并正常结束，诗音说“发过去啦，接着干～”。中断后诗音又说“任务完成～快去看看吧！”，见问题 A。
  4. **草稿**：输入框有 `DRAFT-abc` 时点发送：日志 `发送“继续”：draft`，诗音说“输入框里还有没发出去的字，我就不动啦”，草稿原样，菜单项保留。
  5. **反馈**：工作中点“做得好”→诗音“收到！下次干活时我就转告～”，CC 回应原文：“Both sleeps completed. During the task, I received feedback: "用户觉得你刚才做得很好" (The user thinks you did very well just now).”。空闲时“有问题……”填“回答太长了，简短一点”→诗音“收到，我会转告的”，下一条消息时 CC 回应原文：“Understood—I'll keep replies shorter and more concise going forward.”
  6. **计划/完成提醒**：计划模式下 ExitPlanMode 时诗音只说“计划写好啦，去看看吧～”（`6-plan-bubble.png`），不弹面板，CC 自己显示计划确认；按 Esc 拒绝，文件没创建。完成提醒只说“任务完成～快去看看吧！/做完啦！去看看结果吧～”，不带回复内容。注意：项目 `.claude/settings.json` 是 `opusplan`，**进入计划模式后 CC 自动换成 Sonnet 5.5**，加 `--model haiku` 和 `--settings` 都改不回来；为此这一条计划 prompt 用的是 Sonnet。
  7. **长命令与并行**：A `Start-Sleep 330`（工具超时设 600000ms）从 09:46:49 到 09:52:20 每 30 秒采样都在工作中，结束后才退出（调试模式空闲 60 秒就会退出，说明是“有工具在跑”保持的）。并行时 B `Start-Sleep 20` 先结束，诗音说“做完啦！去看看结果吧～”，A 继续在工作中列表里。第一次没设超时，CC 自己在 2 分钟时把命令超时结束了（CC 工具默认 2 分钟），所以重跑了一次。
- **观感（看截图判断）**：授权面板、暂停标签、计划气泡排版正常，文字无裁切；停住时诗音是挡手表情。CC 里 statusMessage 的中文能完整显示，意思清楚。
- **限制**：
  - 测试全程电脑处于锁屏，前台一直是锁屏程序。每一步前后记录的前台窗口和焦点都没变，但锁屏时别的程序本来就抢不到前台，所以这只能说明“没有出错”，**不能证明解锁时不抢焦点**（之前 10-20/10-21 的实验在解锁状态下测过发送不抢焦点）。屏幕区域截图拍到的是锁屏壁纸，已删除；也看不到真实桌面上标签/气泡/面板的叠放和点穿。
  - 标签点击走的是 `activated` 信号，没用真实鼠标，0.6 秒防误点和悬停提示仍由单元测试覆盖。
  - 只测了中文；桌面端 Code 的项目不在本轮范围。
- **发现的问题**（2026-10-21 已处理，见「问题 A、C 与授权面板及时收起」）：
  - **A 立即中断后又说“任务完成”**（✅ 已修）：中断时 CC 后面没有工具调用，这一轮以普通 Stop 结束；`PetState.claude_event("stop")` 照常算完成：`claude_tasks` +1、done 表情、说“任务完成～快去看看吧！”，之后还会催“结果还在等你看呢～”。两次中断都复现。规格没写这种情况，但和“work_stopped 不算完成任务”不一致。
  - **B 授权框同时显示**（不修，改预期：两边哪边先答都可以，CC 里答了以后诗音面板自动收起）：CC 2.1.289 在 PermissionRequest hook 等待期间就显示自己的授权框，诗音决定后才收起。和清单里的预期“hook 给了决定就不弹”不一致；用户此时在 CC 里自己选也行，但两处同时问。可能是 CC 的行为，不一定能改。
  - **C 取消工具后一直显示工作中**（✅ 已修：收到 idle_prompt 时清掉）：在 CC 的提问框（AskUserQuestion）上按 Esc 取消后，CC 没发 PostToolUse / PostToolUseFailure / Stop，诗音把这个会话当成“工具还在执行”，最长 30 分钟一直显示工作中（实测 09:35 起到收尾时 09:53 仍在工作中列表里）。按 Esc 拒绝授权框、拒绝计划等情况可能也一样，没逐一测。
  - **其他观察**（✅ 已改措辞）：工作中点“做得好”时诗音说“收到！下次干活时我就转告～”，这时其实正在干活，措辞有点不贴切。
- **副作用**：为了把计划模式换回 haiku，我在嵌套 CC 里执行过一次 `/model haiku`，CC 把用户级 `~/.claude/settings.json` 的 `"model"` 改成了 `"haiku"`（“saved as your default for new sessions”）。原来的值没有备份、无法确定，**未恢复，等用户决定**。另外 CC 在 `~/.claude/plans/` 留下两个计划文件，都是测试产物。
- **验证**：测试后 `PYTHONUTF8=1`、`QT_QPA_PLATFORM=offscreen` 全量 **1132 passed、2 skipped、2 warnings**（314 秒），`git diff --check` 通过。
- **下一步**：A/C/措辞已修、B 改预期（见「问题 A、C 与授权面板及时收起」一节）；用户级 model 设置怎么处理仍待用户决定；不 push。

## 2026-10-21：v0.4.1 好感度系统
- **配置与额度**：
  - 新增 `assets/affection.json`（schema_version=1）与纯 Python `shion/affection.py`；阈值 0/50/200/500/1000，等级名初识/熟悉/亲近/信赖/知音，升级台词三语完整。五级戳反应系数 1.2/1.0/0.85/0.7/0.6；挡手与晕同时缩放，概率和超过 1 时按比例归一。
  - `PetState` 接受注入的规则，正式启动加载 JSON，`None` 明确表示旧行为（既有测试环境继续覆盖这条回退路径）；所有时间仍由调用方传入，不依赖 Qt。
  - 摸头每次 +1、每天最多 +20；完成喂食每次 +2、共享前五次；每个已解锁预设每天首次 +1；当天第一次真正打开 +2（包含 hook 拉起，重启不重复，单纯跨天不发奖）。跨午夜喂食归完成当天，取消/未完成不计。达到摸头上限仍正常摸、记次数和冒普通爱心。
  - 经用户确认，新系统启用后“做得好”只加入工作反馈队列，不再加旧的 +3；配置失效时恢复旧规则。好感不会因冷落或久未打开下降。
- **存档、升级和状态**：
  - 存档 schema_version=5，增加 `affection_level`、`affection_daily`（date/pat/snack/open/talks），保留 `snacks` 兼容记录。旧存档按累计好感建立等级基线，不补播；当天已有摸头/喂食会占用额度。配置缺失、坏 JSON、版本/关键字段不合法时禁用新逻辑，保留字段；修复后重新计算等级，并合并回退期间的当天摸头/喂食统计，不补播。
  - 每次实际增长只产生至多一个升级事件，一次跨多级只播最终等级；高优先级气泡遵守静音。升级单独放一圈 12 颗爱心，不占用/受限于普通摸头粒子；沿用点穿和不抢焦点窗口。同一批出现催回提醒时升级排最后，避免立刻被遮掉。
  - 双击保留陪伴时长、摸头/任务数和累计好感，新增等级名、本级升级进度、今天还能获得的总量；只计当前已解锁的对话，满级显示“已满级”并继续累计。配置失效时保留旧状态文本、原始概率、通用台词和不按等级过滤的菜单。
- **内容**：
  - `MenuItem.min_level` 和台词对象 `{text,min_level}` 支持 1～5，旧字符串台词默认可用；菜单过滤后重新连续编号，选择入口再次校验，已打开菜单在等级改变后刷新，不显示锁定占位。
  - “陪我一下”2 级；新增“听我说说”3 级、“分享巧克力”4 级、“以后也陪着我”5 级。每级 3 句专属自言自语、2 句摸头、2 句冷落回归，中英日齐全；越高级越亲近、温柔嘴硬，不用冷落制造负罪感。
  - 五级感谢台词仅在既有自言自语机会中以 5% 抽取，至少间隔 1800 秒（均可在 JSON 调整）；不提高整体主动说话频率，被高优先级气泡挡住时不消耗机会。
- **验证**：
  - `PYTHONUTF8=1`、`QT_QPA_PLATFORM=offscreen`，`.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/affection-full-final` → **1131 passed、3 skipped、2 warnings**（314.71 秒）。跳过项为对话/暂停标签的离屏非激活检查，以及本轮不在 CC 内运行的进程链检查；两条 warnings 是既有 Pillow getdata 弃用警告。
  - `QT_QPA_PLATFORM=windows`、`QT_SCALE_FACTOR=1.5`，`tests/test_affection_ui.py tests/test_dialogue.py tests/test_effects.py` → **102 passed**（25.95 秒）；覆盖新增等级 UI、菜单过滤与真实窗口回归、升级爱心独立限流、静音、同帧催回仲裁等。额外的气泡仲裁回归 **74 passed**。原生自动事件不替代下方亲眼验收。
  - 通过正式 `python -m shion --snapshot` 生成并检查中英日状态与升级气泡共六张截图；中文二级进度、英文满级、日文三级等均正常折行、不截字。未打开原始 PNG 或修改 `reference/`、精灵图。`git diff --check` 通过。
  - 日志、截图和预览辅助脚本在已忽略的 `.venv/preview-run/affection-artifacts/`；测试临时目录在 `.venv/preview-run/affection-*`，均不提交。没有操作用户真实存档或重装 hooks。
- **踩坑**：迁移测试最初把 49 分之后真正获得 +1 的合法升级误当作“补播”；改为仅验证初始化、查询和无奖励交互不播，真实跨阈值由各来源的升级测试覆盖。代码复查还发现喂食升级与催回同帧会被后者覆盖，已调整批内顺序并补回归。
- **待用户验收**（先重启诗音）：
  - [ ] 原存档累计好感保留，直接显示对应等级；迁移不补播旧升级。当天重启不重复领取 +2、额度不恢复。
  - [ ] 双击三语等级名、升级进度、今日剩余量排版清楚；满级文字正常；切换语言立即一致。
  - [ ] 跨过等级阈值时只说一次该等级台词、放一圈爱心；连续摸头已达到普通爱心上限时仍能看到升级圈。静音不说台词但仍放爱心，双击仍可看状态。
  - [ ] 2/3/4/5 级对应对话与零食自然出现，未解锁内容没有占位；数字键与鼠标选择对应同一项目，打开菜单仍不抢原输入框的焦点。
  - [ ] 每级摸头/久别回来/自言自语的语气符合人设，等级越高越亲近；5 级感谢台词偶尔出现，不显得频繁或催促。
  - [ ] 真实桌面下爱心圈不挡点击、不抢焦点；移动、四档大小、贴屏边、高分屏与多显示器表现自然；戳反应随等级变化的体感合适。
- **下一步**：用户亲眼验收本节及之前保留的项目，再决定是否调整数值；不推进 v0.5 内容包，不 push。

## 2026-10-21：悬停不唤醒、不打断状态或动作
- **做了什么**：
  - 删除 `PetWindow.hovered`、`PetController._on_hover` 及连接；`enterEvent` / 无按键 `mouseMoveEvent` / `leaveEvent` 只更新光标，保留 Qt 自带提示；拖动时进入/离开仍保留握手光标。
  - 复查全部 `interact()` 调用，剩余仅为双击、动作菜单、停下和立即中断这些实际操作；`show_menu` 与 `contextMenuEvent` 不再唤醒或停止已有动作。菜单打开期间仍暂停新待机动作调度，已有动作按原时间线继续。
  - 更新原先用悬停唤醒的测试与规格/旧接口说明；新增 `tests/test_hover_passive.py`，覆盖白天睡眠、夜间床睡、菜单床睡/晚安、手动/自动趴桌、落寞/蜷起、九种固定表情、临时/待机表情、工作/暂停、吃零食、转身/侧身/跳跃（手动与自动）、鼓腮/挠痒，以及计时/台词不变、自动入睡不推迟、浏览/取消菜单和真正操作仍唤醒。
- **验证**：`PYTHONUTF8=1`、`QT_QPA_PLATFORM=offscreen`，`.venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/hover-passive/full` → **974 passed、3 skipped、2 warnings**（316.16 秒）。三项跳过分别为 offscreen 不支持的对话/暂停标签非激活显示，以及本轮不在 CC 内运行的进程链检查；两条 warnings 为既有 Pillow getdata 弃用警告。原生 `QT_QPA_PLATFORM=windows`、`QT_SCALE_FACTOR=1.5`，`tests/test_hover_passive.py` → **53 passed**（19.13 秒）。`git diff --check` 通过。日志在已忽略的 `.venv/preview-run/hover-passive/`，不提交；原生自动事件不替代下列用户亲眼验收。
- **踩坑**：直接替换 `QMenu.exec` 未拦住原生菜单事件循环，首轮测试卡住；已终止本轮测试进程并改用菜单执行替身，保留真实 Qt 上下文菜单事件到控制器的路径，避免等待人工关闭菜单。旧测试改成真实点击后会刷新被理会时间，跨夜久别优先说 `neglect_return`；夜间唤醒用例已隔离久别条件，保留原台词优先级。
- **待用户验收**（先重启诗音）：
  - [ ] 坐着睡觉、床上睡觉、晚安后、趴桌、落寞、蜷起来、固定表情时，鼠标反复移入/移出和移动均不唤醒、不换状态、不冒起床台词。
  - [ ] 转身、侧身、跳跃、鼓腮、挠痒等进行中移入/移出不打断；仅打开菜单、浏览子菜单、Esc/点外部取消也不打断，动作按原时间自然结束。
  - [ ] 头顶光标仍为张开的手，身体与移出恢复正常；拖动保持握手光标；暂停标签悬停提示正常，真实桌面点穿与四档尺寸/高分屏表现正常。
  - [ ] 真正左键点击、摸头、捏脸、挠痒、拖动、双击及选择菜单动作仍能脱离睡眠/趴桌；固定表情仍按既有优先级在动作后恢复。
- **下一步**：用户亲眼验收以上项目及之前保留的清单，不推进其他功能，不 push。

## 2026-10-21：这一轮结束后的“继续”（终端发送 / 桌面端复制）
- **做了什么**：
  - 新文件 `shion/console_send.py`（不 import Qt）：`python -m shion.console_send --pid --created --text`，输出一行 JSON。先核对进程（在、claude.exe、创建时间一致）→ AttachConsole → 读屏 `check_screen` → 逐字 VK_PACKET + 回车 → FreeConsole。
  - `shion/controller.py`：`_ended` 记最近一个被诗音结束这一轮的会话（`work_stopped`、被中断会话的 `stop`、`pause_timeout`），该会话再来 prompt / working 就收起。菜单在“停下”上面多一项：终端（`interrupt.is_terminal`：entry=cli 且 claude.exe）→“继续（发送“继续”）”，用 QProcess 跑子进程（10 秒超时、同时只一个、发送中变灰）；其他 → “继续”，复制到剪贴板。停下中的“继续”、立即中断、暂停标签都不变。终端会话停太久也给“发送”（和立即中断同一状态）。
  - 三语台词 7 个 key（`continue_text` 继续/Continue/続けて 等），界面不出现“Claude”。spec v0.3 新增「这一轮结束后的继续」。
  - 测试 `tests/test_continue_after_stop.py`（32 个）：读屏判断（空、草稿、占位提示+光标、多行、信任框、权限框、编号选项、回复里的普通列表）、进程核对、子进程拒绝非 claude 进程、菜单各种情况、各失败原因的台词、单个发送、三语。
- **真机（scratch 目录里开的测试 CC，haiku，2.1.289）**：
  - conhost：信任文件夹对话框 → `dialog`；空输入框 → 送达、CC 回复、前台窗口不变；草稿 `DRAFT-abc` → `draft`，草稿原样；创建时间不对 → `gone`；权限确认框（Do you want to proceed? / > 1. Yes）→ `dialog`。
  - pythonw + QProcess（和正式启动方式一样）→ 送达。
  - Windows Terminal：草稿 → `draft`；空输入框 → 送达，前台不变。
- **踩过的坑**：
  - 空输入框里有灰色占位提示（`> Try "write a test for <filepath>"`），读屏分不出颜色（属性全是 0x7）。改用控制台光标位置：空的时候光标在提示符后面（第 2 列），打过字光标跟在字后面。规则：输入行为空，或是 `Try "…"` 且光标在提示符后面，才算空。
  - CC 回复里的普通编号列表（`1. What you were working on`）会被当成确认框。确认框的编号选项总有选中标记（`> 1.` / `❯ 1.`），所以只认带标记的编号行；确认字样（Yes / Allow / Do you want …）仍按最下面 25 行保守匹配，回复里碰巧有这些字时也不发。
  - conhost 的提示符是 `>`，Windows Terminal 里是 `❯`，后面跟的是不换行空格（ ）。
  - 在 PowerShell 里跑全量时 `test_install_hooks.py::test_corrupt_json_not_touched` 偶尔因 gbk 解码失败（已有问题，和本次无关）；用 `PYTHONUTF8=1` 跑全量通过。
- **待用户验收**（先重启诗音）：
  - [x] 终端版 CC 工作中点“立即中断”，这一轮结束后菜单第一项是“继续（发送“继续”）”；点了以后 CC 收到“继续”接着干，诗音说“发过去啦，接着干～”，前台窗口和焦点不变（✅ CC 自动验收 2026-10-21，终端版；焦点见该节限制）
  - [ ] 终端输入框里有没发出去的字时点它：不发送，草稿不变，诗音说明原因；CC 正在问确认问题时同样不发（CC 自动验收 2026-10-21：草稿部分通过：不发送、草稿原样、诗音说“输入框里还有没发出去的字，我就不动啦”；确认框部分本轮没经诗音测）
  - [x] 桌面端 Code 点“立即中断”：说法和以前一样；这一轮结束后菜单出现“继续”，点了剪贴板里是“继续”，诗音说“已经复制好啦，去 CC 里粘贴发送就行～”，粘贴发送能接着干（✅ 用户验收 2026-10-21，桌面端）
  - [ ] 停下后等满上限（可以先把 `remote.pause_timeout` 调到 60 秒）：桌面端出现复制版“继续”，终端出现发送版
  - [ ] 自己在 CC 里说话后，这一项消失；切换英/日语后菜单和发送的文字跟着变（CC 自动验收 2026-10-21：发送“继续”后这一项消失；切换英/日语本轮没测）
- **下一步**：真机验收上面几项和之前保留的清单；不 push。

## 2026-10-20：可点击的暂停文字标签（取代 ⏸）
- **显示条件**：沿用 `_held_seen`，请求停下但未到检查点时不显示；真正等待后显示，长轮询间隙/别的台词/静音不闪退；继续、CC 新 prompt、超时或立即中断会隐藏。原有 ⏸ 验收项由本节取代。
- **外观与三语**：`shion/badge.py:PauseBadge` 独立小窗口，气泡同款黑底/米白字/橙色 1px 描边、4px 圆角、等宽字体和语言 fallback；字号与气泡一致，按文字量宽，头顶右侧跟随大小、位置与跳跃，夹进可用屏。中“暂停中”+“点一下继续”，英“Paused”+“Click to continue”，日“一時停止中”+“クリックして再開”。切换语言即时生效，截图 `--badge --lang zh|en|ja` 已同步。
- **交互**：移除整个标签窗口的输入穿透，仅标签自身接左键，圆角遮罩外透明，诗音其余透明区继续点穿。`WindowDoesNotAcceptFocus`、`WA_ShowWithoutActivating`、NoFocus，键盘事件一律忽略；复用授权面板 `ARM_DELAY=0.6`，按下和松开都须在解锁后且在标签内，刚出现按住跨过时限再松开也无效。常规定时 sync 不重置时限，隐藏再出现重新防误点。点击经 `PetWindow.resume_requested` 到同一个 `resume_work`，放行并行等待、隐藏标签、按原仲裁/静音规则说“继续干活啦”。
- **验证**：扩充 tests/test_pause_badge.py，保留原可见性和 statusMessage 回归，新增文字量宽/配色、0/0.599/0.6 秒边界、提前按住后松开、右/中键与键盘无效、移出再松开无效、两个检查点同时放行、三语提示与字体/跟随、输入框焦点不变和再显示重新计时。原生 Windows + 150% 缩放 **34 passed**；已生成并检查三语 `--snapshot --badge` 截图，标签不挡脸，带气泡截图留有间距。没有重装 hooks、没有操作正在运行的 CC 会话。
- **最终全量**：`PYTHONUTF8=1 .venv\Scripts\python -m pytest -q -rs --basetemp=.venv/preview-run/props-label-final` → **889 passed、3 skipped、2 warnings**（286.73 秒）。三项跳过：对话窗口/暂停标签的焦点检查需要原生窗口环境（标签已由原生 Windows 150% 的 34 项专项验证，并额外确认活动窗口和输入控件均保留）；CC 进程链检查因本轮不在 CC 中运行而跳过。两条 warnings 均为既有 Pillow getdata 弃用警告。`git diff --check` 通过。
- **待用户验收**（先重启诗音）：
  - [x] 正在 CC 中输入时，真正到检查点才出现标签，键盘仍留在 CC；点“停下”但尚未停住时不显示（✅ CC 自动验收 2026-10-21，终端版；焦点见该节限制）
  - [ ] 三语文字、字体、描边、鼠标悬停提示和位置；静音/其他气泡/拖动/跳起时显示稳定
  - [ ] 出现后立刻点无效；0.6 秒后左键点击，无缝继续、标签消失、诗音说“继续干活啦”；右键/空格/回车不续跑
  - [ ] 标签外及圆角透明处能点到桌面下方窗口；贴屏幕四边及不同大小时位置合适
  - [x] 终端版和桌面端 Code 标签页都能通过该标签放行真实检查点（CC 自动验收 2026-10-21：终端版通过；✅ 用户验收 2026-10-21：桌面端停下后点标签继续通过）
- **下一步**：本轮集中真机验收第 1～5 项及之前保留的验收清单；不推进好感度/内容包，不 push。

## 2026-10-20：床睡、趴桌、宽画布与松手原地停放
- **素材预提交**：`61fe43d`，仅 tools/process_sheets.py、bed/desk 两张 raw 分帧图和五张生成帧；未改动其他原图。bed 为 640×512，desk 为 448×512，RGBA；提交 Author/Committer 均为指定 GitHub noreply 邮箱。
- **宽画布**：同组动作帧完整、同尺寸且高度与 idle 一致即可加载，允许更宽。绘制/混合/遮罩按原比例、脚底中心对齐，淡化结束收窄；贴边时夹回可用屏幕。窗口尺寸变化通知气泡/面板，拖动中的抓取偏移同步修正。床/桌缺帧或坏帧分别回退 sleep / neglect1，不影响其他组。
- **床/桌**：“去睡觉”和对话“晚安”、夜间自动睡眠使用 bed_1/2，每 0.9 秒交替；白天无人理会 15 分钟仍用 sleep.png。趴桌主要显示 desk_1，3～6 秒眨眼 0.15 秒，10～20 秒叹气 1.2 秒，叹气不插眨眼，掉帧跳过已过时的动作。进入 neglect1 时 35% 概率自动趴桌，同一次落寞只抽一次，不刷新被理会或睡眠时间。手动/自动趴桌均可触碰恢复；床睡沿用原唤醒台词/优先级规则。菜单及 bedtime / desk_rest 各三句台词三语齐全，无“Claude”。
- **慢放/甩出**：`ReleaseVelocity` 取最后 0.12 秒轨迹，二维速度 ≥450px/s 下落，否则轻轻压扁后停在原处（含抓住下落中的诗音再慢放），窗口本体夹进可用屏幕。停手后再松开不会沿用旧速度。右键新增“松手后落到任务栏”，默认 false，开启后恢复原重力行为；时间/速度/概率在 behavior.py 常量。拖动挣扎、晃晕、固定表情优先级保留，悬空待机只在原地。
- **存档**：保存实际 y，x 按普通画布换算，床上退出也不会使重启后的脚底中心横移。改大小、恢复存档、任务栏变化只夹边；旧档无 y 时贴底，副屏拔除回默认位置。可选布尔字段 release_to_taskbar 缺失/非法时为 false，未引入新依赖。
- **验证**：新增 tests/test_props_release.py；覆盖时间边界/掉帧、宽图比例与半透明混合、四种大小的遮罩及脚底中心、缺图独立回退、三语菜单、睡姿来源及唤醒、落寞概率只抽一次、慢放/甩出/停手/开关、四边限制和悬空重启；素材脚本新增两组帧数/整体居中/基线检查。专项 **95 passed、1 skipped**；原生 Windows（QT_QPA_PLATFORM=windows、QT_SCALE_FACTOR=1.5）**69 passed**。用 `python -m shion --snapshot` 生成床/桌带气泡截图并检查，没有打开源素材。全量结果与暂停标签完成后的最终复跑见后续记录。
- **待用户验收**（先重启诗音）：
  - [ ] 三语动作菜单：去睡觉、趴一会儿；床的呼吸、桌子的随机眨眼/叹气节奏，触碰恢复和起床台词
  - [ ] 夜间自动床睡；白天久置仍坐着打瞌睡；落寞时概率趴桌
  - [ ] 贴边、各尺寸、跳跃/拖动时宽窄切换的视觉稳定，床/桌透明区真实桌面点击穿透，气泡/面板位置
  - [ ] 慢放在屏幕任意处停稳，甩出落地；停手后慢放；开关开启恢复原行为；悬空重启位置保留、待机原地进行
- **全量首跑与修正**：全量首跑 **872 passed、4 failed、2 skipped**；4 项均为 test_feedback_ui 的旧菜单列表或“松手必下落”断言，已改为新菜单和开启开关后的重力场景。修正后受影响交互专项 **205 passed**；宽画布抓取偏移修正及任意动作组宽图支持的最终专项 **73 passed**。完成第 5 项后再全量复跑，最终结果在下一节记录。两项 skipped 和 Pillow 弃用警告保留如实记录。
- **下一步**：实现本次第 5 项暂停文字标签；不推进好感度或内容包。

## 2026-10-20：暂停可见性（CC 转圈文字 + 诗音 ⏸ 标记）
- **问题**：停下后 CC 只显示通用转圈，分不清是在跑还是被诗音停住。
- **statusMessage**：官方 hooks 文档的通用字段 `statusMessage`（“Custom spinner message displayed while the hook runs”，适用所有 hook 类型，含 `args` 的 exec 形式）。`tools/hooks_config.py` 只给 PreToolUse / PostToolUse 两个检查点条目加；文字取三语 `ui.hook_status_waiting`（都不含“Claude”，提到的按钮名与 `menu_resume` 一致）。安装时按存档语言（与 hook 的 `read_save` 同一路径、同一回退规则）写入，`install_hooks.py --lang` 可指定。**限制**：在诗音里换语言后要重跑一次安装。
- **重装**：`.venv\Scripts\python tools\install_hooks.py --settings .claude/settings.local.json`，存档语言 zh，两个条目已带中文文字，原文件自动备份。
- **⏸ 标记**：新模块 `shion/badge.py`（`PauseBadge` 独立点穿小窗口，同 FpsOverlay 的窗口属性；QPainter 画深色圆角底 + 两根竖条，不依赖字体字形；边长 = 精灵高度 × 0.055，夹在 18～30px；中心在本体 76% 宽、5% 高处，跳起时跟着上移）。控制器新标志 `_held_seen`：`_sync_pause` 看到 hub 真有 hook 在等就置位（与静音无关），`_leave_pause` 清掉；`sync()` 里 `set_paused_badge(paused and _held_seen)`。两段长轮询之间 `is_holding` 变 False 时标记不消失。宠物窗口隐藏时一起隐藏。截图：`python -m shion --snapshot out.png --badge`。
- **测试**：新增 `tests/test_pause_badge.py`（22 项：没到检查点不显示 / 在等就显示 / 长轮询空当与别的台词不影响 / 静音也显示 / 继续、CC 里说话、停满上限、立即中断都会隐藏 / 窗口隐藏跟随 / 位置在头顶右侧不在正上方、跳起上移、贴边夹紧 / 画出两根竖条 / statusMessage 只在检查点、旧调用不加、三语文字、回退中文、存档语言、换语言重装替换不重复）。完整 `PYTHONUTF8=1 .venv\Scripts\python -m pytest -q`：**836 passed、1 skipped**。
- **实测 hook 耗时（= 平时文字显示多久）**：真实启动 `.venv` python + hook，每种 10 次取中位数（脚本在会话 scratchpad）：
  - 诗音在运行：PreToolUse **约 0.34 秒**，PostToolUse **约 0.26 秒**（基本是 Python 启动开销）。也就是每次工具调用前后各闪一下约 0.3 秒的文字，大概率**看得见、但一闪就过**；
  - 诗音没开：PreToolUse **约 1.3 秒**，PostToolUse **约 3.3 秒**——Windows 上连本机关着的端口不会立刻被拒，每个请求要等一阵才报错，PostToolUse 要发的请求更多（停下检查、做完通知、取反馈）。这是**原来就有的**慢，只是现在会以文字的形式露出来。可以作为后续优化（例如先连一次失败就跳过后面的请求），本轮没改。
- **真实 CC 联调**（2.1.289、haiku，`claude -p --settings` 只装两个带 statusMessage 的检查点 hook，隔离端口和数据目录，不碰正在运行的诗音）：① 不停下：CC 接受该字段，Read 前后 hook 照常触发（working → tool_done），正常输出；② 停下：hook 在检查点停住，5 秒后继续，CC 接着读完输出。`-p` 模式没有转圈界面，**文字实际长什么样、闪烁明不明显没法由我看到**，交给你验收。
- **待用户验收**（请先重启诗音；新开的 CC 会话才会读到新的 hooks 配置）：
  - [ ] 平时：CC 每次调用工具前后，转圈处闪过“诗音在看着～（……）”，是否明显 / 是否让人觉得奇怪；诗音没开时会显示 1～3 秒，能否接受
  - [x] 停下后到检查点：转圈处一直显示这段文字，看得懂“这是暂停了，要右键诗音点继续”（✅ CC 自动验收 2026-10-21，终端版；焦点见该节限制）
  - [ ] 诗音头顶右侧出现小 ⏸：点了停下但还没到检查点时**不出现**；真正停住后出现，说别的台词、静音时都还在；位置不挡脸、不和气泡打架；拖动、跳起时跟着走
  - [ ] ⏸ 消失：点继续 / 在 CC 里说话 / 立即中断 都会马上消失（CC 自动验收 2026-10-21：点标签继续、菜单继续、在 CC 里说话三种都会马上消失；停住时立即中断本轮没测）
  - [x] 桌面端 Code 标签页同样显示这段文字（官方文档没写桌面端的表现）——结论：**桌面端不显示 hook 的 statusMessage**，记为已知限制，不修；桌面端靠暂停标签（用户验收 2026-10-21）

## 2026-10-20：停下简化、立即中断、working 不被超时顶掉、区分会话
- **停下**：删除 `HoldPanel`、`--snapshot --panel hold`、常驻提示和“结束这一轮”。点“停下”说一次“好，马上停～”；hook 第一次真的在检查点等着时说一次“已经停下啦～”（并行 hook、两段长轮询之间都不重复）；停下期间菜单第一项变成“继续”（没到检查点就点 = 取消）。在 CC 里说话照旧放行；30 分钟（`remote.pause_timeout`）没继续 → `continue: false` 结束这一轮，提醒一次“停太久了，这一轮先结束啦，在 CC 里说一声就能接着做”，该会话退出 working。
- **立即中断**（工作遥控第二项）：hook 在 prompt / PreToolUse 时沿父进程链找 CC 进程（必须等于 `CLAUDE_PID`，带创建时间防 PID 复用），连同 session_id、tool_use_id、hook 自己的 pid 发给诗音。点击后对每个工作中的会话：校验 CC 进程 → 结束“在执行的工具开始之后才创建”的 CC 直接子进程树（排除 hook 进程；MCP 服务器等早就有的子进程不动）→ 设一次性中断标记，下一个 PreToolUse / PostToolUse 返回 `continue: false` → 会话标成空闲，说“已经中断啦，在 CC 里说一声就能继续”。没有工作中的会话时菜单灰掉；找不到进程时说明原因并退回普通停下。新模块 `shion/winproc.py`（ctypes 进程表，hook 也用）、`shion/interrupt.py`。
- **working**：`PetState` 按会话记录（`WorkSession`）。prompt / PreToolUse 开始；PreToolUse 记下 tool_use_id，PostToolUse（新发 `tool_done`）/ PostToolUseFailure 配对清掉；有工具在执行时一直 working（单个最长 30 分钟），没有时距最近事件 5 分钟（调试 60 秒）退出。Stop 只结束那个会话，别的会话还在工作就 done 后回到 working。**注意**：prompt 现在也进入 working（以前要等第一个工具）。
- **协议**：`/event` 新增可选 `session` / `tool_id` / `proc`（`server.parse_meta` 校验，进程名只认 claude/node/bun）；带会话时回调多一个 meta 参数，旧的两参数回调照常。`/pause/wait` 可带 session。HTTP 仍然没有任何入口能停下、结束或中断。hooks 配置没变，**不用重装**；需要重启诗音。
- **台词**：三语新增 `menu_resume / menu_interrupt / work_held / interrupted / interrupt_no_process / interrupt_idle`，改 `stop_requested / work_stopped_timeout`，删 `menu_stop_pending / work_stopped / hold_*`；都不含“Claude”（有测试）。
- **测试**：`tests/test_stop_work.py` 重写（30 项），新增 `tests/test_interrupt.py`（54 项：会话 working、30 分钟/5 分钟/60 秒、多会话 done 后回 working、中断标记一次性且只对该会话、meta 校验与防伪造、真实进程链找 CC、hook 带会话、PostToolUseFailure 不消耗标记、假进程表选择/排除 hook/防 PID 复用、真实进程树被结束、控制器各路径）；改了 4 处旧的 2 分钟超时断言和 hook 事件断言。完整 `PYTHONUTF8=1 .venv\Scripts\python -m pytest -q`：**814 passed、1 skipped**。
- **真实 CC 联调**（2.1.289、haiku；假桌宠 = 真 PetController + 服务器，offscreen，隔离端口和数据目录；脚本在会话 scratchpad）：
  1. `claude -p` 停下 → 3 秒后继续：Read 前原地等，说了一次“已经停下啦～”，继续后读完 a/b/c、写出 SUMMARY.md，正常 Stop；
  2. `pause_timeout = 60`：停下后不继续，60 秒整 hook 返回 continue:false，CC 退出，没有 OUT.md，诗音提醒一次并回到空闲；
  3. **终端版交互式 CC**（新控制台窗口）：跑 120 秒命令时点立即中断，命令 0.4 秒内被结束，CC 还活着、回到输入框，下一个工具显示“hook stopped continuation: 用户通过诗音让这一轮工作停下……”；
  4. 调试模式（60 秒）跑 90 秒命令：16.6s→108.7s 一直 working，没被顶掉；
  5. 两个 `claude -p` 同时跑（15 秒 / 45 秒命令）：先结束的说“做完啦”并在 3 秒后回到 working，两个都结束才空闲；
  6. `claude -p` 立即中断：长命令被结束，下一个 PowerShell 调用被拦下、这一轮结束，`echo second-command-ran` 没执行；被结束的命令触发的 PostToolUseFailure 不再说“出错了”。
- **关于 Ctrl+C（需要你决定）**：按要求先实测了 `GenerateConsoleCtrlEvent`（AttachConsole 到 CC 的控制台、发一次 CTRL_C_EVENT）。结果：终端版 CC **在 1～4 秒内整个退出**，不是像按 Esc 那样中断当前生成（CC 把控制台信号当成退出，键盘上的 Ctrl+C 走的是原始输入）。所以终端版也改用“结束工具进程 + 下个检查点停止”，没有发 Ctrl+C，也没有改成模拟按键。代价：**正在写、后面没有工具调用的回答拦不住**（写完这一轮就结束）。如果想让终端版也能立刻掐断正在写的回答，可选：①往 CC 的控制台输入缓冲区写一个 Esc 按键事件（`WriteConsoleInput`，不切窗口、不抢焦点，但本质是模拟按键）；②接受现状。
- **踩坑**：①CC 不理会 PostToolUseFailure 返回的 `continue: false`，第一版在那里消耗了中断标记，结果 CC 接着跑了第二条命令；改成标记只给 PreToolUse / PostToolUse。②`.venv\Scripts\python.exe` 是启动器，hook 实际是它的子进程，所以 hook 链是 [真 python, 启动器]，排除 hook 要在 CC 直接子进程这一层做。③从 CC 的 Bash 工具里起的进程会继承“忽略 Ctrl+C”，测 Ctrl+C 时要先在启动器里 `SetConsoleCtrlHandler(NULL, FALSE)`，否则看起来像“发了没反应”。④haiku 偶尔不调工具或把测试指令当注入拒绝，重跑即可。⑤在 bash 里用 Python 打印 stream-json 中文会按 GBK 显示成乱码，文件本身是对的，别误判成 hook 编码问题。
- **限制**：同上；子代理里的工具进程也会被结束（它们也是 CC 的子进程），子代理内 hook 返回 continue:false 是否连带结束主代理仍未实测。
- **待用户验收**（请先重启诗音）：
  - [x] 右键 → 工作遥控：停下 / 立即中断（空闲时灰色）/ 做得好 / 有问题……；点停下说“好，马上停～”，到检查点说一次“已经停下啦～”，菜单第一项变“继续”，点继续 CC 接着干（✅ CC 自动验收 2026-10-21，终端版；焦点见该节限制）
  - [x] 停下后在 CC 里说话：自动继续（✅ CC 自动验收 2026-10-21，终端版；焦点见该节限制）（✅ 用户验收 2026-10-21，桌面端在 CC 里说继续）
  - [x] **桌面端 Code 标签页**：让它跑一个长命令（如 `python -c "import time; time.sleep(120)"`），点立即中断：命令马上结束、这一轮停下，CC 本身和 MCP 不受影响；诗音说“已经中断啦……”，不说“出错了”（✅ 用户验收 2026-10-21，桌面端）
  - [ ] 终端版同上再试一次；正在写长回答（没有工具调用）时点立即中断，确认现在的表现能否接受（见上面 Ctrl+C 一节）（CC 自动验收 2026-10-21：终端版立即中断：命令约 0.9 秒结束、续跑正常，但中断后诗音又说“任务完成”，见该节问题 A（2026-10-21 已修，见「问题 A、C 与授权面板及时收起」）；写长回答时中断本轮没测）
  - [x] 两个会话同时工作时的表情和“做完啦”；一个超过 5 分钟的命令期间一直是工作中（✅ CC 自动验收 2026-10-21，终端版；焦点见该节限制）
  - [ ] 切到英文、日文看新台词和菜单
  - [ ] （可选）`remote.pause_timeout` 改成 60，确认超时提醒只出现一次
- 上一轮“停下与暂停合并”里关于检查点面板的待验收项已被本轮取代。

## 2026-10-20：停下与暂停合并成一个流程
- **挠痒放慢**（先单独提交 `e15de5c`）：`TICKLE_FRAME_SECONDS` 0.11→0.2、`TICKLE_TWIST_PERIOD` 0.32→0.6、`TICKLE_TWIST_DEGREES` 3→2.5；spec 参数和截图示例 `--tickle --at 0/0.2/0.4` 已同步。
- **流程**：右键 → 工作遥控 → “停下”（菜单不再有暂停/继续）→ 诗音说“好，下一个空当就停下～”、挡手表情、菜单变灰“正在停下……” → 下一个检查点（PreToolUse / PostToolUse）hook 原地长轮询 → 诗音弹出检查点面板：“继续”放行无缝接着干；“结束这一轮”返回 `continue: false`（PreToolUse 另带 deny），常驻“已经停下了，在 CC 里说一声就能继续”。在 CC 里说话解除等待；30 分钟没选按结束处理（提示换成超时版）；这一轮没碰到检查点就结束了（Stop）则作废；诗音没开或连不上立即放行。
- **RemoteHub**：删除一次性的 `request_stop / cancel_stop / stop_requested`；新增 `end()`（代数计数 `_end_gen`：此刻在等的所有 hook 都拿到 stop，之后到的不受影响、不留残余）和 `is_holding`（正在等的 hook 数，两段长轮询之间 2 秒宽限）。`wait_gate` 没在停下时直接返回。
- **服务器**：`/pause/wait` 格式不变；`stop` 事件只在没有 hook 正在等时作废停下（别的会话结束不会放掉这里在等的 hook）。HTTP 仍然没有任何入口能开始停下或结束这一轮。
- **hook**：超时不再只 deny，和“结束这一轮”一样输出 `continue: false` + `stopReason`（`ui.hook_stop_timeout`）。hooks 事件和超时配置没变，不用重装。
- **界面**：`panel.py:HoldPanel`，宽 300、按钮高 44；规则同授权面板（`WindowDoesNotAcceptFocus`、`WA_ShowWithoutActivating`、按钮 NoFocus 且忽略按键、出现后 0.6 秒内不可点）。授权面板优先；弹出时收起气泡和对话窗口，开着时不能打开对话；跟随诗音；静音不影响。等着的 hook 消失（CC 里按 Esc）2 秒后面板收起。新增截图 `--snapshot OUT.png --panel hold --lang zh|en|ja`。
- **台词**：三语新增 `hold_title / hold_continue / hold_end / work_stopped_timeout / hook_stop_timeout`，`menu_stop` 改为“停下 / Stop / 止める”；删除 `menu_pause / menu_resume / paused_status / paused_timeout`。界面文字都不含“Claude”（有测试）。
- **测试**：`tests/test_stop_work.py` 重写为 33 项（hub 继续/结束/并行全部拿到 stop/之后不受影响/宽限，服务器防伪造与 Stop/prompt，hook 子进程继续放行、结束 Pre/Post、超时、服务没开，控制器菜单、等 hook 才弹面板、继续/结束/prompt/超时/Stop 作废/hook 消失、授权优先、键盘无效、跟随与对话、静音、三语）；删掉 `test_remote_control.py` 里旧的暂停界面用例；`test_hook.py` 超时用例改为 continue:false；截图测试加上 hold。完整 `PYTHONUTF8=1 .venv\Scripts\python -m pytest -q`：**763 passed、1 skipped**。
- **截图**：`--panel hold` 三语截图（`.venv/preview-run/stop-merge/`，已忽略），看过中文和英文：两个按钮等宽，“继续”橙色高亮，文字没有裁切。
- **真实 `claude -p`**（2.1.289，haiku，隔离端口和数据目录，假桌宠 = ShionServer + RemoteHub，在 prompt 之后 0.3 秒点停下、hook 等到后 3 秒再选，脚本在会话 scratchpad），任务“逐个读 a/b/c.txt 再写 SUMMARY.md”：
  1. **停下 → 继续**：第一次 Read 前 PreToolUse 等了 3 秒，继续后依次读 a/b/c、写出 SUMMARY.md（apple/banana/cherry），正常收到 Stop；
  2. **停下 → 结束这一轮**：第一次 Read 被拦住没执行，没发 working，界面收到 work_stopped，0.6 秒后 CC 退出；没有 SUMMARY.md，也没有 Stop 事件。
- **踩坑**：①两个旧的进程内 hook 测试（超时理由、否决理由）会读真实存档的语言——你的诗音现在是日语，所以按中文断言就失败；已在测试里设 `SHION_DATA_DIR` 隔离。②并行 hook 用一次性 stop 只能放掉一个，其余会继续等，所以改成按代数判断“结束”。③hook 两段长轮询之间有毫秒级空当，`is_holding` 要有宽限，否则面板会闪。
- **限制**：同上一轮——后面没有工具调用的长段文字拦不住；子代理内 hook 返回 continue:false 是否连带结束主代理未实测。
- **待用户验收**（请重启诗音后检查）：
  - [ ] 右键 → 工作遥控：只有“停下 / 做得好 / 有问题……”；点停下后变灰“正在停下……”，气泡“好，下一个空当就停下～”
  - [ ] CC 终端版里做多步任务，中途点停下：到下一个工具前/后诗音弹出面板，外观、位置、按钮大小顺手；0.6 秒内点不动；面板出现时你在 CC 里打字不会被抢焦点，回车/空格不会触发按钮
  - [ ] 点“继续”：CC 无缝接着干
  - [ ] 点“结束这一轮”：这一轮结束，CC 里显示的停止理由文字是否合适；诗音常驻提示，在 CC 里说话后消失
  - [ ] 面板开着时直接在 CC 里说话：面板收起，CC 处理你的新消息
  - [ ] 同上在桌面端 Code 标签页里再试一次
  - [ ] （可选）把 `remote.pause_timeout` 临时改成 60 秒，确认超时按结束处理、提示是超时版
- 上一轮“工作遥控改进”里的“暂停：工具做完后也能停住；点继续后接着写”一项已被本轮流程取代，按本轮清单验收即可。

## 2026-10-20：真实转身、无镜像侧身、捏脸与挠痒
- **素材先提交**：`bd99d3b`，仅 3 张 raw 源图、14 张生成图和 `tools/process_sheets.py`，共 18 个文件。只读检查 turn / tickle / cheek 分别切出 8 / 3 / 3 帧，输出全部可解码且为 448×512 RGBA；现有素材处理测试 **5 passed**。完整功能基线 **723 passed、1 skipped、2 条既有 Pillow 弃用警告**。后续实现未改动源图、生成帧或素材处理脚本。
- **动作和镜像**：删除“散步一会儿”“走到屏幕另一边”，走路素材保留但运行时不加载、不播放；删除 Walk 路径、镜像缓存和截图的 --walk / --mirror。动作菜单为跳一跳、转个身、朝向鼠标。转身顺播 turn_1～8，90ms/帧、720ms 后结束；鼠标在右/左分别用 turn_2 / turn_8 保持 2 秒。菜单与待机共用，按下立即中断，自动动作在工作、固定表情、睡眠或安静档出现时中断；结束恢复当前底层状态（通常 idle）。
- **区域测量与常量**：通过程序 --snapshot 观察 idle，并只读测得 idle alpha 边界约 (43, 24)～(401, 504)。按原 448×512 画布（减窗口留边）把上方 38% 设为摸头、38%～56% 为脸颊；肚子为高度 60%～78%、宽度 32%～68%，其余身体仍可拎起。区域在 pet_window.py，新增动作时长、距离、帧间隔、扭动幅度与频率在 behavior.py；距离是 Qt 逻辑像素，不随桌宠大小自动放大。
- **捏脸**：脸颊按住后横向超过 6px，画面右/左分别用 cheek_1 / cheek_2，可反向切换，窗口不跟着走；二维直线距离 >80px 转拎起，沿用拖动/晃晕/下落。未转拎起时松手 cheek_3 约 2 秒，说 cheek_release 生气台词；开始捏脸说 cheek_pull。脸颊单纯点击仍走普通戳，已移动的捏脸不再补戳；转拎起后不补鼓腮。
- **挠痒**：肚子点击按滚动 1.5 秒窗口计数（含端点），至少三次触发；第一、二次静默。按住半径 ≤40px 的小幅往返，水平反向位移 ≥8px 确认反转，1.5 秒内两次反转触发；>40px 转拎起。tickle_1～3 以 110ms/帧循环，脚底不移位、左右扭动 ±3°（周期 0.32s），持续有效移动（至少 2px）或点击续挠，每约 4 秒尝试笑声；单向移动、小抖动不触发，按住不动不续挠。最后一次有效输入后 1 秒结束，只说一次 tickle_end；转成其他手势直接取消，不补喘气。肚子点击/双击均消费，不进入普通戳或双击状态查询。
- **状态与三语**：cheek_pull / cheek_release / tickle / tickle_end 均原生提供中/英/日各三句傲娇台词。捏脸/挠痒不加好感度、不计摸头、不进入反馈队列，清空普通连戳计数并刷新被理会时间。动作帧覆盖底层表情，结束恢复固定/自动状态；固定设置本身不改变。捏脸开始和笑声为低优先级；松手生气和喘气为中优先级，可接替刚开始的互动台词；静音、重要工作提醒及原有仲裁仍有效，不排队补播。
- **加载/预览**：jump / drag 保留任意连续帧数；turn / tickle / cheek 必须整组 8 / 3 / 3 帧、可解码、同画布，缺号/坏图/多帧/少帧按组独立回退。转身/侧身缺图不执行，捏脸用 stop、挠痒用 happy 加扭动。--snapshot 新增互斥的 --turn / --face left|right / --cheek left|right|release / --tickle，仍保留跳跃和拖动预览。
- **验证**：设置进程级 `PYTHONUTF8=1`，完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/touch-full-final`：**759 passed、1 skipped、2 条既有 Pillow getdata 弃用警告**。跳过项为既有 offscreen 不支持的对话焦点用例；原生 `QT_QPA_PLATFORM=windows`、`QT_SCALE_FACTOR=1.5`，运行 `tests/test_touch_actions.py tests/test_frame_sequences.py tests/test_motion_update.py`：**119 passed**，日志为 touch-native150-final.log。`git diff --check` 通过。新增 tests/test_touch_actions.py，覆盖八帧转身/侧身到期/中断、待机共用、四尺寸划区与遮罩、80px/40px 边界、左右捏脸与松手、肚子点击窗口端点与过期、有效往返/抖动/单向拖动、按住不动与小幅续挠、持续笑声/停止喘气/双击消费、固定恢复/静音/重要提醒，以及新帧组容错与截图入口；移除已废弃走路/镜像断言，保留跳跃、拖动、FPS、hooks 与远控回归。
- **截图**：用原生 Qt --snapshot 生成 12 张新动作截图，目视检查其中 11 张代表图（另先看了 idle 截图以测量区域），含正侧/背面、左右捏脸、鼓腮、扭动和三语气泡，未见裁切、方块字或遮头；静态截图不能替代动态手感验收。日志与截图均在已忽略的 `.venv/preview-run/touch-*`，不提交。
- **踩坑与边界**：旧测试的普通身体点 (60,120) 落进新肚子区，移到身体下方，并单独验证肚子优先；悬停用例的移动点也需留在窗口/人物可交互区域。笑声重复计时不提前容差触发，避免浮点数略小于 4 秒时被原气泡冷却挡掉；已激活挠痒的 2px 有效移动不再被普通 6px 拖动阈值提前拦截。无新依赖、hooks/协议/存档格式变更，不推进好感度或内容包；按 AGENTS.md 跳过不可用的 reviewer 子代理，已自行核对动作覆盖、手势消费、气泡优先级和素材白名单。

**待用户验收**（请重启诗音后检查，自动测试和截图不能替代）：
- [ ] 动作菜单只剩跳一跳、转个身、朝向鼠标；八帧转一圈的 90ms 节奏和待机表现自然，鼠标右/左侧身方向正确，约 2 秒恢复；所有状态均无镜像。
- [ ] 四档尺寸及高分屏下，头顶/脸颊/肚子区域顺手；摸头仍有爱心，普通身体仍能戳和拎起。区域若需微调，修改常量即可。
- [ ] 左右捏脸与反向切换自然，超过 80px 转拎起；松手鼓腮约 2 秒，三语生气台词语气合适；转拎起后不再鼓腮。
- [ ] 肚子三击与按住来回蹭均能挠痒；持续挠就循环笑和左右扭，停手约 1 秒才喘气；单向长拖可拎起，肚子点击不再普通戳或弹状态。
- [ ] 真实桌面的动态轮廓点穿、贴边与高分屏下无裁切；固定表情在结束后恢复，静音不阻止动作，重要工作提醒仍优先。

## 2026-10-20：工作遥控改进（PostToolUse 检查点 + 停下）
- **官方字段确认**（code.claude.com/docs/en/hooks 通用输出字段）：`continue`（默认 true，false 时 hook 运行后 Claude 完全停止处理，优先于事件专属决定）、`stopReason`（continue 为 false 时显示给用户，留在对话里）；文档写明对 PreToolUse 和 PostToolUse 都有效。不模拟按键、不切窗口。
- **RemoteHub**：新增 `request_stop / cancel_stop / stop_requested` 和 `wait_gate(seconds) -> (paused, stop)`；停下在 `wait_gate` 里被原子取走，并行 hook 只有一个能拿到。停下不改暂停标记。
- **服务器**：`/pause/wait` 返回 `{"paused", "stop"}`；取走停下时服务线程发内部事件 `work_stopped`（`/event` 里伪造它返回 400）。`prompt` 和 `stop` 事件作废没用上的停下。HTTP 仍然无法开始暂停或请求停下（有测试）。
- **hook**：`pause_gate` 返回 `None` / `("stop", 理由)` / `("timeout", 理由)`。PostToolUse 变成检查点：先过检查点再取反馈；停下或暂停超时输出 `{"continue": false, "stopReason": …}`，停下时反馈留给下一次 UserPromptSubmit。PreToolUse 停下输出 `continue: false` + `permissionDecision: deny`（双保险，不发 working），暂停超时保持原来的 deny。`stopReason` 按存档语言取 `ui.hook_stop`（`deny_message` 抽成通用的 `ui_text`）。PostToolUse 总时限改为暂停上限 + 30 秒。
- **hooks 配置**：`PostToolUse` 超时 5 → 1900 秒；**项目级 `.claude/settings.local.json` 已重新安装**（备份 `settings.local.json.shion-backup-20261020-125451-616079` 在同目录，未提交）；用户级仍没动。**正在运行的诗音要重启一次**才会用上新服务器（旧服务器不返回 `stop`，新 hook 照常按暂停处理，不会出错）。
- **界面**：工作遥控子菜单第一项“停下工作”；请求后菜单显示灰色“正在停下……”，气泡“好，下一个空当就停下～”；生效后常驻气泡“已经停下了，在 CC 里说一声就能继续”，直到 CC 里说话或在诗音上点暂停/继续。三语（menu_stop / menu_stop_pending / stop_requested / work_stopped / hook_stop）均已补齐，不含“Claude”。
- **测试**：新增 `tests/test_stop_work.py` 21 项（hub 只取一次/并行只一个/暂停中被唤醒，服务器字段与防伪造，hook 子进程 Pre/Post 停下、Post 暂停等待后才送反馈、Post 暂停超时、英文理由、连不上放行，控制器菜单/气泡/静音）；改了旧测试的 `/pause/wait` 返回值、菜单顺序、`pause_gate` 返回值、安装超时。完整 `.venv\Scripts\python -m pytest -q` **723 passed、1 skipped**。
- **真实 `claude -p`（2.1.289，haiku，隔离端口和数据目录，假桌宠 = ShionServer + RemoteHub，脚本在会话 scratchpad）**，任务“逐个读 a/b/c.txt 再写 SUMMARY”：
  1. 读 c.txt 时点停下 → c.txt 的 PostToolUse 返回 continue:false，**没有写总结**，0.6 秒后 CC 退出；
  2. 读 a.txt 时点停下 → 只读了 a.txt，b/c 都没读；
  3. 第一次工具调用前点停下 → PreToolUse 拦住，Read 没执行（tool_result 是 “PreToolUse:Read hook error: 用户通过诗音让这一轮工作停下……”），没发 working；
  4. 读 c.txt 时点暂停、8 秒后继续 → c.txt 的 PostToolUse 原地等了 8 秒（14.5s→22.2s），继续后才写出 SUMMARY。
- **踩坑**：①`continue: false` 结束这一轮后**不触发 Stop hook**，所以不会误说“做完啦”，也不计完成任务；②`-p` 的 stream-json 里看不到 stopReason（交互界面应该会显示，待验收）；③haiku 偶尔不按指令只读一个文件就结束，重跑即可，与 hook 无关；④在 PowerShell 里跑 pytest 时 `test_install_hooks.py` 有个用例会因子进程输出按 GBK 解码失败，设 `PYTHONUTF8=1` 即通过（旧问题，与本次无关）。
- **限制**：停下/暂停都要等到下一个检查点；后面没有工具调用、正在写的长段文字拦不住。子代理内部 hook 返回 continue:false 时是否连带结束主代理，本轮没测。
- **待用户验收**：
  - [ ] 右键 → 工作遥控：第一项是“停下工作”，点后变灰色“正在停下……”，气泡“好，下一个空当就停下～”
  - [ ] 在 CC 终端版里让它做多步任务，中途点停下：这一轮在下一个工具前后结束，CC 里显示的停止理由文字是否合适；诗音常驻“已经停下了，在 CC 里说一声就能继续”，在 CC 里说话后消失
  - [ ] 同上，在桌面端 Code 标签页里再试一次
  - [ ] 暂停：工具做完后（写总结之前）也能停住；点继续后接着写
  - [ ] 切到英文、日文，看三句新台词和菜单文字
  - [ ] 先重启一次诗音（用上新服务器）

## 2026-10-20：八帧走路、四阶段跳跃、变速拖动与 FPS
- **素材先提交**：`4d72c4c`，只含三张 raw 分帧图、walk_1～8 / jump_1～4 / drag_1～4 和 `tools/process_sheets.py`，共 20 个文件。只读检查切出 8 / 4 / 4 帧，16 张生成图可解码且为 448×512 RGBA。提交前完整基线 **657 passed、1 skipped、2 条原有 Pillow 弃用警告**。后续功能没有改动或重新生成这些图片，脚本仅同步用途说明。
- **加载与行走**：三组按数字排序，从 1 到实际最大编号连续、全部可解码且与 idle 同画布才整组启用；任意连续帧数有效，各组独立回退。走路默认 60px/s，参考速度 60px/s、基准 110ms/帧，帧时长反比变化；仍每两帧一步、3px 起伏，每步落地附加约 3% 压扁回弹。左右缓存镜像、按下中断、边界、位置保存保留。没有额外尾帧清单，完整的较短连续组同样有效。
- **跳跃**：下蹲 0.15s → 上升 0.09s → 最高点 0.2s → 加速下落 0.11s，分别显示 jump_1～4；上升三次 ease-out、最高 45px、下落二次曲线。下蹲约 10% 压缩，0.55s 落地恢复底层表情并以最低 sy=0.84 压扁回弹 0.25s。按用户确认，未来任意帧数按四阶段归一化进度映射全部帧，保留阶段时长与曲线；无有效组时保留旧 18px / 0.5s 跳跃。菜单、待机、计划提醒共用；按下中断及掉帧后预定落地计时保留。
- **拖动**：drag 四帧默认 110ms/帧，二维速度与近期有效晃动共同控制，最快 60ms/帧；800px/s 或 2 秒内 3 次有效反转达到目标最快速率。0.08s 指数缓动、解析积分累计相位，变速不重启。松手保持实际速率继续下落，重新抓住仍连续；落地才恢复原状态或晃晕，固定表情和原晃晕规则保留。缺图整组回退静态 drag.png，倾斜仍有效。
- **FPS**：仅 SHION_DEBUG=1 创建独立计数窗口；每 0.5s 按真实经过时间统计桌宠 paintEvent，随诗音移动/改大小、限制在屏内，透明点穿且不抢焦点，隐藏/关闭时停止。计数器自身刷新、定时器与 render_frame 截图不计数；静止时保留重绘优化，因此读数可低于定时器频率。这是 Qt 绘制频率，不是显示器呈现频率。原生 Qt 约 2 秒实时冒烟读数启动后约 43～44 FPS，仅证明计数器工作，不代表所有设备或动作的帧率验收。
- **验证**：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/motion-update-full1`：**702 passed、1 skipped、2 条原有 Pillow getdata 弃用警告**。跳过项仍是 offscreen 不支持的既有对话焦点测试；本次原生 Windows Qt、150% 缩放 `tests/test_frame_sequences.py tests/test_motion_update.py`：**70 passed**。覆盖任意 1/3/6/12 帧、数字排序、缺号/坏图/画布不符、各组回退、八帧循环/速度/压扁、四阶段边界/45px 停顿/加速下落/掉帧/中断、拖动变速/竖向移动/松手/重新抓取/固定恢复、四档尺寸左右镜像与全帧倾斜遮罩、FPS 实际绘制计数/显示周期/生命周期；素材脚本覆盖当前源图、粘连拆分与帧数错误时禁止输出。
- **截图与踩坑**：新增互斥的 `--snapshot --drag --at`；截图入口明确关闭 FPS 窗口。通过 `python -m shion --snapshot` 生成 **34 张原生 Qt 截图**，目视检查其中 **15 张**代表性的左右行走、下蹲/最高点/下落/落地、拖动和三语气泡，无裁切、方块字或气泡遮头；完整动态观感另列待验收。60px/s 的跨屏时长触发原有浮点终点比较误差，已加入 1e-9 容差并在到期时精确采样终点，相关测试通过。测试日志、截图和 FPS 冒烟日志均在已忽略的 `.venv/preview-run/motion-update-*`，不提交。
- **提交边界**：没有新依赖、hooks/协议/存档变更或好感度/内容包实现。保留会话开始前已有的好感度与内容包文档改动，只提交本任务新增的文档差异。按 AGENTS.md 跳过不可用的 reviewer 子代理，已自行核对动作优先级、时间线、遮罩和 FPS 生命周期；不 push。

**待用户验收**（自动测试和静态截图不能替代）：
- [ ] 八帧走路的步态、60px/s 速度、110ms 节奏、每步轻微压扁，向左镜像自然且脚底不滑。
- [ ] 四阶段跳跃的下蹲力度、快速起跳、最高点停顿、下落加速及落地回弹；菜单、待机、计划提醒的跳跃均自然。
- [ ] 慢拖/快拖/大幅晃动时四帧变速自然，松手继续播放、重新抓住不跳帧；落地恢复固定/自动表情，晃晕仍只在落地后发生。
- [ ] 四档尺寸与高分屏下动作不裁切，动态人物轮廓外可点穿；FPS 数字不挡鼠标、不抢焦点，贴边、跳跃和改大小时位置合适。
- [ ] SHION_DEBUG=1 下观察实际动作 FPS，确认正常设备上的流畅度；普通启动不显示数字，静止时低 FPS 不误认为动画定时器停转。

## v0.4：诗音的对话菜单（2026-10-20）
- **内容**：新增 `assets/menu/snacks.json` / `talks.json`，各有 `schema_version: 1`；四种零食（饼干、布丁、奶茶、草莓蛋糕）和四个预设（摸摸头、晚安、今天辛苦了、陪我一下）的名称和每项三条回应全部为中/英/日。吃饱回应也在零食 JSON。新增 `menu_content.py` 只解析数据：翻译缺失回退中文、不连续重复、坏条目/重复 id 跳过，坏文件/未知版本禁用对应列表并显示提示，动作和表情只认白名单。界面通用文字走原语言文件；可见文字不含“Claude”。未接入模型、未增加依赖、未做 v0.5 安装管理。
- **窗口**：右键“对话”，终端配色和等宽字体、三语字体回退；首页 1=零食、2～5=预设，零食页 1～4=选择、0=返回，鼠标同样可操作；执行选项后收起，Esc 关闭整个窗口。打开时 `WA_ShowWithoutActivating`，显式点击窗口才接收按键；失焦停收，重新点击后才恢复。没有全局快捷键或键盘钩子；只给自己的子控件装事件过滤器。跟随诗音、屏幕内定位、打开时暂停待机动作；授权出现时关闭对话，授权待处理期间不能打开对话。
- **喂食与存档 v4**：用 happy 和嘴边程序碎屑代替尚未制作的 eat 图；2 秒完成时统一结算 +2 和当天次数，四种零食共享五次额度，第六次起拒绝进食、说“撑、撑不下了……”（对应语言），不加分。进食中禁止重复开始，未完成退出不计数/不加分；按完成时的本地日期统计，独立 `snacks: {date, count}` 存档，重启保留、跨日归零。v1/v2 反馈迁移保留，v3 旧数据不丢失。碎屑有数量上限、实际时间位移/淡出、掉帧不补发，缩放随开始进食时的桌宠尺寸，透明点穿且不抢焦点。拖动/固定/手动表情仍优先于进食的 happy。
- **预设状态**：摸摸头=happy、今天辛苦了=proud、陪我一下=happy；都不加好感度/摸头统计，不进入工作反馈队列。“晚安”清理短暂反应并进入睡眠，直到下一次交互或工作事件唤醒；固定/手动表情、进食、暂停和既有 working 状态保留优先级。睡眠标记不存档。静音和既有气泡仲裁照常，回应属中优先级，重要工作消息可打断；回应被阻挡时不抽台词、不补播，行为照常。
- **验证**：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/v04/final2`：**657 passed，1 skipped，2 条原有 Pillow getdata 弃用警告**；跳过项仅为 offscreen 不支持的非激活焦点测试，该项在原生 Windows 已通过。`git diff --check` 和暂存差异检查通过，提交仅包含明确核对的 17 个功能/内容/测试/文档文件，Author/Committer 邮箱均为指定 noreply。原生 Windows Qt、150% 缩放 `tests/test_dialogue.py` **47 passed**。覆盖三语内容、容错与白名单、随机不重复、完成边界/一次结算/五次共享额度/跨日/重启/中途退出、迁移、睡眠与唤醒/优先级、静音和高优先级、鼠标/数字键/返回/Esc、失焦/原编辑框继续输入、忙碌禁用、授权面板共存、屏幕内定位、碎屑轨迹与数量上限。更新旧菜单和存档版本断言；扩展 `--snapshot --panel dialogue|snacks|eating`，生成并目视检查六张三语菜单截图和一张 happy + 碎屑截图，无裁切/方块字。日志和截图在已忽略的 `.venv/preview-run/v04/`，不提交。
- **踩坑**：pytest 的多层 basetemp 需要预先创建父目录（首次检查因缺目录报错，已修正运行路径）；Qt 重建可见窗口布局时新增控件需明确 show，否则零食页会缩成空条；原生 Windows 首次手动激活窗口有 deactivate→activate 短暂序列，改为下一轮事件确认最终失焦，同时按键始终检查实际激活状态。原生 150% 回归已覆盖此问题，不能仅靠 offscreen 测试。offscreen 插件会自行激活新窗口、不支持 WA_ShowWithoutActivating，因此“保留其他编辑框焦点”仅在 offscreen 跳过，原生 Windows 的同一测试已通过。
- **审查与边界**：按 AGENTS.md 跳过 Codex 不可用的 reviewer 子代理；已自行核对数据加载、键盘焦点、状态优先级和授权面板只响应鼠标的规则。没有改素材或素材脚本、hooks、HTTP 协议、用户 hooks 配置，旧待验收清单继续保留。按用户本轮授权先记录待验收再提交；不 push。下一步 v0.5 内容包。

**待用户验收**（自动化和静态截图不能代替亲眼检查）：
- [ ] 在其他应用输入时打开“对话”，原焦点保留；点击对话窗口后数字键、0 返回、Esc 关闭正常，切回其他应用后数字键不会触发诗音，再次点击才能恢复。
- [ ] 中/英/日菜单和台词的语气、等宽字体与换行；屏幕边缘、四档桌宠尺寸和高分屏操作。
- [ ] 四种零食的 happy 与嘴边碎屑动态、密度/位置/淡出和点穿；每天前五次各 +2，第六次拒绝；重启后额度仍保留。
- [ ] 四个预设的回应和表情；“晚安”空闲时立即睡觉，下一次交互唤醒；固定表情、暂停/工作期间的优先级符合预期。
- [ ] 工作提醒能正常打断回应、静音只抑制说话；普通授权出现时对话关闭，授权面板继续不抢焦点且只响应鼠标。

## v0.3 修正：计划确认交回 CC、完成时只提醒（2026-10-20）
- **计划确认**：PermissionRequest 的 `tool_name == ExitPlanMode` 在描述/截断内容之前直接旁路，只向 `/event` 发 `{"type":"plan_ready"}`；不登记请求、不轮询、不撤回、不输出决定，交回 CC。无计划、短计划、超长计划同样处理；诗音没开或发送失败仍静默退出。普通工具授权的同意/否决规则保留。
- **桌宠反应**：`plan_ready` 结束 working、刷新被理会时间，以高优先级提示并复用原地跳跃一次；不计完成任务、不进入 done、不启动完成后的定时催促。静音只抑制气泡，仍跳；安静档/固定表情不阻止事件小跳；拖动/下落沿用现有跳跃保护。计划不进入最近活动，旧调用方传来的 detail 也不记录到控制器日志。
- **完成提醒**：Stop hook 只发 `{"type":"stop"}`，删除回复第一句提取函数，不读取回复字段、不打开对话文件；控制器和最近活动也忽略旧 hook 发来的 stop detail。气泡只抽取 `claude_done` 提醒，done 3 秒、任务统计、催促、静音及隐私设置保留；最近活动只写“做完了”。
- **三语**：计划提醒为“计划写好啦，去看看吧～” / “The plan's ready! Take a look~” / “計画ができたよ、見てみてね～”；完成提醒为“做完啦！去看看结果吧～”等三语台词。同步替换原有问候、工作/等待/催促、菜单反馈、状态、端口提示和关于页的品牌字样，所有内置 `lines` / `ui` 的显示值都不含“Claude”；内部兼容键名保留。
- **其他**：`.gitignore` 加入 `*.shion-backup-*`；现有项目级 settings 和备份文件均不提交。无新依赖，不改精灵素材，不安装/卸载 hooks；当前配置直接调用本仓库脚本，桌宠重启后加载新事件处理。spec 已同步替换旧的计划接管和回复转述规则。下一开发步骤仍是 v0.4，旧待验收项继续保留。
- **验证**：默认环境完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/plan-stop-20261020/final-temp`，**611 passed，2 条原有 Pillow getdata 弃用警告**。已用 `python -m shion --snapshot` 生成并目视检查计划/完成提醒各三语，共 **6 张原生 Windows Qt 截图**，无裁切、方块字；英文完成提醒正常换行。截图和测试日志保留在已忽略的 `.venv/preview-run/plan-stop-20261020/`，未查看原始 PNG、未提交截图。回归覆盖 hook 子进程→真实本地 HTTP→GUI 事件处理、计划无登记/无决定/不发送正文/服务器不可用、已有授权队列保留、Stop 无内容及旧 hook 兼容、三语、高优先级、静音、跳跃阶段、安静档/固定表情、计数/状态/活动记录。`git diff --check` 通过，备份忽略生效且没有已跟踪备份。
- **测试踩坑**：移除两条已随功能淘汰的回复截句函数测试；首次全量给测试进程设置 `PYTHONIOENCODING=utf-8` 导致旧安装器测试按 Windows 默认 GBK 解码子进程失败，最终使用默认环境重跑。另一个旧暂停常驻测试会被随机闲聊按设计盖掉再恢复，已仅将该测试设为安静档，隔离随机待机行为，没有修改暂停功能。
- **待用户验收**（自动测试/静态截图不能替代真实 CC 与动态观感）：
  - [x] 重启诗音后，在 **CC 终端版及桌面端 Code 标签页**生成计划：诗音只跳一下并提示去看计划、不弹计划授权面板；由 CC 自己显示确认并处理你的选择。（CC 自动验收 2026-10-21：终端版通过：只提示“计划写好啦，去看看吧～”，不弹授权面板，CC 自己显示计划确认；✅ 用户验收 2026-10-21：桌面端计划提醒通过）
  - [ ] 中/英/日分别检查计划提醒和完成提醒的文字、气泡排版、打字效果与高优先级打断；计划小跳和落地的观感。静音时只跳不说。（CC 自动验收 2026-10-21：中文计划/完成提醒文字通过；三语、跳跃观感、静音本轮没测）
  - [x] 正常完成后只提示去看结果，气泡和双击最近活动不出现回复第一句；done 表情、任务计数和催促照常。已有普通工具授权面板的同意/否决仍可用。（CC 自动验收 2026-10-21：终端版气泡只说“任务完成～快去看看吧！/做完啦！去看看结果吧～”，不带回复内容；双击最近活动本轮没看；✅ 用户验收 2026-10-21：桌面端完成提醒通过）
  - [ ] 菜单、状态、关于页及日常气泡均不出现“Claude”。

## v0.3 审查（reviewer 子代理，2026-10-20）
- 结论：**没找到让 allow 来自诗音界面点击之外的路径**（server 各路由、hook 的 `permission_decision`、`PermissionQueue` 的锁与 id、面板切换瞬间的点击归属、键盘/焦点都核对过）。暂停流程、线程模型、存档迁移、与 spec 的一致性没有问题。
- 已修：① **反馈“取走”和“送达”不原子**：hook 取反馈超时 0.5s 小于 bridge 等 GUI 线程的 2s，GUI 卡顿时 hook 先断开、队列却已被清空而丢反馈。改为 hook 超时 3s（`FEEDBACK_TIMEOUT`）、bridge `TAKE_TIMEOUT` 1.5s，PostToolUse/UserPromptSubmit 总时限 6s；bridge 超时即取消，不会取走队列。② **超长命令被截断仍可点同意**：内容超过 12000 字时 hook 不登记请求、不给决定，交回 CC 自己的授权框（有测试）。③ 新增测试：settings 超时必须大于 hook 最长等待（PreToolUse ≥1895、PermissionRequest ≥180、FEEDBACK_TIMEOUT > TAKE_TIMEOUT）。④ spec 补了威胁模型一句（本机已被攻破的恶意进程不在范围）。
- 没改，记在这里：Edit/Write 只显示文件路径不显示改动内容（符合 spec）；hook 被 CC 杀掉后的“僵尸请求”面板最多停留 25 秒（`PENDING_IDLE`），这期间点按钮无害但没反应；“已经转告啦”在响应写出前就说了（超时修好后窗口极小）；没有专门测“按下旧请求、松开前已换成新请求”的 Qt 事件序列（逻辑上由 `_armed_at` 重置和点击时取 `_rid` 保证）。

## v0.3 第二部分：同意/否决（2026-10-20）
- **硬约束与落实**：allow 只能来自用户在诗音界面上的点击。① `remote.py:PermissionQueue.decide()` 是唯一能写入决定的入口，源码级测试断言整个包里只有 `controller.py` 的按钮回调（`_on_permission_decided`）会调用它、`server.py` 的源码里没有 `decide`；② HTTP 只有 `/permission/open|wait|withdraw`，没有任何字段会被读成决定（测试往所有接口、所有事件类型、各种形状的“同意”字段里灌，请求始终 pending）；③ hook 只有收到 `{"id": 同一个 id, "status": "allow"}`（恰好等于）才输出 allow，大小写不同、`true`、列表、id 对不上、缺字段、超时、连不上、撤回、`gone` 全部不给决定（交回 CC 自己的授权框）；④ 诗音没开：hook 连 `/permission/open` 都失败就立刻退出，无输出。
- **新增/改动**：`remote.py:PermissionQueue`（`secrets.token_hex(16)` 的 id、最多 20 个排队、内容 ≤20000 字、allow/deny 只能取一次、25 秒没人轮询的请求过期、没人取的决定 60 秒后清掉）；`server.py` 三个路由（授权请求体上限 64 KB，其他接口仍 4 KB；`request_queue_size` 调到 64——测试里并发连接偶发 `ConnectionResetError`）；`hooks/shion_hook.py`：`permission_decision` / `describe_permission` / `deny_message`，`ensure_ascii=False` 发请求（中文计划不会膨胀 6 倍）；`hooks_config.py`：新增 PermissionRequest（matcher `*`，超时 180 秒）；`panel.py:PermissionPanel`；`controller.py` 的 `_sync_permission`（tick 里每 100ms 同步，一次显示一条、显示“还有 N 个”）。内容显示规则见 spec「同意/否决的实现要点」。
- **面板**：不抢焦点（`WindowDoesNotAcceptFocus` + `WA_ShowWithoutActivating`），键盘一律不响应（`MouseOnlyButton` 忽略所有按键——测试里直接给按钮发空格/回车也不会同意），每条请求出现 0.6 秒内按钮灰着（防误点，换成下一条同样重新计时），内容区只读、约 6 行，长内容出现“展开/收起”，静音时面板照常弹出（只是不说那句话）。`--snapshot --panel permission|input` 新增，三语/长文本/展开都看过截图，无裁切、无方块字。
- **验证**：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/v03-b/t8`，**581 passed**（521 + `tests/test_permission.py` 60 项）。**真实 `claude -p`（2.1.289，haiku，隔离端口，假桌宠服务器按模式自动“点击”）**：PowerShell 写文件命令 → 请求带着完整命令和描述出现在队列里；点“同意”后文件真的被创建、模型回 RAN；点“否决”后文件没被创建、模型回 DENIED；无人决定（超时 10 秒）后文件没被创建，**没有被默认同意**（`-p` 模式下 CC 没人可问，自己拒绝）。踩坑：①`ExitPlanMode` 在 `-p` 下不会走授权，没法自动实测，留给你；②测试里面板对象被别的线程的垃圾回收销毁会让 Qt 直接 abort（偶发整个 pytest 崩溃），所以 `PetController.dispose()` 在 GUI 线程立刻销毁面板，测试的 `Env.close()` 调用它。③git bash 里用 `
` 写进 Python heredoc 会变成真换行，改文件要用编辑工具。
- **hooks 已重新安装到项目级** `.claude/settings.local.json`（含 PostToolUse、PermissionRequest；备份 `settings.local.json.shion-backup-*` 留在同目录，未提交）；用户级 `~/.claude/settings.json` 仍没动。
- **待用户验收**（我看不到真实桌面和 CC 界面）：
  - [x] **CC 终端版和桌面端 Code 标签页**：授权请求能否被诗音面板接管；点“同意”“否决”后 CC 的反应；CC 自己的授权框会同时显示（**预期已改**：两边哪边先答都可以，CC 里答了以后诗音面板会自动收起）；诗音面板在你同时操作 CC 时不抢键盘焦点。（CC 自动验收 2026-10-21：终端版同意/否决都由诗音接管并生效，CC 自己的框同时显示，即问题 B，不修、改预期；✅ 用户验收 2026-10-21：桌面端同意、否决、在 CC 里自己答都通过）
  - **ExitPlanMode 旧验收项已被替代**：不再验收诗音接管/显示计划全文；按上方“计划确认交回 CC”清单验收。此项不表示旧实现曾通过用户验收。
  - [ ] 面板外观（终端配色、两个大按钮、“还有 N 个”）、0.6 秒防误点的手感、多个请求（子代理并行）排队、你在 CC 里自己答了之后面板**马上收起**（2026-10-21 新改，原来要等约 25 秒，待验收）。
  - [ ] 120 秒超时后 CC 是否照常弹出自己的授权框（可把存档 `remote.permission_timeout` 临时改成 10 测试）。
  - [ ] 面板与气泡同在诗音头顶时的叠放观感（面板在上层，可能盖住气泡；如果不好看再调）。
- 已知取舍/风险：本机若有别的程序在诗音没开时占用 47613 端口并冒充服务器，理论上能回 allow；这需要本机已被攻破，本版不处理。PreToolUse/PostToolUse/PermissionRequest 每次多一个 python 进程（约 0.1 秒）。授权面板里的内容不受“只显示状态，不显示内容”隐私开关影响。

## v0.3 第一部分：暂停/继续 + 反馈队列（2026-10-20）
- **新增** `shion/remote.py`（纯 Python）：`RemoteHub`，用 `Condition` 保护暂停标志，`wait_while_paused(秒)` 供服务线程长轮询（单次上限 30 秒）。服务线程只读/只等；开始暂停只能由 GUI 线程调用 `hub.pause()`。
- **服务端**：`POST /feedback/take`（取代 `/praise/take`，返回 `{"text"}`）、`POST /pause/wait`（只读；坏的 wait 值当 0）。收到 `prompt` 事件时服务线程**直接** `hub.resume()`（紧接着的工具调用不会被误挡），再转给 GUI。HTTP 里没有任何能让暂停开始的接口（有测试）。`bridge.py` 的请求对象泛化为 `_TakeRequest`，超时后不会把队列取走。
- **hook**：PreToolUse 先问 `/pause/wait`，暂停中 25 秒一段循环等；诗音没开、请求失败、返回内容不是 `{"paused": true}` 一律放行；等满上限输出 `permissionDecision: deny`（理由“用户暂停了工作，请停下并等待用户指示”）并发 `pause_timeout`，被拒绝的那次不发 `working`。新订阅 PostToolUse：取反馈非空就输出 `additionalContext`。UserPromptSubmit 改为取 `/feedback/take`。总时限：PreToolUse = 暂停上限 + 30 秒，其他事件不变。暂停上限读存档 `remote.pause_timeout`（夹在 60～1880）。`hooks_config.py`：新增 PostToolUse，PreToolUse 超时 1900 秒。**项目级 `.claude/settings.local.json` 里的 hooks 还没重新安装**，要实测前先 `uninstall` 再 `install`（第二部分结束时一起做）。
- **存档 v3**：`pending_praise` 换成 `feedback_queue`（最多 5 条，满了丢最早的；`bad` 的文字单行、最多 200 字）和 `remote`（暂停/授权秒数）。v1 丢弃旧计数，v2 的 `pending_praise` 迁移成等量“做得好”。`PetState.paused`（不存档）：暂停时显示 `stop`，优先级低于拖动/固定/手动/临时表情，高于 working。
- **界面**：右键新增“工作遥控”子菜单（暂停工作⇄继续工作 / 做得好 / 有问题……），原顶层“做得好”并入。暂停时气泡“暂停中”一直挂着（`sticky`：打完字不淡出；`SpeechGate` 按低优先级占位，别的台词可以盖掉它，说完后 tick 里自动恢复；静音时不显示）；超时后文字换成“已经停下了，在 CC 里说一声就能继续”，暂停标记保留，点“继续”只解除标记。“有问题……”弹出新的 `shion/panel.py:InputPanel`（终端配色、一行输入框、Enter 发送/Esc 取消、可留空，这个面板会拿键盘焦点）。送达反馈后说“已经转告啦”。新增 UI 文字不含 “Claude”，三语齐全。
- **验证**：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/v03-a/t12`，**521 passed**（485 基线；改写了旧 praise 测试，新增 `tests/test_remote_control.py` 30 项和 hook 暂停/反馈子进程测试）。**真实 `claude -p`（2.1.289，haiku）联调**（假桌宠服务器 = `ShionServer`+`RemoteHub`，暂停 8 秒）：PreToolUse 被挡住 8 秒、释放后正常开工；PostToolUse 的 `additionalContext` 被模型原样看到；UserPromptSubmit 注入反馈正常。踩坑：`-p` 一开始就会触发 `prompt` 事件，按规则这会解除暂停，所以联调时要在 prompt 之后再暂停。
- **待用户验收**（我看不到真实桌面/CC 界面）：
  - [ ] 暂停时 CC 终端版和桌面端 Code 标签页里看到什么（工具卡住的样子）；点“继续”无缝继续；在 CC 里说话自动解除；暂停挡手造型和“暂停中”气泡观感。（CC 自动验收 2026-10-21：旧暂停流程已被停下流程取代；终端版停下后点继续、在 CC 里说话均无缝继续）
  - [ ] 暂停超时的提示（可临时把存档 `remote.pause_timeout` 改成 60 测试）。
  - [x] “做得好”/“有问题……”：工作中（PostToolUse）和空闲时（下一条消息）各自送达，Claude 的回应是否自然，“已经转告啦”。（✅ CC 自动验收 2026-10-21，终端版；焦点见该节限制）回应原文见该节（✅ 用户验收 2026-10-21，桌面端做得好/有问题送达）
  - [ ] “有问题……”输入面板的外观、焦点和三语文字。
- 已知取舍：并行子代理的多个 PreToolUse 各自计时，超时时每个都 deny；暂停后诗音被关闭，等待中的 hook 会在下一次长轮询失败时放行（最多 25 秒）。

## 2026-10-20：新版走路分帧与爱心密度
- 先按用户指定范围独立提交 **`4b26f44`**：`assets/sprites/raw/walk_sheet.png`、`tools/process_sheets.py` 和重新生成的 `walk_1~4.png`、`jump_1~2.png`，共 8 个文件。本轮未再修改原图、生成图或处理脚本；程序读取验证连通区域能切出走路 4 帧/跳跃 2 帧，6 张生成图均可解码且为 448×512 RGBA，未直接打开原始 PNG。提交前完整基线 **477 passed**。
- `effects.py`：爱心间隔 **0.6 → 0.2 秒**，同时最多 **3 → 6 颗**，基准大小 **18 → 20px**，上飘 **45 → 55px**；原有 1 秒寿命、0.8～1.2 随机大小、分布范围、缓动、鼠标穿透及精确计时保留。
- 沿用相邻摸头间隔 ≤1 秒的连续过程判定。每个新过程的首次有效摸头反馈立即冒 **2 颗**，不受冒出间隔阻挡，仍服从 6 颗总数上限；此后按 0.2 秒间隔冒一颗，超额丢弃、不排队。连续摸头超过 6 秒的第二次台词尝试不重复双爱心；静音或台词被高优先级提示拦截时爱心照常。
- `PatSession` 仅增加当前一次是否开启新过程的标记，由控制器传给粒子层；不改变摸头台词、好感度、统计和仅菜单产生待表扬的规则。规格同步更新，无新依赖；下一开发步骤仍为 **v0.3 Claude Code 遥控**。
- 相关测试 **115 passed**；完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/hearts-20261020/full-temp`，**485 passed**（基线 477＋新增 8 项），仅 2 条原有 Pillow `getdata` 弃用警告。覆盖开始双爱心、0.2 秒/1 秒边界、6 颗上限/剩余容量、过期与不补播、55px 上飘、第二句不重复双爱心、重要台词/静音不抑制爱心及统计保留。日志在已忽略的 `.venv/preview-run/hearts-20261020/`，不提交；`docs/preview.png` 继续忽略。

**本次待用户验收**：
- [ ] 新版四帧行走、左右镜像及跳跃的观感与对齐。
- [ ] 新摸头过程首次立即冒 2 颗；持续摸头时爱心的密度、20px 大小、55px 上飘距离是否合适。
- [ ] 连续过程与停顿超过 1 秒后重新摸头的反馈，真实桌面上爱心仍不挡鼠标，四档尺寸/高分屏下流畅。
- 自动测试不能替代以上真机视觉和交互验收；用户已授权完成记录后提交，本次不 push。

## 2026-10-19：行走/跳跃帧动画与气泡仲裁
- 按用户要求先独立提交素材准备：`1967da9`，仅包含 `raw/walk_sheet.png`、`raw/jump_sheet.png`、两个处理脚本和生成的 `walk_1~4.png`、`jump_1~2.png`，共 10 个文件；基线 **403 passed**。本轮功能实现没有再改这些素材和脚本。
- 精灵加载增加可选动作帧组：必须整组齐全、可解码且与 idle 同画布才启用；缺图、坏图、画布不匹配时按组回退。两种行走均循环 walk 四帧，原图向右、向左用缓存镜像；80px/s 时每帧 140ms，帧时长随速度反比变化，每两帧一步，附加同步 3px 上下起伏。缺图仍用原状态图及旧的 10px / 0.45 秒起伏。
- 菜单“跳一跳”和待机小跳共用：jump_1 下蹲 0.15 秒 → jump_2 腾空 0.4 秒、程序升高最高 40px → 恢复当前底层表情并落地压扁/回弹 0.25 秒。缺图整组回退 18px / 0.5 秒旧动画。动作帧在显示层覆盖，控制器同步不会重启序列；位移和帧选择都按实际经过时间采样，落地回弹从预定落地时刻算，掉帧不延长动作。保留按下中断、脚底锚点、绘制/遮罩同步与位置保存。
- 新增纯 Python `speech.py`：高优先级（Claude 完成及结果转述、出错、催促、等待确认，预留 permission_request）随时打断，包括另一条高优先级；中优先级（问候/启动/唤醒/回归、菜单反馈、双击状态）只能打断低；低优先级（摸头、戳、拖、自言自语、工作过程提示）不能打断中/高，低之间须当前气泡出现满 2.5 秒、同类已说出台词间隔满 4 秒。工作过程原有 3 秒去重仍保留，并服从低优先级限制。拦截时直接丢弃，不补播、不抽取随机台词；自然结束、静音或切换语言收起后不会残留优先级阻挡。双击状态保留静音豁免，但服从优先级。
- 摸头改为相邻间隔 ≤1 秒的连续过程：开始尝试一句，持续超过 6 秒再尝试一句，每过程最多两句；两次尝试均服从仲裁。爱心、happy、好感度与统计逐次正常处理。戳的普通/挡手/晕共用戳冷却；拖动和落地晃晕共用拖冷却；Claude 出错独立为高优先级。时间集中在 `speech.py`、`behavior.py` 及原有 Animator 常量中，气泡打字/停留/淡出与仲裁共用时间常量。
- 英文菜单精确改为 **Flustered / Teary / Auto expressions / Walk to the other side**。规格同步更新；没有推进 v0.3 授权/遥控功能，没有新依赖。
- 验证：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/frames-full-final`，**477 passed**（403 基线＋74 项；更新了与新冷却规则冲突的旧断言）。覆盖优先级全组合、2.5/4/1/6 秒边界、同类归并、拒绝不补播、不中断爱心/统计、帧循环/步速、跳跃阶段/落地、缺失/坏图/画布不符回退、丢帧、按下中断、四档尺寸的镜像与遮罩。150% Qt 缩放专项 **32 passed**。2 条原有 Pillow getdata 弃用警告，无新增警告。
- 视觉：只通过 `.venv\Scripts\python -m shion --snapshot` 生成并目视检查 **19 张原生 Windows Qt 截图**（左右各四帧、跳跃 8 个时刻、中/英/日腾空气泡各一张），未见裁切、方块字或气泡遮头。新增 `--walk --at ...`，`--jump --at 0.35` 为最高点。截图和日志在已忽略的 `.venv/preview-run/frames-visual/`、`frames-full-final.log`、`frames-dpi-1.log`，不提交。
- 踩坑：40px 跳跃增加顶部留边后，旧截图合成会把气泡放低，已调整气泡利用顶部空白，并按腾空位移留出头顶空间；补截图回归验证气泡不覆盖最高点人物。原始 PNG 未直接打开，只查看 --snapshot 的输出。

**本次待用户验收**：
- [ ] 散步和走到另一边的四帧步频、3px 起伏、左右朝向、结束/按下中断后的恢复与位置保存。
- [ ] 菜单跳跃与待机小跳的下蹲、40px 腾空、落地回弹是否自然，固定/手动表情恢复是否符合预期。
- [ ] 连续摸头开始与超过 6 秒的两句反馈，戳/拖台词冷却是否合适；爱心和表情反馈照常。
- [ ] Claude 完成、出错、等待确认、催促能及时打断；问候/菜单/状态查询及低优先级台词不会盖掉重要提示。
- [ ] 真实桌面中动作帧及跳跃的点穿、四档尺寸/高分屏流畅度，以及四个英文菜单新名称。

## 2026-10-19：交互打磨（7 条反馈＋普通启动台词，历史）
- 用户已确认整体方案及最终概率。连续点击间隔 ≤1.5 秒：1～2 下普通；3～4 下挡手 **60%** / 晕 **20%** / 普通 20%；第 5 下起挡手 **55%** / 晕 **40%** / 普通 5%。单次抽取互斥，挡手/晕后清零，删除固定 5/10 下规则。
- 爱心：统一粒子层限流（≥0.6 秒一颗、同时 ≤3 颗、不排队），18px / 上飘 45px。摸头仅好感/统计/happy/爱心；菜单“做得好”才增加待表扬。hook 按存档语言输出一句 `[诗音] 用户觉得你刚才做得很好。` 的中/英/日版本，无次数、多次合并。
- 存档 `schema_version=2`：旧待表扬无法区分来源，升级仅清空一次旧 `pending_praise`；好感、统计、位置和其他选项保留，新菜单表扬重启保留。
- 拖动晃动：反向摆幅 >40px 才确认转折，过滤抖动；2 秒内至少 3 次反转即记住晃晕，落地才切 dizzy 2.5 秒＋台词。每轮拖动重新计数，下落仍是 drag。
- 表情菜单：九种表情，临时 5 秒；固定选项存档、重启恢复，台词/事件/统计照常，拖动/下落优先 drag、落地恢复固定表情；双击显示“表情已固定”。恢复自动清掉手动表情，不重播固定期间的旧反应。
- 活跃度：安静 / 普通（8～20 秒）/ 活泼（4～10 秒），存档；镜像转身、朝鼠标、原地跳、happy/idle 2 秒、`idle_talk`（10% 抽取、至少间隔 60 秒）。实际 Claude 工作、固定、睡眠、拖动/下落、按住鼠标、打开菜单时暂停；不累积补播、不刷新睡眠/被理会时间。适用的呼吸/眨眼保留；独立 blink 图只用于 idle，不覆盖其他姿势。
- 动作菜单：沿当前屏幕任务栏上沿随机散步 10 秒、走到该屏幕另一侧、跳、转身。行走 80px/s、蹦跳 10px / 0.45 秒，朝向跟随方向；按下鼠标立即中断，再照常戳/摸/拖；结束/中断保存新位置。原地跳 18px / 0.5 秒和镜像转身不改变最终位置。
- 普通非首次启动改为 `startup`，取消随机重复 intro；hook 仅对子进程设置启动来源，非首次拉起交给 session_start 问候。新增台词和 UI 全部中/英/日；相关数值集中在 `state.Config`、`behavior.py`、`effects.py` 常量中。
- 实现沿用原分层，仅新增纯 Python `behavior.py`（晃动、待机调度、按时间采样的行走路径），没有新依赖/精灵素材变更。镜像缓存运行时图像；绘制/遮罩同变换，修正奇数宽度的半像素中心。画布顶部增加原地跳留边。`--snapshot` 新增 `--mirror`、`--jump`。
- 验证：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/feedback-complete`，**403 passed**（原基线 321；更新旧规则测试并补概率边界、晃动/真实手势、表情/存档、待机、路径/中断、三语 hook 等）。150% Qt 缩放下锚点/遮罩/镜像/跳跃专项 **24 passed**。2 条原有 Pillow getdata 弃用警告；无新增弃用警告。原生 Windows Qt `--snapshot` 生成并目视检查 **12 张**镜像/过渡/跳跃/三语大计数固定状态及长 startup/idle_talk 截图，未见裁切、方块字或文字越界；不替代动态真机验收。日志为 `.venv/preview-run/feedback-complete.log`、`feedback-dpi-fixed.log`，截图为 `.venv/preview-run/feedback-visual/`，均已忽略、不提交。
- 踩坑：Qt 的负缩放重采样会让镜像边缘有细小差异，改用缓存镜像；不用已弃用的 QImage.mirrored。概率累加阈值做浮点规整，保证 95% 边界落入普通反应；自动跳被工作状态打断时清理位移。

**本次待用户验收（旧验收结论不替代以下新行为）**：
- [ ] 爱心的密度、大小和上飘距离。
- [ ] 随机挡手/晕的体验，以及清零后前两下的反馈；精确概率以自动边界测试为准。
- [ ] 拎起晃动的灵敏度；小抖不误判，落地才晕 2.5 秒并说话。
- [ ] 摸头不再传表扬；连续点“做得好”只合并一句，Claude 的自然回应；中/英/日转达。
- [ ] 九种表情、临时 5 秒、固定/恢复自动、拖动恢复固定、重启保持、双击固定提示。
- [ ] 三档活跃度、自言自语频率、朝向鼠标、原地跳；工作/固定/睡眠时安静。
- [ ] 镜像与跳跃中的真实桌面点穿、脚底稳定、不同大小/高分屏下的流畅度。
- [ ] 散步/走到另一边的朝向、边界、按下即中断、新位置重启恢复；跳/转身不改变最终位置。
- [ ] 三语新菜单文字和 startup；普通重启不再说“Claude 来啦”，hook 拉起仍正常问候，静音正常。

## 2026-10-19：此前审查记录（历史）
- reviewer 曾审查动画打磨与自我介绍提交 `39b0316`、`ea6aac3`，没有必须修的问题。当时可选项：端口占用提示覆盖首次介绍；普通启动专用 startup（已在本轮解决）；同状态重播需 `immediate=True`；下落中改大小重置速度；淡化帧的 `toImage` 可在出现卡顿时再缓存。
- 以下各节保留当时的实现与测试记录；当前交互规则以上方本轮记录为准。验收标记依据用户本次确认更新。

## v0.2.1：状态感知（2026-10-19，用户外出，只做自动化验证）
- **hook 命令改成 exec 形式**：`"command": "<.venv>/Scripts/python.exe", "args": ["<项目>/hooks/shion_hook.py", "<事件>"]`，绝对路径、不经过 shell，路径带空格也不用引号，PowerShell/bash 都不受影响，不再依赖 PATH 里的 python。已在 Claude Code 2.1.289 上用真实 `claude -p` 实测可用。`_is_shion` 同时识别旧的引号/`python "…"` 格式，重装会替换、卸载会删。新增订阅 `PostToolUseFailure`。
- **hook 脚本**：PreToolUse 发 `working`，detail 是 JSON `{"tool": 类别, "target": 简短目标}`（文件只取文件名、搜索词/Agent 描述 ≤20 字、网址只取域名、目标最长 60 字，**Bash 不带命令内容**）；Stop 发 `stop`，detail 是回复第一句（≤40 字）；PostToolUseFailure 发 `tool_error`（用户中断的不发）。
- **偏离 spec**：spec 写的是读 `transcript_path`，改用官方文档推荐的 stdin 字段 `last_assistant_message`（官方说 Stop 时 transcript 不保证已含最后一条）。
- **桌宠侧**：新增 `shion/activity.py`（最近 20 条、显示 5 条，内存里，不进存档）；working 带描述时气泡说“在读 x.py……”等（同一句 3 秒内不重复，替代随机的 claude_working）；stop 带第一句时说“做完啦：…”；tool_error → dizzy 2 秒 + 台词；Claude 停下 5 分钟（debug 下 20 秒）没新消息 → 提醒并跳一下（`PetWindow.bounce`），最多 2 次，用户理会/睡醒/Claude 重新开始都会取消；双击状态下面多出“最近：”和 5 条记录；右键新增「只显示状态，不显示内容」（存档 `privacy_mode`，打开后不显示也不记日志文件名/搜索词/回复，切换时清空记录）。三语台词/界面文字都已加。
- 气泡 `\n` 现在真的换行（内部用 U+2028，绘制时去掉），之前换行符会被当成一个字符挤在一行。
- 验证：pytest 321 个通过（新增 hook 纯函数/子进程、状态机、控制器、activity、安装卸载测试）；真实 `claude -p` 端到端（隔离端口和数据目录）日志里依次出现 `working {"tool":"read","target":"progress.md"}`、“在读 progress.md……”、`tool_error 'Read'` → dizzy、`stop '读取失败：…'` → “做完啦：…”、20 秒后催促；用 `--snapshot` 看过长状态气泡（多行、最近 5 条）不越界。
- **已验收（用户真机确认，2026-10-19）**：①工具描述气泡会不会太吵（可调 `ACTIVITY_REPEAT`）；②“做完啦：……”转述是否通顺；③出错时晕一下的观感；④5 分钟后跳一下提醒是否合适；⑤双击看最近记录；⑥隐私开关；⑦桌面端 Code 标签页里是否同样生效（只在终端 `claude -p` 测过）。
- 审查可选项（没做）：隐私模式只控制**显示和日志**，不控制传输——hook 不知道桌宠是否隐私模式，文件名/搜索词/回复第一句仍会发到本机 127.0.0.1；静音时催你回来仍会跳一下但不说话；`server.py` 的 `main()` 调试入口会 print detail（只在调试用）。
- 踩坑：Python 里用 heredoc 写含 `\n`、`\\` 的源码时转义会被二次处理，改这类代码要用编辑工具直接改文件再跑测试。

## v0.2：Claude Code hooks（2026-10-19，用户外出，只做自动化验证）
- 新增 `hooks/shion_hook.py`（只用标准库）：5 个事件映射到 session_start/prompt/working/stop/notification；UserPromptSubmit 调 `/praise/take`，count>0 且存档 `inject_praise` 不为 false 时用 UTF-8 字节写出那句表扬；SessionStart 在 `/health` 不通时用 `.venv\Scripts\pythonw.exe -m shion` 脱离父进程拉起桌宠并最多等 3 秒。任何情况返回 0、stderr 为空；请求不走系统代理、单次超时 0.5 秒，另有总时限兜底（普通事件 2.5 秒、SessionStart 12 秒）。
- 新增 `tools/install_hooks.py`、`uninstall_hooks.py`、`hooks_config.py`：`--settings PATH`（默认用户级 `~/.claude/settings.json`）；写前备份为 `*.shion-backup-时间戳`，合并不覆盖、可重复安装、卸载只删 Shion 条目；坏 JSON 不改文件；文件不存在/没有变化时卸载不写盘。
- 桌宠侧只加日志：`收到事件：…`、`取走夸奖：N`，用日志验证事件有没有到。
- **开发阶段只装在项目级** `.claude/settings.local.json`（已 gitignore，含本机绝对路径）；**没有动用户级 `~/.claude/settings.json`**。
- 验证：pytest 287 个通过（新增 hook 子进程测试、服务卡死/关闭/大 stdin、安装卸载往返等）；手动冒烟（隔离端口和数据目录）逐个事件日志正确；**真实 `claude -p` 端到端**：桌宠关闭时 SessionStart 自动拉起，日志依次出现 session_start / prompt / working / stop。
- **踩坑**：Claude Code 在这台机器上用 **PowerShell** 执行 hook，命令以带引号的路径开头（`"D:/…/python.exe" …`）会解析失败（hook 报错但不阻塞）。所以命令改成以不带引号的 `python` 开头：`python "D:/…/hooks/shion_hook.py" Stop`，bash 和 PowerShell 都能解析。代价：要求 PATH 里有真 python（install 脚本会检查，Microsoft Store 占位程序会被拒）；项目路径含 `$`、反引号、引号时拒绝安装。
- **已验收（用户真机确认，2026-10-19）**：①桌面端 Code 标签页和终端里开会话时桌宠自动出现、没有控制台窗口一闪；②用工具时 working、结束 done 的观感；③原摸头/夸夸联动（本次改为仅“做得好”）的下一条消息里 Claude 是否自然回应表扬；④关掉桌宠时 CC 完全无感（PreToolUse 每次多一个 python 进程，约 0.1 秒）；⑤桌面端 Code 标签页是否也读到项目级 `.claude/settings.local.json`（只在终端测过）。
- 审查可选项（没做）：用户级和项目级同时装会让每个事件触发两次（claude_tasks +2）——**装用户级之前先对项目级运行 `uninstall_hooks.py --settings .claude/settings.local.json`**；`inject_praise` 是 hook 读磁盘存档的，右键切换后若还没落盘会读到旧值（目前菜单里没有这个开关，影响小）；`launch_shion` 无自动测试；PowerShell 下解析命令没有自动测试；拉起桌宠超过 3 秒才就绪时那次 session_start 会丢。
- 已知取舍：被 SessionStart 拉起时，桌宠自己的启动介绍会被随后的 session_start 问候盖掉。

## 2026-10-19：动画打磨与启动自我介绍
- 按用户要求先提交此前遗留：截图验收记录/忽略规则、诗音更名和三语 `intro` 台词（`39b0316`）；基线 237 项测试通过。此次实现不新增或修改图片素材，不引入新依赖。
- 全部 QTimer 改用 `Qt.PreciseTimer`。桌宠、爱心、气泡的动画时钟为 `time.perf_counter()`；下落按起点和实际经过时间解析计算重力位置，去掉 50ms 的截断，错过落地后的压扁也会按真实时间结束。
- 精灵切换约 120ms ease-out 交叉淡化，3% 轻微压扁后回弹，脚底固定；快速切换从当前混合画面和姿态继续。眨眼同样淡化，但不额外压扁。粒子位移改三次 ease-out，倾斜保留指数 ease-out，缩放使用平滑压扁/回弹曲线。
- idle 每隔 6～15 秒随机轻微歪头或左右晃约 1.2 秒，幅度 ≤1.8°。眨眼、小动作各用独立随机序列并按预定时刻推进，掉帧不会把后续动作整体推迟。鼠标拖动仍直接跟手，下落保留重力加速。
- 遮罩覆盖淡化中所有可见精灵，按姿态缓存；不随权重重复生成。把重画 13 遍改为绘制一遍后平移合并区域；保留非透明轮廓像素，透明角落仍点穿。180 帧 dizzy 的原生 Qt 本机采样：320px 档位刷新逻辑（含遮罩）P95 约 **4.6ms → 1.5ms**，绘制 P95 约 0.7ms；这是函数计时，不能替代真实桌面帧率，暂不降遮罩更新频率。
- 没有存档文件时启动说当前语言的 `intro`；已有存档时 `<10%` 说 `intro`，其余 `greeting`；遵守静音，Claude session_start 逻辑保留。自动测试覆盖首次、概率边界、静音和真实子进程首次启动日志。
- `--snapshot` 增加 `--from-state`，例如 `--from-state idle --state working --at 0.06` 检查淡化中间帧；原有不带该参数的截图仍直接显示目标状态。
- 验证：完整 `.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/animation-full-1`，**263 passed**（新增 26 项）；150% Qt 缩放下交叉淡化/遮罩专项 **7 passed**；2 条原有 Pillow `getdata` 弃用警告。日志、性能数据及检查图放在已忽略的 `.venv/preview-run/`；`docs/preview.png` 仍不提交。
- 已看过原生 Qt 过渡截图（0/30/60/90/120/240ms）和固定种子的 idle 小动作截图：未见裁切或脚底跳位。修过淡化叠加导致身体短暂闪透的问题，以及遮罩阈值遗漏半透明轮廓的问题，均有回归测试。
- **已验收（用户真机确认，2026-10-19）**：实时淡化/回弹是否自然；连续快速摸头、拖动、松手的跟手感；idle 小动作频率和幅度；淡化中和动画后的真实桌面点击穿透；高分屏下的实际流畅度；中/英/日首次介绍、重启问候及静音体验。自动化和静态截图不算这些项目的人工验收。
- 用户已明确授权本次验收清单标待验收后提交。下一开发步骤仍是 **v0.2 Claude Code hooks**；本次不 push。

## 2026-10-19：截图视觉检查（用户外出，代查静态画面）
- 使用 `.venv\Scripts\python -m shion --snapshot`，原生 Windows Qt 平台生成 **12 张状态截图 + 中/英/日各 4 张气泡截图**：每种语言按字数挑最长的两条台词、使用大计数的状态文字（9999 天 / 99999 次 / 好感度 999999）和端口占用提示，共 24 张。
- 总览：`docs/preview.png`（1280×2449），已加入 `.gitignore`，**不提交**。单图、三语细节图、生成脚本、检查结果和测试日志在已忽略的 `.venv/preview-run/`。
- 已目视检查总览和三语原尺寸细节：12 张状态内容正常；未见方块字、气泡文字越界、遮挡人物或位置异常。另对 90 条文本实例检查 Qt 字形缺失和折行绘制边界，均通过，未改程序或素材。
- 测试：`.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/pytest-temp-20261019`，**237 passed**；2 条现有 Pillow `getdata` 弃用警告。默认 pytest 临时目录访问被拒（WinError 5），改用项目内独立临时目录后通过。
- 此次只完成静态画面检查；上面的拖动、点穿、焦点、高分屏、打字机/淡出等交互已于 2026-10-19 由用户真机验收。下一开发步骤仍是 v0.2 Claude Code hooks。本次未 commit。

## 换 2.3 头身 Q 版精灵图（v0.1 之后的素材更新）
- 精灵图 448x512（人物高约 480，头约 45%），`tools/process_sprites.py` 已重写；旧图备份在 `old_4.3heads/`（已 gitignore）
- 摸头判定区 35% → 45%（`pet_window.HEAD_FRAC`）；默认高度 240 → 200；大小档位 160/200/260/320
- **存档里如果已是旧高度（如 240）不会自动变**，右键 → 大小 → 200 选一次即可
- 测试：`test_anchor_dizzy_sway...` 的脚水平漂移容差 3 → 12px（新图脚更宽，最低 8 行在倾斜时只剩一只脚，是度量方式的问题，不是脚真的在滑）；新增摸头区测试，pytest 共 211 个通过
- 已验收（用户真机确认，2026-10-19）：200 高度下观感、头部 45% 的悬停/摸头手感

## 多语言（中/英/日）
- `shion/lines.py` 重写：`Lines(lang, rng, directory)`、`set_language`、`ui(key, **kw)`、`font_fallback`、`available_languages()`（扫描 `assets/lines/*.json`）、`resolve_language(saved, locale, codes)`；缺 key 回退中文
- 存档新增 `language`（None=还没选）；首次启动跟随系统语言（zh→中、ja→日、其他→英）并写入存档
- 控制器/app 的界面文字全部走 `lines.ui()`；右键菜单新增「语言」子菜单，切换立即生效并存档；气泡 `set_font_fallback` 追加备选字体；`--snapshot --lang ja` 可看日文气泡
- pytest 共 237 个通过；日文气泡截图正常（不是方块）
- 已验收（用户真机确认，2026-10-19）：右键 → 语言 切换三种语言的观感；删掉存档里的 `language` 后按系统语言启动；日文字体在你机器上显示正常
- 注意：`zh.json` 必须完整（它是回退的底）；以后新增台词类别/界面 key 要先加到 zh

## 已完成
- [x] 美术素材：12 张精灵图已处理好（`tools/process_sprites.py`）
- [x] 规格文档
- [x] v0.1-3 状态机 + 持久化（`shion/state.py`，pytest 全部通过）
- [x] v0.1-6 本地 HTTP 服务（`shion/server.py`，回调式，不依赖窗口；pytest 共 72 个通过）
- [x] v0.1-1 骨架 / 透明置顶窗口 / 拖动下落 / `--snapshot`（pytest 共 94 个通过；**真机已验收（2026-10-19）**）
- [x] v0.1-2 程序动画（`shion/animator.py`；pytest 共 121 个通过；**真机已验收（2026-10-19）**）
- [x] v0.1-4 交互接入状态机（`shion/controller.py`、`effects.py`、`lines.py`、`assets/lines/zh.json`；pytest 共 151 个通过；**真机已验收（2026-10-19）**）
- [x] v0.1-5 气泡与台词（`shion/bubble.py`；pytest 共 173 个通过；**真机已验收（2026-10-19）**）
- [x] 把 server 回调接到 Qt 信号上（`shion/bridge.py`、`app.run()` 启动服务；pytest 共 189 个通过；真机 curl 已验收（2026-10-19））
- [x] v0.1 审查（独立子代理，只读）+ 修复（pytest 共 210 个通过）
- [x] v0.2 Claude Code hooks（pytest 共 287 个通过；**真机已验收（2026-10-19）**）
- [x] v0.2.1 状态感知（pytest 共 321 个通过；**真机已验收（2026-10-19）**）
- [x] v0.3 Claude Code 遥控（pytest 共 583 个通过；**真机验收待用户确认**）
- [x] v0.4 诗音的对话菜单（零食、预设对话，不调用模型；**待用户验收**）
- [ ] v0.4.1 好感度系统（等 v0.2.1～v0.4 真机验收完成后再做）
- [ ] v0.5 内容包
- [ ] v1.0 发布

## 第 1 步：已验收（用户真机确认，2026-10-19）
自动验证过：pytest（拖动阈值、拖动切 drag、松手落到底边、屏幕外拉回、落地回 idle、透明角落不在 mask 里、单实例、`--snapshot` 输出透明 RGBA 120x240）；真实第二个进程启动会直接退出（exit 0）；idle 截图目视正常。
**用户已在真机完成以下清单**（运行 `.venv\Scripts\python -m shion`，右键 → 退出可关闭）：
- [x] 启动后桌宠出现在主屏右下角，脚贴任务栏上沿，置顶、任务栏不显示图标
- [x] 按住身体拖动 → 变成 drag 图，窗口跟着鼠标；松手 → 下落贴底，回到 idle；拖到屏幕外松手会被拉回
- [x] **透明区域点穿**：点人物两侧的空白处，能点到下面的窗口；点人物身体不穿透
- [x] 再开第二个 `python -m shion` 会直接退出，不出现第二只
- [x] 高分屏（缩放 150%）下清晰度、窗口大小正常
历史自动验证限制（点穿现已由用户真机验收）：当时电脑处于锁屏状态（`WindowFromPoint` 返回 LockScreenBackstopFrame）。实现用的是 `setMask`（按精灵 alpha 生成遮罩），不依赖 Windows 分层窗口的自动穿透。

## v0.1 审查结论与修复
审查（项目里的 `reviewer` 子代理本会话没注册，改用 general-purpose 子代理加载同样的审查要求）逐项核对了 spec 的数值、判定、状态机、协议和线程模型，**没发现规格错误，线程模型没问题**。修掉的问题：
- 写存档失败（目录只读/被占用）不再抛异常：`SaveScheduler.flush` 记日志、保持 dirty、30 秒退避重试；`controller.quit()` 保证一定能退出；`setup_logging` 目录不可写时只输出到 stderr、不影响启动；日志改为 1 MB 轮转
- 副屏恢复：之前存档在副屏的桌宠每次启动都跳回主屏。现在用存档的 x、y 选屏（`pick_screen_rect`），`PetWindow.place_on` 直接按那块屏的可用区域贴底；拔掉副屏/改分辨率/任务栏变化时 `relocate()` 会把桌宠放回屏内
- 单击/拖动阈值改成欧氏距离（对角 4+4=5.7px 仍是单击）
- 存档里的高度限制在 120～600
- `/praise/take` 超时后不会再丢计数（请求对象带取消标志）
- 服务端加固：拒绝带 `Origin` 头的请求（网页脚本无法伪造事件）和 `Host` 不是本机的请求（防 DNS 重绑定），读请求有 5 秒超时。**hook 脚本必须是普通 HTTP 客户端、不带 Origin，Host 用 127.0.0.1 或 localhost**
- 气泡折行后每一行都有 `> ` 前缀；`take_praise(now)` 用传入时间做防抖；`lines.py` 容错；一个近乎恒真的测试改写
**已知遗留（没修，影响很小）**：气泡停留期间仍每 16ms 刷新（画面不变，CPU 极小）；下落过程中改大小，落地位置会偏一点（不到 1 秒的窗口）；混合 DPI 的副屏上精灵只按主屏 DPR 缩放，可能略糊；子进程冒烟测试依赖真实时间（最长约 20 秒超时）。修完后没有再跑一遍审查，每处修复都有针对性测试。

## 服务接入 Qt：已验收（用户真机确认，2026-10-19）
自动验证过：控制器 `handle_event`（working 续期与 2 分钟超时、stop→done+计数+台词、greeting、notification、react、未知类型/表情忽略、静音时仍改状态）；真 HTTP 服务 + 假时钟控制器（处理函数确实在主线程执行、20 个并发事件全部处理、非法请求 400 且不改状态、`/praise/take` 计数正确且 20 个并发请求总数恰好等于待夸奖数、GUI 不泵事件时超时返回 500）；子进程冒烟：真的启动 `python -m shion`，HTTP 发 working/stop 后日志出现状态变化，第二个实例抢同一端口时不崩溃并记录“HTTP 服务启动失败”。
**用户已在真机确认**（先 `.venv\Scripts\python -m shion` 启动桌宠，另开终端；PowerShell 里用 `curl.exe`，不要用 `curl` 别名）：
- [x] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"working\"}"` → 桌宠变成抱电脑的 working，气泡说「Claude 在努力中」之类
- [x] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"stop\"}"` → done 3 秒 + 气泡「做完啦！」，双击看“Claude 完成了 1 个任务”
- [x] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"notification\"}"` → 气泡「Claude 在等你回话呢」
- [x] 旧版摸头后 `curl.exe -X POST http://127.0.0.1:47613/praise/take -d "{}"` → 返回 `{"count":N}`，再发一次返回 0（旧行为验收记录；新版仅菜单表扬，见本次待验收清单）
- [x] 桌宠没开时这些 curl 会连接失败（符合预期：关了桌宠不影响 Claude）
- [x] 如果端口被别的程序占着，桌宠启动后会说「本地端口 47613 被占用了…」且其他功能正常

## 服务接入 Qt 留给后面步骤的接口
- `ServerBridge(controller, take_timeout=2.0)`：`on_event`/`on_take_praise` 给 `ShionServer` 用；事件用排队信号切到 GUI 线程，夸奖用请求对象 + `threading.Event` 等结果，超时抛 `TimeoutError`（server 回 500）。**ShionServer 的回调都在服务线程，PetState 和界面只在 GUI 线程动**
- `PetController.handle_event(type, detail)`、`take_praise()`
- 环境变量：`SHION_PORT`（覆盖端口）、`SHION_INSTANCE_NAME`（覆盖单实例名，自动测试用）、`SHION_DATA_DIR`、`SHION_DEBUG`
- v0.2 的 hook 脚本只需要往 `http://127.0.0.1:47613/event` POST JSON，超时要短（桌宠没开时不能拖慢 Claude Code）

## 第 5 步：已验收（用户真机确认，2026-10-19）
自动验证过：时间线（30ms/字、打完停留 4s、0.3s 淡出、新台词替换）、`place_bubble`（头顶居中、顶部放不下翻到脚下、左右夹进屏幕）、窗口（不抢焦点/不挡鼠标的窗口标志、打字全程大小不变、字数随时间单调增加、背景 #0A0A0A / 边框 #F58236 / 圆角 / 米白文字、到时自动隐藏）、控制器（默认出口走气泡、静音收起并不再弹、桌宠移动时气泡跟随）；`--snapshot --bubble` 截图目视检查过（中文折行、`> ` 前缀、位置）；真实运行 1.5 秒：单击后气泡出现在桌宠头顶，字体选到 Cascadia Mono。
**用户已在真机确认**：
- [x] 打字机速度（30ms/字）和停留（4 秒）观感合适，淡出自然
- [x] 气泡不抢焦点（点桌宠时别的窗口的输入焦点不丢）、不挡鼠标（气泡所在位置能点到下面的窗口）
- [x] 拖动桌宠时气泡跟着走；把桌宠拖到屏幕最上方，气泡翻到脚下；靠左右边缘时不出屏
- [x] 静音后不再弹，已显示的立刻消失；双击的状态提示不受静音影响
- [x] 字体显示正常（Cascadia Mono，中文回退到系统字体）

## 第 5 步留给后面步骤的接口（`shion/bubble.py`）
- `BubbleWindow(clock, autostart)`：`say(text)`、`follow(body_rect)`、`dismiss()`、`render_image(now)`、`font_family`、`timeline`、`line_count`；纯逻辑 `BubbleTimeline`、`place_bubble`、`pick_font_family`
- `PetController(..., bubble=BubbleWindow)`：默认说话出口就是气泡；`PetWindow.body_rect()`、信号 `moved`
- `--snapshot` 不再强制 offscreen（offscreen 平台没有任何字体，中文会变方块），用原生平台离屏渲染；`--bubble 文字` 把气泡画在头顶，`--at` 是打字进度

## 第 4 步：已验收（用户真机确认，2026-10-19）
自动验证过：窗口手势（头部悬停是张开的手、头部左右移动每 40px 一次 patted 且不会拖动、身体拖动发 drag_started/落地发 drag_finished、单击、双击顺序 clicked→double_clicked、右键发菜单信号、抓住下落中的桌宠再松手会继续落、改大小保持脚底不动）；控制器（摸头→happy+爱心+好感度、5 连戳→stop、10 连戳→dizzy、拖动含下落全程是 drag、菜单各项、静音、双击等待间隔后才显示状态、存档防抖/退出 flush/重启恢复大小、位置恢复与越界回退、睡眠唤醒台词、冷落回归台词）；真实运行 4 秒：存档和日志写到了数据目录，正常退出；爱心粒子截图看过。
**用户已在真机逐项上手确认**（`.venv\Scripts\python -m shion`；`SHION_DEBUG=1` 会缩短冷落/睡眠阈值并在控制台打日志）：
- [x] 头部按住左右摩挲：happy + 摇头 + 爱心，手感合适；头部按住不会把桌宠拖走
- [x] 身体单击压扁；原固定 5/10 下规则由本次随机戳替代（新观感见本次待验收清单）
- [x] 身体拖动→drag 图，松手落地回 idle；重启后位置（x）和大小恢复
- [x] 双击：约半秒后出现「已陪伴… 今天被摸… 好感度…」提示
- [x] 右键菜单：夸夸 Claude（proud）、大小四档（切换后仍贴任务栏）、静音气泡、开机自启灰色、关于、退出
- [x] 台词已在第 5 步换成真气泡（不再用 QToolTip）
- [x] 爱心窗口完全点不到（不挡鼠标）
- [x] 历史验收：睡着后悬停会唤醒并说起床台词；2026-10-21 本轮已取消悬停唤醒，新行为见本轮待用户验收清单
- [x] 存档位置：`%APPDATA%\Shion\state.json`，日志：`%APPDATA%\Shion\shion.log`

## 第 4 步留给后面步骤的接口
- `PetController(window, state, scheduler, lines=None, overlay=None, now_fn=datetime.now, say=None, autostart=True)`：信号 `quit_requested`；`react(reactions)`、`say_key(key)`、`say(text)`、`sync()`、`tick()`、`set_size/set_muted/praise/quit`、`restore_position()`、`build_menu()`、`status_text()`
- **第 5 步只需把 `say` 的出口换成气泡**：控制器的 `_tooltip_say` 是暂代；构造时传 `say=` 回调即可覆盖；静音在 `say_key` 里已处理，双击状态不受静音影响
- **接 server（下一步之后）**：`controller.state.claude_event(...)` 的返回值交给 `controller.react(...)`，再 `controller.sync()`；注意要在 GUI 线程调用（用信号切线程），`take_praise` 要同步返回
- `PetWindow` 不再自己决定精灵：信号 `patted/clicked/double_clicked/drag_started/drag_finished/menu_requested`（2026-10-21 移除 `hovered`），`set_height()`、`snap_to_floor()`、`head_anchor()`；状态机的 `current()` 由控制器同步给 `set_state`
- `app.run()` 已接好存档（`SaveScheduler`）、日志、`SHION_DEBUG`、`SHION_DATA_DIR`（环境变量，覆盖数据目录，测试用）

## 第 2 步：已验收（用户真机确认，2026-10-19）
自动验证过：animator 纯逻辑 14 个 pytest（呼吸 1.000~1.012 / 周期 3s、眨眼只在 idle、间隔 3~6s、连眨约 15%、压扁结束精确回 1、倾斜限幅 ±12° 且松手回 0、晃动幅度）；窗口层用离屏渲染检查锚点（呼吸、压扁时最低行 ±1px、水平不滑；dizzy 晃动时脚不滑、不被画布裁掉）、遮罩覆盖所有可见像素；`--snapshot` 看过 idle / dizzy 最大角度 / land 压扁的截图；真实运行 8 秒 CPU 约 1.6%（单核）。
**用户已在真机确认**：
- [x] 呼吸、眨眼看着自然，不跳位、不抖
- [x] 点一下身体有压扁弹回；松手落地有压扁
- [x] 拖动时向左右拖会随速度倾斜，松手后回正，头没被裁掉
- [x] 动画状态下透明区域仍然点穿（遮罩现在随角度/缩放更新，向外扩 4px，边缘点击略宽松）
- [x] 高分屏下画面清晰
（dizzy / happy 的晃动已实现，要等第 4 步接上摸头、连戳后才能在真机看到）

## 第 2 步留给后面步骤的接口（`shion/animator.py`、`pet_window.py`）
- `Animator(rng)`：`set_state(name, now)`、`squash(now, "click"|"land")`、`set_drag(bool)`、`feed_velocity(vx, now)`、`frame(now) -> Frame(sprite, sx, sy, angle)`；时间都是传入的秒数，纯 Python
- `PetWindow(height, clock, autostart)`：`set_state(name)`（取代第 1 步的 `set_sprite`，第 4 步接状态机时用它）、`advance_to(now)`、`render_frame()`、`displayed_sprite`、`frame`、`sprite_size`
- **窗口现在是画布**：精灵左右各留 64px、上 8px、下 6px（`MARGIN_X/TOP/BOTTOM`），脚底中心在画布底边上方 6px。第 4 步的“头部 35%”命中区要用精灵坐标（减去 `MARGIN_X`、`MARGIN_TOP`）；`landing_geometry` 带了留边参数
- 单击已触发 click 压扁，第 4 步接单击/连戳时不用再做；拖动时 Animator 自己切 drag 状态，松手后回 `_base_state`（第 4 步改成状态机的 `current()`）
- `--snapshot` 新增 `--at 秒数`、`--squash click|land`

## 第 1 步留给后面步骤的接口（`shion/pet_window.py`、`app.py`）
- `PetWindow(height=240)`：`set_sprite(name)`、`place_default()`、`start_fall()`、信号 `quit_requested`；落地后回到 `_base_sprite`（第 4 步接状态机后改成 `state.current()`）
- 拖动/下落没有接状态机（`drag_start/drag_end` 还没调用），第 4 步接；右键菜单目前只有「退出」，第 4 步补全
- 窗口位置/大小还没存档，第 4 步一起做（`state.py` 的 `window.x/y/height`）
- `app.run()` 只建窗口，没接 server 和 `SaveScheduler`，留到“把 server 接到 Qt 信号”那步
- `app.snapshot(out, state, bubble)`：离屏渲染；`--bubble` 第 5 步才生效

## 第 3 步留给后面步骤的接口（`shion/state.py`）
- `PetState(data, now, config=None, on_change=None)`；`current(now)` 返回精灵名；`tick(now)` 清理到期状态
- 输入方法都返回 `list[Reaction]`，`Reaction("say", key)` 的 key 对应台词分类：
  `poke / stop / dizzy / drag / wake / neglect_return / praise_menu / claude_working / claude_done`（已在 spec 的 zh.json 里），
  另外有 **`greeting`（session_start）和 `claude_waiting`（notification）两个新 key，第 5 步写台词库时要补上**
- 界面层调用：`pat`（累计移动 40px 一次）、`click`、`drag_start/drag_end`、`interact`（双击、实际菜单操作，只唤醒；拖动除外，拖动算被理会；2026-10-21 起悬停与浏览/取消菜单不调用）、`praise_claude`、`take_praise`、`claude_event(type, detail, now)`
- 存档：`load(path)` / `save(path, data)` / `SaveScheduler(path, data)`（`mark_dirty`、`poll(now)` 给 QTimer、退出时 `flush()`）。路径用 `QStandardPaths.AppDataLocation` 取，第 1 步的 app 负责
- `Config.debug()` 给 `SHION_DEBUG=1` 用

## 第 6 步留给后面步骤的接口（`shion/server.py`）
- `ShionServer(on_event, on_take_praise, host="127.0.0.1", port=47613)`；`start()`（端口被占用抛 `OSError`）、`stop()`、`port`
- 回调在**服务线程**里调用：`on_event(type, detail)`、`on_take_praise() -> int`（server 内部加锁串行）。事件类型不在 server 校验，交给 `PetState.claude_event`
- 接 Qt 时：`on_event` 只发信号；`on_take_praise` 要同步拿返回值，打算 `BlockingQueuedConnection` 或共享锁，到时再定
- 调试：`.venv\Scripts\python -m shion.server` 起一个无窗口的内存版，用 curl 发 `/event`、`/praise/take`、`/health` 看打印

## 设计决定（第 3 步时定的，spec 没写死的部分）
- 摸头、单击、拖动（开始和松手）、Claude 事件算“被理会”；双击和相应菜单操作只唤醒不算。2026-10-21 更新：悬停与浏览/取消菜单不唤醒，也不刷新计时。唤醒和冷落回归同时发生时只说 `neglect_return`
- 夜间（0:30～6:30）默认睡；被叫醒后当晚不再强制睡，要再空闲 15 分钟才睡
- “做得好”菜单让待表扬 +1；摸头不再产生表扬（2026-10-19 本轮更新）
- 存档里 `window.x/y` 默认是 `null`（表示用默认的右下角），spec 里写的是 0
- `working` 事件每来一次就续期 2 分钟，但已在 working 时不重复说话
- `stop` 事件无论是否在 working 都会算一次任务完成

## 踩坑记录
- `QT_QPA_PLATFORM=offscreen` 下没有任何字体（`QFontDatabase.families()` 为空），文字渲染成方块；要看中文截图必须用原生平台
- 隐藏（没 show）的 QWidget 不会收到 move 事件，`moved` 信号相关测试要先 `show()`
- `QTest.mouseDClick` 在 offscreen 下只发一个双击事件，没有按下/松开；测试里要手动补 `mouseRelease`
- 测试里 `QMenu` 临时对象一旦被回收，里面的 `QAction` 就失效（RuntimeError），要留引用
- `QWidget.grab()` 会被 `setMask` 裁剪，遮罩外的像素是未初始化内存（测试偶发角落有像素）；截图和测试改用 `render_frame()`
- numpy 用 `frombuffer` 读 `QImage.constBits()` 时，QImage 一释放数据就悬空，必须 `.copy()`
- 遮罩要覆盖实际绘制：角度取整 1° 在 250px 处有约 2px 误差，所以遮罩向外扩 4px
- 呼吸每帧都变会让 60fps 重绘（CPU 约 8.6%）；把帧量化到 0.001 / 0.01° 后降到约 1.6%
- `QRegion(QPixmap.mask().scaled(...))` 会报错，要先 `QBitmap.fromPixmap(...)`
- Windows 下 Qt 窗口坐标是逻辑像素，用 `WindowFromPoint` 等 Win32 API 检查时要乘 `devicePixelRatio`；锁屏时它返回 LockScreenBackstopFrame，测不了
- Git Bash 的长 heredoc 里夹中文/引号容易解析失败，写大文件用 Write 工具
- 本机只有 Python 3.10，spec 已从 3.11+ 改成 3.10+
- Windows 下 git 会提示 LF 将转 CRLF，只是警告
