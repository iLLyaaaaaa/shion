# V3 接入开发预览方案

**状态：已完成，随 v3.0.0 发布。** V3 现在是唯一外观，`--renderer` 选项和 V2 绘制代码已在 3.0.0 删除（R2）；下文保留当时的设计与决策作历史记录，其中“可切回旧版”“默认仍为旧版”等已不再适用。最终状态见 `docs/spec.md` 的“V3 正式接入”和 `docs/progress.md`。

原状态：2026-11-09 修订版已批准，接入进行中。2026-11-08 的接入前草案由本版取代。

## 目标与基线

将 V3 骨架立绘接入正式诗音的窗口、状态和功能（当时提供可切回旧版的源码试用入口，3.0.0 已删除）。首版不替换默认立绘，不修改已安装的 Shion-dev、真实连接配置或自启动，不加新依赖，不改 V2 精灵图、raw 素材与 reference，不 push。

- 接入分支 `feature/v3-integrate`（独立 worktree），起点 `feature/v2.2-chat-mcp` 的 `45d87b3`，已合入 `feature/v3-rig`（检查点 `3ec5578`）。
- 主目录另有未提交的窗口、状态、台词和交互修改，不在本阶段纳入，完成后再对齐。

## 结构

- `shion/v3_window.py`：`V3PetWindow(PetWindow)` 子类，重写绘制、遮罩、命中和鼠标处理；复用父类置顶/不抢焦点、下落/落地/夹边/改尺寸与拖动信号。V2 路径行为不变。
- `shion/v3_display.py`：状态→V3 显示映射、Renderer 生命周期、换边、帧节奏；纯逻辑不依赖 Qt。
- `v3proto/window.py` 的手势路由抽到 `v3proto/interaction.py`，实验台与正式程序共用，不复制渲染器。
- （历史）源码入口 `--renderer v3`，默认仍为旧版；3.0.0 起 V3 是默认且唯一外观，该选项已删除。

## 已批准的 5 点调整（2026-11-09）

1. **拎起**：只能从鼓脸颊拎起（向上 >12 逻辑像素且竖向 >1.2×横向），拎起 = 真实移动窗口；松手沿用现有下落/落地逻辑（速度 ≥450px/s 或“放到任务栏”时下落，否则原地停留并夹边），不回原站位；回原站位只保留在 v3proto 实验台。不加其他拖动入口。首次以 V3 启动时气泡提示一次「捏着脸往上提可以挪我」（`v3_lift_hint`，三语，存档记已提示）。
2. **换边**：窗口中心在所在屏幕可用区域右半边鼓向左、左半边鼓向右。只镜像脸部皮肤（`head_skin` 与干净脸部底板，含鼓脸颊），轴为两眼中线；按 `rig.json mirror.swap_layers` 对调左右鬓发上下顺序。头发、刘海、花饰、发带、五官、身体不镜像。旧脸颊在发片中的残留用现有去描线遮罩清除；右侧捏脸贴图取自镜像底板本身。捏脸命中区、横拉方向、拎起入口与倾斜方向随侧取反。（S5a 验证快照已通过。）
3. **换边时机与过渡**：中线两侧死区（可用宽度 5%，至少 40 逻辑像素）；只在停稳时判断（松手停留后、落地后、启动恢复位置、换屏/拔屏后、改尺寸后），拖动中、下落中、互动未结束时不翻，拖过中线保持原侧至落定。过渡在一次眨眼的闭眼帧完成，鼓脸颊用捏脸松手回弹弹簧“啵”一下并给头发冲量，不做水平压扁；启动时直接设定。
4. **台词**：新增三语键 `cheek_pull_combo`（10 秒内第 3 次起捏脸）与 `cheek_lift`（拎起开始，代替 `drag`）；`head_knock` / `head_knock_stop` 现有文案经用户确认后再启用。
5. **需新画清单优先级**：working 道具 > collapse/slump > desk/bed > stop > yawn > neglect1；不混用 V2 精灵图，缺口用现有 V3 表情和姿态回退。

## 状态映射

| 正式状态 | V3 显示 | 缺口 |
|---|---|---|
| idle | neutral，呼吸、眨眼 | — |
| blink | 触发一次 V3 眨眼 | — |
| happy / done | happy | — |
| cheer | happy + 跳一下 | — |
| proud | smug | — |
| stop | angry | 挡手姿势 |
| dizzy | dizzy + 头部小幅画圈 | 可选：转圈星星 |
| working | neutral + 工作气泡 | 工作道具 |
| neglect1 | neutral + 低头、呼吸/眨眼放慢 | 无聊表情 |
| neglect2 | teary + 低头 | — |
| yawn | sleep 眼 + 上抻、手臂轻抬 | 打哈欠嘴眼（先核实 `parts/`） |
| slump（体力 2） | neutral + 下压、低头、手臂下垂 | 疲惫半闭眼 |
| collapse（体力 3） | sleep 眼 + 最大下压低头（站姿） | 瘫倒/坐倒姿势 |
| jump | 按 V2 `jump_sample` 曲线整体上下，蹲落压缩，头发冲量 | — |
| drag | V3 拎起反应 | — |
| sleep | sleep，呼吸放慢 | — |
| bed / desk | sleep 站姿 / sleep + 低头 | 床与躺姿 / 书桌趴桌 |
| 喂零食 | happy + 点头咀嚼；碎屑定位到 V3 嘴部锚点 | 可选：咀嚼嘴型 |

