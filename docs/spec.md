# Shion（诗音）完整规格

> 中文名诗音，日文名詩音（しおん），英文名 Shion。她在台词里会用这个名字称呼自己。
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
│   ├── sprites/               程序使用的精灵图 448x512 RGBA（由脚本生成）
│   │   └── raw/               GPT 原图（只读）
│   └── lines/{zh,en,ja}.json  各语言的台词和界面文字（扫描此目录得到语言列表）
├── tools/process_sprites.py   素材处理脚本（已完成，已重写）
├── shion/                     桌宠主程序包
│   ├── __main__.py            入口：python -m shion
│   ├── app.py                 QApplication、单实例检查
│   ├── pet_window.py          透明置顶窗口、绘制、鼠标交互
│   ├── animator.py            呼吸、眨眼、弹跳、下落等程序动画
│   ├── state.py               状态机 + 持久化
│   ├── bubble.py              终端风格对话气泡
│   ├── effects.py             飘心等粒子特效
│   └── server.py              本地 HTTP 服务（给 hooks 用）
├── hooks/shion_hook.py        Claude Code hook 脚本（v0.2）
```

## 素材

`assets/sprites/` 里有 12 张图，是 Q 版 2.3 头身，尺寸统一为 448x512（人物高约 480，头约占上部 45%，脚底离底边 8px），**画框和脚底基线已对齐**，切换时不需要任何偏移。

处理脚本 `tools/process_sprites.py`：不依赖固定坐标，把 `raw/` 的原图清理 alpha 去毛边；以 idle 为基准把站立图的人物高度统一到 480，坐着/悬空的图（sleep/drag/neglect2）用站立图的平均缩放比例；脚底贴底，水平按头部（上部 40%）重心居中，切换表情时头不跳；个别图用 `EXTRA_SCALE` 手动微调。

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
- 默认显示高度 **200px**（图片按比例缩放，用平滑缩放）。右键菜单可以调成 160 / 200 / 260 / 320。
- 默认位置：主屏幕可用区域（`availableGeometry`，不含任务栏）的右下角，脚底贴着底边。
- 透明像素要能**点击穿透**。Windows 的分层窗口一般会自动穿透，务必实测确认。如果不行，用 `setMask` 根据当前帧的 alpha 生成遮罩。
- 只允许运行一个实例：用 `QLocalServer`/`QLocalSocket` 检测，第二个实例启动后直接退出。

## 交互

| 操作 | 判定 | 反应 |
|---|---|---|
| 鼠标悬停在头部 | 精灵图上方 45% 的区域 | 光标变成张开的手（`Qt.OpenHandCursor`） |
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
- 动画计时器用 `Qt.PreciseTimer`；桌宠、气泡、粒子按 `time.perf_counter()` 的实际经过时间计算，掉帧后直接到达对应时刻；下落使用重力位置解析式，不截断经过时间。
- 切换精灵使用约 120ms 的 ease-out 交叉淡化，附带约 3% 的压扁和轻微回弹；快速切换时从当前混合画面接续，缩放、角度也从当前姿态缓动，脚底锚点保持固定。眨眼的淡化不附加压扁。
- 粒子位移使用三次 ease-out，拖动倾斜使用指数 ease-out，压扁使用先压缩后回弹的平滑曲线；鼠标拖动位置仍直接跟随用户输入，下落保持非线性重力加速。
- idle 每隔 6～15 秒随机轻微歪头或左右晃动约 1.2 秒，幅度不超过 1.8°，离开 idle 结束。眨眼和小动作使用独立随机序列，避免掉帧改变事件次序。
- 遮罩按量化后的姿态缓存，淡化时取两张图的可见区域并集；仅透明度变化时复用遮罩。每次只绘制一遍，再平移合并区域扩边。

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
  "window": {"x": 0, "y": 0, "height": 200},
  "bubble_muted": false,
  "inject_praise": true,
  "language": "zh"
}
```

状态变化后延迟 2 秒写盘（防抖），退出时立即写。写文件时先写临时文件再替换，防止写到一半损坏。

## 对话气泡（bubble.py）

