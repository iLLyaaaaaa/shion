# 进度记录

> 新会话先读本页。历史原文按月保存在 [progress-archive/2026-10.md](progress-archive/2026-10.md)，包括 2026-10-26（含）之前的记录和近期长篇明细。**需要查历史时用 grep 搜归档，不要通读**，例如 `rg -n "关键词" docs/progress-archive/`（也可用 `grep -n`）。归档保留当时状态；旧“下一步”“未安装”“未合并”不代表当前状态。归档原文中的相对链接仍以原 `docs/` 目录为基准，查阅时从该目录解析。规格按需读 `docs/spec.md`。

## 当前状态总览

### 2026-11-17 V3 转正 / 发布 v3.0.0：计划已批准，进行中（本地提交，不 push）

计划全文：`C:\Users\<user>\.claude\plans\` 下的 v3.0.0 计划（同内容摘要如下）。决策：只留 V3、无切换开关；`PetWindow` 保留为 `V3PetWindow` 父类骨架；周报立绘换 V3 预渲染图；程序图标用 V3 头像重做。一个会话只做一步，标【停点】处必须等用户确认，push 前必须等用户同意。

- [x] R1 内存回升排查与修复（2026-11-17，本地提交，待用户真机验收；验收线改为默认高度 200 ≤260MB；260/320 高约 271/290MB，用户决定不设线、不再压）
  - **测量已完成，未改代码**（真实应用，默认高度 200、DPR1.5、启动 25 秒后 5 次中位数，同一时段交替；数据 `build/v300/ws-r1*/ws.log`，不入库）：S7 末 `b663712` 6 轮 252.7MB（专用 157.4）；`7a74395` 254.1；`35751a3` 252.6；HEAD 6 轮 256.8（专用 161.1）；HEAD 关换边 256.7；HEAD 关 scene 252.8；V2 对照 185MB（与 S7 记录一致，说明机器状态没变）。今天各组离散只有 ±2MB。
  - **结论 1**：不是 S8/S9 回归。S7 末源码今天也是 253MB，S7 记的“223 平均”是 199/197/247/251 两档的平均，今天稳定落在高档；S7 之后只多了 +4MB（scene）。
  - **结论 2（真问题）**：窗口存档位置在屏幕左半时（启动应为右鼓）稳定 **289MB**（+32MB），峰值 304MB。原因：`__init__` 先建左侧 rig/渲染器并排预热，首次 show 才发现该用右侧，再建右侧并丢掉左侧；丢掉时左侧预热任务还在跑，引用到任务结束才放开，之后没有再触发 GC。实验（只在 `build/v300/` 的包装脚本里，未动仓库）：25 秒后手动 `gc.collect()` 回到 254MB；换边瞬间立刻 `gc.collect()` 无效（289MB）。
  - **修复**（用户选“修启动并放宽线”）：①`Prewarmer.close()` 返回还在跑的 future；`_v3_drop_side` 记下它们，`_v3_side_step` 在任务都结束且不在互动时补一次 `gc.collect()`（耗时进 `v3_stats["gc_ms"]`）。②`v3_display.startup_side` + `V3PetWindow(initial_side=…)`：`app.run` 按存档位置先选侧，左半屏启动不再白建左侧；`pick_screen_rect` 从 controller 挪到 `v3_display`（controller 仍可导入）。`SHION_V3_AUTO_SIDE=0` 时忽略提示。
  - **修复后实测**（同法，`ws-r1g/h/i/j`）：200 高右半屏 254.8MB（4 轮）、左半屏 255.8MB（4 轮，修复前 289MB，峰值 304→257MB）；260 高 271MB、320 高 290MB（各 2 轮，左右一致）。`v3_perf` 260@1.5 前后：待机 18.2→19.2FPS/总 CPU 0.54→0.65%，工作 16.4→17.0，捏脸 62.1→62.2FPS/P95 15.0→15.0ms，摸头 60.6→60.9，敲头 60.0→60.7/P95 16.4→16.2ms，都在波动内。
  - **测试**：`tests/test_v3_side.py` 新增 13 项（startup_side、窗口宽度估算 ×4 高度、右提示只加载右侧、错提示被纠正、无提示/关换边、`close()` 返回值、GC 只做一次且等任务和互动、释放后弱引用已死）；该文件 32 passed。全仓 `-X faulthandler`：**1 failed、2996 passed、9 skipped**（24 分 41 秒，日志 `build/v300/r1-full.log`）；唯一失败 `test_install_hooks.py::test_corrupt_json_not_touched` 与本次无关：它的子进程用 GBK 解码输出，后台 PowerShell 管道里 stderr 为 None；单独跑和不带本次改动都 11 passed。
  - **踩坑**：①PowerShell 5.1 读无 BOM 的 UTF-8 脚本时，中文注释可能吞掉换行，把下一行变成注释；脚本注释写纯 ASCII。②Git Bash 的 `sed` 替换里写 Windows 路径会把 ``、`` 当转义；改用 Python 或正斜线。③丢弃一侧后立刻 `gc.collect()` 没用（后台任务还拿着引用），要等任务结束。④`Out-File -Encoding utf8` 的日志要用 `utf-8-sig` 读。
  - **分项**（`probe_mem.py`、`tools.v3_mem`）：`import scipy.ndimage` 约 +27～41MB 工作集（连带加载 linalg/sparse/special，共 198 个模块；仅 `scipy.linalg` 单独就 +23MB，无法只拿 ndimage）；单侧 Rig 加载后保留约 28MB、Renderer 约 17MB；rig.images 12.3MB、pink_cleanup 4.3MB、expression_plates 3.2MB 是最大几项；V3 比 V2 多 68MB（专用多 59MB）。运行期用到的 ndimage 函数只有 8 个：map_coordinates、gaussian_filter、distance_transform_edt、binary_dilation/closing/opening、label、zoom。
- [x] R2 默认 V3、删 `--renderer`、删 V2 专用画图代码与测试（2026-11-17，本地提交，待用户真机验收）
  - **提交**：`ddf2605` 默认 V3；`35c4f00` 取证记录；`be12240` 测试迁移；本步删除提交见 `git log`。开始删除前打了本地标签 `pre-r2-delete`（指向 `35c4f00`）。清单 `build/v300/r2/R2a-清单.md` 用户已确认，按用户的 5 条修正执行：①`DRAG_FRAME_SECONDS` / `DRAG_MIN_FRAME_SECONDS` 被 `DragPlayback` 用，保留，其余常量逐个重新核对（含文件内部引用）；②父类 `_hit_zone` 先简化成只返回 outside / body，再删 `HEAD_FRAC` / `CHEEK_BOTTOM_FRAC` / `BELLY_*`；③删 `_belly_mode` 后 `mouseMoveEvent` 阈内改为无条件 return，专测 `test_pet_window.py::test_base_press_move_within_threshold_is_not_a_drag`；④`stop_motion` 整体改写为只剩 `_jump_start` / `_jump_offset` 归零和 `_refresh`；⑤每删一项测试都写明 V3 下的覆盖（`build/v300/r2/test-migration.md`）。
  - **代码**：`pet_window.py` 952 → 约 580 行，只剩窗口骨架（拖动 / 慢放 / 甩出下落 / 夹边 / `set_height` / 暂停标签 / 小跳），`_load_sprites` / `_draw_sprite` / `_mask_for` / `_refresh` / `_sync_sleep_z` 变成留给 V3 的接口（`PetWindow` 不能单独实例化）；删掉 V2 贴图与帧序列、动作边界淡化、遮罩缓存、V2 手势（捏脸 / 肚子 / 摸头区）、`_pose`、`_tickle*`、`_jump_framed`。`behavior.py` 删 `TickleGesture`、`jump_sample` 和只服务它们的常量（`JUMP_HEIGHT` 留作 `MARGIN_TOP`，`DragPlayback` 等留）。控制器里 `hasattr(w, "knocked")` / `getattr(window, "lifting")` 改成直接使用。`tools/process_sheets.py` 与 `tests/test_process_sheets.py` 删除；`tools/v3_perf.py` 的 V2 窗口分支删除（`results.jsonl` 里的 V2 行留作对照基线）；`tools/process_sprites.py` 留到 R3 与 V2 精灵图一起删。
  - **`--snapshot` 参数**：删 `--cheek` / `--tickle` / `--drag` / `--weight-shift` / `--desk-blink` / `--renderer`（argparse 拒绝）；新增 `--gesture pinch|pat|knock|tickle|lift`（让真实窗口的 V3 动画器按 `v3proto` 的确定性输入走到第 `--at` 秒）和 `--side left|right`（不自动换边）。截图模式下 V3 预热改在当前线程内联完成（`v3_prewarm.InlineExecutor`），否则手势素材还没预热好就截了、几个手势会出同一张图；`tools/make_media.py` 同样用它。
  - **两处产品代码小改（为了让同种子可重复）**：V3 窗口的发丝轻摆原来用不带种子的随机数，现在给了 `rng`（截图 / 配图的固定种子）时由它决定（不消耗 `rng`，别处随机序列不变）；`make_media` 的批次因此逐字节可重复，但整套配图因预热内联变慢，一批约 2 分钟（`test_native_full_batches…` 约 6.5 分钟，已把超时放宽到 600 秒）。
  - **测试迁移**：迁移前 3016 项 → 现在 2895 项左右。**删除 135 项**（含 `test_process_sheets` 14 项，随工具删除；其中 7 项以同名改写后的新名字重新加入）、**改写 90 项**（同一条目 ID，正文或参数有改动，名单 `rewritten-ids.txt`）、**新增 14 项**（`test_v3_default.py` 另 8 项含已删参数拒绝、`--gesture` / `--side` 在新进程里互不相同；基类拖动阈值 1 项；`test_touch_actions.py` 4 项；`test_frame_sequences.py` 1 项）。每项删除对应的 V3 覆盖见 `test-migration.md`。
  - **验证**：全仓 `-X faulthandler`（日志 `build/v300/r2/full.log`）：9 failed、2877 passed、9 skipped，35 分 51 秒；9 项里 3 项是真问题已修（`test_idle_life` 的 `--weight-shift`、`test_sleep_motion` 的 `--desk-blink`、`test_v3_gestures` 里给只读属性 `lifting` 赋值），其余 5 项（`test_v3_gestures` 的 lift 裁剪 [320]、两项预热锁 / 未算完补丁、`test_server` 的一条令牌拒绝路由）是满载偶发，单独复跑全过，与 R1 记录的同类时序偶发一致。修完后相关 12 个文件复跑 556 passed、4 skipped；媒体 / 预热 / 换边 / 内存测试复跑见 `build/v300/r2/media-rerun.log`。离屏隔离启动冒烟 14 秒：无报错，约 10 秒时说出首次“捏着脸颊往上提”提示。**没有在真实窗口里验过**，见下方验收项。
  - **留给 R6 / 之后**：`docs/spec.md` 第 40～48 行仍写 `assets/sprites/`、`process_sprites.py`、`process_sheets.py` 的 V2 素材流程，CLAUDE.md / README“从源码运行”里提到 `process_sprites.py` 的句子（R3 / R6 一起改）；hero.gif 里强塞的 V2 眨眼对 V3 无效（`make_media.hero_frames` 里的 `_blinks`），重新生成配图时要用 V3 自己的眨眼；`JUMP_HEIGHT=45` 只用于顶部留白，窗口留边是否收小是候选（会改窗口尺寸，本版没动）；“把 sprite 命名改掉 / `v3proto` 并入 `shion` / V3 并回 `PetWindow`”按总计划 C 类仍不做。
  - **踩坑**：①Qt 回调（`paintEvent`、`enterEvent`、`contextMenuEvent`）离屏测试里次数为 0 但真实窗口会调，不能按“0 次”删；②引用搜索用 PCRE 边界，别用 `\b`（`_v3_pose` 会被当成 `_pose`）；③同一进程里“互不相同”的测试会被热缓存骗过，V3 的后台预热让截图要在新进程里验；④`SwayEnvelope` 默认无种子导致同种子的整条时间线都不可重复；⑤`behavior.py` 删除脚本里 `"JUMP_DURATION" not in s` 会被 `LEGACY_JUMP_DURATION` 误伤；⑥bash 里用 here-doc 写带中文和引号的长脚本容易整段失败，改用 Write 工具写文件再运行；⑦不要在改动中途 `git stash`（这次手快 stash 又 pop 过一次，没丢东西，但很危险）。
  - **待用户真机验收**（源码运行，`.venv\Scripts\python -m shion`）：启动默认就是 V3（无参数）；捏脸 / 拎起 / 摸头 / 敲头 / 挠痒；落地、夹边、慢放停留；右键菜单、各类面板位置、暂停标签；左半屏存档位置启动直接是右鼓；`--snapshot` 新参数的截图（见 `build/v300/r2/shots/`）。
  - **下一步**：R3 周报立绘与图标换 V3，随后删 V2 精灵 PNG 与 `tools/process_sprites.py`（【停点 R3】）。
- [ ] R3 周报立绘与图标换 V3，随后删 V2 精灵 PNG——【停点 R3】
- [ ] R4 打包：Shion.spec 收 V3 素材与依赖、bundle_smoke 加 V3 自检、ZIP 体积前后对比
- [ ] R5 reviewer 审查——【停点 R5】
- [ ] R6 版本 3.0.0、README 三语、spec/CLAUDE.md、V3 配图与 hero.gif、发布说明——【停点 R6a、R6b】
- [ ] R7 打包版真机验收（exe）与替换 Shion-dev——【停点 R7】
- [ ] R8 推送前审查、合并 master、标签、Release——【停点 R8a】，用户同意后才 push

### 2026-11-16 S9 姿势变体（collapse / bed / desk）：第 5 步测量与文档收尾（本地提交，不 push）

- **做了什么**：第 1 步素材（`tools/v3_scene.py` 把三张整图切块、分出角色与家具，`d5ca2d9`）；第 2～3 步显示（整图 + 呼吸仿射、点穿家具覆盖窗、窗口临时加宽，`98a8dd5`）；第 4 步互动、锚点、睡觉 Z、scene 期间冻结换边，及真机验收后的 4b 修复（`5806319`）；右鼓脸型衔接（`2f6d84d`）；第 5 步（本条）测量工具、测试、文档。S8 第 2 项抱电脑用户 2026-11-16 确认已验收，单独提交 `9af0aaf`。详细设计见 spec“姿势变体 scene（S9）”。
- **改掉的原决定（真机验收后，用户同意）**：①scene 切换由 0.3 秒交叉淡化改为**直接切换 + 小弹跳**（轮廓不同的两张图淡化必然叠影、抽搐）；②垫底由整张场景图改为**只含家具颜色的 under 层**（整图里静止的角色描线就是敲头时没跟着下去的黑边），“角色与家具之间不露透明缝”的要求和测试保留。
- **测量工具**：`tools/v3_mem.py` 加 `scenes` 一节与 `--load-bench N`，`SHION_V3_SCENES=0` 时文件名带 `-noscene`；`tools/v3_perf.py` 加 `parse_scenario`、`state:<名>+knock|pat`、`switch` 场景，结果加 `refresh_max_ms`、`scene_load_ms`。数据与汇总表在忽略目录 `build/v3/integrate/s9/`（`measure.md`、`mem/`、`perf/results.jsonl`、`ws/ws.log`）。
- **测量结果**（真实窗口，DPR1.5，预热 20 秒，scene 开 vs `SHION_V3_SCENES=0`）：三个 scene 图像合计 260@1.5 约 3.5MB；静置总 CPU 0.26–0.38%，单核低于站姿回退；scene 内敲头 61.9 / 54.1 FPS、P95 13.9 / 18.8ms，摸头 P95 11.6ms；idle→bed→desk→collapse 每秒轮换最长一帧 ≤35ms；46 次运行无一次同步载入。
- **已知限制（用户决定记录不处理）**：①真实应用总工作集约 254MB（3 轮：scene 开 253MB、关 255MB，V2 约 185MB），超过 S7 的 230MB 线，与 scene 无关，是 S7（223MB 平均、噪声 ±25MB）之后涨起来的；②缓存被挤掉后同步载入单个 scene 约 250～280ms（目标 ≤80ms），真实运行从未触发（启动后后台载入）；③desk 摸头合成测试 28.5 FPS（量化键不变时少画帧，P95 11.6ms，CPU 低），未在真实窗口逐帧确认；④S8 已知瑕疵（左腮红上缘毛边、dizzy 右侧细竖线、拉伸时鼓包上缘锯齿虚线、右眼右下角被盖一点）仍在，S9 只修了下巴衔接。
- **测试**：新增 `tests/test_v3_perf_scenarios.py`（解析 9 项 + 2 项）、`tests/test_v3_memory.py` 4 项 scene 用例（无 `full` 层、图像合计 ≤4.1MB 预算、缓存不超 `SCENE_CACHE`、`SHION_V3_SCENES=0` 不建缓存不提交后台任务）。全仓（`-X faulthandler`，日志 `build/v3/integrate/s9/full/full.log`）：1 failed、**2985 passed**、9 skipped，24 分 29 秒，无崩溃输出；唯一失败是 `test_v3_side::test_switch_frame_does_not_compose_on_the_main_thread`（满载 40ms 线偶发，S9 4b 末也出现过），单独连跑 3 次都通过。对照 S8 末 2790 passed。
- **踩坑**：①新写的窗口测试必须请求 `qapp` 夹具，否则 `QApplication` 不存在时测试进程直接异常退出（退出码 127、无报错）；②`v3_mem` 离屏时 DPR 实际是 1.0，scene 字节数要按 260@1.5 另量（测试用同口径）；③测量时别并行跑测试，会污染 CPU 数字。
- 下一步：合并到 master 的准备另起计划；候选：真实应用工作集削减、同步载入放后台、S8 已知瑕疵、审查低级问题 7～12、14。

### 2026-11-11 v2.2.0 已发布

- **推送**（用户同意后）：`git push origin master`（`cf58821..e974526`，快进）、`git push origin v2.2.0`（附注标签 `f105f74` → `e974526`，标签作者 noreply）。没有推 backup，没用 --all / --mirror / --tags。第一次推送因 GitHub 登录过期、会话里不能弹出 Git Credential Manager 登录而失败（远端未变）；用户在自己的终端重新登录 gh 后推送成功。
- **推送前审查**（范围 12 个提交 `d4dee9e`…`e974526`）：邮箱全部 noreply，提交信息里只有 `noreply@anthropic.com`；逐提交 `check_private --ref` 12/12 无命中；USERNAME / COMPUTERNAME 对完整补丁（UTF-8 与 UTF-16）、提交信息、路径 0 命中；密钥 / 令牌 / 手机号 / 证件号正则 0 命中（未装 gitleaks）；出现过的 34 个文件均为代码、测试、文档、台词；无 >5 MB 文件，无 build/dist/.venv/raw/音频/字体；`ls-files -ci` 为空；与 `feature/v3-integrate` 共有的 6 个提交都是 V2.2 自身提交，没有 V3 专属提交。审查中发现一个本地提交信息带 BOM（PowerShell `Out-File utf8`），未推送前已 amend 修正；以后提交信息用 Write 工具或 `git commit -m` 写。
- **Release**「Shion 2.2.0」：https://github.com/iLLyaaaaaa/shion/releases/tag/v2.2.0 ，Latest、非草稿、非预发布，发布时间 2026-11-11T11:50:46Z；正文与 `build/release-notes-2.2.0.md` 一致；附件 `Shion-2.2.0-win64.zip` 46,380,724 字节，重新下载后 SHA-256 `c8fe82ad…ca7a62` 与本地一致，公开下载地址返回 200。
- **远端核对**：`ls-remote` 的 master 与标签和本地一致；仓库 Public、默认分支 master；远端文件 268 个，与本地 `ls-tree` 逐个路径和 blob 哈希一致。
- 下一步由用户决定：审查建议 6～13 与“连接前检测 Claude 是否在运行”留作后续候选；V3（`feature/v3-integrate`）另行推进。

### 2026-11-11 v2.2.0 剩余真机验收通过

- 用户在已替换的 Shion-dev 2.2.0 上确认通过：英/日自然触发各一长一短、英日聊天气泡、断开后配置恢复与重新连接。连同 11-08 已通过的项目，V2.2 发布前人工验收全部完成。多 CC 逐个继续仍按日常使用验证（自动化回归已覆盖）。
- 下一步：发布第三部分第 1 步，推送前审查。

### 2026-11-11 v2.2.0 打包并替换 Shion-dev，待剩余真机验收

- **打包**：从 `74ddb24` 运行 `tools/build.py`，依赖版本一致（PyInstaller 6.22.3 / hooks-contrib 2026.9 / PySide6 6.12.0 / numpy 2.2.6），230 文件，bundle_smoke **110 项通过**，exe 版本 2.2.0，SHA-256 `9d79dc04…9014ac`。`dist/Shion-2.2.0-win64.zip` 46,380,724 字节，SHA-256 `c8fe82adf7cafedce9ac10566b49852a277f1c9ee7ae547c53de64cc44ca7a62`；2.0.0 / 2.1.0 两个 ZIP 哈希未变。
- **烟测**（隔离目录，`build/v220-release-20261111/smoke.py`）：Observer stdio 响应与 11-08 替换完全一致；聊天 MCP initialize、tools/list（三个工具）、working / need_input / done 均正常，stderr 为空，未写任何文件。
- **替换**：沿用 11-08 替换器，只改目录名。北京时间 19:36:22 完成，两次改名各一次成功，没有强制结束进程。新旧各 230 文件逐个哈希核对一致（替换后另行只读复核一次）；旧包保留为 `D:\desktop\tools\Shion-dev-before-2.2.0-20261111`。配置哈希未变，`v2_scheduler_enabled=false`、`claude_link_enabled=true`，三个 ZIP 未变。证据在 `build/v220-release-20261111/`。
- **踩坑**：①占用旧目录的是 Claude 桌面版拉起的两个聊天 MCP，只关窗口不行，要从托盘退出 Claude。②从本会话（运行在 Claude 里）后台启动的替换器会随 Claude 退出一起被结束：第一次在确认“无进程”的 3 秒内被结束，没有改名，只留下暂存副本（核对与 dist 一致后删除）。改为用户从资源管理器双击 `start_replacer.cmd` 在 Claude 外运行后成功。以后替换都按这个方式。
- 下一步：用户做剩余真机验收（英/日自然触发各一长一短、英日聊天气泡、断开后配置恢复与重新连接），通过后进入发布第三部分（推送前审查）。

### 2026-11-11 v2.2.0 发布准备第二部分：版本号、README、发布说明（本地提交，不 push）

- 版本号改为 2.2.0（exe 版本资源 2.2.0.0），`test_release` / `test_windowing` 的版本断言同步；spec V2.2 标题改为“v2.2.0 发布”。
- 三语 README 结构对齐：「功能」新增 Claude 桌面版聊天联动小节；连接步骤改为编号步骤并逐字引用个人偏好原句（与 `desktop_preference` 一致）、补断开与“清除连接记录”；补隐私（只收工具名和最多 20 字任务名，不写日志；备份含原配置全文）、常见问题、卸载、已知限制（漏调、15 分钟回空闲、须完全退出 Claude、聊天 token 不计）。ja 原先放在「機能」里的连接说明移到独立的「Claude デスクトップ版チャットとの接続」节，菜单名“AI 接続”更正为实际的“AI 連携”。按用户要求补一条已知限制：没有 Git Bash 时原 statusLine 命令经 PowerShell 冷启动可能超过 1 秒，首次刷新可能丢失原状态栏输出（v2.1.0 起已有）。
- 发布说明 `build/release-notes-2.2.0.md`（忽略目录）用户已认可：新功能 / 隐私 / 已知限制 / 从 2.1.0 升级（V2.2 未改 CC hooks，不需重连 CC；聊天连接存的是 exe 绝对路径，挪文件夹要断开再连）/ 结尾预告下一个大版本改用纸偶立绘。
- 下一步：从本提交打包、bundle_smoke、烟测，替换 Shion-dev（等用户退出诗音，不强制结束进程），然后用户做剩余真机验收。

### 2026-11-11 v2.2.0 发布准备第一部分：合并修复、查清失败、审查修复（本地提交，不 push）

- **合并**：`fix/chat-pause-display`（`c2f44ee`）本来就是本分支 HEAD，无需再合；`fix/test-exit-crash`（`8e16027`）普通合并为 `af0672e`，无冲突。`feature/v3-*` 未合入。
- **stamina 失败的原因（已复现）**：不是超时。`test_chain_preserves_exact_stdin_and_stdout` 用 `list2cmdline`（cmd 引号规则）拼命令，实际却交给 Git Bash 执行。路径带空格时会加引号，bash 保留反斜线，测试通过；worktree 路径（如 `shion-exitfix`）没有空格就不加引号，bash 把 `\` 当转义，命令找不到（返回码 127）→ 输出为空 → 断言失败。用临时 junction 复现 3/3，之后只解除链接。修复只改测试：按 `statusline_shell()` 实际用的 shell 拼命令（bash 用正斜线 + `shlex.join`，PowerShell 回退用 `& '…'`），与 spec「路径使用正斜线并按对应 shell 引用」一致；junction 路径 3/3、PowerShell 回退各验证通过。产品行为不变。
- **reviewer 审查 `master..HEAD`**：无严重问题（BOM/CRLF/非 ASCII 等配置 insert→remove 均逐字节还原）。用户选择修 1、3、5：
  - ①断开失败（配置已删除/损坏/shion 条目被改）时回执永远删不掉、菜单卡在“断开”：新增 `ChatConnection.forget()`，失败时询问“清除连接记录”，确认后只删回执、不改配置，提示用户自己检查 shion 条目（三语 `desktop_forget` / `desktop_forgotten`）。
  - ③CC 长时间思考超过 5 分钟没有 hook 事件时，遗留暂停清理会把用户的暂停悄悄解除：`_has_active_cc()` 记录最近一次 CC 活动时间，遗留暂停要在超过 30 分钟（`STALE_PAUSE_GRACE`）无 CC 活动后才清；从未见过 CC 活动仍立即清。
  - ⑤连接/断开失败只弹同一句、没有日志：改为 `log.warning` 只记异常类型（测试确认不记配置内容）；`insert` 里的 `assert` 改为 `raise ValueError`。
  - 第 2 条（轮次结束后“继续”也置灰）是 11-06/11-08 用户已认可的规则，不改。第 4 条（连接前检测 Claude 进程）及建议 6～13 留到以后：回执含整份配置的 base64 且无形状校验；非精确还原留下空 `mcpServers`；MCP 单行超 8192 字节直接退出；未知方法应回 -32601；通知锁非阻塞会丢 working/done；`read_link` 缺 KeyError；暂停时 ChatGPT 工作也会显示 working；重复 working 每次都出气泡。
- **测试**：合并后第 1 次全量 3 failed（`test_stop_work` 三项，均为 V2.2 未改动的老测试：0.3 秒定时器 `hub.end()` 与请求/子进程到达检查点的竞态；当时另有计时脚本和 reviewer 同时运行，单独跑该文件 2 次 30/30 通过）；无负载复跑全量 2301 passed、8 skipped，退出码 0。修复后全量 **2308 passed、8 skipped、2 条既有 Pillow 弃用警告，退出码 0，无退出期崩溃**，日志 `build/v220-full-{1,2,3}.log`。
- spec V2.2 章节同步了 30 分钟宽限和“清除连接记录”规则。
- 下一步：发布准备第二部分（版本号 2.2.0、README 三语核对补齐、发布说明草稿给用户看）。

### 2026-11-12 S8 第 2 项：working 抱电脑，已验收（2026-11-16，本地提交，不 push）

- **素材**：`working-hold.png`（1122×1402）。不先补白边，直接用 `align_head`（新增 `rows` 参数）按身体、脸、腿的未改动部分拟合仿射，一次重采样补边加缩放（缩放约 0.956，头部残差 12、腿 13）；只用头部拟合时腿的残差 23，所以改用全身拟合。
- **切块**（`tools/v3_hold.py`）：新图与“去掉双臂的 neutral”的差异，取粗块为芯再长回 4 像素，去掉和电脑相连的领口、缎带、裙边碎片（它们是新画与现有身体 1～3 像素错位造成的，用 5 个排除矩形和 1 个斜边多边形挡掉，坐标按 `build/v3/integrate/s8/hold/aligned-vs-current.png` 量）。输出 `slices/arms_hold.png` 和 `rig.json` 的 `arms_hold`（层级同 `arm_l`，父级 body，无 pivot）。只有一个连通块，没有单独的道具零件图。
- **接入**：`Settings.arms='hold'`；`Rig.active/rest(arms=)` 二选一（默认部件表不含 `arms_hold`，头部合成、镜像等路径不受影响）；`rest_cache` 键、`_body_frame`、`hit_test`、静态捏脸路径、`draw_key` 都带 arms；`shion/v3_display.py` 的 `STATE_ARMS={"working":"hold"}`，窗口每帧按状态设置。`Renderer.render` 在 hold 时把 `pose.arm_degrees` 置零。
- **互动**（按用户要求）：捏脸挣扎、挠痒躲闪、拎起抬手的手臂动作都不做，电脑始终抱着；身体、头、脸颊照常。`arms_hold` 区域（含电脑）命中算 body：可戳、不挠痒；肚子挠痒只对电脑外露出的肚子（抽样：默认 827 点可挠 → hold 下被块盖住的 757 点变 body，89 点仍是 belly）。
- **测试**：新增 `tests/test_v3_hold.py` 9 项；`test_v3_slice` 的允许来源加 `hold_slice`。全仓（junction，`-X faulthandler`，日志 `build/v3/integrate/s8/full/full.log`）：2790 passed、1 failed、9 skipped，正常退出；唯一失败就是上面的来源白名单（已改）。基线对比：S7 末 2772 passed + 1 偶发。
- **已知瑕疵**：①hold 时身体切片在裙边右侧有一小段斜细线、左袖口外侧有几个虚点（原来被旧手臂盖住的切片残边，没有改默认素材）；②层级默认放手臂层：缎带盖在电脑右上角之上、头发盖住电脑上缘，画稿里是电脑在缎带前面，需要用户在真实窗口确认；③working 头下沉 10px，下巴离电脑上缘很近，未发现压住。
- **验收结论**：用户 2026-11-16 确认真实窗口验收通过（抱电脑外观、层级、互动、切换状态），上面的已知瑕疵用户接受，暂不修。第 1 项的已知瑕疵（左腮红上缘毛边、dizzy 右侧细竖线、拉伸时鼓包上缘锯齿虚线、右眼右下角被盖一点）同属接受范围；其中右侧脸型衔接已在 S9 `2f6d84d` 修过。

### 2026-11-12 S8 第 1 项：右鼓版底板接入，验收一通过（本地提交，不 push）

- **合并**：master（v2.2.0，`8ed6de8`）普通合并进 `feature/v3-integrate`（`3ba5944`），无冲突；本步只合并和接入素材，不做旧版外观清理。
- **素材**：`assets/sprites/raw/v3/s6/head-right-plate.png`（1086×1448）。与 `full-left-ref.png` 的差异热图（`build/v3/integrate/s8/right-plate-diff.png`）：改动只在两侧脸颊，框外无成片改动。对位仿射接近单位阵。
- **做法**（`tools/v3_right_plate.py`）：不整张重切，两块改动区整块以新画为准，区外和左侧逐像素相同。皮肤和描边进 `head_skin`、干净底板、4 张睁眼底板；露出的鬓发进 `side_hair_l`，与皮肤不重叠（测试验证）。捏脸素材直接从新画底板切；运动公式沿用左侧，按 `mirror_sum`=1058 反射并下移 `dy`=34（新鼓包更高）。新文件在 `assets/sprites/v3/right/`，登记在 `rig.json right_side`，左侧文件不动。`v3proto/mirror.py` 有 `right_side` 就加载，没有退回镜像。
- **换边**：`auto_side` 默认打开，`SHION_V3_AUTO_SIDE=0` 固定左鼓。`tools/v3_mirror_check.py` 加“头发甩到 ±4°”两列。
- **踩坑**：①新画里是睁着的 smug 眼，共用的干净底板里残留橙色虹膜，右侧 happy/sleep/dizzy/yawn 眼睛下方透出来。原因是去眼睛的条件限制在皮肤洪泛区内，眼睛碰到刘海就不算封闭的洞。已修，并加测试（11 个表情、睁眼/半眨/闭眼三档，眼窗内右侧不得有左侧没有的橙色，眼睛部件和刘海遮罩与左侧一致）。②曾按“眼窗内一律取左侧像素”试过：新鼓包比镜像位置高，上缘伸进眼窗，被裁平，所以改成“窗内不取睁眼颜色，皮肤和腮红照新画”。③脸部合成在右侧要用右侧底板的 box，不能沿用左侧 box（`v3proto/face.py`）。④“遮罩落在基底皮肤上”这类启发式要先用左侧量一下基线（左侧自己只有 81%）。
- **测试**：V3 子集 475 passed、1 skipped（日志 `build/v3/integrate/s8/v3-3.log`）；合并后的全仓等第 2 项完成后一起跑。
- **已知瑕疵（用户决定暂不修，第 2 项后真实窗口验收时在 320 高、右鼓状态捏脸检查，肉眼可见再修）**：左腮红上缘毛边；dizzy 右侧静止时一条极细竖线；捏脸拉伸时鼓包上缘的锯齿虚线；右眼右下角被盖住一点。
- 下一步：S8 第 2 项，working 抱电脑（`working-hold.png`）；`raw/v3/s6/` 里的 `collapse-pose.png`、`bed-scene.png`、`desk-scene.png` 属于 S9，不处理。

### 2026-11-11 全仓测试汇总后进程崩溃：已定位并修复（分支 fix/test-exit-crash）

- **现象**：全仓 pytest 打印汇总后，进程偶发以 0xC0000409、`Fatal Python error: Aborted`（退出码 3）或 access violation（139）退出。三者是同一个退出期原生崩溃，只是有没有开 faulthandler 的区别。V2.2 起点 `45d87b3` 上就有，和 V3 无关；修复前全仓 3 次崩 2 次。
- **原因**：测试把**显示过的顶层 Qt 窗口**留到了解释器退出，PySide6 退出时的析构顺序不定，偶发崩溃。窗口留下来是因为按钮信号连着捕获 `self` 的 lambda，引用挂在 C++ 连接上，gc 回收不了，只 `close()` 不会释放它。主犯是 `test_permission.py::test_panel_title_is_plain_text`（只跑它 24 次崩 3 次；整个文件去掉它 16 次 0 次）。另外 `PetController.dispose()` 漏清检查点面板 `_checkpoint`，`test_per_session_remote` 3 项、`test_session_labels` 1 项各留下一整套控制器和窗口；`test_weekly` 的 `deleteLater()` 没处理延迟删除。
- **修复**：上述测试改为真正销毁窗口（`deleteLater()` + `sendPostedEvents(DeferredDelete)`）；`dispose()` 也清 `_checkpoint`；`tests/conftest.py` 加会话级兜底（结束时停掉定时器、销毁剩余顶层窗口）。
- **验证**：单个主犯测试并行 24 次、相关 5 个文件组合并行 12 次，全部正常退出（修复前分别崩 3 次、4 次）。全仓并行 3 次：都是 16 failed、2285 passed、8 skipped，退出码 1，无崩溃输出。16 项与修复前基线相同：`test_chat_remote_boundary` 15 项，加 `test_stamina::test_chain_preserves_exact_stdin_and_stdout`（在这个 worktree 里单独跑也稳定失败，修复前基线也一样，与本次无关，未查）。
- **踩坑**：①测试里显示过的窗口必须销毁，不能只 `close()`；②Windows 上没有控制台时 Qt 消息不写 stderr，排查时要设 `QT_FORCE_STDERR_LOGGING=1`（这次确认了不是 qFatal）；③崩溃是概率性的，单次全仓不崩不能说明没问题，要并行多跑几次。
- **待做**：真实程序退出时（`app.exec()` 返回后）也有显示过的面板活到解释器退出，可能同样在退出时静默崩溃，没查。

### 2026-11-11 S7 第 6 条“先显示上一帧”的回归修复（用户批准）

- **问题**：后台排着上百个预热任务时（例如启动头几秒），这一帧要的素材（如某表情的捏脸素材）排在队尾，后台每做完一项马上又拿锁，主线程每帧都判断“会等锁”而一直显示旧图：子集测试里连续推迟 102 帧（约 3 秒）。改第 6 条之前最坏只卡一个后台任务 + 一次现算（约 0.1 秒）。
- **修法**（`shion/v3_window.py`）：
  1. `MAX_DEFERRED = 3`：连续推迟 3 帧（约 50ms）后不再推迟，主线程直接等锁现算；画出新帧后计数清零。
  2. 推迟的那一帧不再直接 `return`：V2 变换照常更新，后面的遮罩重建和 `update()` 照常走（遮罩按“旧图 + 新变换”画，和屏幕一致）。原来直接返回会让旧图按新变换画、伸出遮罩（`test_lift_shake_and_landing_never_clip_visible_pixels[320]` 抓到 1 个像素）。
  - 中间试过“推迟时 `_frame` 也留在上一帧”，不行：父类 V2 窗口拖动时自己也写 `_frame`，会把 V2 倾斜带回来，状态姿态测试读到的姿态也会跳。已放弃。
- **测试**：`tests/test_v3_prewarm_thread.py` 新增“后台一直占锁时最多推迟 MAX_DEFERRED 帧、第 4 帧等锁画出”；`test_mouse_moves_never_render_a_frame_each_the_timer_does` 改为按真实 16ms 间隔推进、最多等 3 秒，失败时打印统计。
- **回归**（junction，`-X faulthandler`，日志 `build/v3/integrate/defer3/`）：display+gestures 子集 96 passed；V3 473 passed、1 skipped；全仓 2772 passed、1 failed（`test_stamina` 满载偶发）、9 skipped。**正常退出，无崩溃**。
- **首次捏脸**（改前 `498d456` 导出 vs 改后，交替 6 轮，捏脸 20 帧里最长一帧的均值，`defer3/first-pinch.txt`）：启动后首次 23.1 / 24.1ms，切表情 0.3 秒后 29.1 / 28.8ms，切表情 4 秒后 28.9 / 24.6ms，另一组首次 26.6 / 25.2ms，均在波动内。
- `test_v3_side::test_switch_frame_does_not_compose_on_the_main_thread` 在前一轮全仓里以 41.2ms 超过 40ms 线失败过一次（换边默认关闭，满载波动），本轮通过。

### 2026-11-11 合入 fix/test-exit-crash（合并提交 0abf44a）

- 冲突 2 处（`tests/conftest.py` 两个会话级收尾 fixture、本页两段新记录），按用户决定两边都保留；`shion/controller.py` 自动合并。
- **测试**（junction，`-X faulthandler`，日志 `build/v3/integrate/merge/`）：V3 `-k v3` 471 passed、1 failed、1 skipped；全仓 2755 passed、17 failed、9 skipped，26 分钟。**两次都正常退出（退出码 1 = 有失败），没有崩溃输出。**
- 17 项失败：`test_chat_remote_boundary` 15（见下条）、`test_stamina` 1（满载偶发，同前）、**新增 `test_v3_gestures.py::test_mouse_moves_never_render_a_frame_each_the_timer_does`**。
- **新增那项不是合并引入**：`35751a3`（S7 审查修复）导出上单独跑也失败，`b1ff143` 上通过。原因是第 6 条“后台占锁时先显示上一帧”：测试在同一瞬间连推 10 帧、不给后台留真实时间，10 帧全被推迟（`deferred=10`）。按真实 16ms 间隔推进时只推迟 1 帧就画出来了，界面行为符合第 6 条的设计。修复见下条。

### 2026-11-11 `test_chat_remote_boundary` 15 项失败：查明并修复

- **结论：不是环境、时间或测试互相污染，是 `45d87b3` 提交漏了要测的代码。** 11-08 那次 `2344 passed、10 skipped`（`build/v22-acceptance-full-20261108.log`，17:28，比提交早 1 分钟）跑的是**当时的工作区**（progress 原文“全量测试当前工作区”，控制器是分片暂存的），不是提交本身：那次共 2354 项，`45d87b3` 干净导出只收集到 2309 项。
- **证据**：
  1. 干净导出单独跑该文件：15 failed、13 passed，每次一样（不随时间、不靠别的测试）。
  2. 失败全是同一处：只暂停 CC、Claude 聊天仍在工作时，`sprite_name` 是 `stop`，测试期望 `working`。spec“聊天与 CC 同时工作时，只暂停 CC……本体仍显示工作中”与测试一致。
  3. `45d87b3` 没有改 `shion/state.py`；其中 `State.current()` 把 `paused → "stop"` 排在 `observed_working → "working"` 前面。
  4. 只在导出副本里把 `observed_working` 提到 `paused` 前面：该文件 + stop_work / continue_after_stop / chatgpt_ui / controller / per_session_remote / state 共 310 passed。
- **最小复现**：在 `45d87b3` 导出目录运行 `python -m pytest -q tests/test_chat_remote_boundary.py::test_chat_started_after_cc_pause_never_inherits_pause_display`（CC prompt → `stop_work()` → 聊天开始 → 仍显示 stop）。
- **顺带发现**：主目录 `feature/v2.2-chat-mcp` 本次会话开始时有 8 个未提交改动（含 `shion/state.py`、`controller.py`）和未跟踪的 `tests/test_head_touch.py`，11-11 调查中途被清空，没有 stash/reflog 记录（不是本会话操作）。是否就是 11-08 漏提交的那部分，无法再核对。
- **修复**（用户批准）：分支 `fix/chat-pause-display`（从 `45d87b3`，提交 `c2f44ee`），`State.current()` 改为 聊天工作中 → 暂停 → CC 工作中；相关 9 个文件 391 passed。已合入本分支（`498d456`）。

### V3 第 2 步：接入诗音本体（S1～S7 完成，已验收）

- 分支 `feature/v3-integrate`，worktree `D:\desktop\work\shion-v3integrate`。起点 `feature/v2.2-chat-mcp` 的 `45d87b3`，已合入 `feature/v3-rig`（检查点 `3ec5578`）。本地提交，不 push。
- 修订方案 2026-11-09 已批准（计划原稿 `docs/v3-integration-plan.md` 在被合入的 V3 分支里，批准版以会话方案为准），批准时的 5 点调整：
  1. 只能从鼓脸颊拎起诗音（拎起 = 真实移动窗口，松手沿用现有下落/落地）；首次以 V3 启动时气泡提示一次「捏着脸往上提可以挪我」（`v3_lift_hint`，三语，存档记已提示）。
  2. 换边只镜像脸部皮肤（含鼓脸颊），以脸部中线为轴，按 `rig.json mirror.swap_layers` 对调左右鬓发顺序；头发、刘海、花饰、发带、五官、身体不镜像。先做左右各一张验证快照（8 表情、捏脸拉伸中、拎起中），不行再讨论新画右鼓版底板。
  3. 换边在一次眨眼的闭眼帧完成，鼓脸颊用捏脸松手回弹弹簧“啵”一下并给头发冲量，不做水平压扁；死区、只在停稳时判断、拖动中不翻。
  4. 新台词键（三语）：`cheek_pull_combo`、`cheek_lift`；`head_knock` 系列现有文案确认前不启用。
  5. 需新画清单优先级：working 道具 > collapse/slump > desk/bed > stop > yawn > neglect1（S6 改为：working 道具 > 右鼓版脸部底板 > collapse/slump > desk/bed > stop > yawn > neglect1）。验收线：互动场景 DPR1.5 平均 ≥55 FPS、paint P95 ≤14ms；待机/工作 CPU ≤ 单核 3% 且不超过 V2 的 2 倍。**（此条已在 S2 改为新验收线，见下方 S2 记录。）**
- **当前进度**：S1～S6 已验收（S5 换边已实现但**默认关闭**）；S7 全仓回归、CPU/内存评估、reviewer 审查、文档收尾已完成（2026-11-10），审查中级问题 1～6 已按用户要求修复（2026-11-10）；**S7 真实窗口验收通过（2026-11-11），V3 第 2 步收工**。仍在 `feature/v3-integrate`，未合并 master、未 push。
- **下一步候选**：
  1. 审查低级问题 7～12、14（未修，用户决定暂不修，可按需挑）；第 13 条 `cheek_pull_combo` 对 V2 也生效，用户确认保留并已写入 spec。全仓汇总后的退出崩溃是 V2.2 起点就有的问题，已在 `fix/test-exit-crash` 修复并合入本分支（见上方 2026-11-11 记录）。
  2. **S8：接入新画素材**：右鼓底板已接入并打开换边（见上方 2026-11-12）；抱电脑已验收并提交（`9af0aaf`）；S9 姿势变体完成（见最上方 2026-11-16）。
  3. 可选 CPU 优化：待机时遮罩重建约 7.6 次/秒、占主线程 CPU 约三分之一，可按姿态漂移判断少建。
  4. 合并到 master 的准备（另起计划）；`head_knock` 文案已启用，无待确认项。

#### 2026-11-10：S7 审查修复（中级 1～6）

- **做了什么**：
  1. 大 dt：`_refresh` 每帧最多推进 `MAX_DT=0.25` 秒（`shion/v3_window.py`），隐藏 10 分钟后第一帧 <0.2 秒、动画只前进 0.25 秒。
  2. 淘汰后重新预热（`shion/v3_prewarm.py`）：头部帧按“在缓存或在排队”判重，不再用“曾经请求过”；`request_blinks` 每帧只补当前表情缺的档；失败的记 `failed` 不重试；`collect` 淘汰时先不动当前表情的帧（`FRAME_LIMIT=64`）。去掉 `blink_requested`。
  3. 仿射 QImage 缓存 64→8（`shion/v3_layers.py` `QFRAME_LIMIT`），仍是副本，不共享 numpy 内存。
  4. 后台线程退出：`_BackgroundExecutor.shutdown()`（取消排队、哨兵、join 1 秒）、`Prewarmer.shutdown_pool()`，挂 `atexit` 和 `aboutToQuit`；`tests/conftest.py` 会话结束时调用。测试仍用真线程（S3/S4 卡顿回归要测真线程）。
  5. 右键/中键按下或松开不再清 `_v3_gesture`，拎起中右键后左键松开照常 `release_lift()`。
  6. 主线程不等后台锁：已缓存的反应脸补丁不抢锁直接取；新 `Prewarmer.would_block()`——要现算的东西没缓存且锁被后台占着时，本帧保留上一帧画面、下一 tick 再画（`v3_stats["deferred"]`）。
- **测试**：新增 `tests/test_v3_prewarm_thread.py` 10 项（大 dt、拎起/捏脸中右键、淘汰后重预热与保留当前表情、失败不重试、QImage 缓存上限、线程关闭与重建、等锁时推迟一帧、已缓存补丁不抢锁）。`test_v3_display::test_mask_rate_limited_and_follows_state` 改为看“状态切换后第一张真正画出来的帧”更新遮罩（后台占锁时那一帧会被推迟，这是第 6 条的预期效果）；`test_v3_gestures` 去掉对已删除的 `blink_requested` 的断言。V3 全部 472 passed、1 skipped。
- **全仓回归**（junction，`-X faulthandler`，`build/v3/integrate/s7/fix/all-tests.log`）：2756 passed、16 failed、9 skipped，16 项与 S7 第一次完全相同（chat_remote_boundary 15 + stamina 1，都与 V3 无关）。**汇总后进程以 abort 退出（退出码 3，faulthandler：`Fatal Python error: Aborted`，当时只剩一个线程、没有 Python 栈）**——预热线程已被关掉，不是它引起。**在未改动的 V2.2 起点 `45d87b3` 干净导出上跑全仓也一样 abort（退出码 3）**，所以这个退出崩溃（以及早先的 0xC0000409）是 V3 之前就有的问题，大概率是解释器收尾时 Qt 对象析构顺序，未进一步定位。
- **对比**（`b1ff143` 导出 vs 修复后，6 轮，18:38～18:55，`fix/first-pinch*.txt`、`fix/cpu.jsonl`）：
  - CPU（320@1.5，`--warmup 20`，2 轮）：待机 30.3/24.6 → 27.6/29.7，工作 26.9/24.0 → 20.4/23.9，没变高。
  - 首次捏脸首帧均值 18.0→20.4ms（另一组 18.8→17.5ms）；切表情 0.3 秒后 25.9→30.0ms；切表情 4 秒后 11.9→15.3ms。cProfile 两版这一帧做的事相同，新加的判断不占时间；20ms 上下的帧是遮罩重建（`setMask` 7～8ms）恰好落在那一帧，两版都有，属于时序波动。切表情 0.3 秒后的帧仍常到 35～40ms，原因是那一帧本身要现算新表情的东西、而后台占锁时会推迟一帧再算，最终还是要算一次；第 6 条只保证“等锁时界面不卡住”，没有减少这次计算。
- **待用户验收**（隔离启动 V3，`SHION_DATA_DIR=build3\integrate\s7\data`、`SHION_PORT=47699`）：① 拎着脸颊时按一下右键（会弹菜单），再松左键能正常放下；② 隐藏诗音几分钟（或电脑睡眠）后恢复不卡；③ 切表情后马上捏脸/摸头不卡；④ 眨眼正常、待机/工作看着同之前。

#### 2026-11-10：S7 全仓回归、CPU/内存评估、reviewer 审查、文档收尾

- **全仓回归**（建 `.venv`、`assets/sprites/raw` junction，`-X faulthandler`，22 分钟）：**2742 passed、16 failed、9 skipped，退出码 1（正常的“有失败”），这次没有出现 0xC0000409**。旧 16 项基线失败（process_sheets 10、install_hooks 2、connection_ui 2、hook 1、pause_badge 1）**全部通过**——都是缺 junction 导致。剩下 16 项：`test_chat_remote_boundary` 15 项在未改动的 V2.2 起点 `45d87b3` 和 S6 `5a79587` 的干净导出上同样失败，**不是 V3 引入**（主目录 `feature/v2.2-chat-mcp` 有未提交改动，可能就是在修这些，本次没碰）；`test_stamina::test_chain_preserves_exact_stdin_and_stdout` 单独重跑在三处都通过，属满载下偶发。比对表 `build/v3/integrate/s7/baseline-comparison.json`，日志 `all-tests.log`。0xC0000409 只复现于早先 V3 原型分支的两次全量跑，本次未复现；reviewer 指出的“后台预热守护线程退出时仍在 PIL/numpy 里工作、多数 V3 测试用真线程”是最可能的原因（待确认，见审查第 4 条）。
- **CPU 排查**（真实窗口 320@1.5，6 个提交各自 `git archive` 导出、统一用 S6 版 `v3_perf`，同一时段乱序轮流跑；预热等待 3 秒 2 轮 + 20 秒 3 轮，各 30 秒；15:17～16:03；`build/v3/integrate/s7/cpu/summary.md`）。单核%平均：

  | 版本 | 待机（等 3 秒） | 待机（等 20 秒） | 工作（等 3 秒） | 工作（等 20 秒） |
  |---|---|---|---|---|
  | V2 基线 45d87b3 | 23.7 | 23.9 | 6.4 | 5.8 |
  | S2 a7133f2 | 24.9 | 27.0 | 24.4 | 25.1 |
  | S3 3387b28 | 32.4 | 27.9 | 26.4 | 23.8 |
  | S4 b700221 | 32.6 | 29.3 | 29.1 | 24.7 |
  | S5 d77197a | 33.4 | 26.8 | 28.4 | 24.5 |
  | S6 5a79587 | 36.1 | 28.5 | 34.0 | 22.5 |

  **结论：没有哪一步带来常驻 CPU 退化**。等预热做完后 S2～S6 待机 27～29%、工作 22～25%，在波动内。“回升”有两个原因：① S6 记录只等 3 秒就开始测 30 秒，S3 起后台启动预热（捏脸素材、反应脸补丁）、S6 又多 3 个表情，都落在测量窗口里（等 3 秒时 S3～S6 比 S2 高 7～11 个点）；S2 当时测 60 秒，被稀释。② 机器今天更慢：同一份 S2 代码每帧计算中位数今天 8.8ms，S2 记录是 5.55ms（今天 CPU 约 2.0GHz/最高 2.4GHz）。按今天同时段数据，S6 待机 28.5% ≤ V2 待机 2 倍（47.8%），工作 22.5% ≤ V2 待机 23.9%，总 CPU <1%，**都在验收线内**（工作是临界）。`tools/v3_perf.py` 加 `--warmup`（默认 3，排除预热用 20）。
- **待机帧耗时去向**（S6 代码 30 秒 cProfile，`cpu/profile-idle.txt`）：主线程 6.9 秒中 `setMask` 1.65 秒、遮罩更新合计 2.25 秒（约 7.6 次/秒、每次约 7ms），`drawImage` 1.38 秒。遮罩是可选优化点（列为下一步候选，未改已验收的遮罩逻辑）。
- **内存**（`tools/v3_mem.py` 分项；真实应用测法同 S5，`build/v3/integrate/s7/ws/ws2.ps1`，每次启动 25 秒后取 5 次中位数，同时记任务管理器的“专用工作集”）：
  - 分项（真实窗口 260@1.5，只开窗口）：能统计到的图片/数组 86.8MB，大头是 rig 源图（整画布稀疏遮罩：各表情捏脸保护遮罩 18MB、pink_cleanup 6MB、face_contour 6MB、刘海遮罩 3MB）和头发位移场缓存 11.5MB；头部帧本身很小（每张约 0.2MB，帧缓存约 6MB）。另有 scipy 导入约 42MB（DLL）。离屏测时会多一个 DPR1 的渲染器，真实窗口只有一个。
  - 削减（都不改画面）：窗口用 rig 的稀疏遮罩改存有内容的一块（`shion/v3_memory.py` `SparseCanvas`，crop 逐像素相同），有 face_plate 时释放用不到的 face_contour；捏脸只留平面纹理（原来同一份存了两种排列）；反应脸遮罩缓存 64→8（只是建补丁的中间结果）；头发位移场存 float32；pink_cleanup 按 alpha 取范围（只用于整张叠加，再省约 1.5MB，下面的真实应用数字未含这一项）。原型唯一改动：`Rig.rest` 叠 pink_cleanup 时带偏移（普通图偏移为 0，行为不变）。
  - 结果：只开窗口工作集 205.8→**170.8MB**，统计到的图片/数组 86.8→52.7MB。**真实应用**（同时段 4 轮）：总工作集 V3 改前平均 242MB → **改后平均 223MB**（199/197/247/251，启动间呈两档，噪声 ±25MB，V2 自己也在 145～174 之间跳）；专用工作集 169→**144MB**（稳定，−25MB）；V2 同时段 162MB / 84MB。按平均值达到 ≤230MB 目标，停止削减。
  - 诊断：V3 窗口待机时真正在用的页只有约 40MB（清空工作集后 44 秒只长回 41MB），工作集大部分是驻留但闲置的 DLL 和源图页，所以启动间波动大。没有用“启动后主动清空工作集”的做法（只是让数字变小，提交内存不变）。
  - 流畅度：V3 全部测试 462 passed（含 S3/S4 卡顿回归）；首次捏脸帧（启动 15 秒后，8 轮）中位数改前 21.7ms / 改后 18.5ms；切表情 4 秒后捏脸首帧 10.8 / 11.9ms（均值 11.3 / 11.6，波动内）；切表情 0.3 秒后捏脸首帧两边都常到 35～55ms（主线程等后台眨眼帧的锁，改前就有，18 轮均值 30.2 / 33.3ms，波动内），记录在 `mem/first-pinch*.txt`。
- **reviewer 审查**（相对 45d87b3，报告原文 `build/v3/integrate/s7/review.md`）：**严重 0**；中 6、低 8。我核实了中级第 1、5 条确实存在：
  1. `_refresh` 的 `dt` 没上限，`advance` 按 1/120 秒切子步：窗口隐藏几分钟或电脑睡眠恢复后第一帧可能卡几秒。
  2. 帧缓存满 64 被淘汰的帧不会再预热（`requested` 没清），切回该表情时眨眼由主线程现算。
  3. `_v3_qframes` 每条是头部帧的 QImage 副本，内存翻倍。
  4. 后台预热守护线程退出时仍可能在跑，多数 V3 测试用真线程（可能与 0xC0000409 有关）。
  5. 拎着脸颊时按一下右键会清掉手势，左键松开不走 `release_lift()`，拎起状态卡住。
  6. 低优先级后台线程持锁，主线程首次切表情等锁卡顿。
  低级：prepare 中途异常留半成品、rig 级懒缓存双渲染器并发、换边失败每帧重试、悬停每次移动都做完整命中、失焦未复位 V2 按下状态、两次隐藏覆盖恢复标记、`cheek_pull_combo` 对 V2 也生效（用户确认保留）、若干漏测。中级 1～6 已修（见下条），低级未修。
- **文档**：`docs/spec.md` 新增“V3 正式接入”章节；`docs/v3-integration-plan.md` 分步表标注各步状态；V3 第 0/1 步的长记录原样搬到 `docs/progress-archive/2026-11.md`。
- **junction**：任务结束前已单独解除 `.venv`、`assets/sprites/raw` 两个链接（只删链接），目标目录仍在。
- **待用户验收**：① 隔离启动 V3（`SHION_DATA_DIR=build3\integrate\s7\data`、`SHION_PORT=47699`）切表情后立即捏脸/摸头不卡、眨眼正常、待机/工作看着和之前一样；② 看审查报告，决定中/低级问题修哪些。

#### 2026-11-10：S6 状态姿态与需新画清单，用户真实窗口验收通过

- **做了什么**：
  - 状态姿态表 `STATE_POSES` 与周期动作 `StateMotion`（`shion/v3_display.py`），只用原型 Pose 已有字段（头部位移/旋转、身体下压、手臂角度）。working 头略低 + 每 4～6 秒轻点头（0.5 秒）；neglect1/neglect2 低头；slump 下压低头手臂收拢；collapse 最大下压低头（站姿）；desk 低头；sleep/bed/neglect1/slump/collapse 呼吸和眨眼放慢；yawn 每 6～8 秒一次上抻（约 2.5 秒）；dizzy 头部画圈（半秒渐入）；喂零食时点头咀嚼。stop 双臂略外抬作占位。幅度是初值。
  - 窗口接入（`V3PetWindow._v3_state_pose`）：静态姿态 0.35 秒缓动到位；换状态时上一状态的周期动作余量衰减掉，不跳；捏脸/摸头/敲头/挠痒/拎起期间整体淡出、结束淡回；周期动作进行中临时 30 FPS，其余帧率不变；全部走仿射路径。V2 动画器的整图点头在 V3 下关掉（`Animator.whole_nod`，V2 默认不变），避免叠两次。
  - 原型唯一改动：`Settings.breath_rate`、`Settings.blink_gap`（默认 1，呼吸/眨眼时间线逐位不变；呼吸相位用单独累加的 `breath_time`，改速率不跳相）。
  - 碎屑锚点：`PetWindow.mouth_anchor()`（V2 位置不变）与 `start_chewing()`（V2 什么也不做）；V3 覆盖为 rig 嘴部中心，跟随低头/点头和 V2 压扁/倾斜/跳。控制器和 `--panel eating` 截图都改用它。
  - 参考图工具 `tools/v3_art_refs.py`（`refs` 生成 GPT 输入参考图和 refs.json，`pad` 把 GPT 输出等比缩放白边补齐）；`tools/v3_perf.py` 加 `state:<名字>` 场景。
  - **需新画清单**写进 `docs/v3-integration-plan.md`“需新画清单”章节，按用户定序：working 道具 > 右鼓版脸部底板 > collapse/slump > desk/bed > stop > yawn > neglect1；每项写明 GPT 输入参考图（含尺寸）、背景、分层、切片/对位工具、接入改动位置。
- **试拼三表情**（S0 留下的部件按现五官比例缩放，`build/v3/integrate/s6/trial-faces.png`）。用户决定：**slump、neglect1 采用**；yawn 嘴 ×1.0 不采用，另出以嘴中心放大 1.6 / 1.8 倍的对比（`build/v3/integrate/s6/trial-yawn.png`），**用户选 1.8 倍**。
- **新表情接入**：新工具 `tools/v3_s0_faces.py` 生成 `tired`（neutral 底 + 半闭眼）和 `bored`（neutral 底 + 半闭眼 + 波浪嘴）的五官图，以及 `yawn`（sleep 底 + 张大嘴放大 1.8 倍，`YAWN_SCALE`）（`assets/sprites/v3/expressions/expr_tired_*`、`expr_bored_*`、`expr_yawn_*`）并写 rig.json（部件、`faces`、表情槽位，眨眼轴取新眼底边上 1 像素）；`tools/v3_face_features.py REGIONS` tired/bored 沿用 neutral 范围、yawn 沿用 sleep；再跑 `tools/v3_cheek.py` 重建捏脸素材（原 8 个表情的素材重建后逐字节不变）。`STATE_EXPRESSIONS` 改为 slump→tired、neglect1→bored、yawn→yawn，预热自动包含。生成命令：`python -m tools.v3_s0_faces` 然后 `python -m tools.v3_cheek`。检查图 `build/v3/integrate/s6/new-faces-check.png`、`yawn-check.png`（睁眼/眨眼中/捏脸三格正常，yawn 与 sleep 行为一致）。踩坑：Rig 加载时校验捏脸素材必须覆盖全部表情，所以工具先移除 `interactions.cheek_left`，由 `v3_cheek` 整体重建。
- **状态总览**：`build/v3/integrate/s6/states-dpr1.png`、`states-dpr1.5.png`（`tools/v3_state_sheet.py`，四档高度 × 全部状态）。
- **性能**（真实窗口 320@1.5，各 30 秒，`build/v3/integrate/s6/perf*.jsonl`）：同一时段对比 S6 前（`499c6b4`）/后：待机单核 34.5%→32.2%，工作 29.3%→30.1%，**S6 没有带来退化**。slump 19.9%、collapse 18.7%（比待机低，帧率降到 9～12）；dizzy 68.2%（总 CPU 2.1%，V2 本来就整图 60 FPS 摇晃，且 dizzy 是几秒的临时状态）。今天整体比 S2 记录高（V2 待机 24.5% vs S2 22.0%，V3 待机 32% vs S2 17.8%），按 S2 的工作线（≤V2 待机单核）V3 working 超线，改动前就超；机器状态不同，**留 S7 统一复测评估**，和内存一起。
- **测试**：新增 `tests/test_v3_state_pose.py` 18 项（姿态表覆盖、工作点头间隔、哈欠/画圈/咀嚼、压身体时头跟着脖子、换状态不跳、点头走仿射且 V2 不再整图点头、呼吸眨眼放慢、互动淡出淡回、嘴部锚点位置与跟随、V2 锚点不变、原型默认时间线不变、参考图尺寸与 refs.json 一致、pad）回归（V3 全部 + pet_window/touch_actions/motion_update/idle_life/controller/state/lines/animator/effects）**850 passed、1 skipped、0 失败**，日志 `build/v3/integrate/s6/s6-regression.log`。接入 tired/bored 后重跑（加 1 条映射测试）：851 中 1 条失败——`test_v3_slice.py::test_committed_rig_v2_is_consistent` 只认三种部件来源，新增来源 `s0_part` 后补进允许列表（`source` 在代码里只用来区分垫底），该文件重跑 16 passed；日志 `s6-regression-2.log`。接入 yawn 后同组回归 **851 passed、1 skipped、0 失败**（`s6-regression-3.log`）。
- **验收工具**：`tools/v3_state_preview.py`（只开 V3 窗口 + 按钮面板，可切到菜单里没有的 neglect1/yawn/slump/collapse，带“喂零食”按钮；不连 Claude、不读写存档）。喂零食碎屑和菜单固定表情另用隔离启动的完整应用看（`SHION_INSTANCE_NAME` / `SHION_DATA_DIR=build3\integrate\s6\data` / `SHION_PORT=47699`）。
- **验收**：用户按下列清单用预览工具和隔离启动的完整应用验收，回复“没问题”。清单：① 菜单固定表情逐个切：working 低头和点头、neglect1/2 低头、slump/collapse 下压低头、yawn 偶尔上抻、dizzy 头画圈、desk 低头，切换不跳；② 工作中点头自然、不和整图点头叠加；③ 喂零食：碎屑从嘴里掉、头在点；④ 低体力状态下捏脸/摸头时姿态先收回、松手后回去；⑤ slump、neglect1、yawn 的新表情在桌面尺寸下看着对、眨眼正常。

#### 2026-11-10：S5 收尾（用户认可 S5 处理）

- 换边保持默认关闭，等新画右鼓版脸部底板后再开。
- **删除临时开关 `SHION_V3_FPS30`**：卡与降帧无关（原因见 S4 踩坑），开关已移除（`shion/v3_display.py` 的 `FPS30_ENV` 与对应测试）。
- **两条偶发超线的测试**：
  - `test_mouse_handler_cost_stays_far_below_the_frame_budget`：命中判断 P95 线 1.5ms → 3ms。单独跑 0.3～0.5ms，全量跑机器有负载时到过 1.57ms；3ms 仍不到一帧（16ms）的五分之一，真退化（每次命中重新合成，约 10ms 以上）照样会抓到。
  - `test_idle_is_mostly_affine_and_hair_settles_after_each_episode`：查下来**不是计时问题**，是窗口里的轻摆包络 `SwayEnvelope` 没设种子，30 秒里摆 2 次还是 3 次随机，占比在 60% 上下浮动。测试改为固定种子 1/2/3 各跑一次（线仍 60%）。实测三个种子各两次占比 70.7%～73.1%（眨眼等仍有少量随机，不完全一样），余量足够。
- 内存记为待优化项，S7 统一评估。

#### 2026-11-10：S5 换边逻辑完成，因右鼓素材问题默认关闭

- **做了什么**：`desired_side`（`shion/v3_display.py`）：窗口中心在可用区域右半边 → 左鼓，左半边 → 右鼓，中线两侧死区 max(5% 宽, 40px) 内保持。`V3PetWindow` 每帧检查“停稳”（位置/尺寸/DPR 连续 0.5 秒不变，且没在拖动/下落/按下/拎起/互动/跳/程序动作），停稳后需要换才在后台加载另一侧 rig 并建渲染器（`load_rig` / `_build_side`），主线程登记预热；新侧当前表情的睁眼帧、最深闭眼档、捏脸素材就绪后先眨眼，在闭眼最深处（实测眨眼开始后 0.062 秒）换 rig/渲染器/预热器，新侧脸颊从外拉 30% 弹回（“啵”）并给头发冲量，不出反应脸、不说话、窗口几何不变。准备途中被挪回原侧则取消；换走的一侧闲置 5 分钟释放（rig、渲染器、预热缓存）。启动时按恢复后的位置直接设定侧，不播过渡，用不到的一侧不留。渲染器缓存键改为 (侧, 高度, DPR)，每侧最多两份。右侧捏脸把传给动画器的点按 `Cheek.motion_x` 反射，外拉在两侧都是外拉。拎起倾斜由水平速度驱动、绕抓住的脸颊转，两侧角度相同（对照图 `build/v3/integrate/s5/lift-tilt-left-vs-right.png`），没有额外取反。
- **为什么默认关闭**：真实窗口验收发现右鼓时“脸歪了、两眼之间的刘海中间空心”。用原型直接渲染右侧（与窗口设置无关）画面相同，问题在 S5a 的镜像素材本身：可见的脸部底板画在刘海之上、带着刘海发梢，底板以两眼中线镜像后这些发梢翻到对面，和没镜像的头发对不上（`build/v3/integrate/s5/head-left-vs-right-zoom.png`）。S5a 验收看的是放大局部，桌面尺寸下的整体效果当时没暴露。用户决定暂停换边：`auto_side` 默认 False，环境变量 `SHION_V3_AUTO_SIDE=1` 可开启试用；等新画右鼓版脸部底板再打开。
- **顺带修掉的问题**：S4 的“已完成的表情不抢锁”用 `cheek.backgrounds` 判断，但后台 `prepare` 做到一半时它已经有了（`protection` 还没写），主线程跳过锁就会 KeyError。改为 `_locked()` 里记录“整段做完”的集合（`surface._v3_cheek_done`），快速路径和换边就绪都看它。
- **数据**（离屏单窗口，260 高、DPR1.5）：单侧常驻比空进程多约 135MB（工作集 170MB）；换边准备（挪过去到换完，含 0.5 秒停稳）2.0 秒，新侧其余预热再约 6.5 秒；双侧同时存在工作集 269MB、峰值 298MB；释放旧侧后 195MB（未完全回落，可能是 Python/Qt 没立即把内存还给系统，未验证）。换边那一帧 17～26ms（一次全量测试跑中超过 40ms，未定位）。真实应用总工作集（260 高，启动后 25 秒，两次）：V2 约 184MB，V3 约 286MB。
- **测试**：新增 `tests/test_v3_side.py` 21 项（死区/多屏、启动直接设定、停稳后眨眼换并“啵”、按下中不换、死区不准备、挪回取消、5 分钟释放、右侧捏脸外拉与拎起、换边帧耗时、默认关闭与环境变量开启）。`tests/test_v3_display.py` 的 `make()` 固定 `auto_side=False`。两条计时类测试在长时间全量跑里偶尔略超线、单独跑通过：`test_mouse_handler_cost_stays_far_below_the_frame_budget`（P95 1.57 vs 1.5ms）、`test_idle_is_mostly_affine_and_hair_settles_after_each_episode`（59.4% vs 60%，依赖随机轻摆间隔），当时未放宽；已在 S5 收尾处理（见上方）。


#### 2026-11-10：S4 拎脸颊移动真实窗口，移除 S3 过渡拖动，用户真实窗口验收通过

- **做了什么**：只能从脸颊拎起：脸颊上相对按下点向上 >12 逻辑像素且竖向 >1.2×横向，就 `begin_lift(cheek=True)` 并复用 `PetWindow` 的整套拖动（`drag_started`、移动窗口、`drag_finished`、慢放原地停留并夹边、速度 ≥450px/s 或放到任务栏下落、落地 `squash("land")`），不回原站位。拎起中 V3 的 `root_offset` 每帧置 0（窗口自己在动），`root_roll` / 身体 / 手臂 / 头发 / 泪眼 / 晕脸照常；V2 的拖动倾斜关掉（`set_drag(False)`）避免叠加。接住下落中的宠物时只有按在脸颊上才可拎或捏，按别处接住后松手照旧继续（受“放到任务栏”菜单开关控制）。
- **S3 过渡行为已删除**：拖脸/头发/身体/空白处不再挪窗口（单击仍戳，拖动后松手什么也不发）；肚子没在挠时不再转整窗拖动，停手(pause)只是 `release_tickle()`；脸颊横拉再远也只是捏脸，不再转整窗拖动。
- **台词与状态**：新增三语 `cheek_lift`（3 条，第一条“脸、脸不是把手啦！”/ “My cheek is NOT a handle!” /「ほっぺは取っ手じゃないってば！」）代替 `drag`，`state.drag_start(now, line)` 加可选参数，V2 窗口不变；晃晕以 V3 拎起的 `lift.dizzy`（来回 ≥24px 三次/2 秒，原 V2 是 40px）为准，`consume_shaken` 重写；`dizzy` 台词与 `drag` 同属 LOW 的“drag”类别，4 秒冷却内会被压掉（V2 同）。新增三语 `v3_lift_hint`：首次启动约 10 秒后说一次（被气泡门控挡住 30 秒后重试，说成功才写存档新字段 `v3_lift_hint_shown`，旧存档默认 False）；在脸颊以外按住拖动超过点击容差（窗口不动，新信号 `drag_ignored`）时 LOW 优先级再说，冷却 60 秒，每次按下最多一次，不写存档。
- **原型唯一改动**：`v3proto/lift.py` `move_lift(..., clamp=True)` 和 `Animator.move_lift(..., clamp=True)` 新增 `clamp` 参数，窗口版传 False（窗口位移远超实验台 ±240 rig 像素，限幅会让速度/倾斜变 0）；默认行为不变。
- **遮罩**：拎起期间（`animator.lift.active`）每渲染一帧重建；其余按“V2 帧（sx/sy/角度/跳跃）相对上次遮罩漂了多少像素”提前重建（`MASK_DRIFT_PX=3`，遮罩外扩 4px），其余仍 10 次/秒。拎起摇晃落地逐帧被裁像素 0（有测试）。
- **踩过的坑：摸头/敲头卡**（用户验收时发现，**与降帧无关**）。S3 测试都在“只有窗口、假时钟、鼠标事件时钟不前进”的环境里，测不出下面三个问题；改在“完整应用栈（控制器 + 气泡 + 爱心特效）+ 真实时钟”下复现（`NOPROF` 计时 + 事件循环 1ms 监视 + 卡顿时抽样主线程栈）：
  1. **鼠标每个移动事件都渲染一帧**：S3 的 `mouseMoveEvent` 末尾调 `_refresh`，鼠标 125～1000Hz 时每 16ms 帧渲染 2～16 次（摸头每帧 13～41ms，捏脸最高 136ms）。移除，动画交给 60 FPS 定时器；回归测试保证 400 个移动事件不触发渲染。
  2. **后台预热占锁让主线程白等**：摸头会让状态机进 happy，后台为 happy 合成 19 张眨眼帧（每张 ~45ms、持锁），而主线程每帧都调一次 `cheek.prepare`（该表情已完成时本来什么也不做，但包装函数先抢锁），于是每帧白等 16～260ms。修法：已完成的表情不抢锁；互动期间取消排队中的眨眼预热（`Prewarmer.cancel_blinks`），互动结束再补。
  3. **摸头时每帧重建遮罩**（我在 S3 修“落地头发闪”时引入）：判据里“按着鼠标”也算程序动作，摸头/捏脸时每帧调原生 `setMask`（~4～5ms）。改为按像素漂移判断。另外摸头每 40px 控制器调 `stop_motion()`，父类末尾同步渲染一帧（~10～15ms），手势进行中跳过；反应脸眨眼的补丁没算过时这次不眨（现算 ~50ms）。
  复测（完整栈、260 高、DPR1.5、预热完成后）：摸头每帧中位数 13～14ms → 7.3ms，P95 37～47 → 14.8ms，超过 33ms 的事件循环间隔 22～63 次 → 2 次；敲头中位数 9.3ms、P95 16.5ms。启动后约 5 秒内后台仍在预热，此时第一下摸头/敲头可能停顿（实测最长 ~440ms），属已知。
- **性能抽查**（320@1.5 拎起，`tools/v3_perf.py`，含每帧遮罩重建）：58.9 / 56.4 FPS，帧 P95 16.1 / 16.8ms，达标（≥50 FPS、P95 ≤20ms）。
- **测试**：`tests/test_v3_gestures.py` 增加拎起触发边界、窗口跟随、慢放停留/快甩下落、接住下落中的宠物、其它入口不挪窗口、`root_offset` 恒 0 与 V2 倾斜为 0、晃三次变晕并只报告一次、失焦、拎起全程不裁像素、控制器台词与提示冷却、存档兼容、四条卡顿回归；相关测试（gestures、display、pet_window、touch_actions、motion_update、idle_life、v3_lift、v3_cheek_lift、v3_proto、controller、state、lines）**533 passed**。全仓回归的 31 个环境相关失败不变，仍在 S7 建 junction 复测。
- **用户验收**：捏脸往上提挪窗口、倾斜/泪眼/晕脸、慢放停留与快甩下落、其余入口不能拖、点击仍戳、接住下落中的宠物、两种提示，均通过；摸头/敲头不卡。
- 隔离启动用的环境变量同 S2（`SHION_DATA_DIR` 用 `build/v3/integrate/s4/data-a|data-b`，`SHION_PORT` 47699/47698；B 另设 `SHION_V3_FPS30=1`）。

#### 2026-11-09：S3 捏脸 / 摸头 / 敲头 / 挠痒接入台词、好感、统计，用户真实窗口验收通过

- **做了什么**：V3 窗口改用 V3 命中测试（cheek/crown/face/head/belly/body，`_to_rig` 把窗口坐标按 V2 帧变换反算回 rig 坐标），`shion/pet_window.py` 不改，`V3PetWindow` 重写 press/move/release/focusOut/hover 光标。沿用既有信号，控制器/状态机几乎不动：捏脸 `gesture("cheek_pull")` 只发一次、松手 `cheek_release`；摸头顶 `patted`（每 40px，好感 +1 日上限 20、统计 pats 照旧）；挠肚子 `gesture("tickle")` 开始并每 4 秒重复、停手 1 秒后 `tickle_end`；肚子单击仍是普通戳（V2 肚子单击不发 clicked，V3 发，已告知用户）。
- **敲头顶**：只播 V3 敲头动画，新信号 `knocked(bool)`，**不发 `clicked`**（不算戳、无好感/统计）；1.5 秒内第 3 下为抗议。控制器 `_on_knock`：有周报邀请先消费，否则说 `head_knock` / `head_knock_stop`（LOW，4 秒类别冷却）。抗议句在第一句还显示不足 2.5 秒时会被 LOW_MIN_VISIBLE 压掉，未改优先级。
- **新台词**：`cheek_pull_combo`（10 秒内第 3 次及以后的捏脸，状态机滑动窗口计数，不存档），三语各 3 条；`head_knock` / `head_knock_stop` 三语现有文案启用。`cheek_lift` 留给 S4。
- **摸头/敲头区域**：只有 crown（hair_top/bangs/ahoge）；V2 是图片上 40%。用户在 160 高下测过，可接受。
- **踩过的坑 1：首次捏脸卡顿。** 捏脸素材（每表情首次约 100～130ms）和反应脸补丁（每张约 50ms）原来懒建，第一次捏脸整窗冻 ~108ms。修法：都放进后台预热，`_locked()` 整段持锁，主线程只在结果出来后用；首次捏脸帧 ≈13.6ms；预热完约需 3.5 秒。鼠标处理本身 hit_test P95 0.3～0.5ms，捏脸 move P95 ≈0.5ms。
- **踩过的坑 2：落地头发“闪”。** 用户怀疑头发角度在 0.05° 附近抖动导致仿射/网格路径来回切换，**逐帧记录不支持**：纯拎起摇晃落地头发角度全程 0（窗口拖动不驱动头发）；互动后衰减尾巴里每次路径切换都是单次穿越（只对应“互动尾巴结束”和“间歇轻摆开始/结束”），没有往返，所以**没加滞回**。真正原因是**窗口遮罩滞后**：遮罩最多 10 次/秒更新，落地压扁/回弹（sy 0.88→1.036）和拎起摇晃时轮廓每帧在变，最外沿像素被旧遮罩裁掉（160/200/320 高有被裁像素的帧 12/20/24 个，最多 21/282/1701 px）。修法：程序动作（`_program_active`：拖动/下落/跳/快速压扁）期间 V2 帧键变化就当帧重建遮罩，其余仍 10 次/秒（重建一次 P50 0.9～1.7ms，P95 ≤2.4ms）；修后三档被裁像素 0。逐帧对比在 `build/v3/integrate/s3/land/compare.md`。用户真实窗口确认不再闪。
- **测试**：新增 `tests/test_v3_gestures.py`（命中映射、捏脸/摸头/敲头/挠痒、拖动与点击、控制器台词与好感、新台词键、落地不裁像素、静止不每帧重建遮罩）；display 测试增加 30 FPS 开关。V3 与窗口相关（display、gestures、pet_window、touch_actions、motion_update、idle_life）65+174 条通过。全仓回归的 31 个环境相关失败不变，仍在 S7 建 junction 复测。
- 隔离启动用的环境变量同 S2（`SHION_DATA_DIR` 用 `build/v3/integrate/s3/data`，`SHION_PORT=47699`）。

#### 2026-11-09：S2 点穿遮罩、定位、改尺寸、换屏 DPR、性能优化，用户真实窗口验收通过

- **做了什么**：点穿遮罩按当前帧 10 次/秒更新并外扩 4px；气泡/菜单/面板按 V3 头顶锚点定位（与 V2 同位置同大小）；改尺寸与换屏 DPR 重建/复用渲染器（最多缓存 2 份）；帧间隔 16/33/66ms 分档，画面量化后没变就不重画；`tools/v3_perf.py` 在真实窗口里测 V2/V3 的 FPS 与 CPU，结果在 `build/v3/integrate/perf/`（`before-opt/`、`round1/`、当前为第二轮）。
- **外描边：已做、对比后用户决定不要，已整体移除**（`--v3-outline`、`outline` 参数、`add_outline`、`tools/v3_outline_compare.py`、相关测试）。选“移除”而不是“留函数不接入”：不接入的代码没有人维护和测试守护，还要多一个分支判断；需要时重做成本低（整数版算法见本次 S2 提交的 git 历史）。性能表和结论以无描边 v3 为准，`v3o` 行只作记录（旧 results.jsonl 里保留）。
- **踩过的坑 1：眨眼缓存。** `eye_scale` 是连续值，`HeadSurface.frames` 以它为键，眨眼的每一帧都未命中，整张头部重新合成 + LANCZOS 缩放约 45ms/帧，P95 因此很差。修法：`eye_scale` 量化到 0.05 一档（19 档，`shion/v3_prewarm.py`）；后台低优先级守护线程预热各表情睁眼帧和当前表情的眨眼帧，结果只在主线程写入缓存；缓存上限 24→64（`v3proto/surface.py` 唯一改动）；预热没好时先用最近的已缓存档位。
- **踩过的坑 2：待机头发常摆导致每帧走网格。** 待机时 6 缕头发一直在 ±2° 轻摆，而头部是一整张合成图，头发只能靠网格变形移动，只要任一头发角度非零就每帧跑网格变形（320@1.5 约 8～12ms/帧），待机 CPU 因此长期偏高；且无法用图层仿射代替（拆图层会在发缝露接缝）。
- **双路径方案**（`shion/v3_layers.py`）：头发静止（所有角度 round(角×10)==0）、无捏脸形变、无反应脸、无金星时走**仿射路径**（身体照旧 QPainter，头部用缓存帧整张平移/旋转，给 0.0001° 极小旋转避免 Qt 整数像素快速拷贝吞掉小数位移）；其余（头发摆动、捏脸、拍/敲/挠/拎起反应、金星）走原**网格路径**。待机头发改为**间歇轻摆**：每 6～12 秒摆一次、约 2.5 秒，0.6s 淡入淡出包络乘到 `sway_degrees` 上（互动时立刻满幅）。头发静止时待机 15 FPS、工作 20 FPS、睡着 15 FPS；眨眼与轻摆开始前后临时 30 FPS；头发在摆 30 FPS；互动 60 FPS。两条路径同姿态差：平均 <0.1/255，最大 ≤3（头转+躯干倾斜+整体旋转的极端组合最大 9，仅出现在拎起/挠痒尾声）。逐帧切换对比在 `build/v3/integrate/s2/switch/`。
- **新验收线**（用户 2026-11-09 确认）：互动 DPR1.5，160/200 ≥55 FPS 且计算+绘制 P95 ≤14ms；260/320 ≥50 FPS 且 P95 ≤20ms。待机：总 CPU ≤3% 且单核% ≤ V2 同尺寸同 DPR 待机的 2 倍。**工作场景 CPU 线改为：总 CPU ≤3% 且单核% ≤ V2 同尺寸同 DPR 的 idle 单核%**（V2 的 working 几乎不画，按 V2 working 比不现实）。320 lift、320 knock、200 lift(v3o) 超线幅度在测量波动内，判为通过（临界）。
- **结果**（真实窗口，无描边 v3；详见 `build/v3/integrate/perf/compare-round2.md`）：320@1.5 待机单核 54.6%（优化前）→50.0%（第一轮）→**17.8%**（V2 同档 22.0%），工作 51.9→48.5→**16.9**；待机全部通过，约 65% 的待机帧走仿射路径。工作场景有 2 项 v3 略超新线（160/DPR1 单核 8.52 vs V2 idle 7.42，200/DPR1 12.58 vs 11.43），超出 ≤15%；另有 2 项 v3o 记录行同样略超。未单独判定，随 S2 验收通过记录在案。互动 160/200 全部通过，260/320 全部通过或临界。第二轮只全测 idle/working（60 秒）并抽查 320@1.5 pinch/lift，其余互动沿用第一轮并在表中注明来源；V2/200/DPR1 的 pinch/tickle/lift 曾被手动拖动污染，不作对比依据。
- 测试：新增预热/量化/双路径/包络/帧率相关测试，`tests/test_v3_display.py` 全部通过；V3 与窗口相关（display、pet_window、windowing、v3_extract/reaction/slice）**201 passed、2 skipped**。全仓回归含 31 个环境相关失败（S1 干净检出同样失败：`test_process_sheets` 10 项缺 `assets/sprites/raw`、`test_install_hooks` 2 项缺 `.venv`、`test_connection_ui` 2 项，另有 `test_chat_remote_boundary` 15、`test_hook` 1、`test_pause_badge` 1 原因未确认），**S7 全仓回归前建 junction 复测并任务结束前单独解除**。
- 隔离启动用的环境变量：`SHION_INSTANCE_NAME`、`SHION_DATA_DIR`（`build/v3/integrate/s2/data*`）、`SHION_PORT`；用户验收了点穿、边缘点击、改尺寸、面板跟随、眨眼、头发间歇轻摆和路径切换。

#### 2026-11-09：S1 `--renderer v3` 入口与显示骨架，用户真实窗口验收通过

- `python -m shion --renderer v3`（运行与 `--snapshot`）用 V3 纸偶显示，默认仍为 V2，不写存档。新增 `shion/v3_display.py`（状态→V3 表情映射、纹理比例）与 `shion/v3_window.py`（`V3PetWindow(PetWindow)`，只换绘制，窗口属性/状态机/拖动下落/信号沿用父类）；`app.window_class()` 选窗口类。
- 映射：idle/working/neglect1/slump→neutral，happy/done/cheer→happy，proud→smug，stop→angry，dizzy→dizzy，neglect2→teary，yawn/collapse/sleep/bed/desk→sleep，drag→surprised，cheek_*→angry，tickle_*→happy；blink、jump_* 沿用底层状态表情。
- 尺寸：V3 可见身高对齐 V2 同档 idle（V2 不透明高度 480/512），窗口高度与脚底线相同；纹理比例 = 显示高度×DPR（320@1.5 为 0.32）。接触表与 V2 对照在 `build/v3/integrate/s1/`（`states-dpr1*.png`、`size-compare.png`、`metrics.json`）。
- 真实窗口用 `SHION_INSTANCE_NAME`、`SHION_DATA_DIR`（`build/v3/integrate/s1/data`）、`SHION_PORT=47699` 隔离启动，用户确认大小、固定表情、置顶与不抢焦点。
- 测试：新增 `tests/test_v3_display.py` 10 项通过；V2 窗口/截图相关 21 个文件 + V3 显示/镜像/原型：726 passed、5 skipped、2 failed。2 个失败在 `tests/test_connection_ui.py`，原因是 worktree 无 `.venv` junction（测试需 `<worktree>\.venv\Scripts\pythonw.exe`），与 S1 无关；**S7 全仓回归前建 junction 复测**。
- S1 限制（留给后续步骤）：手势仍是 V2 规则；遮罩只在状态切换时更新；固定 60 FPS 重绘；真实窗口 FPS/CPU 未测。

#### 2026-11-09：S5a 右侧鼓脸颊验证快照，用户验收通过

- 实测发现可见的脸画在刘海之上的脸部底板（face plate）里，只镜像 `head_skin` 几乎看不到效果，左侧还会露洞。实际做法：镜像 `head_skin` 和干净脸部底板（轴为两眼中线，`mirror_sum=1041`），鬓发上下顺序对调；旧左脸颊在发片里的残留用现有去描线遮罩（8 表情并集）清掉，露出垫底头发；刘海尖的原稿恢复避开新鼓脸颊区域。头发、刘海、花饰、发带、五官、身体不镜像。
- 捏脸接缝真因：右侧表情底板被放回了原底板位置，整体偏移约 34px，腮红一半落在脸颊贴图外（已修）。右侧 8 个表情的捏脸贴图统一取自镜像底板本身，表情只覆盖眼和嘴。修后右侧拉伸与左侧质量一致。脸颊外侧零星碎发描线仍在，桌面尺寸下不可见，用户决定不处理。
- 代码：新增 `v3proto/mirror.py`；`Rig(cheek_side='right')`；`Cheek` 在运动计算前后做坐标反射（姿态里的拉伸仍按左侧语义，外拉为负 x）；快照参数 `--cheek-side right`（仅快照）；对照工具 `tools/v3_mirror_check.py`，输出 `build/v3/integrate/mirror/{left,right}-contact.png`。左侧行为不变。
- 测试：新增 `tests/test_v3_mirror.py` 7 项；V3 相关 294 passed（日志 `build/v3/integrate/v3-all-after-mirror.log`）。
- **未做，归入 S5**：拎起倾斜方向随侧取反；窗口内鼠标命中、拉伸方向、换边时机与眨眼过渡。

### V3 第 0 步、第 1 步（已归档）

- 原型阶段（2026-11-05～11-09，`feature/v3-rig`）的完整记录已搬到 [progress-archive/2026-11.md](progress-archive/2026-11.md)。

### 2026-11-08 V2.2 真机验收与本地提交

- 用户确认通过：仅 Claude 聊天工作时，工作遥控整组置灰、tooltip 正确、无暂停标记；Claude 聊天与 Claude Code 同时工作时只暂停 CC，聊天仍显示工作中，气泡说明作用范围。
- 用户此前已确认连接成功、中文长任务自然触发通过。
- 未专测，转入日常使用中验证：多 CC 逐个继续、英日自然触发、英日气泡、断开后配置恢复。以上项目不记作本轮已通过。
- 下一步为日常使用中验证上述四项；若出现漏调、误暂停或配置恢复异常，按实际现象记录并修复。
- 本轮仅提交 V2.2 聊天联动、品牌/台词池、遥控隔离与对应测试和记录。工作区另有敲头/摸头动画改动，留待对应任务处理。
- 全量测试当前工作区：2344 passed、10 skipped、2 条既有 Pillow getdata 弃用警告，退出码 0，耗时 716.16 秒；日志在忽略目录 build/v22-acceptance-full-20261108.log。另用暂存版控制器运行聊天/配置/遥控/菜单/调度回归 192 passed，确认分片暂存后的控制器通过这些回归。暂存区 check_private.py 与 git diff --cached --check 通过。用户授权本地提交，不 push。

### 2026-11-08 遥控隔离修复开发包已替换，待人工验收

- 按用户授权使用当前未提交工作区构建目录包，依赖版本匹配，沿用 build_environment；bundle_smoke 110 项通过。打包版 Observer stdio 与上次响应相同且 stderr 为空；打包版聊天 MCP 隔离烟测与源码遥控边界回归共 29 passed。141 个构建输入文件在构建后哈希核对未变，现有 ZIP 哈希未变，未生成 ZIP。
- 新目录包 230 文件，新 exe SHA-256 为 00ce9f524ec3dc5451de5b25868e4446cd994704962cc83668e7b8e47db3ee7d。已原地替换 D:\desktop\tools\Shion-dev；旧目录保留为 D:\desktop\tools\Shion-dev-before-chat-remote-20261108。
- 用户先退出诗音本体，随后仍有 2 个 Claude 聊天 MCP、4 个 Codex Observer 占用旧目录。等待客户端自然退出后，后台替换器于北京时间 2026-11-08 11:05:34 完成两个目录改名，各一次成功，没有强制结束进程。
- 替换器核对旧目录、暂存目录、Claude/CC/Codex 配置哈希、联动开关及 ZIP；新安装和旧备份各 230 文件逐个哈希验证一致。用户重新打开本聊天后再次只读核对两份完整目录及安装 exe 哈希通过。配置哈希未变，v2_scheduler_enabled=false、claude_link_enabled=true；现有 ZIP 未变，未生成 ZIP。证据和最终状态 complete 在忽略目录 build/chat-remote-replacement-20261108/status.json。
- 本轮未改产品代码、未提交、未 push。真实客户端遥控隔离验收仍待新版安装后进行。

### 2026-11-06 V2.2 聊天与 CC 遥控隔离修复，待人工验收

- 用户真机发现只有 Claude 聊天活动时仍可点暂停，且会误设 CC 全局暂停。修复前查询实际运行实例的零等待检查点，返回 paused=false、stop=false：当时没有该次误点遗留的全局暂停，无需清理。暂停仅存于内存；旧版再次误点可在诗音里点“继续”解除。
- 工作遥控只以 CC 的实际工作、检查点等待、待授权判断可用性；无 CC 活动整组置灰（包括已结束轮次的继续），三语 tooltip 说明聊天无法从诗音暂停，应在 Claude 里点停止。暂停执行入口再次检查活动及目标，过期菜单不能为聊天或已结束的会话设置暂停。无 CC 活动的遗留标记在同步时解除。
- 并行聊天保留工作显示，CC 的暂停请求/检查点气泡三语说明只暂停 Claude Code，聊天仍在继续；聊天工作中时检查点标签/面板明确写 Claude Code，面板行只包含 CC。聊天 need_input 不进入 CC 授权队列，真实 CC 授权保持独立。
- 多会话回归另发现并修复：全局暂停后快速逐个继续，已放行会话在检查点 2 秒宽限期内仍被算作其他等待者，可能残留全局暂停；现在只把仍被暂停的等待者计入，全部继续后新 CC 检查点直接放行。
- 新增 28 项隔离边界用例，覆盖三语、静音/隐私、调度开关、先暂停后聊天、旧菜单、遗留标记、单会话/多会话/旧 hook、独立 CC 授权。菜单基线只刷新 21 个 menu_sha256，其余状态/计数/精灵字段逐项核对未变。遥控及调度相关回归 201 passed；补充边界与逐个继续回归 30 passed（有重叠）。全量首轮 2296 passed、10 skipped、1 failed、2 条既有 Pillow 弃用警告；唯一失败为旧“空闲时点好评”断言，已按整组置灰规则先建立 CC 活动，该用例包含在上述 30 项补测中，再次 --lf 复跑 1 passed，退出码 0。没有宣称重新跑过全量全绿。日志在忽略目录 build/chat-remote-*.log。
- 工作区全部 24 个修改/新增文件使用 check_private 的扫描器检查，0 命中；默认暂存区扫描及 git diff --check 通过。
- 待人工验收：①仅聊天工作时遥控全灰、tooltip 正确且不出现暂停标记；②聊天与 CC 同时工作时暂停 CC，聊天仍显示工作中，气泡说明作用范围；③多 CC 全部暂停后逐个继续，新 CC 检查点不会被卡住；④只有 CC 时暂停/继续/中断及真实授权仍正常。
- 本轮尚未打包或替换运行实例，未提交、未 push；按约定在人工验收通过后再本地提交。

### 2026-11-06 V2.2 开发包已替换，待人工验收

- 按用户授权，用当前未提交代码经 build_environment 构建目录包，依赖版本匹配，bundle_smoke 110 项通过。Observer stdio 与此前替换响应一致；聊天 MCP 初始化、工具列表、working / need_input / done 五个响应的隔离烟测通过，stderr 为空。
- 用户退出诗音后，旧包 Observer 仍由 Codex 占用；用户完全退出 Codex 后，后台替换器于北京时间 2026-11-06 07:13 完成两次目录改名。没有强制结束进程。新包与旧包各 230 文件逐个哈希核验一致，旧包保留为 D:\desktop\tools\Shion-dev-before-v2.2-20261106。
- 新 exe SHA-256 为 150cca18d385064a4e188d5297a1b9774e1d65ee7d784c8123bd9ba5df7153ff。配置哈希核对通过，存档开关 v2_scheduler_enabled=false、claude_link_enabled=true。既有 ZIP 哈希一致，未生成 ZIP。
- 证据在忽略目录 build/v22-replacement-20261106/。实际客户端聊天连接和三语自然触发仍待人工验收。按用户要求未提交、未 push。

### 2026-11-06 V2.2 步骤 2 实现，待人工验收

- 按用户要求更新品牌边界。三语关于页只保留诗音介绍，README 非官方声明保留。desktop_chat_working / need_input / done 从 UI 单句迁入台词池，三语每类两句，中文逐字采用用户给定文案，英文和日文同义翻译。复用 Lines.pick 连续去重。
- 新增「AI 连接 → Claude 桌面版」的连接、断开和个人偏好复制。探测 LOCALAPPDATA 的 Claude-Data 档案与 APPDATA 传统路径，但文件存在仅作提示。首次连接由用户通过 Claude 开发者设置的「编辑配置」确认实际文件并选择，须先从托盘完全退出客户端。本轮未验证自动判定活动档案，当前仍需手动核对文件。
- 配置事务复用步骤 0 的字节插入/删除思路：先创建独占备份，再核对原字节并替换，写后回读。原配置无后续变化时断开逐字节恢复；有其他变更时只删未修改的 shion 项；同名冲突、重复 JSON key、损坏配置及已改过的自身条目均拒绝覆盖。备份保留至断开成功，可恢复写入中断。比较与替换之间仍存在外部写入的短暂竞态，操作前必须退出 Claude。
- 三语 README 补充连接、退出重启、个人偏好、工具列表核验及漏调/超时限制。自动化测试隔离 LOCALAPPDATA / APPDATA，没有修改实际客户端配置。
- 验证：首轮全量 2251 passed、10 skipped、2 warnings，唯一失败为旧菜单断言，已修正。随后配置/台词/控制器/菜单/调度回归 195 passed，新增三语菜单操作与剪贴板复制 3 passed，配置与台词专项 50 passed。菜单基线仅更新 21 个 menu_sha256，其余字段核对一致。全量通过数不宣称已复跑全绿。
- 待人工验收：①三语菜单与 working/need_input/done 气泡，每类随机切换，静音与隐私模式；②在隔离测试配置验证连接、退出重启、客户端工具列表和 MCP 上线；③断开后重启，条目消失且其他配置保留；④英日偏好分别做一个长任务与一个短问答，need_input 单独显式调用。真实配置操作应在验收时单独确认范围。
- 当前未提交、未打包、未部署、未 push。按 CLAUDE.md 在人工验收通过后再更新验收结论并本地提交。

### 2026-11-05 V2.2 步骤 1 人工验收通过

- 正式 `--chat-mcp` 已接入“Claude 聊天”观察来源。沿用探针工具说明和 instructions；初始化上线、stdio 关闭下线。工具通知最多等待 0.4 秒，通道失败仍向 Claude 返回成功。任务等待 15 分钟后静默回空闲。
- 最终全量测试 2252 passed、10 skipped、2 warnings。首次演示包因 QtCore DLL 加载失败而提前退出；按项目净化构建环境重新打包后，通过离屏截图及真实窗口演示。
- 在隔离存档中用同一测试 EXE 启动桌宠和 MCP，正常、隐私两遍均依次显式调用 working、need_input、done，再关闭 stdio。用户确认气泡、等待与完成提醒、隐私隐藏任务名的表现通过。真实 Claude 配置未改动。
- 下一步为步骤 2 方案 A：实际配置探测、受保护的连接与断开、菜单、三语个人偏好及复制。英日译文的自然触发各测一个长任务和一个短问答；need_input 仅作显式验收。

### 2026-11-05 V2.2 步骤 0 最后一轮：Claude 个人偏好

用户在个人偏好中保存原句：“做需要用工具或耗时较长的任务时，开始前先调用 shion_working，完成后调用 shion_done；简单问答不用调用。”沿用上轮同一探针。每题新开聊天，用户报告任务结果及弹窗情况，按每题起止的 JSONL 字节位置核对工具调用。

| 模型 | 第 1 题联网、第 3 题运行代码并绘图 | 漏 working / done | 第 4 题算术、第 6 题常识 | 误调 |
| --- | --- | --- | --- | --- |
| Sonnet 5.5 | 2/2 均依次调用 working、done 各一次 | 0 / 0 | 两题均无调用 | 0 |
| Opus 5.5 | 2/2 均依次调用 working、done 各一次 | 0 / 0 | 两题均无调用 | 0 |

八个有效用例均无确认弹窗，共收到八次工具调用。Sonnet 第 3 题首次执行时用户误删了偏好规则，该次无调用，单列为排除样本；表中计入恢复原句后的重测。首次实验中 Sonnet 的两个无偏好长任务均漏调，本轮有偏好时四个长任务均完整调用。两轮之间做过显式调用授权，题目也有差异，无法把改善单独归因于偏好。日志证实 working 在 done 之前，未独立测量它们相对实际工具执行或最终回复的精确时点。本轮未覆盖 need_input。

收尾时确认 Claude 已完全退出，实际配置按本轮登记前的备份逐字节恢复，SHA-256 一致（`23b8e2d6…55d28`）。已核验配置中无 shion-probe，剩余聊天探针进程为 0。此轮仅更新实验记录。

### 首轮探针与原有进度

- **2026-11-05 V2.2 步骤 0 探针实验收尾（本地提交，不 push）**：固定使用用户报告的 **Sonnet 5.5**。探针进程及客户端工具列表确认可用后，实际联网答复、生成 PPT 文件两个长任务均无自动调用：自动调用覆盖 **0/2**，漏 `shion_working` **2 次**、漏 `shion_done` **2 次**，共 **4 个预期调用缺失、影响 2 个任务**。最初写错配置位置的尝试排除在这两个有效样本之外。连续两次未调用后缩短测试，第三个长任务和三个短问答未执行，故**短问答误调次数未评估**，`shion_need_input` 自然调用亦未验证。随后单独做显式连通对照：用户报告出现确认弹窗，日志实际收到 working（task 为“连通测试”）和 done，各一次，证明通路可执行；这次不计入自然调用成功率。两例说明当前原文 instructions/工具说明不能作为可靠自动联动的验收依据，不外推为模型永远不会调用；也未验证授权后的后续自然调用是否改善。说明原文未改，未继续开发步骤 1/2。
- **V2.2 安装调研结论**：优先建议方案 A，且必须先探测实际配置位置。[MCPB 规范](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md) 将 binary 描述为自包含程序；[官方校验器](https://github.com/modelcontextprotocol/mcpb/blob/main/src/node/validate.ts) 检查包目录下的 entry_point 文件存在。[配置生成源码](https://github.com/modelcontextprotocol/mcpb/blob/main/src/shared/config.ts) 允许 command 使用用户配置变量，说明外部路径可以被表达，但不能据此证明 Claude Desktop 接受不带包内入口的 binary 扩展。方案 B 按携带入口程序与依赖评估；“只指向已安装 Shion.exe”的标准支持尚未证实。本步只查资料，未制作或安装 .mcpb。

- **V2.2 实现与验证**（`feature/v2.2-chat-mcp`，从本地 `master` 派生）：新增仅写本地 JSONL 的 `--chat-mcp` 探针，三个工具及 instructions 使用用户给定原文；源码和打包版均不加载 Qt、不连接诗音，task 原文保留，schema 标注 20 字但探针允许记录超长字符串。16 项专项、整包自检 110 项、移除 Qt 副本的 stdio 验证通过；全量复跑 `2247 passed, 10 skipped, 2 warnings`，直接记录 Python 退出码 0。前一轮相同通过数但外层退出码 1，原因未查明；默认临时目录权限失败的初次测试也保留在忽略目录日志中。仅生成独立测试包，未替换已安装 Shion。
- **V2.2 配置恢复已核验**：本机实际配置位于 `%LOCALAPPDATA%\Claude-Data\claude_<后缀>\claude_desktop_config.json`，不在原先假设的 `%APPDATA%`；**一键连接必须先探测实际使用的配置文件**。安装前确认无 Claude 进程，备份后仅按字节插入 `mcpServers.shion-probe`，其余字节不变。实验结束后用户完全退出 Claude，再次确认无进程；实际配置恢复后的 SHA-256 与原始备份完全一致（`23b8e2d6…55d28`），无需合并并发内容，探针条目已移除。旧 `%APPDATA%` 临时配置此前已按哈希撤回，目前仍不存在。已有 mcpServers 合并、BOM/空白/转义保留、并发新增项保留及拒绝删除被改过的探针条目均通过隔离验证。备份、原始日志、配置事务和测试包只保存在本机/忽略目录，不入库。
- **V2.2 下一步**：本轮按缩短样本结束步骤 0 实验，未满足原定 3 长 + 3 短完整验收，不开始步骤 1/2；如继续研究，应另行验证首次授权后自然调用是否改善，以及短问答误调、need_input 与不同模型的表现。真实客户端重启后的卸载观感未验证，配置恢复已按字节核验。

- V2.1 基线分支 `master`（本地 V2.1 开发）；v1.0.1 hook 延迟热修、调度 GUI 审查修复、菜单 Claude Code 标名和 v2.0.0 发布前安全修复均已合并。2026-11-01 已替换本机 Shion-dev 开发预览包（安全修复版）；未 push、未发布，默认关闭的调度能力不等于已启用或完成人工验收。
- 阶段 1 v3 全局安装已完成，MCP 与七项无 matcher Hook 保留；已安装 Shion-dev 更新为菜单标名开发包（替换记录核验 228 文件）。替换记录确认配置哈希未变，旧包保留为 `Shion-dev-before-menu-label-20261030`；阶段 1 仅部分通过人工验收。旧会话 Observer 异常退出后自动恢复未证明，新开 CLI 会话恢复已有证据。
- 阶段 2 P1～P5 核心、2 秒心跳/10 秒租约及 GUI 适配已完成隔离开发。`v2_scheduler_enabled` 默认 false，没有普通用户菜单开关；ChatGPT 仅观察，无控制入口；Claude 原授权/暂停/继续/中断保留。真实 Claude 缺可靠 turn_id，真实前台缺完整任务绑定，生产端缺可信 coverage；完整身份与仲裁能力仍主要是合成证据。Work 未开发。
- V2.1 第 2 步本轮全量（2026-11-03，修正前）：`1 failed, 2147 passed, 9 skipped, 2 warnings in 643.42s`，日志 `build/stamina-full.log`。唯一失败是旧安装提示测试使用不存在的示例程序路径，被新增安装前校验拒绝；已改用有效路径，单独及后续专项复核通过。不是全量全绿；后续改动按下方专项/打包验证记录，未再次全量。较早的中断时序、ZIP 替换失败记录保留在各日摘要，不视为已修复。
- 分支 `feature/menu-claude-label`（从 `4c4db02` 派生，功能提交 `81b8361`，交接提交 `a4edba0`）已快进合并到当前分支，分支保留、未 push；菜单标名已随本次 Shion-dev 开发包替换部署，详见下方 2026-10-30 记录。
- 分支 `feature/menu-parity`（从 `dc9fe3d` 派生）：右键菜单 Claude Code / ChatGPT 连接管理对齐，并新增 Claude 的“临时关闭联动”。未合并、未部署、未 push；本分支全量结果见下方 2026-10-30 记录。
- 分支 `feature/remove-codex-autolaunch`（从 `fad0e3a` 派生）：删除 Codex 新开会话自动拉起诗音，保留 Claude 拉起、单实例互斥锁和 Codex 窗口层级跟随。未合并、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/remove-face`（从 `5062919` 派生）：删除“朝向鼠标”动作并停用 turn 帧，待机动作只剩小跳 : 表情 = 1 : 2。2026-10-31 已快进合并到当前分支并部署到 Shion-dev，分支保留、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/per-session-remote`（从 `5062919` 派生）：工作遥控四个按钮按会话区分，多个会话同时停住时用检查点面板分别继续/结束。2026-10-31 已合并到当前分支（合并提交 `7abd815`）并部署到 Shion-dev，分支保留、未 push，详见下方 2026-10-31 记录。
- 分支 `feature/session-labels`（从 `e5fee12` 派生）：同一项目多个会话时，工作遥控菜单和检查点面板用各会话的第一句话摘要区分。2026-11-01 已快进合并到当前分支（`4ecaaaa`）并部署到 Shion-dev，分支保留、未 push，详见下方 2026-11-01 记录。
- 2026-11-01 本机 Shion-dev 先替换为 `4ecaaaa` 的开发包（旧包 `Shion-dev-before-session-labels-20261101`），同日再替换为 `b016547` 的安全修复开发包（220 文件），旧包保留为 `Shion-dev-before-security-20261101`。
- 分支 `feature/v2-security-fixes`（从 `1500086` 派生）：v2.0.0 发布前审查的 3 条应修 + 2 条小问题和复审第二轮（hook ↔ 服务端令牌、令牌绑定诗音进程、独占绑定、ChatGPT 状态显示时效、按会话中断共用进程保护、prompt_head 读不到存档不发）。2026-11-01 已快进合并到当前分支（`f8ec0a6`），之后追加 bundle_smoke 修正 `b016547`；worktree 已移除，分支保留、未 push，详见下方 2026-11-01 记录。
- 2026-11-01 v2.0.0 发布准备（2026-11-02 已快进合并到本地 `master`、打包、打本地标签；未 push、未发布）：版本号改为 2.0.0；三语 README 补 ChatGPT 只读观察、临时关闭联动、AI 连接菜单新结构、工作遥控选会话、同项目第一句话区分、诗音没开时不拖慢 CC、已知限制和隐私说明；新增 6 张菜单截图；发布说明在忽略目录 `build/release-notes-2.0.0.md`。详见下方 2026-11-01 记录。2026-11-02 追加：ChatGPT 未安装时顶层只显示“ChatGPT：未安装”、子菜单活动显示“—”；6 张菜单图改为原生 Windows 11 风格重新渲染。详见下方 2026-11-02 记录。
- 公开稳定版为 **v2.2.0**（2026-11-11 发布，标签指向 `e974526`）：https://github.com/iLLyaaaaaa/shion/releases/tag/v2.2.0 ；上一版 v2.1.0（2026-11-04，标签指向 `ca9df3f`）；更早 v2.0.0（2026-11-02，标签指向 `0034dbb`）、v1.0.0；私有备份仍含旧历史。历史改写后的哈希以当前 Git 为准，旧报告的失效哈希仅作决策记录。
- **2026-11-04 V2.1 发布前收尾**（`master`，本地提交、未 push）：①周报 token 标签三语改为 Claude Code 口径（en 输出格缩成 `CC OUTPUT`，否则被截断），有 7 天额度时额度行旁加小字“含聊天等全部用量”（`weekly_quota_note`）；`test_lines` 把 `weekly_total/weekly_output` 列为允许出现 Claude Code 的文案。②statusLine 串联：原命令成功（返回码 0 且有输出）后把输出原子写入 `%APPDATA%\Shion\statusline-last.bin`，超时/失败/异常时输出这份缓存；断开连接时删除缓存和内容为 `{}` 的记录文件。这也缓解了“没有 Git Bash 的机器首次刷新丢状态栏”的边界。③`UsageScanner.scan` 扫描后移除缓存里已不存在的 jsonl 条目。④`tools/make_media.py` 输出路径 relpath 跨盘抛 ValueError 时退回绝对路径。⑤周报统计格默认高度 124→118，柱状图高度上限 320→520，多出的空白归柱状图（预览数据里没有富余，版面不变）。全量 pytest：首轮 `3 failed, 2207 passed`（失败均为上述文案规则测试，已改），改后 `test_lines` 全过。下一步：从新提交打包到暂存目录并挂等待替换（见下方记录）。

- **2026-11-04 V2.1.0 发布准备第 0 步：7 天额度最后已知值**（本地提交、未 push）：存档可选字段 `seven_day_last = {value, resets_at, at}`（无会话标识），收到未过期 seven_day 即更新，数值/重置时间变化或满 10 分钟才写盘；双击状态的 7 天行改用它，超过 5 分钟附“（N 分钟/小时/天前）”，过 resets_at 隐藏；5 小时额度仍只用内存新鲜值，不按 token 推算（spec 已写原因）。原测试“7 天值 73→70 不写盘”改为写盘但不重绘周报。全量 `2214 passed, 8 skipped`，日志 `build/v210-step0-full.log`。下一步：版本号 2.1.0、配图、三语 README、发布说明、审查。

- **2026-11-04 V2.1.0 发布准备：版本号、配图、README、发布说明、审查修复 A–G**（本地提交、未 push）：版本号改为 2.1.0（exe 版本资源 2.1.0.0）；`make_media.py` 新增周报卡片和体力四档两组合成图（三语，隔离目录生成，旧 7 张不变）；三语 README 新增「诗音周报」「体力」两节，并更新 statusLine 接管、隐私、已知限制、卸载；发布说明写在 `build/release-notes-2.1.0.md`。reviewer 和安全审查之后，用户选择修 A–G：A shell 查找不搜 cwd（Windows 的 `shutil.which` 会先查当前目录；PowerShell 固定用 System32 里那个，`CLAUDE_CODE_GIT_BASH_PATH` 必须是绝对路径）；B statusLine 被改过时也能断开（hooks 照删，别人的 statusLine 原样保留并提示，损坏的记录改名成备份）；C 称号表坏了用内置兜底；D 原命令放进 Job Object，超时时整个进程树一起结束，输出上限 64 KB；E 缓存按项目目录哈希分开，失败时删 tmp，断开后不再写回，断开时全部清掉；F 单个 jsonl 读不了就跳过（保留旧统计），读到一半出错整次放弃、不写缓存；G 精确识别诗音自己的 statusLine。H–K（备份累积、扫描整份复制、probe_chat 本地日志、每次刷新新进程）留到以后。
- **2026-11-04 v2.1.0 已发布**（用户同意后推送）：`master` 快进 `22282d4..ca9df3f`，注释标签 `v2.1.0`（`dfb95fa` → `ca9df3f`），Release「Shion 2.1.0」为 Latest，附件 `Shion-2.1.0-win64.zip`（46369115 字节，SHA-256 `a59c1c5b…8f925`），说明来自 `build/release-notes-2.1.0.md`。推送前检查：范围内 15 个提交与标签的邮箱均为 noreply；正则扫描整段 diff，无密钥或个人信息（未装 gitleaks）；无大文件；`ls-files -ci` 为空。全量 `2233 passed, 8 skipped`，bundle 自检 110 项通过，exe 版本 2.1.0。远端核对：`ls-remote` 的 master 与本地 HEAD 一致；仓库 Public，默认分支 master；远端文件列表与本地 `ls-tree` 完全一致（262 个文件）；重新下载的附件 SHA-256 与本地一致。`gh release create` 第一次返回 HTTP 500，核实没有残留的半成品 Release 后重试成功。
- 下一步由用户决定：H–K 优化；从 2.0.0 升级后重新连接，并在真机验收 statusLine 串联（含超时结束进程树、按项目缓存）；桌面版撞限额倒地仍缺真实样本。
- 踩坑：`taskkill /T` 每次约 1.2 秒，状态栏等不起，改用 Job Object；`cmd /c` 遇到 `list2cmdline` 产生的 `\"` 会解析错，进程树测试只用不带空格的路径。