体力四档：0 正常（恢复时 jump）、1 yawn、2 slump、3 collapse；有授权请求时强制 idle。调度器覆盖和菜单固定表情走同一张表。

## 交互的台词与好感

| 交互 | 台词键 | 好感 / 统计 |
|---|---|---|
| 捏脸 | `cheek_pull`、`cheek_release`、`cheek_pull_combo` | 无 |
| 敲头 | `head_knock`、1.5 秒内第 3 下 `head_knock_stop`（待文案确认） | 无 |
| 摸头 | `pat`、`pat_level_1..5`（PatSession） | +1，每天上限 20；`stats.pats` 与周统计；业务仍按累计 40px 计一次 |
| 挠痒 | `tickle`（每 4 秒）、`tickle_end` | 无；只认揉动，单击肚子算戳 |
| 拎脸颊 | `cheek_lift`；晃晕 `dizzy` | 无；松手后保存位置 |
| 戳 | `poke` / `stop` / `dizzy` | 无 |

## 性能

- 纹理比例 = 显示高度 × DPR ÷ rig 角色可见高度，生成的 QImage 1:1 绘制；换到不同 DPR 的屏幕时重建，按尺寸×DPR 缓存。
- 帧节奏：互动/反应/拎起/下落/头发弹簧未停 60 FPS；待机、工作 30 FPS；睡眠类 15 FPS；量化姿态键不变时跳过重绘与遮罩更新，窗口隐藏时停计时器。点穿遮罩最多 10 次/秒更新。
- 测量：CPU 用 `time.process_time()`（占单核与占总 CPU 百分比）；FPS 统计实际 paintEvent，记录 P50/P95 与帧间隔 P95。矩阵：高度 160/200/260/320 × DPR 1 与 1.5 × 待机/工作/持续捏脸/摸头/敲头/挠痒/拎起，并与 V2 同场景对比。
- 验收线（S2 修订）：互动场景 DPR1.5，160/200 平均 ≥55 FPS、计算+绘制 P95 ≤14ms，260/320 ≥50 FPS、P95 ≤20ms；待机总 CPU ≤3% 且单核不超过 V2 同档待机的 2 倍；工作总 CPU ≤3% 且单核不超过 V2 同尺寸同 DPR 的待机单核%。达不到先报告，不靠降低纹理分辨率换帧率。

## 分步

| 步 | 内容 | 状态 |
|---|---|---|
| S1 | `--renderer v3` 入口与显示骨架、静态状态映射、纹理按高度×DPR | 已验收 2026-11-09 |
| S2 | 点穿遮罩、气泡/菜单/面板定位、改尺寸、换屏 DPR、降帧与跳帧、FPS/CPU 测量 | 已验收 2026-11-09 |
| S3 | 捏脸、敲头、摸头、挠痒接入台词/好感/统计；优先点击先消费 | 已验收 2026-11-09 |
| S4 | 拎脸颊移动真实窗口，松手走现有下落/落地 | 已验收 2026-11-10 |
| S5a | 右侧鼓脸颊验证快照 | 已验收 2026-11-09 |
| S5 | 换边判断与眨眼过渡；拎起倾斜随侧取反；窗口命中与拉伸方向 | 已实现；S8 接入右鼓版底板后**默认打开**（`SHION_V3_AUTO_SIDE=0` 固定左鼓）2026-11-12 |
| S6 | 其余状态动作与需新画清单 | 已验收 2026-11-10 |
| S7 | 全仓回归、CPU/内存评估、reviewer 审查、文档收尾 | 已完成，待用户验收与审查中级问题决定 2026-11-10 |
| S8 | 接入新画素材：右鼓版底板（打开换边）、working 抱电脑 | 已验收 2026-11-16 |
| S9 | collapse / bed / desk 整图姿势变体（scene）：素材、显示、互动、测量 | 第 1～4 步已验收，第 5 步测量与文档完成（见 progress）2026-11-16 |

**S3、S4 已完成**：S3 启用 `head_knock` / `head_knock_stop` 与 `cheek_pull_combo`；S4 把窗口移动限定为“只能拎脸颊”，S3 过渡的“拖身体挪窗口”“捏脸拖过 80px 转整窗拖动”“肚子拖出 40px 转整窗拖动”均已删除。按错地方拖动时提示 `v3_lift_hint`（60 秒冷却）。