- 独立的无边框置顶小窗口，跟随在桌宠头顶上方；如果靠近屏幕边缘，自动翻到另一侧。
- **终端风格**：背景 `#0A0A0A`，1px 橙色 `#F58236` 边框，圆角 4px，米白色文字，等宽字体（优先 `Cascadia Mono`，回退到 `Consolas`），每行开头加 `> `。
- 打字机效果：每 30ms 出一个字，全部显示完后停留 4 秒再淡出。新台词出现时直接替换旧的。
- 台词从当前语言的 json 随机抽取，同一类台词不要连续重复。静音时不弹气泡。
- 气泡字体：首选等宽字体不变，后面追加当前语言 `meta.font_fallback` 里已安装的字体（日文、中文字符走它）。

### 多语言（lines.py）

- 语言文件 `assets/lines/<代码>.json`，格式：`meta`（`name` 是该语言自己的名字，显示在菜单里；`font_fallback` 是字体备选列表）、`lines`（台词类别 → 台词数组）、`ui`（界面文字，`{xxx}` 是占位符，如 `{version}`、`{span}`、`{port}`）。
- **语言列表自动扫描**该目录下所有能解析的 `*.json`（坏文件跳过），中文排第一，其余按代码排序。新增语言只需放一个 json，不用改代码。
- **回退**：缺的台词类别、缺的界面文字都回退到中文（`zh.json` 必须完整）；`ui()` 在占位符对不上时不抛异常；语言文件不存在就用中文。
- **首次启动**（存档里没有 `language`）跟随系统语言（`QLocale`）：`zh*` → 中文，`ja*` → 日文，其他 → 英文；结果写入存档，之后固定。
- **启动台词**：没有存档文件时说当前语言的一句 `intro`；已有存档时每次启动以 10% 概率说 `intro`，其余说 `greeting`，遵守静音设置。Claude 的 session_start 事件仍独立使用原来的问候逻辑。
- 右键菜单「语言」子菜单列出扫描到的语言（单选），选择后立即生效（菜单、双击状态、之后的台词、气泡字体），保存到存档，正在显示的气泡收起。

`assets/lines/zh.json` 的 `lines` 部分的初始内容（Shion 的性格：温柔、有点傲娇，很在意 Claude 有没有被夸）：

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
| `react` | 预留（目前没有调用方） | `detail` 是表情名，临时切换到该表情 3 秒 |

- `POST /praise/take` → 返回 `{"count": N}`，并把 `pending_praise` 清零（读取和清零是同一个原子操作）
- `GET /health` → `{"ok": true}`
- 安全：带 `Origin` 头的请求（来自网页）和 `Host` 不是 `127.0.0.1` / `localhost` 的请求一律返回 403，不触发任何回调；读请求体有 5 秒超时。hook 脚本是普通 HTTP 客户端，不受影响。

## Claude Code hooks（v0.2）

`hooks/shion_hook.py <事件名>`：

- 只用标准库（`urllib.request`），**超时 0.5 秒**。桌宠没运行或请求失败时**静默退出、返回码为 0**，绝不能影响 Claude Code 的正常使用。
- 从 stdin 读取 hook 输入的 JSON（可以不用，但必须读完）。
- `UserPromptSubmit`：先发送 `prompt` 事件，再调用 `/praise/take`。如果 `count > 0` 且配置里 `inject_praise` 为 true，向 stdout 打印一行上下文：
  `[Shion 桌宠] 自你上次回复后，用户通过摸 Shion 的头表扬了你 N 次。可以自然地回应，不必刻意。`
- `SessionStart`：如果 `/health` 不通，就启动桌宠（`.venv\Scripts\pythonw.exe -m shion`，脱离父进程，不弹出控制台窗口），然后发送 `session_start` 事件。
- 其他事件（`PreToolUse` 发 `working`、`Stop`、`Notification`）只负责转发。
- 配置写进**用户级** `~/.claude/settings.json` 的 `hooks` 字段，这样终端和桌面端的 Code 标签页都会加载。写之前先备份原文件，**合并而不是覆盖**用户已有的配置。另外写一个 `tools/install_hooks.py`（安装）和 `tools/uninstall_hooks.py`（卸载）。

## 状态感知（v0.2.1）

让诗音知道 Claude Code 正在干什么，当好状态窗口，也是 v0.3 遥控功能的“眼睛”。全部基于 hooks，只读，不打扰工作。

