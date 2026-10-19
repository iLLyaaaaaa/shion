# 进度记录

> 每个步骤结束时更新这份文件。新会话从这里接手。步骤定义见 `docs/spec.md`「开发步骤」。

## 当前状态
- **v0.2 Claude Code hooks 已实现**（pytest 共 **287** 个通过，reviewer 已审、必须修的已修），见下面「v0.2」一节。**待用户验收**真机项；验收通过后用 `tools/install_hooks.py` 装到用户级，再按 v0.2.1 → v0.3 → v0.4 → v0.5 → v1.0 的顺序继续（v0.2.1 不依赖真机验收，可以先做）
- v0.1 及之后的素材/三语/动画打磨都已完成，真机验收清单仍在下面各节，用户回来后一次性验收
- 2026-10-19 用 reviewer 审查了动画打磨与自我介绍两个 commit（`39b0316`、`ea6aac3`）：**没有必须修的问题**，未改代码。可选项（都没做）：①端口被占用时 `port_busy` 提示会立刻盖掉首次启动的 intro（`controller.py:132`、`app.py:136-138`）；②非首次启动的 `greeting` 台词是“Claude 来啦”，Claude 不一定在，可考虑专用 `startup` 类别；③同状态重复 `set_state` 不再重播动画，以后要重播用 `immediate=True`；④下落中改大小会重置下落速度；⑤淡化时每帧做 `toImage` 转换，卡了再缓存预乘 ndarray
- v0.2 之后的顺序： 把 server 回调接到 Qt 信号 → 审查
- 环境：`.venv` 已建好（Python 3.10.11，requirements.txt 已装），`shion/`、`tests/` 包已建。git 仓库已初始化，本仓库 `user.email` 已是 noreply 邮箱

## v0.2：Claude Code hooks（2026-10-19，用户外出，只做自动化验证）
- 新增 `hooks/shion_hook.py`（只用标准库）：5 个事件映射到 session_start/prompt/working/stop/notification；UserPromptSubmit 调 `/praise/take`，count>0 且存档 `inject_praise` 不为 false 时用 UTF-8 字节写出那句表扬；SessionStart 在 `/health` 不通时用 `.venv\Scripts\pythonw.exe -m shion` 脱离父进程拉起桌宠并最多等 3 秒。任何情况返回 0、stderr 为空；请求不走系统代理、单次超时 0.5 秒，另有总时限兜底（普通事件 2.5 秒、SessionStart 12 秒）。
- 新增 `tools/install_hooks.py`、`uninstall_hooks.py`、`hooks_config.py`：`--settings PATH`（默认用户级 `~/.claude/settings.json`）；写前备份为 `*.shion-backup-时间戳`，合并不覆盖、可重复安装、卸载只删 Shion 条目；坏 JSON 不改文件；文件不存在/没有变化时卸载不写盘。
- 桌宠侧只加日志：`收到事件：…`、`取走夸奖：N`，用日志验证事件有没有到。
- **开发阶段只装在项目级** `.claude/settings.local.json`（已 gitignore，含本机绝对路径）；**没有动用户级 `~/.claude/settings.json`**。
- 验证：pytest 287 个通过（新增 hook 子进程测试、服务卡死/关闭/大 stdin、安装卸载往返等）；手动冒烟（隔离端口和数据目录）逐个事件日志正确；**真实 `claude -p` 端到端**：桌宠关闭时 SessionStart 自动拉起，日志依次出现 session_start / prompt / working / stop。
- **踩坑**：Claude Code 在这台机器上用 **PowerShell** 执行 hook，命令以带引号的路径开头（`"D:/…/python.exe" …`）会解析失败（hook 报错但不阻塞）。所以命令改成以不带引号的 `python` 开头：`python "D:/…/hooks/shion_hook.py" Stop`，bash 和 PowerShell 都能解析。代价：要求 PATH 里有真 python（install 脚本会检查，Microsoft Store 占位程序会被拒）；项目路径含 `$`、反引号、引号时拒绝安装。
- **待用户验收**：①桌面端 Code 标签页和终端里开会话时桌宠自动出现、没有控制台窗口一闪；②用工具时 working、结束 done 的观感；③摸头/夸夸后的下一条消息里 Claude 是否自然回应表扬；④关掉桌宠时 CC 完全无感（PreToolUse 每次多一个 python 进程，约 0.1 秒）；⑤桌面端 Code 标签页是否也读到项目级 `.claude/settings.local.json`（只在终端测过）。
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
- **待用户验收**：实时淡化/回弹是否自然；连续快速摸头、拖动、松手的跟手感；idle 小动作频率和幅度；淡化中和动画后的真实桌面点击穿透；高分屏下的实际流畅度；中/英/日首次介绍、重启问候及静音体验。自动化和静态截图不算这些项目的人工验收。
- 用户已明确授权本次验收清单标待验收后提交。下一开发步骤仍是 **v0.2 Claude Code hooks**；本次不 push。

