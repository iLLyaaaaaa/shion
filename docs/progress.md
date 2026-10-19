# 进度记录

> 每个步骤结束时更新这份文件。新会话从这里接手。步骤定义见 `docs/spec.md`「开发步骤」。

## 当前状态
- 下一步：**v0.1 第 1 步**（骨架 / 透明置顶窗口 / 拖动下落 / `--snapshot`），需要用户在电脑前验收
- 之后的顺序：1 → 2 → 4 → 5 → 把 server 回调接到 Qt 信号 → 审查
- 环境：`.venv` 已建好（Python 3.10.11，requirements.txt 已装），`shion/`、`tests/` 包已建。git 仓库已初始化，本仓库 `user.email` 已是 noreply 邮箱

## 已完成
- [x] 美术素材：12 张精灵图已处理好（`tools/process_sprites.py`）
- [x] 规格文档
- [x] v0.1-3 状态机 + 持久化（`shion/state.py`，pytest 全部通过）
- [x] v0.1-6 本地 HTTP 服务（`shion/server.py`，回调式，不依赖窗口；pytest 共 72 个通过）
- [ ] v0.1-1 骨架 ← 下一步 / 窗口 / 拖动下落 / 截图模式（等用户在电脑前）
- [ ] v0.1-2 程序动画
- [ ] v0.1-4 交互
- [ ] v0.1-5 气泡与台词
- [ ] 把 server 回调接到 Qt 信号上（第 1 步之后）
- [ ] v0.1 审查
- [ ] v0.2 Claude Code hooks
- [ ] v0.3 MCP
- [ ] v1.0 发布

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
- 本机只有 Python 3.10，spec 已从 3.11+ 改成 3.10+
- Windows 下 git 会提示 LF 将转 CRLF，只是警告