- **转述结果**：Stop hook 的输入里有对话记录文件路径（`transcript_path`，字段名按官方文档确认）。读取 Claude 最后一条回复，取第一句（最多约 40 字），气泡显示“做完啦：……”
- **显示正在干什么**：PreToolUse 时根据工具名和参数生成简短描述，例如“在读 state.py……”“在跑命令……”“在改 bubble.py……”。同一个描述 3 秒内不重复弹出
- **出错反应**：工具执行失败时（PostToolUse 结果里带错误，或官方提供的失败事件），切到 dizzy 2 秒，说一句“呜……出错了”
- **催你回来**：Claude 停下后，如果 5 分钟（可配置）没有新的 UserPromptSubmit，诗音跳一下提醒；最多提醒 2 次
- **最近活动记录**：内存里保留最近 20 条事件（时间、类型、简短描述），双击状态里可以看最近 5 条；不写入存档
- **隐私开关**（右键菜单）：“只显示状态，不显示内容”。打开后不显示文件名、命令和回复内容

## Claude Code 遥控（v0.3）

诗音成为 Claude Code 的遥控器。**只用官方 hooks 机制，不模拟按键，不往对话里发消息。** 界面文字里不出现“Claude”（见 v1.0「名称与品牌」），统一叫“工作”。

右键菜单新增“工作遥控”子菜单；需要用户决定时，诗音会主动弹出带按钮的气泡。

| 操作 | 实现 | 行为 |
|---|---|---|
| **同意 / 否决** | **PermissionRequest hook**：返回 `hookSpecificOutput.decision.behavior` 为 `allow` / `deny`（字段按官方文档确认）。hook 脚本向本地服务器长轮询，等待用户在诗音上的选择 | 气泡显示要执行的命令或要改的文件（完整显示，过长时可展开）和两个大按钮。退出计划模式的确认同样适用 |
| **做得好 / 有问题** | 放进**反馈队列**；送达方式见下 | “有问题”可以附一句话（单行输入框，可留空） |
| **暂停 / 继续** | **PreToolUse hook**：暂停期间 hook 长轮询等待，不返回 | 见下面「暂停规则」 |

**同意 / 否决的安全规则**
- 决定**只能由用户在诗音界面上亲手点击产生**。本地 HTTP 服务**不提供**任何“设置决定”的接口，hook 只能“等待结果”
- 默认等待 **120 秒**（可配置）。超时后 hook 不给决定，CC 照常弹出自己的授权框。**任何情况下都不能默认同意**
- 诗音没在运行、连不上服务器时，hook 立刻退出、不给决定，交回 CC 自己处理
- 同一时间可能有多个授权请求（例如子代理并行）：按顺序排队，一次只显示一个，显示“还有 N 个”
- 否决时附带理由“用户通过诗音否决了这个操作”

**反馈队列（做得好 / 有问题）**
- 内容示例：`[诗音] 用户觉得你刚才做得很好。` / `[诗音] 用户认为刚才的改动有问题：<用户输入的话>。请重新检查。` 不加“请回复”之类的话
- 送达（只用附加上下文，不产生聊天消息）：
  - Claude 正在工作：下一次 **PostToolUse** 的 `additionalContext`（官方说明：放在工具结果旁边，Claude 下一轮会读到，不作为聊天消息显示）
  - Claude 空闲：下一次 **UserPromptSubmit** 时附加
- 多条合并成一次送达；队列最多 5 条；送达后诗音说一句“已经转告啦”
- 右键原有的“夸夸”菜单项并入“做得好”；原来的 `pending_praise` / `/praise/take` 由反馈队列取代（保留兼容或迁移，测试要覆盖）

**暂停规则**
- 点“暂停”后，Claude 在**下一次调用工具之前**停住（PreToolUse hook 等待）。正在执行的命令不会被掐断；正在写的文字会写完。诗音切到暂停状态，气泡显示“暂停中”
- 恢复方式有两种：
  1. 在诗音上点“继续”：hook 立即放行，Claude 无缝接着干
  2. 在 CC 里直接对 Claude 说话：任何一次 **UserPromptSubmit** 都会自动解除暂停