## 2026-10-19：截图视觉检查（用户外出，代查静态画面）
- 使用 `.venv\Scripts\python -m shion --snapshot`，原生 Windows Qt 平台生成 **12 张状态截图 + 中/英/日各 4 张气泡截图**：每种语言按字数挑最长的两条台词、使用大计数的状态文字（9999 天 / 99999 次 / 好感度 999999）和端口占用提示，共 24 张。
- 总览：`docs/preview.png`（1280×2449），已加入 `.gitignore`，**不提交**。单图、三语细节图、生成脚本、检查结果和测试日志在已忽略的 `.venv/preview-run/`。
- 已目视检查总览和三语原尺寸细节：12 张状态内容正常；未见方块字、气泡文字越界、遮挡人物或位置异常。另对 90 条文本实例检查 Qt 字形缺失和折行绘制边界，均通过，未改程序或素材。
- 测试：`.venv\Scripts\python -m pytest -q --basetemp=.venv/preview-run/pytest-temp-20261019`，**237 passed**；2 条现有 Pillow `getdata` 弃用警告。默认 pytest 临时目录访问被拒（WinError 5），改用项目内独立临时目录后通过。
- 此次只完成静态画面检查；上面的拖动、点穿、焦点、高分屏、打字机/淡出等真机交互清单仍待用户回来验收。下一开发步骤仍是 v0.2 Claude Code hooks。本次未 commit。

## 换 2.3 头身 Q 版精灵图（v0.1 之后的素材更新）
- 精灵图 448x512（人物高约 480，头约 45%），`tools/process_sprites.py` 已重写；旧图备份在 `old_4.3heads/`（已 gitignore）
- 摸头判定区 35% → 45%（`pet_window.HEAD_FRAC`）；默认高度 240 → 200；大小档位 160/200/260/320
- **存档里如果已是旧高度（如 240）不会自动变**，右键 → 大小 → 200 选一次即可
- 测试：`test_anchor_dizzy_sway...` 的脚水平漂移容差 3 → 12px（新图脚更宽，最低 8 行在倾斜时只剩一只脚，是度量方式的问题，不是脚真的在滑）；新增摸头区测试，pytest 共 211 个通过
- 待用户真机确认：200 高度下观感、头部 45% 的悬停/摸头手感

## 多语言（中/英/日）
- `shion/lines.py` 重写：`Lines(lang, rng, directory)`、`set_language`、`ui(key, **kw)`、`font_fallback`、`available_languages()`（扫描 `assets/lines/*.json`）、`resolve_language(saved, locale, codes)`；缺 key 回退中文
- 存档新增 `language`（None=还没选）；首次启动跟随系统语言（zh→中、ja→日、其他→英）并写入存档
- 控制器/app 的界面文字全部走 `lines.ui()`；右键菜单新增「语言」子菜单，切换立即生效并存档；气泡 `set_font_fallback` 追加备选字体；`--snapshot --lang ja` 可看日文气泡
- pytest 共 237 个通过；日文气泡截图正常（不是方块）
- 待用户真机确认：右键 → 语言 切换三种语言的观感；删掉存档里的 `language` 后按系统语言启动；日文字体在你机器上显示正常
- 注意：`zh.json` 必须完整（它是回退的底）；以后新增台词类别/界面 key 要先加到 zh