### 本分支提交现状（相对本地 master，按拓扑日期顺序）

| 提交 | 当前作用与状态 |
| --- | --- |
| `e6e3865` | 全局生命周期观察 MVP；已由后续精简方案、事务修订及租约扩展演进 |
| `fe78a25` | 全局安装审查基线记录，保留历史边界 |
| `5dc9eda` | 精简安装、便携 MCP；替代独立 ACL 存储方案 |
| `c847994` | 安装事务、Hook 信任变化保留及精确卸载加固 |
| `c6889c3` | Observer 租约与独立多任务调度核心，已接开发 GUI |
| `ce732f2` | Windows ACL 继承规范化测试修复，已保留 |
| `a55825f` | 菜单整合与默认关闭的 GUI 接入，后续审查修复已应用 |
| `1f54cb6` | hook 未运行快速退出与连接熔断热修；已由合并提交接入 |
| `ef1149a` | 观察空档恢复、中性待机、Claude 独立连接行、切换与冲突降级修复 |
| `3548f23` | 原阶段 1 待验收记录保存；本次原样转入月度归档 |
| `c0e7482` | 合并热修；隐私扫描冲突和进度记录冲突已解决 |
| `9ba3e66` | 合并验证与逐提交隐私补扫报告，现迁入 experiments |