- **超时（默认 30 分钟，可配置）**：hook 返回 `deny`，理由写“用户暂停了工作，请停下并等待用户指示”，Claude 结束这一轮。此时诗音提示“已经停下了，在 CC 里说一声就能继续”。之后在诗音上点“继续”只解除暂停标记，无法替用户发消息
- 诗音没在运行、连不上服务器时，hook 立刻放行，不会把 CC 卡住
- 子代理的工具调用同样受暂停影响

**hooks 配置**
- PermissionRequest、PreToolUse 的 hook 超时要设得比上面的等待时间长（例如 PermissionRequest 180 秒、PreToolUse 1900 秒），由 hook 脚本自己控制提前返回
- 实现后要在 CC 终端版和桌面端 Code 标签页里实测：授权请求能否被诗音接管、暂停时 CC 界面显示什么。结果记录到 progress.md

## 诗音的对话菜单（v0.4）

右键 → **对话**，在诗音旁边弹出终端风格的小窗口（和气泡同样的配色和字体），数字键选择，Esc 关闭。**全部用内置内容，不调用任何模型。**

- **喂零食 ▸**：饼干 / 布丁 / 奶茶 / 草莓蛋糕。播放吃东西的反应（先用 happy + 碎屑粒子，以后补 `eat.png`），好感度 +2；每天第 6 次起说“撑、撑不下了……”，不加好感度
- **预设对话**：例如“摸摸头”“晚安”“今天辛苦了”“陪我一下”，每个选项有三种语言的若干句回应，可以附带表情和好感度变化
- **数据驱动**：零食、对话选项、回应全部从 json 读取，不写死在代码里，为 v0.5 内容包做准备。格式要有版本号字段

## 内容包（v0.5）

类似创意工坊：别人做好内容包发到 GitHub，其他人下载就能用。

- **只允许数据，不允许代码**：内容包里只能有 PNG 和 json。加载时只解析这两类文件，忽略其他一切文件；解压时防止路径穿越（`../`）和超大文件（单个文件、总大小都设上限）
- **类型**（一个包可以包含多种）：
  - 角色包：精灵图（同 `assets/sprites/` 的 12 个状态，缺的用最接近的状态代替）+ 该角色的台词
  - 台词包：新增或覆盖某个角色、某种语言的台词
  - 零食包、对话包：给 v0.4 的菜单新增选项