## 已完成
- [x] 美术素材：12 张精灵图已处理好（`tools/process_sprites.py`）
- [x] 规格文档
- [x] v0.1-3 状态机 + 持久化（`shion/state.py`，pytest 全部通过）
- [x] v0.1-6 本地 HTTP 服务（`shion/server.py`，回调式，不依赖窗口；pytest 共 72 个通过）
- [x] v0.1-1 骨架 / 透明置顶窗口 / 拖动下落 / `--snapshot`（pytest 共 94 个通过；**真机验收待用户**）
- [x] v0.1-2 程序动画（`shion/animator.py`；pytest 共 121 个通过；**真机验收待用户**）
- [x] v0.1-4 交互接入状态机（`shion/controller.py`、`effects.py`、`lines.py`、`assets/lines/zh.json`；pytest 共 151 个通过；**真机验收待用户**）
- [x] v0.1-5 气泡与台词（`shion/bubble.py`；pytest 共 173 个通过；**真机验收待用户**）
- [x] 把 server 回调接到 Qt 信号上（`shion/bridge.py`、`app.run()` 启动服务；pytest 共 189 个通过；真机用 curl 验收待用户）
- [x] v0.1 审查（独立子代理，只读）+ 修复（pytest 共 210 个通过）
- [x] v0.2 Claude Code hooks（pytest 共 287 个通过；**真机验收待用户**）
- [ ] v0.2.1 状态感知 ← 下一步
- [ ] v0.3 Claude Code 遥控（同意/否决、做得好/有问题、暂停/继续）
- [ ] v0.4 诗音的对话菜单（零食、预设对话，不调用模型）
- [ ] v0.5 内容包
- [ ] v1.0 发布

## 第 1 步：待用户验收（用户不在电脑前，没法手动测）
自动验证过：pytest（拖动阈值、拖动切 drag、松手落到底边、屏幕外拉回、落地回 idle、透明角落不在 mask 里、单实例、`--snapshot` 输出透明 RGBA 120x240）；真实第二个进程启动会直接退出（exit 0）；idle 截图目视正常。
**以下需要用户在电脑前做**（运行 `.venv\Scripts\python -m shion`，右键 → 退出可关闭）：
- [ ] 启动后桌宠出现在主屏右下角，脚贴任务栏上沿，置顶、任务栏不显示图标
- [ ] 按住身体拖动 → 变成 drag 图，窗口跟着鼠标；松手 → 下落贴底，回到 idle；拖到屏幕外松手会被拉回
- [ ] **透明区域点穿**：点人物两侧的空白处，能点到下面的窗口；点人物身体不穿透
- [ ] 再开第二个 `python -m shion` 会直接退出，不出现第二只
- [ ] 高分屏（缩放 150%）下清晰度、窗口大小正常
没能真机验证透明点穿的原因：测试时电脑处于锁屏状态（`WindowFromPoint` 返回 LockScreenBackstopFrame）。实现用的是 `setMask`（按精灵 alpha 生成遮罩），不依赖 Windows 分层窗口的自动穿透。

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

## 服务接入 Qt：待用户验收（同样没手动测）
自动验证过：控制器 `handle_event`（working 续期与 2 分钟超时、stop→done+计数+台词、greeting、notification、react、未知类型/表情忽略、静音时仍改状态）；真 HTTP 服务 + 假时钟控制器（处理函数确实在主线程执行、20 个并发事件全部处理、非法请求 400 且不改状态、`/praise/take` 计数正确且 20 个并发请求总数恰好等于待夸奖数、GUI 不泵事件时超时返回 500）；子进程冒烟：真的启动 `python -m shion`，HTTP 发 working/stop 后日志出现状态变化，第二个实例抢同一端口时不崩溃并记录“HTTP 服务启动失败”。
**需要用户在电脑前确认**（先 `.venv\Scripts\python -m shion` 启动桌宠，另开终端；PowerShell 里用 `curl.exe`，不要用 `curl` 别名）：
- [ ] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"working\"}"` → 桌宠变成抱电脑的 working，气泡说「Claude 在努力中」之类
- [ ] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"stop\"}"` → done 3 秒 + 气泡「做完啦！」，双击看“Claude 完成了 1 个任务”
- [ ] `curl.exe -X POST http://127.0.0.1:47613/event -d "{\"type\":\"notification\"}"` → 气泡「Claude 在等你回话呢」
- [ ] 摸几下头后 `curl.exe -X POST http://127.0.0.1:47613/praise/take -d "{}"` → 返回 `{"count":N}`，再发一次返回 0
- [ ] 桌宠没开时这些 curl 会连接失败（符合预期：关了桌宠不影响 Claude）
- [ ] 如果端口被别的程序占着，桌宠启动后会说「本地端口 47613 被占用了…」且其他功能正常

