# Shion（知音）完整规格

> 名字取自“高山流水遇知音”：“知”是智能，“知音”是最懂你的人。日语读作 しおん / Shion。
> 非官方粉丝作品，与 Anthropic 无关。

## 技术栈

- Python 3.10+，GUI 用 **PySide6**
- 虚拟环境：`.venv`（`python -m venv .venv`，然后 `.venv\Scripts\pip install -r requirements.txt`）
- 依赖尽量少：`PySide6`、`pytest`；`numpy`、`scipy`、`pillow` 只给素材脚本用。hook 脚本**只能用标准库**。

## 目录结构

```
claude pet/
├── CLAUDE.md / AGENTS.md
├── docs/                      spec.md（本文件）、progress.md
├── tests/                     pytest 测试
├── requirements.txt
├── reference/                 原始黑底立绘（只读，暂不进 git）
├── assets/
│   ├── sprites/               程序使用的精灵图 256x512 RGBA（由脚本生成）
│   │   └── raw/               GPT 原图（只读）
│   └── lines/zh.json          台词
├── tools/process_sprites.py   素材处理脚本（已完成）
├── shion/                     桌宠主程序包
│   ├── __main__.py            入口：python -m shion
│   ├── app.py                 QApplication、单实例检查
│   ├── pet_window.py          透明置顶窗口、绘制、鼠标交互
│   ├── animator.py            呼吸、眨眼、弹跳、下落等程序动画
│   ├── state.py               状态机 + 持久化
│   ├── bubble.py              终端风格对话气泡
│   ├── effects.py             飘心等粒子特效
│   └── server.py              本地 HTTP 服务（给 hooks / MCP 用）
├── hooks/shion_hook.py        Claude Code hook 脚本（v0.2）
└── mcp/shion_mcp.py           MCP 服务器（v0.3）
```

## 素材

`assets/sprites/` 里有 12 张图，尺寸统一为 256x512，**画框和脚底基线已对齐**，切换时不需要任何偏移。

| 文件 | 用途 |
|---|---|
| idle | 默认站立 |
| blink | 眨眼帧（只有眼睛和 idle 不同） |
| happy | 被摸头 |
| proud | 叉腰得意（被夸 / 连续完成任务） |
| stop | 伸手挡住、脸红（戳太多次，傲娇） |
| dizzy | 蚊香眼（戳到爆 / Claude 出错） |
| working | 抱着电脑打字（Claude 正在干活） |
| done | 抱着电脑闭眼笑（Claude 刚完成任务） |
| sleep | 坐着打瞌睡，图里自带 zzz |
| drag | 被拎起来乱扑腾 |
| neglect1 | 落寞发呆（冷落 1 级） |
| neglect2 | 蜷膝泪笑（冷落 2 级） |

配色（从原图取样）：黑 `#0A0A0A`、米白 `#FCF2E6`、橙 `#F58236`。

## 窗口

- 无边框、背景透明、始终置顶、不在任务栏显示：`FramelessWindowHint | WindowStaysOnTopHint | Tool`，加上 `WA_TranslucentBackground`。
- 默认显示高度 **240px**（图片按比例缩放，用平滑缩放）。右键菜单可以调成 180 / 240 / 320 / 400。
- 默认位置：主屏幕可用区域（`availableGeometry`，不含任务栏）的右下角，脚底贴着底边。
- 透明像素要能**点击穿透**。Windows 的分层窗口一般会自动穿透，务必实测确认。如果不行，用 `setMask` 根据当前帧的 alpha 生成遮罩。
- 只允许运行一个实例：用 `QLocalServer`/`QLocalSocket` 检测，第二个实例启动后直接退出。

## 交互

| 操作 | 判定 | 反应 |
|---|---|---|
| 鼠标悬停在头部 | 精灵图上方 35% 的区域 | 光标变成张开的手（`Qt.OpenHandCursor`） |
| **摸头** | 在头部按住左键并左右移动，累计移动超过 40px 算摸 1 次 | 切到 happy，头部轻微左右摇，往上冒爱心粒子；好感度 +1；待夸奖计数 +1（每分钟最多 +5） |
| 单击身体 | 按下到松开，移动不超过 6px | 轻微压扁再弹回（0.2s），随机说一句话 |
| 连续戳 | 3 秒内单击 5 次 | 切到 stop 2 秒，说傲娇台词 |
| 戳到爆 | 5 秒内单击 10 次 | 切到 dizzy 3 秒，身体左右晃 |
| **拖动** | 在身体上按住并移动超过 6px | 切到 drag，窗口跟着鼠标走，图片随拖动速度轻微倾斜 |
| 松手 | — | 带重力下落到脚底贴住屏幕可用区域的底边（不能越出屏幕），落地时压扁一下，再回到 idle |
| 双击 | — | 气泡显示状态：已陪伴多久、今天被摸了几次、Claude 今天完成了几个任务 |
| 右键 | — | 菜单：夸夸 Claude ／ 大小 ／ 静音气泡 ／ 开机自启（v1.0）／ 关于 ／ 退出 |

## 程序动画（animator.py）