**S6 已完成**（2026-11-10）：状态姿态、工作点头、碎屑锚点；slump/neglect1/yawn 表情用 S0 部件拼成；需新画清单见下方。

**S5 换边已实现但默认关闭**（2026-11-10）：右鼓的 S5a 镜像脸部底板在桌面尺寸下刘海发丝断开、脸像歪了，需新画右鼓版脸部底板后再开启（`SHION_V3_AUTO_SIDE=1` 可试用）。“需新画清单”增加：右鼓版脸部底板（含刘海发梢）。

每步：测试 → 用户验收 → 更新 progress → 本地提交。全仓原有 16 项基线失败与汇总后原生退出异常单独比对，不笼统宣称全量通过。

## 需新画清单（S6，2026-11-10，用户定序）

顺序：**working 道具 > 右鼓版脸部底板 > collapse/slump > desk/bed > stop > yawn > neglect1**。slump、yawn、neglect1 的表情已用 S0 部件解决（见各项），还需新画的是：working 道具、右鼓版脸部底板、collapse 姿势、desk/bed、stop 手臂。可选（不排序）：dizzy 转圈星星、咀嚼嘴型。

### 通用约定

- 坐标系：rig 画布 **1086×1448**（`rig.json canvas`，即 ref.png 像素坐标）。左右一律指画面左/右。
- **背景**：纯白 #FFFFFF；不要投影、地面、渐变、边框、文字或水印（`tools/v3_extract.py remove_white_bg` 按白底切连通块）。
- **画风**：与参考图一致的深棕描边、平涂加少量高光；线宽与原图相同，不要加粗或改色。
- **参考图**：一条命令生成到 `build/v3/art-refs/`，每张图的尺寸、对应的 rig 裁切框和放大倍数写在同目录 `refs.json`：
  ```
  .venv\Scripts\python -m tools.v3_art_refs refs
  ```
  裁切图的 rig 坐标 = 裁切框左上角 + 图内像素 ÷ 放大倍数。
- **GPT 输出尺寸不对时**：等比缩放后白边补齐到目标尺寸（居中），再交给切片工具：
  ```
  .venv\Scripts\python -m tools.v3_art_refs pad <GPT 输出> <补齐后> [--size 1086x1448]
  ```
- GPT 原件放 `assets/sprites/raw/v3/s6/`（只读、不进 git）；处理结果进 `assets/sprites/v3/`。

| 参考图 | 尺寸 | 内容 |
|---|---|---|
| `working-full.png` | 1086×1448 | neutral 全身 |
| `arms-x2.png` | 1580×620 | 双臂区域 ×2（rig 框 150,700–940,1010） |
| `full-left-ref.png` | 1086×1448 | 当前左鼓原图（smug，S0 定稿） |
| `head-left-ref.png` | 1820×1520 | 左鼓头部 ×2（rig 框 90,0–1000,760） |
| `pose-full.png` | 1086×1448 | 站姿全身，姿势比例参考 |
| `scene-wide.png` | 2172×1448 | 左右各扩 50%，给家具留位置（rig 框 -543,0–1629,1448） |
| `face-smug-ref.png` | 1086×1448 | 表情输入底图（`v3_replace_expressions` 对位用） |
| `face-neutral.png` / `face-sleep.png` | 1086×1448 | 现有 neutral / sleep 表情参考 |

### 1. working 道具——已于 S8 接入（2026-11-12，抱电脑整块替换双臂，无单独道具零件图）

- **用途**：工作中手边的道具（参照 V2 working 精灵的道具语义）。现回退：neutral + 头略低 + 每 4～6 秒轻点头 + 工作气泡。
- **GPT 输入**：`working-full.png`（对位）+ `arms-x2.png`（手的位置和大小）。
- **要两张图**：① 道具**单独**一张白底零件图，道具完整、不被手遮挡、不带角色；② 角色拿着道具的全身图（与 `working-full.png` 同画布同姿势），只用来对位。
- **分层**：道具一层；若道具压在手上，另出“手在道具前”的前景小块（可选）。
- **切片/对位**：零件图复用 `tools/v3_extract.py extract` → 写 `parts_map.json` → `name` 切出 PNG；对位**需新写**小工具：在 ② 上做模板匹配（复用 `v3_extract` 的匹配函数），把位置写成 rig.json 新 part。
- **接入改动**：`rig.json`（新 part 与 layer）；`v3proto/render.py`（按 `Settings.props` 显示/隐藏）；`shion/v3_display.py` 加 `STATE_PROPS`；`shion/v3_window.py` 每帧设 props、遮罩；预热。

### 2. 右鼓版脸部底板（含刘海发梢）——已于 S8 接入（2026-11-12）