详见 [核心](experiments/shion-v2-phase2-core.md)、[GUI](experiments/shion-v2-phase2-gui.md)、[审查修复](experiments/shion-v2-scheduler-review-fixes.md)、[热修合并与隐私补扫](experiments/shion-v2-merge-hotfix-report.md)。旧热修提交 `1f54cb6` 的虚构目录测试字面量曾被新扫描规则命中；合并版已修正，未改写历史，不宣称历史每个快照都扫描通过。

## 正在进行的阶段与下一步

- **2026-11-03 V2.1 周报真机验收问题修复（用户验收真实数据预览通过，本地提交，不 push）**：窗口按实际尺寸直接重绘、深色按钮、默认上周可切本周、本周进行中不评称号、摸鱼周改按 token 天数、空计数提示、数字取整、`<synthetic>`/全 0 不计未计价。详见下方 2026-11-03 记录；真机观感按清单验收。
- **2026-11-03 V2.1 第 2 步开发完成（代码及合成预览已验收，本地提交，不 push）**：statusLine 串联、配置原值恢复/冲突保护、认证额度接口、终端四档与 hook 两档、状态气泡和周报额度峰值已接通；沿用现有替代图。第 1 步已提交 `6d6801f`，未 push。第 2 步计划、代码和合成预览均已获用户确认；本轮只用隔离 HOME / APPDATA / CLAUDE_CONFIG_DIR 与合成数据，未读真实对话，未修改真实配置或替换已安装 Shion-dev。用户已授权本地提交；下一步由用户安排真实接入验收或第 3 步新图，不自动改配置、部署或开始新步骤。
- 当前是阶段 2 开发预览、阶段 1 人工验收暂缓；暂缓不阻塞独立开发，也不代表阶段 1 全部验收通过。
- **v2.0.0 已发布（2026-11-02）**：https://github.com/iLLyaaaaaa/shion/releases/tag/v2.0.0 ，详见下方发布记录。原定的三项发布前人工专测（立即中断后工具进程是否结束、Codex 配置断开再重连、真实干净环境解压运行）没有做，改为**发布后日常使用中验证**；Codex 配置的安装/卸载/冲突已有隔离自动测试，但不代替真实 Codex 客户端里的断开再重连。
- 下一步由用户决定：日常使用中留意上面三项和下方清单；`test_real_process_tree_is_terminated` 满载时失败的根因仍未确认。
- 更正（2026-11-01 核对 `git branch --merged`）：`feature/menu-parity`、`feature/remove-codex-autolaunch` 均已在当前分支历史里，上方“未合并”的描述已过时；`feature/remove-face`、`feature/per-session-remote` 已合并并部署，真机验收按下方清单在日常试用中进行。
- 普通用户开关开放前，先处理下方全局 `ledger.uncertain` 恢复遗留；不得用心跳、重复包或新 turn 结束推断旧任务成功。真实身份、前台绑定、coverage 和人工权限能力必须各自有证据。（更正 2026-11-01：这个粘滞标志原先也让默认配置下的 ChatGPT 菜单“活动”一直显示“待确认”，不只影响调度器；`feature/v2-security-fixes` 已给显示层加时效，调度器语义仍是遗留。）
- `feature/v2-security-fixes` 已合并并部署到 Shion-dev；bundle_smoke（99 项）和隔离实例验证已通过，剩余真机项按下方清单在日常使用中验收。