- **呼吸**：idle、neglect1 状态下，纵向缩放在 1.000 和 1.012 之间正弦变化，周期 3 秒，以脚底为锚点。
- **眨眼**：idle 状态下每隔 3～6 秒（随机）切到 blink 120ms；有 15% 的概率连续眨两次。
- 所有缩放、倾斜都以**脚底中心**为锚点，避免人物飘起来。
- 动画用一个 60fps 的 `QTimer` 统一驱动，状态改变时只切换贴图，并设置对应的动画参数。

## 状态机（state.py）

优先级从高到低（高优先级的临时状态结束后，回到底层状态）：

1. **drag**：正在被拖动
2. **临时反应**（有持续时间）：happy、stop、dizzy、done（3 秒）、proud（3 秒）
3. **working**：收到 Claude 开始干活的事件；收到 stop 事件或 2 分钟没有新事件后退出
4. **sleep**：本地时间 0:30～6:30，或者 15 分钟没有任何鼠标交互、也没有 Claude 事件。任何交互都会唤醒，唤醒时说一句起床台词
5. **底层状态**：根据冷落值决定
   - 距离上次“被理会”（摸头、点击、或任意 Claude 事件）**< 30 分钟** → idle
   - **30 分钟～2 小时** → neglect1
   - **> 2 小时** → neglect2
   - 从 neglect2 回到 idle 时，说一句特别的台词（例：`> ……你终于回来了。`）
   - 阈值写在配置里，方便调整

好感度：整数，只增不减（摸头 +1，夸夸 Claude +3），目前只在双击状态里显示，后续可以用来解锁台词。

## 持久化

`%APPDATA%\Shion\state.json`（用 `QStandardPaths.AppDataLocation` 获取）：

```json
{
  "first_run": "2026-10-19T20:00:00",
  "affection": 0,
  "last_attended": "ISO 时间",
  "pending_praise": 0,
  "stats": {"date": "2026-10-19", "pats": 0, "claude_tasks": 0},
  "window": {"x": 0, "y": 0, "height": 240},
  "bubble_muted": false,
  "inject_praise": true
}
```

状态变化后延迟 2 秒写盘（防抖），退出时立即写。写文件时先写临时文件再替换，防止写到一半损坏。

## 对话气泡（bubble.py）

- 独立的无边框置顶小窗口，跟随在桌宠头顶上方；如果靠近屏幕边缘，自动翻到另一侧。
- **终端风格**：背景 `#0A0A0A`，1px 橙色 `#F58236` 边框，圆角 4px，米白色文字，等宽字体（优先 `Cascadia Mono`，回退到 `Consolas`），每行开头加 `> `。
- 打字机效果：每 30ms 出一个字，全部显示完后停留 4 秒再淡出。新台词出现时直接替换旧的。
- 台词从 `assets/lines/zh.json` 随机抽取，同一类台词不要连续重复。静音时不弹气泡。

`assets/lines/zh.json` 的初始内容（Shion 的性格：温柔、有点傲娇，很在意 Claude 有没有被夸）：

```json
{
  "poke": ["嗯？", "干嘛戳我啦", "我在呢", "有事吗～"],
  "stop": ["够、够了啦！", "再戳我就生气了哦"],
  "dizzy": ["世界在转……", "呜……晕了"],
  "pat": ["……嘿嘿", "再摸一下也不是不行", "我会转告 Claude 的！"],
  "praise_menu": ["收到！下次见到 Claude 我就告诉它～"],
  "claude_working": ["Claude 在努力中……", "嘘，别打扰它"],
  "claude_done": ["做完啦！快夸夸 Claude", "任务完成～"],
  "wake": ["唔……早", "我才没有睡着"],
  "neglect_return": ["……你终于回来了。", "我还以为你不要我了"],
  "drag": ["放我下来！", "哇啊啊——"]
}
```

## 本地通信协议（server.py）

- 监听 **`127.0.0.1:47613`**，只绑定本机。用标准库 `http.server` 在后台线程运行，通过 Qt 信号把事件转发给 GUI 线程，**不能在后台线程里直接操作界面**。
- `POST /event`，请求体为 `{"type": "...", "detail": "可选"}`

| type | 来源 | 桌宠行为 |
|---|---|---|
| `session_start` | SessionStart hook | 说一句问候，刷新“被理会”时间 |
| `prompt` | UserPromptSubmit hook | 刷新“被理会”时间 |
| `working` | PreToolUse hook | 进入 working（已经在 working 时忽略） |
| `stop` | Stop hook | 退出 working → 播放 done 3 秒 + claude_done 台词，claude_tasks +1 |
| `notification` | Notification hook | 气泡提示“Claude 在等你确认哦”（只有终端版会触发） |
| `react` | MCP（v0.3） | `detail` 是表情名，临时切换到该表情 3 秒 |

- `POST /praise/take` → 返回 `{"count": N}`，并把 `pending_praise` 清零（读取和清零是同一个原子操作）
- `GET /health` → `{"ok": true}`

## Claude Code hooks（v0.2）

`hooks/shion_hook.py <事件名>`：