- **格式**：`manifest.json`（`id`、`name`、`version`、`author`、`license`、`types`、`min_shion_version`、各语言的名字和简介）+ 按类型分的子目录。诗音自带的内容也做成一个默认包
- **安装**：把 `.zip` 拖到诗音身上，或右键“导入内容包”；安装前显示名称、作者、许可证让用户确认。安装到 `%APPDATA%\Shion\packs\`
- **管理**：右键“角色”切换当前角色；“内容包”里勾选启用、查看详情、删除
- **给制作者**：模板仓库（带说明的空白包）；`tools/validate_pack.py` 检查尺寸、透明度、json 格式、缺失状态并给出具体报错；素材处理脚本改成能处理任意角色
- 社区索引（`shion-packs` 仓库 + 应用内浏览）暂不做，等有人做了内容包再说

## 可测试性要求（重要）

CC 看不到屏幕，所以设计上必须让大部分东西能**不靠人眼**验证：

- **状态机是纯 Python**：`state.py` 不能 import Qt。时间通过参数传入（例如 `now: datetime`），不能在内部直接调用 `datetime.now()`，这样“2 小时后进入冷落”可以在测试里瞬间模拟。
- 测试用 `pytest`，放在 `tests/` 下。运行方式：`.venv\Scripts\python -m pytest -q`，只看失败的输出。
- **调试截图模式**：`python -m shion --snapshot out.png [--state happy] [--bubble "文字"]`，离屏渲染一帧存成 PNG 后退出。`--from-state idle --state happy --at 0.06` 可检查淡化中间帧；不传 `--from-state` 时直接显示目标状态。CC 需要检查画面时，生成截图再打开看，**只看截图，不要打开 assets 里的原始素材**。
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

**v0.2.1：状态感知**（见对应章节），结束时审查

**v0.3：Claude Code 遥控**（见对应章节）：先做暂停/继续和反馈队列，再做同意/否决。结束时审查

**v0.4：诗音的对话菜单**（见对应章节），结束时审查

**v0.5：内容包**（见对应章节），结束时审查

**v1.0：打包发布**

目标：**普通用户下载 zip → 解压 → 双击 `Shion.exe` → 右键点“连接 Claude”，全程不用敲命令、不用装 Python。**

1. **打包成 exe**（建议交给 Codex）
   - 用 PyInstaller 的 onedir 模式（启动比 onefile 快，也不容易被杀毒软件误报），输出 `dist/Shion/Shion.exe`
   - `assets/` 跟随打包；代码里查找资源路径要同时兼容源码运行和打包运行（`sys._MEIPASS` / exe 所在目录）
   - 加上程序图标（从 idle 图生成 `.ico`）和版本信息
   - 写 `tools/build.py`：一条命令完成打包，并把结果压缩成 `Shion-v1.0.0-windows.zip`
   - hook 脚本在打包版里不能依赖 `.venv`：改为调用 `Shion.exe --hook <事件名>`（同一个 exe 带一个轻量的 hook 模式，只用标准库逻辑、启动要快），或者另外打包一个小的 `shion-hook.exe`。两种方案先测启动耗时，选更快的

2. **一键连接 Claude Code**（交给 Claude Code）
   - 右键菜单新增“连接 Claude Code”，显示当前状态（已连接 / 未连接 / 路径已失效）
   - 连接：把 hooks 合并写入用户级 `~/.claude/settings.json`；写之前弹窗说明会改什么，并**自动备份**原文件；已存在的配置不重复添加
   - 断开：只删除诗音自己加的条目，不动用户其他配置
   - hooks 里写的路径一律指向**当前 exe 的实际位置**；用户移动文件夹后显示“路径已失效，点击重新连接”

3. **开机自启**
   - 右键菜单“开机自启”做成可勾选，用 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 实现（不需要管理员权限）
   - 关闭时删除对应注册表项

4. **首次启动引导**
   - 第一次运行时，诗音做完自我介绍后，用气泡问一次“要连接 Claude 吗？”，点击后打开连接菜单；之后不再自动询问

5. **README 与许可**
   - `README.md`（英文为主）+ `README.zh.md` + `README.ja.md`：截图和 GIF 演示、下载与使用方法、连接 Claude 的说明、常见问题（端口被占用、杀毒软件误报、如何卸载）
   - 醒目写明：**非官方粉丝作品，与 Anthropic 无关**；不使用 Anthropic / Claude 的 logo
   - 许可：**代码用 MIT**（`LICENSE`）；**美术素材（`assets/sprites/`）用 CC BY-NC 4.0**（`assets/LICENSE`），README 里写清楚两者的区别
   - 仓库不包含 `reference/` 和 `raw/` 里的旧图、草稿

6. **卸载**
   - 右键菜单“卸载准备”：自动断开 Claude 连接、关闭开机自启、询问是否删除存档，然后退出；之后用户直接删除文件夹即可

7. **名称与品牌**（参考 badclaude 收到 Anthropic 停止侵权函的事件：问题出在名称里用了“Claude”、宣传围绕 Claude 展开，容易让人以为是官方合作）
   - 仓库名用 `shion`；程序名、窗口标题、exe 名、“关于”页面都只用 Shion / 诗音
   - 介绍写成“一个能和 Claude Code 联动的桌宠”：只在说明兼容性时提到 Claude，不放进名称和标题
   - README 开头写明：非官方作品，与 Anthropic 无关，未获其认可或赞助
   - 不使用 Anthropic / Claude 的 logo，宣传图不模仿其品牌配色
   - 代码和文档里的“Claude 的桌宠”等说法改掉（包括 CLAUDE.md、spec.md 的标题）

8. **发布**（发布前必须经用户确认，未经同意不 push）
   - 推送到 GitHub，在 Releases 上传 zip，附更新说明
   - 只支持 Windows 10/11，README 里注明；macOS 以后有需求再考虑

验收：在一台**没有装 Python** 的干净 Windows（或新建的 Windows 用户账户）上，从下载 zip 到 Claude Code 里看到诗音邀功，全程不碰命令行。