## 服务接入 Qt 留给后面步骤的接口
- `ServerBridge(controller, take_timeout=2.0)`：`on_event`/`on_take_praise` 给 `ShionServer` 用；事件用排队信号切到 GUI 线程，夸奖用请求对象 + `threading.Event` 等结果，超时抛 `TimeoutError`（server 回 500）。**ShionServer 的回调都在服务线程，PetState 和界面只在 GUI 线程动**
- `PetController.handle_event(type, detail)`、`take_praise()`
- 环境变量：`SHION_PORT`（覆盖端口）、`SHION_INSTANCE_NAME`（覆盖单实例名，自动测试用）、`SHION_DATA_DIR`、`SHION_DEBUG`
- v0.2 的 hook 脚本只需要往 `http://127.0.0.1:47613/event` POST JSON，超时要短（桌宠没开时不能拖慢 Claude Code）

## 第 5 步：待用户验收（同样没手动测）
自动验证过：时间线（30ms/字、打完停留 4s、0.3s 淡出、新台词替换）、`place_bubble`（头顶居中、顶部放不下翻到脚下、左右夹进屏幕）、窗口（不抢焦点/不挡鼠标的窗口标志、打字全程大小不变、字数随时间单调增加、背景 #0A0A0A / 边框 #F58236 / 圆角 / 米白文字、到时自动隐藏）、控制器（默认出口走气泡、静音收起并不再弹、桌宠移动时气泡跟随）；`--snapshot --bubble` 截图目视检查过（中文折行、`> ` 前缀、位置）；真实运行 1.5 秒：单击后气泡出现在桌宠头顶，字体选到 Cascadia Mono。
**需要用户在电脑前确认**：
- [ ] 打字机速度（30ms/字）和停留（4 秒）观感合适，淡出自然
- [ ] 气泡不抢焦点（点桌宠时别的窗口的输入焦点不丢）、不挡鼠标（气泡所在位置能点到下面的窗口）
- [ ] 拖动桌宠时气泡跟着走；把桌宠拖到屏幕最上方，气泡翻到脚下；靠左右边缘时不出屏
- [ ] 静音后不再弹，已显示的立刻消失；双击的状态提示不受静音影响
- [ ] 字体显示正常（Cascadia Mono，中文回退到系统字体）

## 第 5 步留给后面步骤的接口（`shion/bubble.py`）
- `BubbleWindow(clock, autostart)`：`say(text)`、`follow(body_rect)`、`dismiss()`、`render_image(now)`、`font_family`、`timeline`、`line_count`；纯逻辑 `BubbleTimeline`、`place_bubble`、`pick_font_family`
- `PetController(..., bubble=BubbleWindow)`：默认说话出口就是气泡；`PetWindow.body_rect()`、信号 `moved`
- `--snapshot` 不再强制 offscreen（offscreen 平台没有任何字体，中文会变方块），用原生平台离屏渲染；`--bubble 文字` 把气泡画在头顶，`--at` 是打字进度

## 第 4 步：待用户验收（同样没手动测）
自动验证过：窗口手势（头部悬停是张开的手、头部左右移动每 40px 一次 patted 且不会拖动、身体拖动发 drag_started/落地发 drag_finished、单击、双击顺序 clicked→double_clicked、右键发菜单信号、抓住下落中的桌宠再松手会继续落、改大小保持脚底不动）；控制器（摸头→happy+爱心+好感度、5 连戳→stop、10 连戳→dizzy、拖动含下落全程是 drag、菜单各项、静音、双击等待间隔后才显示状态、存档防抖/退出 flush/重启恢复大小、位置恢复与越界回退、睡眠唤醒台词、冷落回归台词）；真实运行 4 秒：存档和日志写到了数据目录，正常退出；爱心粒子截图看过。
**需要用户在电脑前逐项上手玩**（`.venv\Scripts\python -m shion`；`SHION_DEBUG=1` 会缩短冷落/睡眠阈值并在控制台打日志）：
- [ ] 头部按住左右摩挲：happy + 摇头 + 爱心，手感合适；头部按住不会把桌宠拖走
- [ ] 身体单击压扁；5 连戳→stop 傲娇；10 连戳→dizzy 晃
- [ ] 身体拖动→drag 图，松手落地回 idle；重启后位置（x）和大小恢复
- [ ] 双击：约半秒后出现「已陪伴… 今天被摸… 好感度…」提示
- [ ] 右键菜单：夸夸 Claude（proud）、大小四档（切换后仍贴任务栏）、静音气泡、开机自启灰色、关于、退出
- [x] 台词已在第 5 步换成真气泡（不再用 QToolTip）
- [ ] 爱心窗口完全点不到（不挡鼠标）
- [ ] 睡着（15 分钟无操作，或 `SHION_DEBUG=1` 下 1 分钟）后悬停会唤醒并说起床台词
- [ ] 存档位置：`%APPDATA%\Shion\state.json`，日志：`%APPDATA%\Shion\shion.log`