- 只用标准库（`urllib.request`），**超时 0.5 秒**。桌宠没运行或请求失败时**静默退出、返回码为 0**，绝不能影响 Claude Code 的正常使用。
- 从 stdin 读取 hook 输入的 JSON（可以不用，但必须读完）。
- `UserPromptSubmit`：先发送 `prompt` 事件，再调用 `/praise/take`。如果 `count > 0` 且配置里 `inject_praise` 为 true，向 stdout 打印一行上下文：
  `[Shion 桌宠] 自你上次回复后，用户通过摸 Shion 的头表扬了你 N 次。可以自然地回应，不必刻意。`
- `SessionStart`：如果 `/health` 不通，就启动桌宠（`.venv\Scripts\pythonw.exe -m shion`，脱离父进程，不弹出控制台窗口），然后发送 `session_start` 事件。
- 其他事件（`PreToolUse` 发 `working`、`Stop`、`Notification`）只负责转发。
- 配置写进**用户级** `~/.claude/settings.json` 的 `hooks` 字段，这样终端和桌面端的 Code 标签页都会加载。写之前先备份原文件，**合并而不是覆盖**用户已有的配置。另外写一个 `tools/install_hooks.py`（安装）和 `tools/uninstall_hooks.py`（卸载）。

## MCP 服务器（v0.3，给 Claude 桌面端的聊天用）

- `mcp/shion_mcp.py`，使用官方 Python SDK `mcp`，stdio 方式运行。
- 工具：
  - `shion_react(emotion: happy|proud|stop|dizzy|done, message?: str)`：让 Shion 做表情、说话
  - `shion_get_praise()`：读取并清零待夸奖计数
- 内部同样通过 HTTP 调用本地服务器。用户需要在 `claude_desktop_config.json` 里添加这个服务器；配置示例写进 README。

## 可测试性要求（重要）

CC 看不到屏幕，所以设计上必须让大部分东西能**不靠人眼**验证：

- **状态机是纯 Python**：`state.py` 不能 import Qt。时间通过参数传入（例如 `now: datetime`），不能在内部直接调用 `datetime.now()`，这样“2 小时后进入冷落”可以在测试里瞬间模拟。
- 测试用 `pytest`，放在 `tests/` 下。运行方式：`.venv\Scripts\python -m pytest -q`，只看失败的输出。
- **调试截图模式**：`python -m shion --snapshot out.png [--state happy] [--bubble "文字"]`，在屏幕外渲染一帧（`QWidget.grab()`）存成 PNG 后退出。CC 需要检查画面时，生成截图再打开看，**只看截图，不要打开 assets 里的原始素材**。
- **调试模式**：设置环境变量 `SHION_DEBUG=1` 时，冷落、睡眠的阈值缩短为秒级，并在控制台输出状态变化日志。
- 程序日志写进 `%APPDATA%\Shion\shion.log`，不要大量打印到终端。

## 开发步骤

每一步单独开一个会话完成。完成后更新 `docs/progress.md`，然后 commit。

**v0.1：独立运行的桌宠（不接 Claude）**

| 步 | 内容 | 验收 |
|---|---|---|
| 1 | 项目骨架、`.venv`、单实例检查；透明置顶窗口显示 idle；拖动（切换到 drag）+ 松手重力下落贴底；`--snapshot` 截图模式 | 用户：启动、拖动、松手；透明区域可以点穿 |
| 2 | `animator.py`：呼吸、眨眼、压扁弹回、晃动、倾斜，全部以脚底为锚点 | 用户：动画自然、不跳位 |
| 3 | `state.py` 状态机 + 持久化（纯逻辑） | `pytest` 覆盖：优先级、临时状态到期、working 超时、睡眠时段与唤醒、冷落三档与回归台词、连戳计数窗口、摸头每分钟上限、存档损坏时的恢复 |
| 4 | 交互接入状态机：摸头 + 爱心粒子、单击、连戳、戳到爆、双击、右键菜单、大小设置 | 用户：逐项上手玩 |
| 5 | `bubble.py` 终端气泡 + 台词库 + 静音 | 截图检查 + 用户看打字机效果 |
| 6 | `server.py` 本地 HTTP 服务 | `pytest` + 用 curl 发事件，桌宠有对应反应 |
| ✓ | **审查**：调用 `reviewer` 子代理，对照本规格检查整个 v0.1 | 修完审查意见后，v0.1 完成 |

**v0.2：接入 Claude Code**（终端和桌面端 Code 标签页都要测）
- 开发阶段 hooks 先装在**项目级** `.claude/settings.local.json` 测试，避免 bug 影响 CC 自身；稳定后再用 install 脚本装到用户级
- 验收：开启会话时自动唤醒桌宠；使用工具时显示 working，完成后显示 done；摸头后的下一条消息里 Claude 能看到表扬；桌宠关闭时 CC 完全不受影响；install / uninstall 能正确合并、还原 settings.json
- 结束时调用 `reviewer` 审查

**v0.3：接入 Claude 桌面端聊天（MCP）**，结束时审查

**v1.0：打包发布**：开机自启、Claude Code 插件形式、README（含“非官方粉丝作品”声明）、开源到 GitHub