## 未完成的人工验收清单

以下是当前交接清单；历史原文中的 125 条未勾选明细全部留在月度归档（包括后续版本已取代的旧方案/旧计划，不自动改勾）。需要执行某项时用 `rg -n '关键词|\[ \]' docs/progress-archive/2026-10.md` 定位对应小节，并以最新实现为准。

V2 进入日常试用阶段，人工验收以日常使用中的反馈为主；平时碰不到的项目（立即中断后工具进程是否结束、Codex 配置断开再重连、干净环境解压运行）原定发布前专测，v2.0.0 发布时未做，改为发布后日常使用中验证。

- [x] V2.1 第 2 步代码及合成预览（2026-11-03 用户确认通过，可本地提交，不 push）：statusLine 串联与恢复保护、体力隔离路径、四档替代图/三语台词、双击状态行、周报额度峰值行。
- [ ] V2.1 第 2 步真机动态观感：延后播报与复活跳跃、授权期间临时站起、双击状态行及不同 DPI；代码与合成预览验收不代替这些真实体验。
- [ ] V2.1 真实接入：先审阅实际 settings 差异再授权安装，确认已有 statusLine 输入/输出、冲突拒绝与断开恢复；本轮未改真实 settings。（2026-11-03 已在副本上 dry-run 出连接差异给用户审阅，见下方记录；尚未授权连接。）
- [x] V2.1 周报外观（2026-11-02 用户确认）：v3 三语卡片、日文比例字形、标签/数字基线对齐、价格右栏、柱图区分隔与首末日标注；按用户可选要求追加 Yu Gothic UI / Medium 字重，新快照 `build/weekly-ja-ui-medium-v4.png`，授权的小改已完成。真实窗口/导出仍按下项人工验收。
- [ ] V2.1 周报真机（2026-11-03 修复后）：窗口高度约为屏幕可用高度 85%、实时重绘清晰度、深色按钮观感、默认打开上周、窗口内上周/本周切换、窗口显示不抢焦点、主动点击后 Esc 关闭、不同 DPI/屏幕定位、保存 PNG / 复制粘贴观感、统计用量/署名开关。
- [ ] V2.1 周报真机：周一或之后首次启动的提醒，必须在问候与连接引导结束、无授权或输入面板时出现；点击查看上一周。本轮仅合成/隔离验证，未部署 Shion-dev、未重扫真实对话。
- [ ] V2.1 桌面 hook 两档体力：Code 标签页真实撞限额时是否触发 `StopFailure.error=rate_limit`，额度等待后自动继续时是否触发 `Notification.notification_type=quota_auto_resume_fired`；确认倒地/复活只改变待机，不影响授权、暂停、继续和中断。已通过合成路径和权限优先级测试，尚无桌面真实触发样本。