## 第 4 步留给后面步骤的接口
- `PetController(window, state, scheduler, lines=None, overlay=None, now_fn=datetime.now, say=None, autostart=True)`：信号 `quit_requested`；`react(reactions)`、`say_key(key)`、`say(text)`、`sync()`、`tick()`、`set_size/set_muted/praise/quit`、`restore_position()`、`build_menu()`、`status_text()`
- **第 5 步只需把 `say` 的出口换成气泡**：控制器的 `_tooltip_say` 是暂代；构造时传 `say=` 回调即可覆盖；静音在 `say_key` 里已处理，双击状态不受静音影响
- **接 server（下一步之后）**：`controller.state.claude_event(...)` 的返回值交给 `controller.react(...)`，再 `controller.sync()`；注意要在 GUI 线程调用（用信号切线程），`take_praise` 要同步返回
- `PetWindow` 不再自己决定精灵：新增信号 `hovered/patted/clicked/double_clicked/drag_started/drag_finished/menu_requested`，`set_height()`、`snap_to_floor()`、`head_anchor()`；状态机的 `current()` 由控制器同步给 `set_state`
- `app.run()` 已接好存档（`SaveScheduler`）、日志、`SHION_DEBUG`、`SHION_DATA_DIR`（环境变量，覆盖数据目录，测试用）

## 第 2 步：待用户验收（同样没手动测）
自动验证过：animator 纯逻辑 14 个 pytest（呼吸 1.000~1.012 / 周期 3s、眨眼只在 idle、间隔 3~6s、连眨约 15%、压扁结束精确回 1、倾斜限幅 ±12° 且松手回 0、晃动幅度）；窗口层用离屏渲染检查锚点（呼吸、压扁时最低行 ±1px、水平不滑；dizzy 晃动时脚不滑、不被画布裁掉）、遮罩覆盖所有可见像素；`--snapshot` 看过 idle / dizzy 最大角度 / land 压扁的截图；真实运行 8 秒 CPU 约 1.6%（单核）。
**需要用户在电脑前确认**：
- [ ] 呼吸、眨眼看着自然，不跳位、不抖
- [ ] 点一下身体有压扁弹回；松手落地有压扁
- [ ] 拖动时向左右拖会随速度倾斜，松手后回正，头没被裁掉
- [ ] 动画状态下透明区域仍然点穿（遮罩现在随角度/缩放更新，向外扩 4px，边缘点击略宽松）
- [ ] 高分屏下画面清晰
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
- 界面层调用：`pat`（累计移动 40px 一次）、`click`、`drag_start/drag_end`、`interact`（悬停、双击、右键，只唤醒；拖动除外，拖动算被理会）、`praise_claude`、`take_praise`、`claude_event(type, detail, now)`
- 存档：`load(path)` / `save(path, data)` / `SaveScheduler(path, data)`（`mark_dirty`、`poll(now)` 给 QTimer、退出时 `flush()`）。路径用 `QStandardPaths.AppDataLocation` 取，第 1 步的 app 负责
- `Config.debug()` 给 `SHION_DEBUG=1` 用

## 第 6 步留给后面步骤的接口（`shion/server.py`）
- `ShionServer(on_event, on_take_praise, host="127.0.0.1", port=47613)`；`start()`（端口被占用抛 `OSError`）、`stop()`、`port`
- 回调在**服务线程**里调用：`on_event(type, detail)`、`on_take_praise() -> int`（server 内部加锁串行）。事件类型不在 server 校验，交给 `PetState.claude_event`
- 接 Qt 时：`on_event` 只发信号；`on_take_praise` 要同步拿返回值，打算 `BlockingQueuedConnection` 或共享锁，到时再定
- 调试：`.venv\Scripts\python -m shion.server` 起一个无窗口的内存版，用 curl 发 `/event`、`/praise/take`、`/health` 看打印

## 设计决定（第 3 步时定的，spec 没写死的部分）
- 摸头、单击、拖动（开始和松手）、Claude 事件算“被理会”；悬停、双击、右键只唤醒不算。唤醒和冷落回归同时发生时只说 `neglect_return`
- 夜间（0:30～6:30）默认睡；被叫醒后当晚不再强制睡，要再空闲 15 分钟才睡
- “夸夸 Claude”菜单也会让待夸奖 +1（不受每分钟 5 次限制）
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