- **用途**：换边（S5）开关的前提。S5a 的镜像底板在桌面尺寸下刘海发丝断开、脸像歪了（`build/v3/integrate/s5/head-left-vs-right-zoom.png`）。现回退：换边默认关闭。
- **GPT 输入**：`head-left-ref.png`（1820×1520）为主，`full-left-ref.png` 看整体。
- **要求**：按左鼓原图**整张重画头部，不镜像**；刘海、发梢、花饰、发带、呆毛、五官位置和形状与原图一致，只把鼓起的脸颊从画面左侧换到右侧，左脸颊恢复正常轮廓。输出与 `head-left-ref.png` 同尺寸同构图。不要求分层。
- **切片/对位**：**需新写** `tools/v3_right_plate.py`：先把 ×2 图缩回 rig 坐标；用 `tools/v3_replace_expressions.py` 的 `align_head` 对位到原图；用现有 `face_fringe_mask` / `face_contour`（翻到右侧）切出 `head_skin` 与干净底板；再跑 `tools/v3_cheek.py` 生成右侧捏脸素材。
- **接入改动**：`v3proto/mirror.py` `apply_cheek_side('right')` 改为加载画好的底板；`rig.json mirror` 段；`shion/v3_window.py` `auto_side` 默认改 True；`tests/test_v3_side.py` 默认开启；重出 `tools/v3_mirror_check.py` 对比快照。

### 3. collapse / slump——collapse 已于 S9 接入（整图姿势变体 scene，不是下面写的分零件做法）

- **用途**：体力 3 档瘫倒、2 档疲惫。现回退：站姿下压 + 低头 + 手臂收拢 + 呼吸眨眼放慢。
- **GPT 输入**：collapse 用 `pose-full.png`；slump 表情用 `face-smug-ref.png`（同画布同姿势只改五官）+ `face-neutral.png`（风格）。
- **collapse 分层**：坐倒全身，按零件分开画在一张白底图上：身体、左腿、右腿、左臂、右臂各一块，互不重叠、不缺遮挡部分；另出一张拼好的合成图用来对位。头部沿用现有，不画。
- **slump 表情**：**不用新画**——用户已采用 S0 部件拼的 `tired`（半闭眼，`tools/v3_s0_faces.py`）。此项只剩 collapse 姿势。
- **切片/对位**：表情复用 `tools/v3_replace_expressions.py`（需小改：允许新表情名）+ `tools/v3_face_features.py REGIONS` 补区域 + `tools/v3_cheek.py` 生成捏脸素材；姿势零件 `v3_extract` 切 + 新对位工具（同 #1）。
- **接入改动**：表情：`rig.json faces`、`STATE_EXPRESSIONS`、预热表情列表、`tests/test_v3_display.py` 的表情集合；姿势：rig 加姿势变体、`load_rig` 的脚底/可见范围按姿势算、`STATE_POSES` 改用新姿势。整身新姿势需扩 rig，接入时另开计划。

### 4. desk / bed——已于 S9 接入（整图姿势变体 scene，家具点穿，不是下面写的分零件做法）

- **用途**：书桌趴睡、床上躺睡。现回退：站着睡 / 站着睡 + 低头。
- **GPT 输入**：`scene-wide.png`（家具位置与比例）+ `pose-full.png`。
- **分层**：书桌、床各自单独一张零件图（不带角色）；趴桌姿势、躺姿按 #3 的方式分零件 + 合成图对位。
- **切片/对位**：同 #3；家具同 #1 道具流程。
- **接入改动**：同 #1 + #3；另调睡觉 Z 的位置、窗口遮罩和点穿（家具不可点）。

### 5. stop 挡手

- **用途**：“停”状态伸手挡。现回退：angry + 双臂略外抬。
- **GPT 输入**：`arms-x2.png`。
- **分层**：只要伸出的手臂零件（手掌朝外），左右各一块，白底单张；肩部接口与现有手臂对齐。
- **切片/对位**：`v3_extract` 切；对位到 `rig.json pivots` 的 `shoulder_l` / `shoulder_r`。
- **接入改动**：`rig.json` 加手臂变体；`v3proto/render.py` 按状态换手臂；`STATE_POSES["stop"]` 去掉占位抬手。

### 6. yawn 表情 / 7. neglect1 无聊表情（已解决，不用新画）

- **neglect1**：用户采用 S0 部件拼的 `bored`（半闭眼 + 波浪嘴）。
- **yawn**：用户选了 sleep 眼 + S0 张大嘴放大 1.8 倍（`tools/v3_s0_faces.py YAWN_SCALE`）。
- 以后若要换成新画的版本：GPT 输入用 `face-smug-ref.png` + `face-sleep.png` / `face-neutral.png`，整张同姿态脸，走 #3 的表情流程。