- [ ] 阶段 1：修复后桌面普通任务的完整生命周期、真实故障画面、活动中断连；原会话自动恢复或明确的恢复边界。
- [ ] 人工权限长等待、实际 PermissionRequest 语义；工具执行中 Interrupt 后工具进程及时终止。现有视觉“轮次 0、无异常”和官方 turn interrupted 不等于工具被及时终止。
- [ ] 两个现有项目真正并发、GUI 会话辨别（顺序 CLI 已通过，但短 ID 曾碰撞）；Claude/ChatGPT 并行隔离及桌面重连/观察开关的完整链路。
- [ ] 真实卸载/恢复、安装事务完整用户流程与长期附加延迟；62 次正常 Hook 样本不足以代表长期性能。
- [ ] 阶段 2：完整真实身份、前台任务绑定、可靠人工请求及 coverage；当前合成 GUI/Qt 截图不代替真实客户端、焦点、多屏或动态观感验收。
- [ ] 热修真机：诗音关闭时 hook 等待改善、运行时无回退、自定义端口分支；`find_cc_process` 和服务端协议进一步优化未做。
- [ ] v1 系列遗留：图标/README 媒体观感、ZIP 解压启动、干净无 Python Windows、杀毒表现；本任务不打包。
- [ ] v1 桌面交互：Win+D 恢复、置顶与附属面板避让、透明区点穿、不抢焦点、多屏/高 DPI、四档尺寸、动态动作及爱心/Z/睡眠观感。
- [ ] v1 Claude 实际联动：授权自动收起、暂停/继续、中断文字与工具分支、超时/静音、终端草稿与确认框保护、桌面复制“继续”、连接迁移不重复事件和登录自启。
- [ ] 三语菜单/台词/气泡、对话数字键与焦点、每日额度/时段问候/等级与存档迁移；逐项条件见归档，自动化通过不能替代用户观感。
- [ ] 菜单对齐与临时关闭联动（`feature/menu-parity`）：真机右键看两个子菜单的结构、截断与 tooltip；Claude 临时关闭后真实 CC 的授权框、停下中的 hook、反馈注入与重新开启的表现；离屏渲染和合成测试不代替真机。
- [x] Claude 临时关闭联动（2026-10-31 真机通过）：关闭时不弹面板、交回 CC 授权框；重新开启后授权面板同意/拒绝生效。
- [ ] 菜单标名（`feature/menu-claude-label`）：真机右键看顶层“Claude Code：…”状态行，以及“AI 连接 › Claude Code › / ChatGPT ›”两个子菜单的展开位置、宽度和 tooltip（高 DPI、多屏）；离屏渲染截图不代替真机观感。
- [x] ~~Codex 自动拉起（`feature/codex-autolaunch`）~~ **已取消（2026-10-31）**：功能已在 `feature/remove-codex-autolaunch` 删除，不再验收；Codex 用户改用“开机自启”。原因（Codex 的 KILL_ON_JOB_CLOSE Job）见下方记录和 spec.md 末节。
- [x] Codex 不再自动拉起（2026-10-31 真机通过）：诗音没开时新开 Codex 对话，诗音不出现，Codex 正常工作。
- [ ] Codex 窗口层级跟随（`feature/codex-autolaunch`）：关闭“置于最上层”后，Codex 桌面端窗口在前台时诗音浮在其上方且不抢焦点；在 Codex 里临时关闭 ChatGPT 联动或未安装联动时不再跟随；终端窗口（Windows Terminal 等）前台时不跟随；Claude 桌面端跟随不变；高 DPI/多屏观感。
- [x] Codex 桌面端窗口层级跟随（2026-10-31 真机通过）：未置顶时诗音浮在 Codex 窗口上方，其他程序照常遮挡。
- [ ] 单实例互斥锁（`feature/codex-autolaunch`）：多个 Claude 会话同时新开只剩一个诗音；Claude 临时关闭联动后新开 CC 会话不拉起诗音（源码版与打包版各验一次；原属上面已取消的条目，Claude 侧保留）；旧版诗音（无互斥锁）运行时新版不会重复启动；诗音被强制结束后能正常重新启动；退出后再启动正常。
- [x] 单实例互斥锁（2026-10-31 真机通过）：同时新开两个 CC 会话只出现一个诗音。
- [ ] 工作遥控按会话区分（`feature/per-session-remote`），日常试用时留意：只开一个 CC 会话时右键菜单和以前一样；开两个项目同时工作时，“停下 / 立即中断 / 做得好 / 有问题……”展开成子菜单，名称是项目文件夹名（同名带“(2)”，隐私模式显示“会话 1 / 会话 2”）；停下 A 时 B 继续干活；A 停住时暂停标签写“暂停中：A 的文件夹名”，在 A 的 CC 里说话只放开 A；两个都停住时出现检查点面板，可分别“继续 / 结束这一轮”，面板不抢焦点、出现后 0.6 秒内点击无效；“做得好 / 有问题……”只在选中的会话下一次工具调用时注入，选“全部”时每个会话各收到一份、好感度只加一次。
- [ ] 会话第一句话区分（`feature/session-labels`）：同一项目开两个 CC 会话并各说一句话，工作遥控子菜单显示“文件夹名 · 第一句话前 12 字…”；只开一个会话时仍只显示文件夹名；诗音启动前就开着、还没说话的会话显示原来的“(2)”编号；开隐私模式后显示“会话 1 / 会话 2”，关掉后不再出现之前的摘要；长名字被截断时鼠标悬停看到全文（高 DPI、多屏）；检查点面板的名字一致。
- [ ] 发布后日常使用中验证（按会话中断，原“发布前专门验收”）：两个会话都在跑长命令时只中断 A，A 的工具进程结束、B 的不受影响；选“全部”时两边都结束。

- 发布前安全修复（`feature/v2-security-fixes`，已部署 Shion-dev `b016547`）：
  - [x] 1. 启动后数据目录出现 `claude-link.json`，正常退出后消失（**隔离实例自动验证**，2026-11-01：打包版隔离实例 + WM_ENDSESSION 正常退出；真实 Shion-dev 启动后也确认文件存在）
  - [ ] 2. CC 里授权面板同意/拒绝、停下/继续、做得好/有问题照常（日常使用验收）
  - [ ] 3. 诗音没开时 CC 不卡、不弹面板（日常使用验收）
  - [x] 4. 诗音被强制结束、`claude-link.json` 留下后，hook 不采用旧令牌、交回 CC 自己处理（**隔离实例自动验证**，2026-11-01：强制结束隔离实例、伪造已不存在进程号的令牌两种情况，hook 均不发请求、占端口 socket 0 连接）；真实 CC 里“再启动诗音后联动恢复”的观感仍在日常使用中留意
  - [x] 5. 47613 被占时诗音不写 `claude-link.json`、日志有警告，hook 不给决定、不连占端口者（**隔离实例自动验证**，2026-11-01）
  - [ ] 6. ChatGPT 菜单“活动”几分钟后不再一直显示“待确认”（日常使用验收）
  - [ ] 7. 两个独立终端各一个 CC 会话，“立即中断”只选其一：只有被选的停下（日常使用验收）
  - [ ] 有条件时：用户目录经 junction 搬过家的机器上联动正常；令牌写不进去时诗音会说“联动凭据写不进数据目录……”（难以手动制造，可跳过）

- [ ] 删除朝向鼠标（`feature/remove-face`）：右键“动作”只剩跳一跳 / 去睡觉 / 趴一会儿（三语）；普通/活泼档待机时不再出现侧身，只有小跳和开心/发呆表情，表情明显多于小跳；旧存档正常加载。

## v1.1 待办
- [x] hook ↔ 服务端令牌认证 + `SO_EXCLUSIVEADDRUSE`（安全审查建议）：`feature/v2-security-fixes` 已实现、合并并部署 Shion-dev（2026-11-01），剩余真机项见验收清单
- [x] hook 耗时：诗音没开时的等待已在 v1.0.1 热修里去掉（见当前状态）。诗音运行时 PreToolUse 仍约 354 ms（源码）/ 435 ms（exe）：主要是进程启动，`find_cc_process` 只占约 26 ms；是否继续降另议
- [x] V2.1 第 0 步 statusLine 探测：桌面版不运行（现有/新会话均无记录），终端 rate_limits 在首条回复后出现；四档体力仅终端可用，桌面采用 hook 两档，真实触发见人工验收项。
- [ ] 接入 GPT / Codex
- [ ] 后续候选：Claude 桌面版聊天连接/断开前检测 Claude 桌面版是否在运行并提醒（v2.2.0 审查第 4 条，本次不做；目前只靠弹窗、README 和发布说明提示先完全退出 Claude）
- [ ] V2.1 候选：Codex 控制能力。实验结论：授权可行（异常时交回 Codex 自己处理，桌面端未测）；停下只能做到"检查点暂停 → 继续"；中断目前不可行。详见 docs/experiments/shion-v2-codex-control.md。

- [ ] **开关对用户开放之前**：缺身份、来源冲突或容量耗尽导致的全局 `ledger.uncertain` 也要加恢复条件或时效（审查遗留）。ChatGPT 菜单显示已在 `feature/v2-security-fixes` 加 600 秒时效（`TaskLedger.uncertain_at`）；调度器 `scheduler.py` 仍读粘滞标志，这一条仍未完成。
- [ ] ChatGPT 观察端凭据 `chatgpt-observer.json` 的读写仍走 `observer_files.reject_reparse`（检查所有上级目录）：用户目录在 junction 下时 ChatGPT 观察会报错。Claude 联动令牌已在 `feature/v2-security-fixes` 改为只查最后两层；观察端涉及 Codex 配置事务和 ACL 审查，未在该分支改动（范围外发现）。

## 最近几天的记录（摘要，完整原文见月度归档及专项报告）

