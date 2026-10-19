# 进度记录

> 每个步骤结束时更新这份文件。新会话从这里接手。步骤定义见 `docs/spec.md`「开发步骤」。

## 当前状态
- 下一步：**v0.1 第 5 步**（`bubble.py` 终端气泡，替换控制器里的 QToolTip 临时出口）。第 1、2、4 步代码已完成并自测，但**真机验收项还没做**（见下）
- 之后的顺序：5 → 把 server 回调接到 Qt 信号 → 审查
- 环境：`.venv` 已建好（Python 3.10.11，requirements.txt 已装），`shion/`、`tests/` 包已建。git 仓库已初始化，本仓库 `user.email` 已是 noreply 邮箱

## 已完成
- [x] 美术素材：12 张精灵图已处理好（`tools/process_sprites.py`）
- [x] 规格文档
- [x] v0.1-3 状态机 + 持久化（`shion/state.py`，pytest 全部通过）
- [x] v0.1-6 本地 HTTP 服务（`shion/server.py`，回调式，不依赖窗口；pytest 共 72 个通过）
- [x] v0.1-1 骨架 / 透明置顶窗口 / 拖动下落 / `--snapshot`（pytest 共 94 个通过；**真机验收待用户**）
- [x] v0.1-2 程序动画（`shion/animator.py`；pytest 共 121 个通过；**真机验收待用户**）
- [x] v0.1-4 交互接入状态机（`shion/controller.py`、`effects.py`、`lines.py`、`assets/lines/zh.json`；pytest 共 151 个通过；**真机验收待用户**）
- [ ] v0.1-5 气泡与台词 ← 下一步（台词库 zh.json / lines.py 已在第 4 步做好，只剩 bubble.py）
- [ ] 把 server 回调接到 Qt 信号上（第 1 步之后）
- [ ] v0.1 审查
- [ ] v0.2 Claude Code hooks
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

## 第 4 步：待用户验收（同样没手动测）
自动验证过：窗口手势（头部悬停是张开的手、头部左右移动每 40px 一次 patted 且不会拖动、身体拖动发 drag_started/落地发 drag_finished、单击、双击顺序 clicked→double_clicked、右键发菜单信号、抓住下落中的桌宠再松手会继续落、改大小保持脚底不动）；控制器（摸头→happy+爱心+好感度、5 连戳→stop、10 连戳→dizzy、拖动含下落全程是 drag、菜单各项、静音、双击等待间隔后才显示状态、存档防抖/退出 flush/重启恢复大小、位置恢复与越界回退、睡眠唤醒台词、冷落回归台词）；真实运行 4 秒：存档和日志写到了数据目录，正常退出；爱心粒子截图看过。
**需要用户在电脑前逐项上手玩**（`.venv\Scripts\python -m shion`；`SHION_DEBUG=1` 会缩短冷落/睡眠阈值并在控制台打日志）：
- [ ] 头部按住左右摩挲：happy + 摇头 + 爱心，手感合适；头部按住不会把桌宠拖走
- [ ] 身体单击压扁；5 连戳→stop 傲娇；10 连戳→dizzy 晃
- [ ] 身体拖动→drag 图，松手落地回 idle；重启后位置（x）和大小恢复
- [ ] 双击：约半秒后出现「已陪伴… 今天被摸… 好感度…」提示
- [ ] 右键菜单：夸夸 Claude（proud）、大小四档（切换后仍贴任务栏）、静音气泡、开机自启灰色、关于、退出
- [ ] 台词目前用 **QToolTip 暂代气泡**，可能因为窗口没有焦点而不显示或位置不对——这个第 5 步会换成真气泡，先看看能不能看到就行
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
