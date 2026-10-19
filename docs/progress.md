# 进度记录

> 每个步骤结束时更新这份文件。新会话从这里接手。步骤定义见 `docs/spec.md`「开发步骤」。

## 当前状态
- **v0.1 已完成**（审查已做、意见已修）。下一步：**v0.2 Claude Code hooks**（见 spec「Claude Code hooks」）。但 v0.1 的**真机验收项还没人做**，用户回来后先按下面各节的清单一次性验收
- v0.2 之后的顺序： 把 server 回调接到 Qt 信号 → 审查
- 环境：`.venv` 已建好（Python 3.10.11，requirements.txt 已装），`shion/`、`tests/` 包已建。git 仓库已初始化，本仓库 `user.email` 已是 noreply 邮箱

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
- [ ] v0.2 Claude Code hooks ← 下一步
- [ ] v0.3 MCP
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
- 服务端加固：拒绝带 `Origin` 头的请求（网页脚本无法伪造事件）和 `Host` 不是本机的请求（防 DNS 重绑定），读请求有 5 秒超时。**hook 脚本和 MCP 服务器必须是普通 HTTP 客户端、不带 Origin，Host 用 127.0.0.1 或 localhost**
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