- **2026-11-04 用发布提交 `ca9df3f` 重新打包并替换 Shion-dev**（证据在忽略目录 `build/v210-replacement-20261104/`，沿用 `v21-final-replacement-20261104` 的脚本，只改目录名、对比基准，并新增前置检查）：
  - **打包**：工作区干净，相对 `ca9df3f` 只差不进包的 `docs/progress.md`（打包不读 git、不含 docs），依赖版本一致，不生成 ZIP。新包 230 文件，exe `66a1bc8c…dfd78d890`。
  - **验证**：bundle_smoke **110 项通过**；观察端 stdio 烟测通过，响应与早上那次替换完全一致。
  - **替换**：替换器等用户退出诗音后原地替换，两次改名均一次成功。旧包（`1869f53` 版，exe `446ef22d…a17650a3`）230 文件逐个核对后保留为 `D:\desktop\tools\Shion-dev-before-2.1.0-20261104`，新目录 230 文件逐个核对一致。
  - **未变**：Codex / CC 配置哈希与任务开始时一致；存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true`；`Shion-2.0.0` / `Shion-2.1.0` 两个 ZIP 未变。
  - 没有强制结束进程，未 push。

- **2026-11-04 只读探测：Claude 桌面版普通聊天有没有可用的开始/结束信号**：结论**没有**（只读，未改任何 Claude/系统配置；工具 `tools/probe_chat.py`，未提交；原始数据在被忽略的 `build/probe-chat-run1.jsonl` 和 `build/probe-chat-report-run1.md`）。
  - 记录范围：只存时间戳和元数据，不存对话、窗口标题原文、通知正文、日志行。
  - **第一轮**（前台一次 61 秒、最小化一次 84 秒，五种方法同时记录）：
    - UI Automation：无障碍树只有 37~50 个节点，像是窗口外框，没有聊天内容区；全程没出现过“停止/Stop”按钮。继续做需要给 Claude 加启动参数（如 `--force-renderer-accessibility`）或开系统屏幕阅读器标志，**不适合做成产品，已放弃**。
    - Shell Hook：没有任何任务栏闪烁（`HSHELL_FLASH`）；看到的“激活”事件是用户自己切窗口造成的，不是信号。
    - 窗口标题：长度全程不变。
    - 日志：`%LOCALAPPDATA%\Claude\logs\main.log` 等（不在 `%APPDATA%`）空闲时也持续写入，`start/complete` 等关键词的出现与开始/结束对不上，不可靠。
    - 通知：两轮都没有新的 Claude 通知。
  - **第二轮只重测通知**：通知访问授权已是允许；Claude 的“回复完成”开关本来就开着，用户检查过 Windows 勿扰和 Claude 的系统通知权限。通知中心里本来有 19~20 条来源是 Claude 桌面版的旧通知（只读应用 ID 和时间，不读正文），所以 Claude 确实会发通知；但不能确认它们来自聊天还是 Code 标签页。10:23~10:34 监听 11 分钟，用户在聊天里约 10:25 发了一个 3~5 分钟的长任务并最小化（中间切回来看过几次）：**没有任何新的 Claude 通知**。
  - **通知与 CC 活动的只读比对**（只用时间戳，不读内容；20 条 Claude 通知，时间范围 11-01 ~ 11-04）：
    - 按“每个会话最后一条 assistant 消息”比，±30 秒内对上 9 / 20。
    - 按“任意一条 assistant 消息”（含子代理文件）比，20 / 20 都在 11 秒内（多数 1~4 秒）；每条通知前后 5 分钟内都有 CC 对话记录写入（最少的两条为 7 条、12 条）。**20 / 20 与 CC 活动吻合，没有“非 CC 来源”，没有任何一条能归到普通聊天。**
    - 更正：口头汇报曾把“会话最后一条对不上”的数量说成 7 条，实际是 8 条（离会话末尾 22.9 分钟～3.4 小时）加 3 条（141/180/309 秒）；这 8 条在“任意 assistant 消息”口径下都在 1~2 秒内，对应会话中间某一轮的结束。
    - 证据强度：CC 活跃时 assistant 消息很密，“最近 1~2 秒”和“±5 分钟有记录”都容易满足，只能说明没有反例，不能证明每条都是回合结束。
  - **局限**：通知只测了一轮长任务，且用户中途切回窗口过几次；没测过“发完就一直最小化不看”的纯净情形。
  - **结论与影响**：外部信号（UIA/Shell Hook/通知/日志/标题）目前都不可用，**通知这条路关闭**（只会反映 Code 会话，不反映聊天）；普通聊天联动只走 V2.2 MCP 方案（见 spec「V2.2 Claude 桌面版聊天联动」）。
  - 工具备注：`tools/probe_chat.py` 有 `--only toast`（只开通知监听）、`--report`（对比表）、`build/probe-chat.stop`（让后台进程干净退出）；依赖 `uiautomation`、`pywin32`、`winrt-*` 只装在 `.venv`，没加进项目依赖。

- **2026-11-04 只读探测：CC 是否本地缓存额度信息（桌面版体力用）**：结论**没有**。
  - 范围：`~/.claude.json` 与 `~/.claude/`（排除 `projects/`，跳过名含 credential/token/secret/auth 的文件），1745 个文件；只记键路径和值类型，快照只存值哈希，不输出值。
  - 没有 `five_hour` / `seven_day` / `resets_at` / `utilization` / `rate_limit_status` 一类键。命中的只有静态项：`oauthAccount/organizationRateLimitTier`、`userRateLimitTier`、`hasExtraUsageEnabled`、`cachedExtraUsageDisabledReason`、`cachedGrowthBookFeatures/*usage*`、`pluginUsage`/`skillUsage` 的 `usageCount`、`projects/*/lastModelUsage`。
  - 在 Code 标签页发消息前后对比：值有变化的只有会话/备份/模型目录缓存的 mtime 和插件 `usage-rows-queued`，**没有任何额度类键更新**。
  - 结论：体力数据不能从本地缓存读；桌面版只能用 hook 两档 + 7 天额度最后已知值（终端 statusLine 的 rate_limits 已在第 0 步验证）；不按 token 推算额度。`lastModelUsage` 未展开看内容，若要用需单独评估。

- **2026-11-03 V2.1 周报第三轮修正**（用户验收真实数据预览通过，本地提交，不 push）：
  - **字体**：称号和总 TOKEN 大数字用真粗体（`card_font(..., hero=True)`：zh Microsoft YaHei Bold；en Segoe UI Bold，其余文字不变；ja 保持）。离屏渲染原先只加载 `msyh.ttc`，粗体没有真字库所以预览里偏细，`ensure_fonts()` 补加载本机已安装的 `msyhbd.ttc`、`segoeui.ttf`、`segoeuib.ttf`（只读系统字体，不复制不打包）。
  - **评语换行**：`wrap_lines` 改为两行均衡断行（`balanced_break`）：偏好两行等宽、上行略长、断在空格/全角标点后；不拆拉丁文本（英文只在空格处断）；末行至少 3 个非空字符；行首不出现 `，。！？…` 等。zh 示例得到“这周的 token 一口一口 / 全吃光啦，好能吃！”。纯宽度均衡会断成“一口一 / 口全…”，所以加了上行偏长的偏好。
  - **版面**：评语与“总 TOKEN”标签间距约 40px（标签 y 484→492）；本周未结束时隐藏“本周称号”标签。
  - **最拼的一天**：`peak_day` 改为在“已过去的日子 + 今天”中选（不含未来），卡片和高亮柱共用同一个值；周一只有今天有用量时为当天。
  - **英文**：标签统一全大写（`HARDEST DAY` 等）；估算说明 `Estimate only`，未计价为 `Estimate only · Some models not priced`；窄卡标签全大写，`APPROVED` 放不下被截成 `APPROV…`，改用 `ALLOWED`；第一排三张卡片等高有测试。
  - **两个偶发测试复核**（`test_permission::test_no_http_route_can_set_a_decision[extra5]`、`test_server::test_every_route_rejects_missing_or_wrong_token[token4-POST-/pause/wait]`）：上一轮全量里失败的错误类型都是 `ConnectionAbortedError: [WinError 10053]`（连接被中止，`socket.py` 读取处）。单独各重跑 3 次，共 6 次全部通过（日志 `build/flaky-*.log`）；之后全量（`build/weekly-fix-full3.log`）这两项也通过。判断为满载时的连接关闭类偶发，不是逻辑问题，未改代码。
  - **测试**：周报测试 80 项通过（新增字体、断行、40px 间距、最拼的一天一致、标签隐藏、英文大写与说明、首行等高）；全量 `1 failed, 2205 passed, 8 skipped`，唯一失败仍是 `test_make_media` 的跨盘 relpath（改动前同样失败，未处理）。
- **2026-11-03 V2.1 周报第二轮重排**（用户逐轮验收真实数据预览通过，本地提交，不 push）：
  - **称号**：`assets/weekly_titles.json` 八条评语（三语）和立绘按用户给的文案替换（quota→collapse、night→yawn、gold→cheer、approval/partner→done、hands_off→idle、treats→happy、quiet→slump），额度刺客日文名“枠キラー”；测试保证文案不含产品名。
  - **版面**（`shion/weekly_ui.py` 的 `paint_card` 重写，坐标仍以 1200×1500 为基准）：顶栏一行（左标题，日期 30px 以立绘轴线 x≈877 居中，跨年显示完整年份）；称号区“本周称号”标签 + 128px 粗体称号（过长自动缩字）+ 34px 评语最多两行（`QTextLayout` 断行）；立绘高 430（x 689～1066、y 225～655）加居中光晕；总 TOKEN 136px；3×2 圆角卡片格（输出 TOKEN / API 估价含卡内估算注 / 日均 TOKEN / 活跃天数 / 最晚活动 / 最拼的一天强调色边框）；诗音自身计数有记录时追加一行 6 张窄卡（新增紧凑标签 `weekly_chip_*`）；柱图占剩余高度，柱宽 118、顶部圆角，最高柱数字强调色加粗，不再单独写“最拼的一天”；底栏左项目链接（受开关控制）右“诗音 · Shion”。旧分隔线全部去掉。
  - **统计**：`report()` 增加 `active_days`、`days_elapsed`、`daily_avg`（总量 ÷ 已过天数，本周含今天）；用量关闭时这些不显示。
  - **台词**：新增 `weekly_title_label`、`weekly_active_days`、`weekly_daily_avg`、`weekly_latest_label`、`weekly_price_label`、`weekly_chip_*`；删除 `weekly_price`、`weekly_latest`、`weekly_no_stats`。
  - **测试**：周报测试 68 项通过（含逐语言“不溢出、不被省略号截断”、卡片格几何/颜色像素、立绘位置、最小字号 ≥28）。全量（`build/weekly-fix-full2.log`）`3 failed, 2191 passed, 8 skipped`：`test_make_media` 跨盘 relpath（改动前同样失败，未处理）；`test_permission`、`test_server` 各一项满载时偶发，单独重跑 190 项全通过。菜单指纹基准 `scheduler_disabled_a55825f.json` 已随上一轮更新。
  - **遗留**：内容最拥挤时（计数行 + 额度峰值行 + 未计价两行注）柱图只剩约 40px 高；真实数据未出现。日文估算注在卡内偶尔折出单字孤行。
- **2026-11-03 V2.1 周报真机验收问题修复**（用户验收通过，本地提交，不 push）：
  - **probe**：上周一至今触发“部分模型未计价”的模型名只有 `<synthetic>`（原先被 `model_name()` 归进 `<unknown>`）。
  - **显示**：`paint_card()` 以 1200×1500 为坐标基准；导出/复制仍画 1200×1500 位图，窗口用 `CardView` 在 `paintEvent` 里按实际尺寸缩放坐标直接重绘（不缩放位图）。窗口总高 = 屏幕可用高度 × 85%。卡片最小字号 28px（自动缩字下限也是 28，放不下省略）。底色 `#1A1212`，按钮深底橙边、选中橙底。“最拼的一天”标签框在首末日向内收以保持边距。
  - **逻辑**：菜单“诗音周报”改为单个动作，默认打开上周，窗口内“上周/本周”切换（`controller.switch_weekly`）。`report(..., today=)`：本周未结束（含周日当天）不评称号，显示“本周进行中 · 第 N 天”；今天之后画暗色虚框不标数字；最拼的一天只在今天之前的日子里选。摸鱼周规则改为 `usage_days ≤ 1`，`title_for` 里缺失字段视为不满足（用量统计关闭时不会误判）。诗音六项计数整周为 0 时换成一行“诗音这周还没记到数据～”。数字：≥1亿 两位小数、≥1000万 取整（英文 ≥1B 两位小数、≥10M 取整）。
  - **计价**：`<synthetic>` 原名保留；`estimate` 跳过 `<synthetic>` 和 token 全 0 的条目。用量缓存 version 1→2，首次启动会重扫一次。
  - **真实数据预览**（只在 `build/weekly-real-{prev,this}-{zh,en,ja}.png` 及窗口截图）：上周“吞金兽”2.95亿、本周进行中第 2 天；两周都不再提示未计价。真实存档 `weekly_stats` 为 0 天（已装 Shion-dev 尚未部署 V2.1 计数），所以显示空计数提示。预览用临时缓存只读重扫真实对话，未写真实 `usage.json`。
  - **测试**：周报与相关专项 174 项通过；全量 `2174 passed, 5 failed`（`build/weekly-fix-full.log`）。其中 3 项是菜单结构变化导致 `scheduler_disabled_a55825f.json` 菜单指纹过期，已只更新 21 个指纹值并通过；`test_hook` 耗时检查满载偶发，单独重跑通过；`test_make_media` 的跨盘 relpath 失败在改动前代码上同样失败，未处理。
  - **坑**：`test_menu_layout` 的 360 像素截断检查和 `test_weekly` 同进程跑时会差 1 像素（周报离屏加载字体影响菜单字体度量），改动前已存在，单独跑通过。

- **2026-11-03 V2.1 真实接入验收准备：替换 Shion-dev + 连接差异 dry-run**（证据在忽略目录 `build/v21-replacement-20261103/`；未连接、未改真实配置、未 push）：
  - **打包**：沿用 `security-replacement-20261101` 的 `build_no_zip.py`（调用 `tools/build.py` 的 `build_environment()`），从 `081111a` 构建，不生成 ZIP，依赖版本一致，226 文件，exe `ee5e6b9a…aeada60ba`。第 1 次 bundle_smoke 失败 `statusline-chains-original`：隔离环境 PATH 无 Git，原命令回落 PowerShell，冷启动超过原命令 1 秒上限，输出为空；隔离复现第 1 次空、之后正常（约 0.5 秒）。同一包重跑 bundle_smoke **110 项通过**（第 1 次结果留 `*-attempt1`）。观察端烟测通过、响应与上次一致。**遗留**：没有 Git Bash 的机器上，首次 statusLine 刷新可能丢掉原状态栏输出（时序边界，未改代码）。
  - **替换**：替换器等用户退出诗音后原地替换，两次改名均一次成功；旧包 220 文件逐个核对后保留为 `D:\desktop	ools\Shion-dev-before-v2.1-20261103`，新目录 226 文件逐个核对一致。Codex / CC 配置哈希与任务开始时一致，存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true` 未变，`Shion-2.0.0-win64.zip` 未变，没有强制结束进程。旧 exe `b1c65811…278d6a`。坑：本会话每次工具调用都会触发 hook 短暂启动 `Shion-dev\Shion.exe`，替换器“连续无进程”检测会被干扰，等待期间不要调用工具。
  - **dry-run**：把真实 `settings.json` 复制到临时目录，模拟打包版菜单连接（`sys.frozen`、exe 指向 Shion-dev、root 为 `_internal`，Git Bash），只对副本执行 connect / disconnect；真实文件哈希不变、真实目录无新文件。当前状态 `stale`（缺 statusLine 记录）。语义变化只有两处：`statusLine` 由原 `python <home>/.claude/statusline.py` 换成 `Shion.exe --statusline --record <home>/.claude/settings.json.shion-statusline.json`（原值存记录文件并串联），新增 `StopFailure` hook；已有 8 个 hook 事件不变，其他键值不变但 `statusLine` 被挪到最前。真实连接还会产生 1 个 `settings.json.shion-backup-*` 和记录文件。副本上断开：statusLine 恢复原值，但会同时移除诗音全部 hook（断开语义），记录文件留下内容 `{}`。脱敏 diff 在 `dryrun/`。
  - **下一步**：用户审阅差异后决定是否授权真实连接。

- **2026-11-03 V2.1 第 3 步 体力正式图（用户验收通过，本地提交，不 push）**：
  - **素材**：`process_sprites.py --only yawn cheer slump collapse` 只新增这 4 张 448×512 图，其他 PNG 和 `fx_z.png` 不变。yawn、cheer 在 `STANDING`，slump、collapse 在 `SCALE_FROM_STANDING`。坑 1：yawn/cheer 进 `STANDING` 会让平均缩放比 0.8277→0.8239，使 sleep 重新生成与入库图不一致（`test_process_sheets` 失败）；新增 `AVG_EXCLUDE={yawn,cheer}` 让它们不参与平均，旧图可逐字节复现。坑 2：slump 横躺比画布宽（485>448），头居中会被裁；`EXTRA_SCALE["slump"]=0.90`，并在图宽≤画布时把整体夹进画布（对现有图无影响）。头大小只用数字与 idle 对比，没看原图。验收后 collapse 头偏小（宽约 277px vs 站立图约 295px），加 `EXTRA_SCALE["collapse"]=1.08` 并 `--only collapse` 重新生成（scale 0.439，尺寸 325×438），并排对比图 `build/s3-collapse-compare.png`。
  - **接入**：体力 1 档待机表情 yawn（替换 blink）、2 档 slump（替换 desk）、3 档 collapse（替换 sleep）；周报提醒用 cheer（`TEMP_STATES` 加 cheer，3 秒，不进菜单表情）。slump/collapse 与 desk/sleep 同样视为安静、不待机动作、不播时段台词；collapse 无 Z、不进 bed。授权面板弹出仍站起。同步 `bundle_smoke` 快照、spec 精灵表/体力表和测试。
  - **测试**：首次全量 `3 failed, 2159 passed, 8 skipped`（`build/step3-full.log`）；collapse 调整并修复坑 1 后再跑全量 `2 failed, 2160 passed, 8 skipped in 649.65s`（`build/step3-full2.log`），失败仅下面两项环境相关用例，不是全绿。失败项：`test_process_sheets` 首次失败已按坑 1 修复，第二次全量通过；`test_make_media` 在基线（stash 后）同样失败，原因是 pytest 临时目录在 C: 而仓库在 D:（`os.path.relpath` 跨盘），与本步无关；`test_find_cc_process…` 依赖本机是否有 claude 进程，基线单独复测通过，两次全量都失败，基线单独复测曾通过，原因未确认，疑似环境相关。
  - **下一步**：真机看动态观感、体力档位真实切换。

- **2026-11-03 V2.1 第 2 步 statusLine 与体力（代码及合成预览已获用户确认，本地提交，不 push）**：
  - **串联与配置**：标准库 `hooks/shion_statusline.py` / `--statusline` 读取 stdin，仅转发会话和两个窗口各两项数字，认证 POST `/usage/limits`，单次超时 0.3 秒；无效字段或不可达静默。原命令收到同一份原始输入，stdout 不做解码或修改，最多等待 1 秒，超时只保留已收到的原始输出。Windows 按官方规则用 Git Bash / PowerShell，兼容自定义 Bash 路径和 mingw64/bin，避免改成 cmd 语义；保留原 padding。安装记录与 settings 共用现有备份/原子替换事务，保留原 JSON 值字节，恢复只处理接管项；当前接管项、记录或任一事务依赖漂移时停止，回滚也不覆盖外部新内容。缺失活动记录时拒绝接管/断开，重复连接不写盘。
  - **额度与体力**：两个窗口独立校验有限非负数，允许超过 100%，过期/缺失隐藏。逐会话保存，展示有效观测最大值；statusLine 会话使用终端四档，不再被该会话的 hook 锁成两档。未知客户端的 `rate_limit` / `quota_auto_resume_fired` 仅设置/清除各自两档信号，不推断百分比、不看错误正文、不结算授权/暂停、不以普通消息复活。体力只在底层待机生效，工作/授权/暂停/拖动/手动表情/喂食优先；授权期间临时站起，播报等待空闲和气泡结束。终端去重用 v5 可选 `stamina_announced`，只存窗口时间和枚举，跨重启同档不重播。
  - **周报与文档**：只把本次收到且未过期的 seven_day 记入接收日期的峰值，保留 8 周；有值才显示额度行，参与“额度刺客”称号。不把旧会话的值重记到新日。同步三语文案、连接说明、README 和 spec；替代图沿用 blink/desk/sleep，没有制作新图或更改原始素材。
  - **测试**：首轮专项 510 通过、2 个新增测试把编号误当对象，修正后专项 80 通过；后补去重/记录冲突/存档/打包配置专项 `183 passed in 12.56s`。全量见总览：2147 通过、9 跳过，唯一旧测试失败已修正。最后专项 `369 passed, 1 skipped`，另有旧认证路由测试 WinError 10053（关闭未读完的 HTTP 连接）；该例及额度接口、旧安装提示、Bash/PowerShell 选择复核 `5 passed in 2.05s`，不宣称全量全绿。早一轮周报缓存原子替换曾出现 WinError 5，疑似文件被占用，原因未确认；随后该用例在 80 项中复核通过，未修改 usage 扫描实现。日志均在忽略目录 `build/stamina-*.log`。
  - **收尾验证**：PowerShell / Git Bash 最终专项 `85 passed in 9.88s`（`build/stamina-powershell-final.log`）；峰值未增加时不再反复推迟存档或重绘卡片，新增频繁更新回归，最新核心专项 `210 passed in 14.50s`（`build/stamina-complete.log`）。`check_private.py` 默认暂存区扫描通过；另外用同一检查器检查全部 28 个改动/新增文件，零命中（`build/stamina-worktree-private.txt`），`git diff --check` 通过。用户已确认代码与合成预览通过并授权本地提交（不 push）；提交前按 28 文件清单精确暂存并重跑暂存区隐私检查。
  - **打包验证**：仅在 `build/stamina-package/` 构建隔离测试包，未替换 dist 发行目录或已安装 Shion-dev。第一次直接调用打包器漏用 `tools.build.build_environment()`，包中混入不同的 ICU / UCRT 等 DLL，诊断见 QtCore 入口加载失败并表现为快照超时，具体故障 DLL 未单独定位；临时诊断脚本/包只在 build 中。按项目净化环境重打后整包冒烟 `102` 项通过（初次通过日志 `build/stamina-package-clean-check.log`，最终代码复核日志 `build/stamina-package-final-check.log` 同为 102 项），包括三语连接/恢复、快照、原状态栏串联、认证白名单和活实例事件。移除 Qt 的隔离副本也分别通过 PowerShell / Bash 的精确输入输出与认证元数据验证（`build/stamina-frozen-report.json`），最终再次验证两种 shell 均通过，普通冻结版快照重试 1.125 秒成功（`build/stamina-frozen-final.log`），确认 statusLine 无 Qt 依赖；源码模式同样有无 Qt 导入测试。最精简 PATH 找不到 PowerShell 的问题已改为系统绝对路径回退并复核。
  - **预览**：全为合成数据，终端四档 `build/stamina-step2-20261103-overview.png`；带 93% 峰值和对应称号的三语周报 `build/weekly-quota-step2-20261103-v2-{zh,en,ja}.png`，无数据隐藏由测试验证。新文件名避免旧图片缓存。真正桌面 hook 是否发出、窗口焦点/动态跳跃/高 DPI 仍待人工验收，未部署、未改真实配置。

- **2026-11-02 V2.1 第 1 步周报完成（用户已确认，可本地提交，不 push）**：
  - **范围**：新增 `usage.py`（标准库扫描/缓存/计价）、`usage_service.py`（单后台线程与取消）、`weekly.py`（纯数据计数/称号/周区间）、`weekly_ui.py`（QPainter 卡片/窗口）。接入状态存档 v5 可选字段、控制器现有事件与设置菜单、快照入口；打包清单补价格和称号 JSON。不增加依赖，不修改真实 settings、正式 hook 逻辑、体力或已安装 Shion-dev。
  - **用户补充已同步 spec**：每条消息 input + cache write + cache read 选档，按日期/明确模型版本/档位聚合；5m/1h cache write 分开累计（缺失全部按 5m）；渲染时乘当前单价，改单价无需重扫。`pricing.json` 仅采用官方页标准全局 API 数字，`as_of=2026-11-02`，用户已核对通过；Fast/Batch/地域/工具附加费不在估算范围。匹配仅允许明确版本和日期/latest 后缀；未知版本未计价，专测 `claude-opus-4-1` 不匹配。
  - **隐私与恢复**：只取白名单字段，消息去重键及缓存文件键分别用 sha256 / 前 16 位，不落明文路径/标识或内容；按本地日期保留 8 周，去重记录保留 8 天。较新有效流式 usage 用差额更新；截断、替换或过期去重键晚到时重建，未完成尾行不推进偏移；损坏缓存重建、失败不写部分结果，日志只记跳过条数。扫描只在后台，启动延迟 10 秒、Stop 后 30 秒合并触发及打开周报触发，关闭统计会取消扫描。
  - **统计**：任务/工作时长按会话记录（只算收到 Stop 的轮次，单轮 2 小时封顶，诗音中断的 Stop 不算完成），批准/拒绝只统计诗音实际生效决定，摸头和吃完零食沿用本机计数；不补造旧历史。最晚活动和夜猫子只使用 user/assistant 记录 timestamp，05:00 划活动日；额度无数据隐藏，不显示“未获取”。称号配置含 2 亿 token 阈值及八种三语称号。
  - **卡片与交互**：1200×1500，三语/大数单位，字体回退 Microsoft YaHei / Yu Gothic / Consolas；离屏 Qt 字体为空时只读取系统已安装字体，不复制/打包字体。终端色初稿经用户要求调整为背景 #1A1212、强调 #F4772E 等六种诗音配色；总/输出标签对齐，价格两行在右栏，唯一最高柱强调并标三语“最拼的一天”。窗口显示不激活，主动点击后 Esc 可关闭，保存与剪贴板自动测试使用假对话框/假剪贴板。现有立绘暂代，举报告新图仍属第 3 步。
  - **预览与提交状态**：诗音配色外观已获用户基本通过；本次五处修正已完成：日文 Yu Gothic 比例字形与零字距、柱图区上方分隔线及统一间距、最高日标注以柱子居中且根据边距缩小、总/输出 token 数字基线对齐、英文顶部 `> SHION / WEEKLY`。v3 三语快照 `build/weekly-layout-v3-{zh,en,ja}.png` 已离屏检查并获用户确认，用户明确允许本地 commit。价格已核对通过；全部快照、日志和临时 probe 仍在忽略的 build，不入库。
  - **日文字重小改**：按用户授权，日文优先 Yu Gothic UI / Yu Gothic，正文请求 Medium、标题 Bold，保留比例字形及零字距；离屏只加载系统已有 Medium/Bold 文件，不打包字体。新增快照 `build/weekly-ja-ui-medium-v4.png`；36 项测试通过（`build/weekly-ja-medium-verified.log`）。Yu Gothic UI 本身已有比例假名，测试检查自然假名宽度而非强制要求 palt 再次缩窄。
  - **v3 排版回归**：`tests/test_weekly.py` 36 项通过（`build/weekly-layout-v3-verified.log`），新增三语首日/末日最高柱的标注中心、完整文字缩放、卡片边距及唯一强调色测试；数字共用基线、英文标题、日文比例假名与零字距均有专测。此次只改周报渲染与规格/进度，未重跑产品全量；全量基线及 ZIP 偶发问题按下条保留。
  - **验证进展**：周报新增 28 项已通过（含用户指定 Opus 4.1 不匹配测试）；周报与状态机合跑 116 项通过；HTTP 复测通过。菜单/控制器/连接引导/调度显示/时段台词相关 230 项通过。第一次全量为 `50 failed, 2028 passed, 9 skipped, 2 warnings in 570.25s`（`build/weekly-full-tests.log`）；主要是新菜单位置使旧索引断言失效、周报先于连接引导播报及独立时段测试被新提醒影响，已调整位置/优先级及隔离测试；另两处 WinError 10053 均单独重跑通过。菜单基线只刷新 21 个菜单哈希，其他状态/计数/精灵字段逐项比对一致。第二次全量为 `1 failed, 2081 passed, 9 skipped, 2 warnings in 557.57s`（`build/weekly-full-final.log`）；唯一失败 `test_release.py::test_zip_contains_exact_bundle_and_licenses_with_stable_bytes` 在 ZIP 原子替换时 WinError 5 拒绝访问，记为“疑似文件被占用，原因未确认”。构建函数未修改，发布测试文件单独重跑 `4 passed in 1.50s`（`build/weekly-release-check.log`）；没有确认原因，不宣称全量全绿。本次运行中追加的空闲启动 8 周清理用例已随 116 项单独验证。两条警告为既有 Pillow getdata 弃用。

- **2026-11-02 V2.1 第 0 步可行性探测完成（本地提交，不 push）**：
  - **范围**：只新增标准库工具 `tools/probe_usage.py` 及隔离测试，未修改 `shion/`、正式 hooks 或安装器；真实 statusLine 经用户确认临时修改，现已按字节恢复。已有 spec/progress 规划改动按用户要求纳入本任务；三语 README 补上规划功能的平台限制，不表示功能已经实现。
  - **入库边界**：临时 statusLine probe 接收器/控制器及所有探测输出留在忽略目录 `build/`，不入库；`tools/probe_usage.py` 和 `tests/test_probe_usage.py` 按用户要求保留在 Git。此次只同步结论与规格，不修改产品代码或真实配置；提交前再次运行 `tools/check_private.py`。
  - **usage 结果**：真实只读扫描 199 个 jsonl；assistant usage 行 16,154，合格条目去重前 16,154、去重后 7,016；本地日期范围 2026-10-02～2026-11-02。最近 7 天四项逐日合计、模型名列表、客户端字段分布只写在忽略目录 `build/probe-usage.txt`，没有路径、项目名、对话内容或消息标识。`entrypoint` 分布：`claude-desktop` 35,728、`claude-vscode` 165、`cli` 861、`sdk-cli` 272；这是带该字段的顶层记录分布，不等于 usage 条目数，也不证明每条 usage 都能区分客户端。未知客户端值和不符合公开 Claude 模型名格式的值分别合并为 `<other>` / `<other-model>`，不回显自由文本。
  - **统计口径与局限**：完整扫描并按 `(message.id, requestId)` 去重，缺两种标识或日期/数值非法的条目不纳入；本次重复键保留首次遇到的有效记录。坏行及超过 1 MiB 的行在内存计数，不增加规格以外的报告项。第 1 步仍须明确流式重复记录的 usage 是否变化、应采用哪条；本探测不作为账单核验。按本机时区取本地日期，测试同时隔离 HOME / APPDATA / 配置目录，未运行产品全量测试。
  - **hook 调研**（官方文档核对；本机终端 CLI `2.1.289`）：[StopFailure](https://code.claude.com/docs/en/hooks#stopfailure) 的 `error == "rate_limit"` 是限流候选信号；[Notification](https://code.claude.com/docs/en/hooks#notification) 的 `quota_auto_resume_fired` 表示额度等待后自动继续，`quota_auto_resume_stale` / `quota_auto_resume_disabled` 不表示任务已经继续，这三种类型要求 2.1.234+。这些字段不能提供 five_hour/seven_day 百分比；rate_limit 也不保证是订阅窗口耗尽，自动继续不保证已用比例回到 50 以下。未新增真实 hook、未故意撞限额；桌面版支持和实际触发仍未验证，不能把文档信号当作真机验收通过。
  - **statusLine 实测**：已有第三方命令，临时接收器只投影顶层键名和额度数字，并串联原命令（1 秒超时）；未知键名合并为占位。用户在桌面版现有会话发两条并等回复：0 条记录；新开桌面版会话重试两条并等回复：仍为 0。终端版 rate_limits 在首条回复后出现；终端发两条并等回复：共 6 条调用记录，其中 4 条未带 rate_limits，后续 2 条带 `five_hour.used_percentage=9` / `resets_at=1793627400` 和 `seven_day.used_percentage=8` / `resets_at=1794186000`。调用次数不等于消息数；本次用户确认的结论为桌面版不运行 statusLine；版本变化后可重新验证。聚合元数据只在忽略目录 `build/probe-statusline.jsonl`。
  - **恢复核验**：原始备份 SHA-256 `88446db17715def1e3924ca0043a678567d025b2ac5d67eea6b497d6a5b130b5`；临时写入后 SHA-256 `e2706d60e3639e2f800c5df6bd9485a78a9af9ea5b8664a288bc56c78a9a1c51`。恢复前确认当前哈希等于临时写入后哈希，原子替换前再核对原字节未变；原始备份哈希通过后恢复，恢复后 SHA-256 与原始备份完全一致。无并发冲突。备份留在用户配置目录，文件名及阶段记录只在忽略目录 `build/probe-statusline-state.json`；接收器恢复后停止记录，防止会话缓存临时命令继续采样。隔离的安装/备份/并发修改拒绝恢复/原字节恢复测试均通过。
  - **结论与下一步（用户确认后更新）**：token 周报的数据源可行；桌面版不运行 statusLine，终端版 rate_limits 在首条回复后出现，临时配置已按哈希恢复。终端采用 statusLine 四档；桌面采用 `StopFailure.error=rate_limit` → 倒地、`Notification.notification_type=quota_auto_resume_fired` → 复活的 hook 两档，真实触发仍待人工验收。README 已注明四档仅终端可用；吞金兽阈值改为总 token ≥ 2 亿。第 1 步先做周报，体力和额度接入留在第 2 步。
  - **验证**：隔离 `tests/test_probe_usage.py` 6 项通过，覆盖跨文件重复、坏行/截断/超长行、非法标识/计数、时区、未知模型和客户端字段的隐私隔离、输入字节不变与固定输出位置。初次测试有一处期望数误写（把 user 行也算入 assistant 行），已修正；收尾重跑仍为 6 项通过。`tools/check_private.py` 暂存区检查与 `git diff --cached --check` 通过；真实聚合输出、临时接收器/控制器和状态记录均忽略、不入库。未运行产品全量测试。

- **2026-11-02 发布 v2.0.0**（证据在忽略目录 `build/release-2.0.0-check/`、`build/release-build-2.0.0-final.log`、`build/release-final-pytest.log`）：
  - **Codex 联动隔离测试**（`codex_isolated.py`，走菜单同一函数 `review_connection`，确认框自动点“是”，观察端命令指向打包版 `Shion.exe`；CODEX_HOME / HOME / USERPROFILE / APPDATA / SHION_DATA_DIR / SHION_INSTANCE_NAME / SHION_PORT 全部指向临时目录和空闲端口）：准备一份带注释、怪格式、末尾无换行、其他 MCP 和其他 hook 的 config.toml / hooks.json。两轮“安装 → 卸载”：安装后只有插入、原有字节逐字保留，MCP 只多 `shion_lifecycle_v1`，hook 多 7 组；按配置命令能启动打包版观察端；卸载后两个文件与原始字节完全一致，无残留。冲突 A（安装后改用户自己的行再卸载）：只移除诗音条目，用户修改保留。冲突 B（改诗音自己的条目再卸载）：拒绝卸载，文件不动。无残留进程，临时目录已删除。
  - **发现并修正的文案问题**：第一次跑时“备份文件存在”4 项不通过——Codex 安装本来就不另存配置副本（只在写入期间有事务记录，内容是哈希和插入位置），但三语菜单提示和 README 写了“写入前备份/保留备份”。用户选择改文案：提交 `0034dbb` 改为“只插入诗音条目、不另存配置副本、断开时按记录精确移除”，卸载提示改为“Codex 里的信任记录保留不动”；该检查项随之改为“只有 1 个所有权记录，且不含用户原文”，最终 **60/60 通过**。
  - **重新打包**：因菜单文案进了程序，从 `0034dbb` 重打；本地标签 `v2.0.0`（未推送过）挪到 `0034dbb`，标签对象 `9f7d867`，标签作者 noreply。zip **45,346,758 字节**，SHA-256 `7b2318fe79ed95cc3a27cf76cc14bd4b3bf2241dd8f6a1b49292bf83ebe08628`；bundle_smoke 99 项、观察端烟测、中文空格路径解压自检（99 项）均通过。上一版 zip（`9dde196a…`，基于 `db5b58a`）作废，挪到 `build/dist-archive-dev-20261102/`。全量 pytest `1 failed, 2049 passed, 8 skipped, 2 warnings in 603.39s (0:10:03)`，唯一失败仍是满载时的 `test_real_process_tree_is_terminated`。
  - **推送前审查**（40 个提交 + 标签）结果同下方记录：`check_private` 只有 `1f54cb6` 的已知虚构测试字面量；USERNAME / COMPUTERNAME 全文 0 命中；邮箱全部 noreply；无 >5 MB 文件，无 raw/build/dist/.venv。
  - **推送**：`git push origin master`、`git push origin v2.0.0` 两条命令。`git ls-remote origin`：`refs/heads/master` = `0034dbb04716…`，`refs/tags/v2.0.0` = `9f7d8677eda3…`（`^{}` = `0034dbb`），均与本地一致；与推送前相比只新增 `v2.0.0`，没有 feature 分支、`refs/codex/*`，没有推 backup。仓库 `iLLyaaaaaa/shion` Public、默认分支 master。
  - **Release**：中途发现本机 `gh` 凭据失效，由用户本人在本机重新登录后创建。`gh release create --verify-tag`，标题 “Shion 2.0.0”，Latest、非 Pre-release，发布时间 2026-11-02T00:16:35Z，正文与 `build/release-notes-2.0.0.md` 一致（只差末尾换行），附件 45,346,758 字节；从 Release 下载后 SHA-256 一致，公开下载地址返回 200。README 引用的 13 张图片/GIF 及 README、LICENSE 链接在 GitHub 上都返回 200，大小与本地一致。
  - **未做**：三项人工专测改为发布后日常使用中验证（见上）。

- **2026-11-02 合并 master、打包 v2.0.0、推送前审查**（只在本地，没有 push、没有创建 Release；证据在忽略目录 `build/release-2.0.0-check/`、`build/release-build-2.0.0.log`）。**注意：本条里的标签位置（`db5b58a`）和 zip（`9dde196a…`）已被上方发布记录取代。**
  - **合并与标签**：起点工作区干净、HEAD 为 `db5b58a`，`master`（`74121dc`，与 `origin/master` 一致）是其祖先；`git merge --ff-only` 快进到 `db5b58a`（38 个提交）。附注标签 `v2.0.0`（标签对象 `093f9c9`）打在发布提交 `db5b58a` 上，标签作者是 noreply 邮箱。**标签位置沿用 v1.0.0 的做法**：v1.0.0 标签指向发布内容提交 `7c34de6`，之后的“记录发布”文档提交（`3cc27ee`）排在标签之后；所以 v2.0.0 指向 `db5b58a`，本条进度记录是标签之后的单独提交，标签不移动。
  - **打包**：`tools/build.py` 从 `master` 正常构建，`dist/Shion` 220 文件 / 104.44 MB（99.6 MiB），bundle_smoke **99 项全部通过**；`dist/Shion-2.0.0-win64.zip` **45,346,513 字节**（222 个条目），SHA-256 `9dde196aeedf267e844053eb643217a8fdafd223a92921c89ad03e4a403a1107`（另用 `sha256sum` 复核一致）。构建前把 `dist` 里旧的开发版残留 `Shion-1.0.0-win64.zip`（46,695,060 字节，SHA-256 `7a1410dc…602ca9`）挪到 `build/dist-archive-dev-20261102/`，没有删除。
  - **烟测**：观察端 stdio 烟测（initialize / tools/list / ping / EOF 正常退出）通过，stderr 为空，响应与上一次替换逐项一致（`serverInfo.version` 仍是协议版本 `1.0.0`，有意保留）。解压自检：zip 解压到路径含中文和空格的临时目录，`testzip` 无错，根目录只有 `Shion/`、`LICENSE`、`assets/LICENSE`，解压出的 220 个文件与 `dist/Shion` 逐文件 SHA-256 一致，没有 `.venv`、`raw`、`build`、令牌或存档文件；对解压目录运行同一套 bundle_smoke 通过 99 项；临时目录已清理。这不等于干净机器验收。
  - **推送前审查**（范围 `origin/master..master`，38 个提交加本条记录）：每个提交运行 `check_private.py --ref`，37 个无命中，`1f54cb6` 命中 1 处（`tests/test_check_private.py` 里虚构用户名的测试字面量，同一文件在后续提交已改写，未改写历史，与 11-01 记录一致）；用 `USERNAME`、`COMPUTERNAME` 的值对完整补丁（含二进制，约 7.1 MB）、全部提交信息、标签和文件路径做不区分大小写全文匹配，均 0 命中；所有提交的作者与提交者邮箱都是 noreply 邮箱，提交信息里唯一的邮箱是 `noreply@anthropic.com`；范围内没有超过 5 MB 的文件（树内最大是 `hero.gif` 1.4 MB），没有 `assets/sprites/raw/`、`build/`、`dist/`、`.venv` 内容，没有音频/字体/字幕类文件，`git ls-files -ci --exclude-standard` 为空。
  - **待推送的引用**：`git push --dry-run origin master v2.0.0` 只显示 `74121dc..db5b58a master -> master`（快进，无需强推）和新标签 `v2.0.0`；`remote.origin.push` 未配置，不使用 `--all`/`--mirror`/`--tags`。本地存在的 `refs/codex/turn-diffs/*`、各 feature 分支、`v1.0.0` 都不会被推送；`backup` 远端不推。

- **2026-11-02 ChatGPT 未安装状态显示 + 原生风格菜单截图**（本地提交，没合并 master、没打包、没 push）：
  - **状态显示**：`ChatGPTConnection.activity()` 在临时关闭**或未安装**时返回“—”（`activity_link_none`），子菜单显示“活动：—”。`build_menu` 的 `status_row` 在 not_installed 时改用新增三语 key `menu_link_status_bare`（“{name}：{state}”），顶层只显示“ChatGPT：未安装”，原来的多行全文仍放在 tooltip。已安装、临时关闭、出错时的显示不变（新增三语×三状态参数化测试）。Claude 未连接时仍显示“未连接 · 空闲”，按用户决定没有改。`test_chatgpt_ui.py` 的辅助函数把连接视为已安装，因为它测的是“待确认”时效。基线 `scheduler_disabled_a55825f.json` 只刷新 `menu_sha256`：21 项中 18 项变化，12 个不同哈希一一对应；不变的 3 项是 ChatGPT 临时关闭阶段，其余字段逐项比对一致。
  - **截图**：`--platform windows` 时 Qt 已经使用 `windows11` 样式（圆角高亮、未勾选项没有方框），但 `QMenu.grab()` 只截客户区，真机上的圆角外框、细边框和阴影是 Windows DWM 加的，所以原图是方角。`render_menu.py` 在原生平台下照样补上外框（圆角 8 逻辑像素、1px 半透明边框、柔和阴影），offscreen 输出不变。`SESSION_SPECS` 改为按语言给虚构的第一句话，项目名都是 `my-app`。6 张图取 scale1.5，大小 48～61 KB，文件名不变。日文和英文的第一句话按程序规则截断到 12 个字。
  - **坑**：曾想把真实菜单弹到屏幕上再截屏来测外框，`grabWindow` 截到的是桌面壁纸（没有菜单），文件已立即删除，之后不再用截屏方式。外框参数按 Windows 11 规范模拟，需要真机对照确认。
  - **其他 README 媒体**：hero.gif（抽 4 帧）、pat、desk、permission 三语、sleep-bed 都只有桌宠和授权面板，没有菜单，不涉及旧菜单结构。
  - **验证**：全量 `--basetemp=.venv/preview-run/release-prep2`，结果 `1 failed, 2049 passed, 8 skipped, 2 warnings in 603.42s (0:10:03)`（日志 `build/release-prep2-pytest.log`）。唯一失败仍是满载时出现的 `test_real_process_tree_is_terminated`（见下方 11-01 记录），根因未确认。

- **2026-11-01 v2.0.0 发布准备**（只改版本号、文档、截图，没改功能代码；没合并 master、没打包、没 push）：
  - **版本号**：`shion/__init__.py` 改为 `2.0.0`。关于页、`QApplication` 版本、snapshot 标题、exe 版本资源（`tools/build.py` → `Shion.spec`）、ZIP 文件名都从这里读取。同步修改了测试里写死的地方（`test_release.py` 的 QApplication 版本、ZIP 名和 `fileVersionMS == 2 << 16`，以及 `test_windowing.py`），还有 spec.md 两处、三语 README 的下载文件名。`shion/codex_mcp.py` 里 `serverInfo.version "1.0.0"` 是 `shion_lifecycle_v1` 协议的版本，有意保留。
  - **README 三语**：结构不变，新增“ChatGPT（Codex）只读观察”“连接 ChatGPT（Codex）”“已知限制”三节。多会话选择、临时关闭联动、诗音没开时不拖慢 CC、Codex 窗口层级跟随写进功能；菜单路径改成“AI 连接 › Claude Code / ChatGPT › …”；隐私节补上一次性令牌与独占端口，以及第一句话摘要只在内存（隐私模式下不发送）。商标声明补上 OpenAI。
  - **截图**：原有 7 张用 `tools/make_media.py` 重新生成后像素完全一致（`permission.en.png` 只差 PNG 编码字节），没有替换。新增 6 张菜单截图 `docs/images/menu-ai.{zh,en,ja}.png`（AI 连接 › Claude Code）和 `menu-sessions.{lang}.png`（工作遥控 › 停下 › 按会话），由 `tools/render_menu.py` 渲染（scale 1.5，20～52 KB）。工具里的合成项目名改为虚构的 `my-app` / `notes`，第一句话改为虚构英文。菜单树 json 已检查，没有路径或用户名。
  - **发布说明**：`build/release-notes-2.0.0.md`（忽略目录、不入库），英中日三语。
  - **坑**：`rg 1\.0\.0` 搜不到 `test_release.py` 里以 `1 << 16` 写死的主版本号，第 1 次全量才暴露（日志 `build/release-prep-pytest-attempt1.log`）。修正后第 2、3 次全量都是 `1 failed, 2040 passed, 8 skipped, 2 warnings`（第 3 次 `in 607.48s (0:10:07)`，日志 `build/release-prep-pytest.log`；第 2 次 `-attempt2.log`），唯一失败是 `test_interrupt.py::test_real_process_tree_is_terminated`：`killed` 里只有 1 个 pid，没有直接子进程。单独跑这个测试 5/5 通过，整个 `test_interrupt.py` 3/3 通过（84 passed）；本次 `shion/` 只改了版本号字符串，没碰中断代码。推测是满载时的时序竞争：`.venv\Scripts\python.exe` 是转发器，子进程（转发器）在真正的 python 被结束后自己退出，`TerminateProcess` 就返回失败，曾孙进程也可能还没创建。**未修复、未确认根因**；这个用例对应发布前专测的“立即中断后工具进程是否结束”，专测时要实机确认。`make_media.py --output-dir` 指到 C 盘会因 `relpath` 跨盘报错，应输出到仓库内的 `build/`。

- **2026-11-01 合并安全修复、隔离验证并替换 Shion-dev**（证据在忽略目录 `build/security-replacement-20261101/`）：
  - **合并**：`git merge --ff-only feature/v2-security-fixes`，HEAD 由 `1500086` 快进到 `f8ec0a6`。worktree `..\shion-security-fixes` 扫描无 reparse point（junction 已在上一任务解除）、无未提交改动（只有被忽略的 `build/` 和缓存），用 `git worktree remove`（未加 `--force`）移除，分支保留；主仓库 `.venv` 与 `assets/sprites/raw`（23 项）完好。
  - **打包**：沿用 `build/session-labels-replacement-20261101/` 的脚本，只改目录名和备份名，不生成 ZIP。
    - 第 1 次：打包成功（220 文件），但 bundle_smoke 失败，`list index out of range`。原因是 `tools/bundle_smoke.py` 的 `MockHooks.link` 只写了 `{"token"}`，没有第二轮新增的 `pid` / `created`；打包版 hook 的 `read_link` 正确地拒绝了它、一个请求都没发，`mock.events` 为空。这是第二轮漏改的测试工具（当时只做了编译检查），不是产品代码问题。
    - 修正：`MockHooks.link` 改用正式的 `shion.loopback.write_token`，单独提交为 `b016547`（只改测试工具）。第 1 次的结果改名保留为 `*-attempt1`。
    - 第 2 次：从 `b016547` 完整重打，220 文件，bundle_smoke **99 项全部通过**（新增 `hook-sends-link-token`、`server-rejects-missing-token`），没有新 ZIP。观察端 stdio 烟测通过，响应与上次替换完全一致。依赖版本 PyInstaller 6.22.3 / pyinstaller-hooks-contrib 2026.9 / PySide6 6.12.0 / numpy 2.2.6，与 `requirements-build.txt` 一致。
  - **隔离验证**（`isolated_verify.py` → `isolated-verify.json`）：打包版在系统临时目录里运行，独立 HOME / APPDATA / CODEX_HOME / SHION_DATA_DIR、空闲端口、唯一实例名，ChatGPT 观察端预置为别的端口并关闭，存档预置 `permission_timeout=10`；隔离实例用原生 windows 平台（正常退出靠 WM_ENDSESSION，等同注销）。**a～d 全部通过**：
    - a. 启动后出现 `claude-link.json`，记录的写入者就是该实例；带令牌 `/health` 返回 200；`--hook PermissionRequest` 登记成功（日志有“有东西要你决定哦”），10 秒超时后撤回，不输出决定，退出码 0；WM_ENDSESSION 正常退出（退出码 0）后令牌文件被删。
    - b. 普通 socket 先占住端口：日志有“HTTP 服务启动失败”，没有令牌文件，实例仍在运行；`--hook PermissionRequest` 不输出决定，占端口 socket 0 连接。
    - c. 伪造进程号已不存在（句柄也已关闭）的令牌文件：PermissionRequest 和 UserPromptSubmit 都不发请求，0 连接；隔离实例被强制结束后令牌文件留下，`read_link` 拒绝，hook 不发请求，0 连接。
    - d. 不带令牌、错误令牌、300 字符畸形令牌请求 `/health`、`/event` 都返回 403。
    - 3 个隔离进程均已结束，4 个临时目录已删除，之后也没有 dist 下的 Shion 进程残留。
  - **替换**：开始时没有任何 Shion.exe 在运行，不需要用户关闭程序。替换器原地替换，两次改名均一次成功；旧包 220 文件逐个核对后保留为 `D:\desktop\tools\Shion-dev-before-security-20261101`，新目录 220 文件逐个核对一致。Codex / CC 配置哈希与任务开始时一致，存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true` 未变，`Shion-1.0.0-win64.zip` 未变，没有强制结束进程。旧 exe `4834ed5a…55f458`，新 exe `b1c65811…278d6a`。
  - **用户启动新版后只读核对**：PID 5780 来自 `Shion-dev\Shion.exe`（exe 哈希与新包一致），同时监听 127.0.0.1:47613 和 47614；19:28:58 启动，19:29:01 真实数据目录出现 `claude-link.json`（只确认存在，没有读取或记录内容）。启动后日志 13 行，没有 WARNING/ERROR，没有端口被占或令牌写入失败；真实 CC hook 发来的 prompt / working / tool_done 都被新服务端接收（新 hook 带令牌和新服务端对上），prompt 行只有 `None` 和会话 ID，没有提示词内容。
  - 验收清单第 1、4、5 项注明“隔离实例自动验证”并打勾，第 2、3、6、7 项留待日常使用验收。未 push、未发布。

- **2026-11-01 安全修复第二轮**（同分支 `feature/v2-security-fixes`，在 `5164056` 之后新提交，不改写历史；本地提交、未合并、未 push）。来源是 reviewer 子代理对 `5164056` 的复审（结论“可以合并”）加我的独立复核。
  - **应修 1：旧令牌被信任。** 诗音被强制结束后令牌文件会留下；命名管道名是整台机器共用的，别的账户能在诗音没开时同时冒充管道和 47613，hook 就会带着旧令牌发出完整命令、采纳伪造的 allow。（子代理原判断只影响设了 `SHION_PORT` 的情况，复核后更正。）修法：令牌文件加 `pid` / `created`（写入者进程号、FILETIME 创建时间），hook 改用 `loopback.read_link`，只有写入者还在运行才采用令牌。新增 `winproc.process_running`，同一句柄上核对创建时间，并要求退出码是 `STILL_ACTIVE`。**踩坑**：最初只比创建时间，测试发现进程被 `kill()` + `wait()` 后，`Popen` 仍握着句柄，内核对象还在，`GetProcessTimes` 照样成功，旧令牌被当成有效。真实环境里任何握着诗音句柄的程序都会造成同样情况，所以加上退出码判断。Windows 上读不到自己的创建时间时，`write_token` 抛 OSError，按写失败处理。
  - **应修 2：junction 回退。** 令牌读写原来复用 `observer_files.reject_reparse`，会检查所有上级目录，用户目录在 junction 下时联动会悄悄失效。改为 `loopback` 自己读写，只检查数据目录本身和令牌文件本身；写入用同目录唯一临时文件 + `os.replace`，失败时删掉临时文件；读取限 4 KB。`start_linked` 改成返回 `ok` / `port_busy` / `token_failed`，`app.link_warning` 在 `token_failed` 时说新台词 `link_token_failed`（三语）。日志只记异常类型，不记路径。
  - **小问题**：hook 的 `request()` 收到 403 时重读令牌，令牌换了才用新令牌重试一次；`_Server.server_bind` 补设 `server_name` / `server_port`；所有选中会话都因共用进程没法结束时说新台词 `interrupt_shared_process`（三语）。
  - **新增测试**：
    - 写入者已退出（握着句柄的情况）、进程号复用两种情况下 `read_link` 拒绝，6 种缺字段或坏字段也拒绝；
    - 上级目录是 junction 时能读写；数据目录本身或令牌文件位置是 junction 时拒绝，且不往别处写；
    - 不留临时文件；`token_failed` 与三种提示文字；
    - 端到端：只靠 `start_linked` 写令牌，用 hook 真实的 `link_token` 读到并 `/health` 返回 200，退出后读不到；
    - 旧令牌 + 冒充者：2 种事件 × 2 种失效方式，hook 一个请求都不发；
    - 403 后令牌换了能重试成功，令牌没变时不重试、也不熔断；共用进程时的提示语。
  - **验证**：全量 pytest（PowerShell `$LASTEXITCODE`，worktree 内临时 junction，`PYTHONUTF8=1`）汇总原文：`2041 passed, 8 skipped, 2 warnings in 618.99s (0:10:18)`，退出码 0；两条警告都是既有的 Pillow `getdata()` 弃用提示。`tools/bundle_smoke.py` 仍未打包运行。
  - **范围外**：ChatGPT 观察端凭据仍会检查所有上级目录（已记入 v1.1 待办）。

- **2026-11-01 v2.0.0 发布前安全修复**（分支 `feature/v2-security-fixes`，从 `1500086` 派生，worktree `..\shion-security-fixes`，本地提交、未合并、未 push）。起因是同日的发布前审查（master `74121dc`..`1500086`，结论“修复后发布”，没有阻塞项）。
  - **令牌（应修 1、3）**：新模块 `shion/loopback.py`（只用标准库）。诗音每次启动生成 `secrets.token_hex(32)`；`server.start_linked` 先删旧的 `claude-link.json`，绑定 47613 成功后才写新令牌（复用 `observer_files.replace_private`，先清掉崩溃残留的暂存文件），端口被占时不写；`stop_linked` 退出时先删令牌再停服务。服务端 `_allowed()` 对所有路由（含 `/health`）核对 `Authorization: Bearer`（`hmac.compare_digest`），不对就 403、不读请求体。hook 读不到令牌就不发任何请求（按诗音没开处理），`probe_health` 重新读令牌。修复前，抢先占住 47613 的进程（包括别的 Windows 账户）能收到完整命令并回 allow，还能注入反馈、解除暂停；`/event` 等接口本机任何进程都能调。
  - **独占绑定**：47613 的 `_Server.server_bind` 和 47614 的 `_ExclusiveHTTPServer` 在 Windows 上设 `SO_EXCLUSIVEADDRUSE`，不设 `SO_REUSEADDR`（47614 原来用标准库默认，会设 `SO_REUSEADDR`）。
  - **ChatGPT 状态（应修 2）**：`TaskLedger.uncertain` 改成带 setter 的属性，并记录 `uncertain_at`，读取时仍是原来的粘滞布尔值（调度器不变）。`ChatGPTConnection` 的 `status()`/`activity()` 只看最近 600 秒（`UNKNOWN_WINDOW`）内的不确定/断开；`_unobserved_start` 只在启动后 `ledger.ttl` 内算；不开调度器时一次降级只断开一次，然后清标记。修复前 `_unobserved_start` 从不清除，菜单“活动”永远显示“待确认”，切换一次开关也会永久卡住。
  - **小问题**：`interrupt_work` 中，选中会话和没选中的工作会话报来同一个 CC 进程（pid + 创建时间）时不结束进程、改为只停下这个会话；hook 新增 `read_save_strict()`，存档读不到或损坏时不发 `prompt_head`。
  - **测试**：`tests/link_support.py` 加 conftest 的 autouse fixture：测试里起的 ShionServer 按端口登记令牌、写进当前 `SHION_DATA_DIR`，`run_hook` 在目标目录没有令牌时补上，hook 模块的令牌缓存每个测试清零。原来 13 个文件共 156 个用例因缺令牌失败，已全部改好。“连不上 / 不回包 / 熔断”这类用例改为先写一个令牌，保证仍真的去连。
  - **新增用例**：8 个路由 × 6 种错误令牌都返回 403；错令牌不转发事件、不取反馈、不能解除暂停；冒充者占着端口回 allow 时 hook 一个请求都不发（PermissionRequest / UserPromptSubmit / PostToolUse）；旧令牌被真服务端拒绝时不给决定；两个端口二次绑定失败；`start_linked` 写/删令牌、端口被占不写；真实 app 子进程不带令牌 403、第二个实例没有令牌文件；ChatGPT 五个时效用例；共用进程中断三个用例；prompt_head 在没有存档、存档损坏时不发。
  - **工具**：`bundle_smoke.py` 的 MockHooks 要求令牌，并新增 `hook-sends-link-token`、`server-rejects-missing-token` 两项；`benchmark_hooks.py` 写令牌。两者只做了编译检查，**没有打包、没有实际运行**。
  - **验证**：全量 pytest（worktree 内，临时 junction 指向主仓库 `.venv` 和 `assets/sprites/raw`，`PYTHONUTF8=1`）。
    - 第 1 次：`1 failed, 2022 passed, 8 skipped, 2 warnings in 623.91s`。唯一失败是 `test_permission.py::test_http_input_validation_and_limits` 发超大请求体时遇到 `ConnectionAbortedError [WinError 10053]`（服务端没读完请求体就回 400 并关连接），和调度审查报告里记过的同类偶发问题一样；单独连跑 15 次都通过。
    - 第 2 次：`2023 passed, 8 skipped, 2 warnings in 630.57s`，但测试全部通过后 Python 进程退出码是 `-1073740791`（0xC0000409，退出阶段崩溃）。
    - 第 3 次（`-X faulthandler`）：`2023 passed, 8 skipped, 2 warnings in 626.86s`，退出码 0，没有崩溃栈。
    - 第 4 次（和第 2 次同样的命令）：`2023 passed, 8 skipped, 2 warnings in 614.04s`，退出码 0。
    - 原代码 `1500086` 在临时 worktree 跑一次：`1955 passed, 8 skipped, 2 warnings in 604.41s`，退出码 0。
    - 退出阶段崩溃只出现过 1 次、没复现、原因未查明，**不能断定和本次改动无关**，后续全量留意。两条警告都是既有的 Pillow `getdata()` 弃用提示。
    - Git Bash 下记到的退出码 127 不可信（审查时原代码也是 127），本次改用 PowerShell 的 `$LASTEXITCODE`。
  - `tools/check_private.py` 检查暂存区通过，`git diff --cached --check` 通过。基线 worktree 已先单独解除 junction、扫描确认无 reparse point 后移除。

- **2026-11-01 合并 session-labels，替换 Shion-dev**：`git merge --ff-only feature/session-labels`，HEAD 由 `e5fee12` 快进到 `4ecaaaa`。worktree `..\shion-session-labels` 扫描无 reparse point（junction 已在上一任务解除）、无未提交改动（只有被忽略的 `build/` 和缓存），用 `git worktree remove`（未加 `--force`）移除，分支保留；主仓库 `.venv` 与 `assets/sprites/raw`（23 项）完好。打包沿用 `build/per-session-replacement-20261031/` 的脚本，只改目录名（证据在忽略目录 `build/session-labels-replacement-20261101/`）：依赖版本一致，不生成 ZIP，bundle_smoke 97 项通过，观察端 stdio 烟测与上次替换响应完全一致；新包 220 文件。替换器等用户退出旧诗音后原地替换，两次改名均一次成功，旧包 220 文件逐个核对后保留为 `D:\desktop\tools\Shion-dev-before-session-labels-20261101`，新目录 220 文件逐个核对一致；Codex/CC 配置哈希与任务开始时一致，存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true` 未变，`Shion-1.0.0-win64.zip` 未变，没有强制结束进程。旧 exe `2c3f163b…81cd38`，新 exe `4834ed5a…55f458`。用户启动新版后只读核对：PID 365416 来自 `Shion-dev\Shion.exe`，同时监听 127.0.0.1:47613 和 47614，09:15:53 启动后日志 19 行、无 WARNING/ERROR；UserPromptSubmit 的日志行只有 `prompt None <会话 ID>`，没有提示词内容。未 push、未发布。

- **2026-11-01 同项目多会话用第一句话区分**（分支 `feature/session-labels`，从 `e5fee12` 派生，worktree `..\shion-session-labels`，本地提交、未合并、未 push）：原来 hook 的 UserPromptSubmit 不发提示词。现在 hook 新增 `prompt_head`（stdin 的 `prompt` 去掉 Cc/Cf 字符、压缩空白、最多 40 字），只在 UserPromptSubmit 且存档 `privacy_mode` 不是 true 时发送；服务端 `clean_prompt_head` 与 `clean_project` 同法清理，非字符串、为空或超过 40 字只忽略该字段（不 400）。控制器只对 `prompt` 事件把它交给 `SessionNames.note`，后者只记每个会话的第一句、截成 12 字 +“…”，存在内存字典里（随会话淘汰、`forget_all` 清除），隐私模式下不记录，打开隐私模式时 `forget_prompts()` 清掉已记的摘要。不写日志（控制器日志只有事件类型/detail/会话 ID，服务端只记请求路径）、不进存档。显示规则：文件夹只有一个会话 → 文件夹名；同文件夹多个 → “文件夹名 · 摘要”，摘要相同再加“(n)”，没有摘要的退回原来的“(n)”编号；隐私或无文件夹名仍是“会话 n”。工作遥控多会话子菜单的会话项按 240 逻辑像素截断、全文放 tooltip；检查点面板由 24 字截断改为同样 240 像素截断（`sessions.LABEL_W`）。`render_menu.py` 新增 `same_project` 场景（新场景在 `--baseline` 对照里跳过）。新测试 `tests/test_session_labels.py` 25 个。验证：全量 pytest（`--basetemp` 在 worktree 内 `build/pytest-tmp`）汇总原文：`10 failed, 1945 passed, 8 skipped, 2 warnings in 584.03s (0:09:44)`；10 个失败全在 `tests/test_process_sheets.py`，原因同前几次：新 worktree 缺 `assets/sprites/raw` junction，补上后单独重跑 `14 passed`。`render_menu.py --platform windows` 三语 `same_project` 子菜单已自查（显示“shion-pet · 把菜单截断的问题修一下，…”“shion-pet · Write the RE…”，不提交截图）。局限：摘要按字符截断，英文 12 字较短；同一会话第一句之后改名不跟随（按需求只记第一句）。

- **2026-10-31 合并 remove-face 与 per-session-remote，替换 Shion-dev**：`git merge --ff-only feature/remove-face`（`242b5bc`），再 `git merge --no-ff feature/per-session-remote`，合并提交 `7abd815`。唯一冲突在 `docs/progress.md`：两边在同样位置各加了状态、下一步和记录行，两边都保留；另外 `242b5bc` 把这个文件存成了 CRLF（`.gitattributes` 是 `* text=auto`），而且 remove-face 记录里的 `..\claude-pet-wt\remove-face` 中 `\r` 被写成了回车字符，合并时已恢复路径，并按 LF 存储。快照 `scheduler_disabled_a55825f.json` 没有冲突（per-session 没改它），合并后快照测试直接通过，`menu_sha256` 不需要重算，文件与 `242b5bc` 一致。全量 pytest（`--basetemp=.venv/preview-run/merge-per-session`）汇总原文：`1 failed, 1929 passed, 8 skipped, 6 warnings in 517.01s (0:08:37)`；唯一失败是已知的 `test_install_hooks.py::test_corrupt_json_not_touched`（GBK 解码），`PYTHONUTF8=1` 单独重跑 `1 passed`。两个 worktree（`remove-face`、`per-session-remote`）扫描无 reparse point、无未提交改动，用 `git worktree remove`（未加 `--force`）移除，分支保留，空的 `claude-pet-wt` 目录已删除。打包沿用 `build/lines-turn-replacement-20261031/` 的脚本（证据在忽略目录 `build/per-session-replacement-20261031/`）：不生成 ZIP，bundle_smoke 97 项通过，观察端 stdio 烟测与上次替换响应完全一致；新包 220 文件，比旧包少的正好是 8 张 `turn_*.png`。替换器等用户退出旧诗音后原地替换，两次改名均一次成功，旧包 228 文件逐个核对后保留为 `D:\desktop\tools\Shion-dev-before-per-session-20261031`，新目录 220 文件逐个核对一致；Codex/CC 配置哈希与任务开始时一致（Codex `config.toml` 相比上次替换后有变化，是本任务开始前就有的），存档 `v2_scheduler_enabled=false`、`claude_link_enabled=true` 未变，`Shion-1.0.0-win64.zip` 未变，没有强制结束进程。旧 exe `f852c131…75fb8d`，新 exe `2c3f163b…81cd38`。用户启动新版后只读核对：PID 342244 来自 `Shion-dev\Shion.exe`，同时监听 127.0.0.1:47613 和 47614，22:48:07 启动后日志事件正常、无 WARNING/ERROR。未 push、未发布。

- **2026-10-31 删除朝向鼠标（face）并停用 turn 帧**（分支 `feature/remove-face`，从 `5062919` 派生，worktree `..\claude-pet-wt\remove-face`，本地提交、未合并、未 push）：face 借用 turn_2 / turn_8 侧身，看起来仍像转身，一并删除。删去 `behavior.FACE_SECONDS`、`PetWindow.face()` 及只为它服务的 `_automatic_pose`（`idle_motion_active` 现只看自动跳跃）、controller 待机与菜单两处分支、三语 `action_face`、截图 `--face` 参数（现在传入会被 argparse 拒绝）；`SEQUENCE_GROUPS` / `EXACT_SEQUENCES` 去掉 turn，`assets/sprites/turn_1～8.png` 已删除，旧目录残留的 turn_*.png 会被忽略；`tools/process_sheets.py` 的 `SHEETS` / `EXPECTED` 去掉 `turn_sheet`（raw 里的 turn_sheet.png 保留不动，脚本不再读取也不再生成 turn 帧，`--only turn` 不再是合法选项；`process_sprites.py` 本就跳过 `*_sheet`）。待机动作 `IDLE_ACTIONS = ("jump", "expression")`，权重 1 : 2：自言自语可抽时 talk 10% / jump 30% / expression 60%（原 face/jump/expression 各 30%），冷却中 jump 33.3% / expression 66.7%（原各 33.3%）。存档从未有 face/turn 字段，新增测试确认带陌生字段的旧档照常加载。原来以 face 为载体的淡化/遮罩/中断测试改用跳跃或静止的捏脸松手姿势。`scheduler_disabled_a55825f.json` 只刷新 21 个 `menu_sha256`，其余字段逐项比对一致。验证：全量 pytest（`--basetemp=build\pytest-tmp-face`，在 worktree 内，`PYTHONUTF8=1`）汇总原文：`1877 passed, 8 skipped, 2 warnings in 517.70s (0:08:37)`，退出码 0；两条为既有 Pillow `getdata()` 弃用警告。截图 `--snapshot --jump --at .24` 正常。
- **2026-10-31 工作遥控按会话区分**（分支 `feature/per-session-remote`，从 `5062919` 派生，worktree `..\claude-pet-wt\per-session-remote`，本地提交、未合并、未 push）：hook 所有事件多带 `project`（只是 `cwd` 的文件夹名，不带完整路径），`/feedback/take` 也带 `session`；服务端 `clean_project` 去掉 Unicode Cc/Cf 字符和首尾空白，非字符串、含 `/` `\`、为空或超过 64 字时只丢掉这个字段，事件照常，旧格式事件不受影响。`RemoteHub` 新增按会话暂停、按会话放行（全局暂停中被单独放行的会话）和按会话的一次性“结束这一轮”代数；`wait_gate` 在全局或自己会话暂停时等待，不带会话的旧请求只看全局。UserPromptSubmit 只放开自己会话；为了单会话时与原来一致，放行某会话后如果没有别的会话单独停着或在等，就整个解除全局暂停；多会话选“全部”停下时会同时给每个会话单独打标记，所以 A 说话不会放掉 B。新文件 `shion/sessions.py` 负责菜单名称（首次出现顺序、同名 “(2)”、隐私或无名时“会话 n”）。菜单：0/1 个会话时走原代码路径，三语菜单树与 `5062919` 逐项一致；≥2 个时四个按钮变成子菜单（各会话 + “全部”），“继续”在多个目标时也是子菜单，“有问题……”选完会话再弹输入框。立即中断只结束选中会话的工具进程，收尾只解除这些会话的暂停。反馈队列项带可选 `session`，每个归属各最多 5 条；带 session 的取走“自己的 + 无归属的”，旧请求只取无归属的；“全部”给每个相关会话各放一份，好感度、表情、台词只算一次。检查点：1 个会话停住仍是暂停标签，文字为“暂停中：{名称}”；≥2 个停住时换成 `badge.CheckpointPanel`，每个会话一行“继续 / 结束这一轮”，不抢焦点、只响应鼠标、出现或会话集合变化后 0.6 秒才生效、键盘无效。新增三语 key：`pause_label_named`、`session_n`、`menu_all`、`checkpoint_title`、`checkpoint_resume`、`checkpoint_end`、`checkpoint_ended`。新测试 `tests/test_per_session_remote.py` 53 个。`render_menu.py` 增加 `one_session`、`two_sessions` 场景；基线快照 `scheduler_disabled_a55825f.json` 未改动（单会话菜单不变，快照测试直接通过）。验证：全量 pytest（`--basetemp=build\pytest-tmp\full`，在 worktree 内）汇总原文：`1 failed, 1951 passed, 8 skipped, 6 warnings in 494.08s (0:08:14)`；唯一失败是已知的 `tests/test_install_hooks.py::test_corrupt_json_not_touched`（子进程 stderr 按 GBK 解码失败），设 `PYTHONUTF8=1` 单独重跑 `1 passed`，与本次改动无关。三语单/双会话菜单截图和双会话停住的面板截图已自查（在忽略目录 `build/menu-shots/`、`build/checkpoint-shots/`，不提交）；面板最初因字体回退把标题裁掉一半，已改用台词字体并设最小行高。范围外发现（未实现）：单会话时没有“结束这一轮”的界面按钮（只有多会话面板有）；“继续（这一轮已结束）”只记最近一个会话；授权面板不显示项目名。
- **2026-10-31 删除 Codex 新开会话自动拉起**（分支 `feature/remove-codex-autolaunch`，从 `fad0e3a` 派生，worktree `..\claude-pet-wt\remove-codex-autolaunch`，本地提交、未合并、未 push）：诊断结论是 Codex 把 MCP 观察端放进 `KILL_ON_JOB_CLOSE` 且不允许脱离的 Job，观察端拉起的诗音会随 Codex 退出或关闭 MCP 一起被结束，所以决定不再由 Codex 拉起，Codex 用户改用“开机自启”。删除 `codex_mcp.py` 的 `autolaunch()`、`codex_link_enabled()`、`_AUTOLAUNCH`、`dispatch()` 中的调用及相关 import，`git diff d907e33 -- shion/codex_mcp.py` 为空（观察端转发、心跳、租约与 668962c 之前一致）；`launcher.py` 删除 `AutoLaunch`、`AUTOLAUNCH_COOLDOWN` 及不再用的 `logging`/`time`，保留 `shion_running()`、`launch_shion()`、`INSTANCE_NAME`；`tests/test_autolaunch.py` 删掉 Codex 观察端拉起的全部用例，Claude 拉起、公共函数、Claude 联动开关、单实例竞争用例保留；三语 README 常见问题各加一条“用 Codex 时诗音不会被自动拉起，建议右键 → 设置 → 开启开机自启”；spec.md 末节记录决定与原因。Claude hook 的 `claude_link_enabled` 判断、单实例互斥锁（`fad0e3a`）、Codex 窗口层级跟随（`4a6e9eb`）均未改动。验证：全量 pytest（`--basetemp=build/pytest-tmp4`，在 worktree 内）汇总原文：`1913 passed, 8 skipped, 2 warnings in 648.08s (0:10:48)`，退出码 0。首轮为 `11 failed, 1902 passed, 8 skipped, 6 warnings in 628.37s (0:10:28)`：其中 10 个是 `tests/test_process_sheets.py`，原因是新 worktree 没有 `assets/sprites/raw` junction（补上后通过）；另 1 个 `tests/test_install_hooks.py::test_corrupt_json_not_touched` 是子进程 stderr 按本机 GBK 解码失败，主仓库未改动的 `fad0e3a` 上同样失败，设 `PYTHONUTF8=1` 后通过，与本次改动无关。`tools/check_private.py` 暂存区通过，作者与提交者邮箱均为 noreply 邮箱。
- **2026-10-30 单实例改用命名互斥锁**（分支 `feature/codex-autolaunch`，本地提交、未合并、未 push）：`SingleInstance.acquire()` 在 Windows 上先 `CreateMutexW("Local\\" + 实例名)`（原子，实例名仍支持 `SHION_INSTANCE_NAME` 覆盖），返回 `ERROR_ALREADY_EXISTS` 就关掉本次句柄、照原样连一下已有实例的管道后返回 False；拿到锁的实例在整个生命周期内持有句柄，`release()` 才关闭，崩溃由系统回收。拿到锁后仍做原来的管道连接检查（兼容没有互斥锁的旧版诗音），再 `listen`，listen 失败会释放锁。命名管道服务保留，`launcher.shion_running()` 和 hook/观察端接口不变；非 Windows、创建锁失败时行为与原来一致。上一条的 xfail 竞态用例改为必须只剩一个：4 个进程对齐到同一时刻、一个测试里连跑 3 轮，另独立连续跑 5 次全部通过；另有 `tests/test_single_instance.py` 覆盖锁语义。
- **2026-10-30 Codex 桌面端窗口层级跟随**（分支 `feature/codex-autolaunch`，本地提交、未合并、未 push）：未开“置于最上层”时，`shion/foreground.py` 原来只在 `claude.exe` 前台时让诗音紧邻其上，Codex 桌面端窗口会盖住诗音。跟随目标改成常量集合 `CLAUDE_IMAGES={"claude.exe"}`、`CODEX_IMAGES={"chatgpt.exe"}`；Codex 只在控制器的 `_follow_codex_window()` 为真时才跟随（ChatGPT 联动 `connection_state()=="installed"`，即已安装且未临时关闭；关闭/未安装/读失败都不跟随，判断在每次前台事件时动态进行）。不加任何终端程序；重验、不激活、不绑定 owner、置顶时不跟随都不变，日志与注释改为中性说法。Codex 桌面端实际映像：已装包 `OpenAI.Codex_26.1027.3384.0_x64__2p2nqsd0c76g0`，主窗口（Chrome_WidgetWin_1，标题 ChatGPT）属于该包 `app\ChatGPT.exe`，只读枚举进程与可见窗口确认。局限：按映像名匹配，另一个同名 `ChatGPT.exe`（独立 ChatGPT 桌面应用）也会命中。
- **2026-10-30 Codex 新开会话自动拉起诗音（已于 2026-10-31 删除，见上方记录；`shion/launcher.py` 的公共函数和 Claude 侧改动保留）**（分支 `feature/codex-autolaunch`，从 `d907e33` 派生，worktree `..\claude-pet-wt\codex-autolaunch`，本地提交、未合并、未 push）：新增公共模块 `shion/launcher.py`（仅标准库）——`shion_running()`（命名管道检查，从 hook 挪来）、`launch_shion()`（DETACHED/NEW_PROCESS_GROUP/优先 BREAKAWAY、标准流 DEVNULL、`SHION_LAUNCHED_BY_HOOK`，只 Popen 不等待）、`AutoLaunch`（30 秒冷却，异常只记日志）和 `INSTANCE_NAME`（`shion/app.py` 改为从这里取）。Claude hook 改为薄包装调用它，行为不变；唯一新增：存档 `claude_link_enabled` 为 false 时 SessionStart 不拉起（读失败/缺字段按默认开启）。Codex 观察端 `dispatch()` 在转发 SessionStart 之后调用 `AutoLaunch.attempt`，管道返回 False 才拉（True/None 都不拉），任何异常只记日志、`observe_lifecycle` 返回不变；Codex 的“临时关闭”开关实际在 `chatgpt-observer.json` 的 `enabled`（不在 state.json），只有明确为 false 才不拉。conftest 新增 autouse 保护，所有测试都不能真的拉起诗音。**发现（已在后续提交修复，见下一条）**：Qt 6.12 在 Windows 上允许两个 `QLocalServer` 同时 listen 同名管道，`SingleInstance.acquire()` 先连后 listen，多个进程在同一毫秒内都通过“连接失败”检查时会同时成为赢家（实测 3～4 个对齐启动的进程全部 WON）；先后相隔几百毫秒则只有一个。另：刚拉起时那条 SessionStart 会丢（1 秒预算内不等 /health）。
- **2026-10-30 菜单连接管理对齐 + Claude 临时关闭联动**（分支 `feature/menu-parity`，worktree `..\claude-pet-menu-parity`）：两个子菜单统一为“连接：… / 活动：… / ─ / 连接 / 查看配置 / 临时关闭联动（重新开启联动）/ 断开并移除配置”，三语文案两边一致；顶层每个提供方一行“{名称}：{连接} · {活动}”，截断 240 挂 tooltip。Claude 新增临时关闭：`RemoteHub.set_link_enabled` 关闭授权队列（撤回全部请求，含已决定未取走的）、清暂停和中断并唤醒检查点等待；服务端 `/event` 忽略、`/pause/wait` 放行、`/permission/open` 不给 id、`/permission/wait` 一律 gone、`/feedback/take` 返回空且不取走队列；hook 脚本未改。开关存 `state.json` 的 `claude_link_enabled`，旧档默认开启。删除不再使用的 `menu_connect/menu_reconnect/menu_disconnect/menu_connection_status/chatgpt_install/disable/enable/uninstall`，`test_lines.py` 白名单缩小为 `connection_explain`、`menu_claude`。`scheduler_disabled_a55825f.json` 只刷新 21 个 `menu_sha256`，其余字段逐项比对一致。全量（`--basetemp=build\pytest-tmp\full2`）：`1870 passed, 8 skipped, 2 warnings in 607.21s (0:10:07)`，两条为既有 Pillow `getdata()` 弃用警告。第一次全量有 2 个失败：`test_menu_contents` 是旧断言没跟上，已改；`test_install_hooks.py::test_corrupt_json_not_touched` 是环境问题：当前会话设了 `PYTHONIOENCODING=utf-8`，子进程按 UTF-8 写 stderr，测试用 `text=True` 按 GBK 解码；去掉该变量后通过，与本改动无关。`render_menu.py --platform windows --baseline dc9fe3d` 三语无未挂 tooltip 的截断，ChatGPT 子菜单比旧版窄，英文 Claude 子菜单约宽 70 逻辑像素（“Disconnect and remove configuration”）。范围外发现：`ChatGPTConnection._unobserved_start` 从未被清除，所以 ChatGPT 活动总显示“待确认”；工作遥控置灰时好评/差评也无法入队（按要求整体置灰）。未合并、未打包、未部署、未 push。

- **2026-10-30 Codex 控制能力隔离实验**：仅临时 CODEX_HOME、临时项目、独立 CLI/TUI/app-server 和固定回环响应器，不改产品代码、真实 Codex/CC 配置或 Shion-dev。同步 Pre/Post 每次 125 秒等待可用；Pre deny 只挡当前调用，Post continue:false 的 stopped 状态仍未阻止下一工具。官方 turn/interrupt 可结束轮次，但两组测试父子工具进程八秒后仍运行。PermissionRequest allow/deny 有效；超时/崩溃回原审批，自动审批仍可能放行；事件输入无可靠人工等待标志且缺 tool_use_id/request_id。桌面独立实例隔离未证实，GUI 六项均未验证。详见 [控制实验报告](experiments/shion-v2-codex-control.md)，不开放 ChatGPT 控制能力；后续须先解决失败关闭、进程归属和桌面隔离。本地提交，不 push。
- **2026-10-30 `.venv` 事故恢复与替换收尾**：移除菜单 worktree 时漏解除指向主 `.venv` 的 junction，误删共享依赖；已单独解除链接、清理残留并重装运行、测试、构建依赖及 pip。本次 `pip check` 和全量 pytest 通过（汇总见上）；旧环境无完整版本清单，不保证所有开发依赖逐版本还原。`CLAUDE.md` 已加入 junction 单独解除及 worktree 移除前 reparse point 扫描规矩。替换状态 `complete`；只读核对新 exe 哈希与记录一致、47613/47614 均归新 Shion-dev（PID 30104）、08:39:40 最新启动以来日志正常、存档 `v2_scheduler_enabled=false`。证据在忽略目录 `build/menu-label-replacement-20261030/`；本次仅改规则与进度文档，本地提交、不 push。
- **2026-10-30 菜单给 Claude Code 标名**（分支 `feature/menu-claude-label`，`81b8361`）：顶层状态行改为“Claude Code：{状态}”；“AI 连接”拆成并列的“Claude Code ›”（禁用状态行 + 连接/重连/断开，tooltip 不变）和“ChatGPT ›”（原子菜单迁入，未启用 ChatGPT 时只剩前者）。新增 `menu_connection_status`、`menu_claude`、`menu_chatgpt` 三个 key，没有改 `connection_status`（双击状态气泡仍用）和 `chatgpt_manage`（ChatGPT 面板窗口标题），所以气泡和面板标题仍不出现 Claude。spec 品牌规则改为只有连接类标签可写“Claude Code”，`test_lines.py` 按新边界断言，其余文案仍不含 Claude。`scheduler_disabled_a55825f.json` 只刷新了 `menu_sha256`（菜单形状变了），其余字段未动。验证：全量 1820 passed、8 skipped、10 failed；10 个失败都在 `test_process_sheets.py`，原因是 worktree 缺被忽略的 `assets/sprites/raw/`，链接后 14 项全过，主仓库同样通过，不是本次改动造成；`render_menu.py --platform windows` 三语截图无截断或过宽（最宽为 en 路径失效状态行，约 450px）。未打包、未 push、未部署。
- **2026-10-29 文档整理**：8 份原未跟踪实验文档和 2 个脚本纳入本地版本管理；加上迁移的合并报告共 9 份文档。ACL 报告与探针标记废弃；先暂存扫描再脱敏。进度历史原文按月归档，首页改为当前交接摘要；没有修改产品代码、测试或实验脚本运行逻辑，没有打包、部署或 push。
- **2026-10-29 合并与审查**：热修和 V2 已合并；GUI 空档恢复审查修复已保留，最新验证及历史扫描限制见合并报告。早先热修 worktree 的失败记录留在归档，不覆盖本次合并全量结果。
- **2026-10-29 阶段 2**：租约与 P1～P5 核心、菜单及 GUI 隔离接入完成；真实能力缺口和默认关闭边界继续保留。
- **2026-10-29 阶段 1 续验**：工具离线放行、新会话恢复、单次 MCP 无响应后恢复、Interrupt 观察与视觉收尾有证据；进程及时终止、原会话自动恢复等仍未证明。新 41 次 Hook 与旧 21 次分组保留；两个现有项目仅顺序任务通过。
- **2026-10-28**：v3 真实安装和 PermissionRequest 修复部署；阶段 1 部分验收。事务/精简方案隔离验证通过；CLI 嵌套目录 ACL 阻断后根目录离线命令通过，未手工改 ACL。
- **2026-10-27**：全局观察 MVP 开发，后续已完成真实安装；公开历史用户名清理和隐私扫描工具落地，私有备份未清理。旧独立 ACL 方案已废弃，仅保留决策记录。

原条目核对（不计本页新增摘要）：原状态记录 58 条 + 历史小节 58 个 + v1.1 待办 4 条 = 120 条；归档保留 116 条，本页原样保留 4 条，合计 120 条，缺失 0。逐条原文及重复次数核对通过；包括嵌套清单在内的原列表项 780 条 → 780 条。归档原文加回本页原 v1.1 待办后，可逐字节重建整理前的 progress.md。人工明细的历史勾选状态未改写。
