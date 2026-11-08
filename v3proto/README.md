# V3 动起来的原型

独立 PySide6 预览，不导入 `shion/`，不读个人设置，不加依赖。当前素材使用用户手工修改的 v3.1；运行只读生成后的 rig v2，不访问 raw。

在 `shion-v3rig` worktree 根目录运行：

```powershell
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto
```

窗口标题包含 `诗音 V3 · 拎起 / 拖动`，旧窗口需要关闭后重新运行。默认 0.4 倍，支持八款原表情、呼吸、眨眼、头发摆动、捏脸、敲头、摸头、拎起、只看垫底及 FPS。

## 拎起、拖动与回原位（默认预览手感已验收）

- 按住可见的身体、手臂或腿，移动严格超过 6 个 Qt 逻辑像素后才拎起；点击、双击或容差内抖动不触发。头顶、脸颊保留原手势，不转为拎起。
- 整体随鼠标移动并随横向速度轻倾，最大 8°；手臂绕肩、双腿绕胯轻晃，头发沿用弹簧。停手后倾斜回正。先惊讶 0.2 秒，之后委屈。
- 水平反向移动至少 24 个逻辑像素才记一次有效反转，2 秒内第 3 次晃晕；直线移动、竖向移动、小抖动及仅按住均不计。晃晕锁定到松手后的余韵结束。
- 松手回到原站位，不保留横向落点；0.9 秒内轻微弹簧回弹并回正。普通委屈余韵 0.6 秒，晃晕余韵 2 秒，再用 0.35 秒淡回原表情。失焦等同松手，重复松手不重启返回。
- 回弹中可以重新抓住身体，也可捏脸/敲摸接管表情；整体继续回原位，旧反应不再复活。原表情选择在互动中锁定；关闭拎起开关会松手返回，恢复默认结束动作。

移动限定在实验台留出的空间：横向 ±240、纵向 −220～40 原图像素。渲染与命中共用整体变换，不移动桌面窗口，不引入新图片、依赖、好感或台词系统。

```powershell
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --snapshot build/v3/lift/held.png --lift-preview held --time .6
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --snapshot build/v3/lift/return.png --lift-preview release --time 1.35
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --snapshot build/v3/lift/dizzy.png --lift-preview shake --time .8
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --benchmark 60 --benchmark-lift --benchmark-output build/v3/lift/benchmark.json
```

`release` / `shake` 场景在 1.2 秒松手；`held` 保持抓取。`--lift-preview` 与 `--head-preview` 互斥；三种互动性能基准也互斥。真实窗口验收：轻拖/快速晃动、停手回正、回弹中重抓、敲摸/捏脸接管、不同尺寸和 DPI、原表情恢复及 FPS。离屏结果不代替手感验收。

## 敲头与摸头（待人工验收）

头顶、刘海及呆毛的可见区域支持敲摸；左侧鼓脸颊继续用于捏脸，其余头发保留拨动。点击按当前完整头部网格逆映射，不使用整图百分比分区。

- 轻点头顶：整个头（五官、头发和饰物一起）短促下沉约 28 原图像素再回弹，身体与脚保持原位；头下沉后冒出一小阵金星，切为委屈，保持约 0.9 秒后用 0.35 秒淡回原表情。双击算两次敲头。
- 相邻敲击间隔不超过 1.5 秒，第 3 下把委屈保持延长至 2 秒；期间继续敲会刷新保持时间。金星从实际点击位置向上、向外蹦出，再受重力落下、旋转并淡出。每次随机 6–10 颗，大小、速度、方向、转速和寿命独立变化；金星展开后略小于手掌，采用暖金渐变和轻微柔光，约 1 秒内消散。连点时前一阵继续落下，最多保留三阵，避免无限堆积。
- 按住头顶水平拖动至少 12 个 Qt 逻辑像素开始摸头，显示开心，头向手移动方向轻倾至 ±2.5°；6 像素内抖动保留点击容差，竖向移动不触发摸头。手势一经移动超过点击容差，松手不补敲。
- 有效摸头会立即清空连敲和抗议。停手或松开后约 0.25 秒回正，开心余韵 1.5 秒，再用 0.35 秒淡回。仅按住、垂直移动和微小抖动不续摸头。
- 捏脸按住时拥有手势；松手后可以摸头安抚，脸颊继续自然回弹，旧反应不再恢复。重新捏脸可接管敲摸，保留最初原表情和当前二级运动。

面板提供独立敲头/摸头开关及折叠参数，整头下沉量、委屈保持时间可调；一次反应锁定参数，修改在下一次反应生效。金星由程序绘制，发射参数只在点击时抽样，绘制时不重新随机；实际预览每次不同，快照使用 `--seed` 可复现。粒子发射点使用画布世界坐标，不随头部回弹漂移。不使用参考图素材。互动期间锁定原表情选择，关闭对应动作或恢复默认清理状态；失焦取消待判定点击并按松手结束摸头。普通动画全关时仍可单独测试敲摸。不导入旧版交互代码，无好感、台词或工作联动。

确定性截图仍使用同一个 V3 渲染器，`--time` 为互动开始后的秒数；摸头场景持续到 1.2 秒再松手：

```powershell
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --snapshot build/v3/head-touch/knock.png --head-preview knock --time .08
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --snapshot build/v3/head-touch/combo.png --head-preview combo --time .65
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --snapshot build/v3/head-touch/pat.png --head-preview pat-left --time .6 --no-animation
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --benchmark 60 --benchmark-head pat --benchmark-output build/v3/head-touch/pat-benchmark.json
```

`--head-preview` 还支持 `pat-right`；`--benchmark-head` 支持 `knock`、`pat`，与 `--benchmark-pinch` 互斥。人工验收包括连敲、安抚、停手回正、捏脸接管、八原表情恢复、不同缩放/DPI 及真实窗口 FPS。快照和离屏测试不代替真人手感验收。

## 左脸颊与独立反应

仅画面左侧鼓脸颊可抓取，悬停显示抓手。向外拖伸默认 120 原图像素（滑条 20–200），高斯半径默认 110（60–160）；上下微调最多 24，向内轻压最多 12。圆头、腮红和完整轮廓共用局部网格，眼嘴保持原位。

每次有效抓取覆盖原表情，原表情选择在反应期间锁定：

1. 前 0.2 秒惊讶，身体轻缩、头部跟随，脚不移动。
2. 持续抓取显示 dizzy 眼嘴，不带星星；双臂绕肩快速小幅挣扎。
3. 持续超过 2 秒或向外拉过上限 70%，锁定为委屈、挣扎加快。超过拉伸阈值仍先播完惊讶。
4. 松手回弹显示鼓嘴生气，手臂平滑停止，头随回弹轻晃。
5. 脸颊弹簧真正停稳后保持 1.5 秒，再用 0.35 秒淡回原表情。

彩蛋：滚动 10 秒内第 3 次及以后，每次立即委屈，松手后仍委屈。回弹、保持、淡回中重新抓取也计数，并保留最初原表情及当前脸颊位移。

移出画布可继续拖；失焦松手。关闭捏脸会恢复原表情并清空计数。反应中点恢复默认也保留原表情并结束互动。无气泡台词。

展开“被捏反应参数”可调各阶段时间、委屈阈值、回弹时间倍率、彩蛋窗口、两档摆臂速度和幅度。参数在每次有效抓取时锁定，修改从下次抓取生效；原有拖伸/半径滑条继续即时控制几何形变。默认回弹 3 Hz、阻尼比约 0.3，倍率只改变回弹用时，不截断弹簧。

普通动画中反应只更换五官；同一轮反应使用固定的皮肤、脸颊材质与头发交界。关闭普通动画时，在精确静止合成上应用相同的脸颊/五官网格及连续的缩身、肩部、头部运动；淡回末帧保持原画面逐像素一致。

## 截图与验证

截图自动离屏，使用预览的同一渲染器：

```powershell
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --snapshot build/v3/step1/rest.png --no-animation --scale 1
& '..\claude pet\.venv\Scripts\python.exe' -m tools.v3_reaction_check
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --benchmark 60 --benchmark-output build/v3/reaction/normal-benchmark.json
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto --benchmark 60 --benchmark-pinch --benchmark-output build/v3/reaction/pinch-benchmark.json
```

`build/v3/reaction/` 包含八款原表情的反应截图、接触表、阶段时间记录及 `normal.gif` / `combo.gif`。基准统计实际绘制完成数，持续捏脸基准包括委屈反应、挣扎及正常动画；离屏结果不能代替真实窗口手感和 FPS 验收。

可重建派生资产，原图始终只读：

```powershell
& '..\claude pet\.venv\Scripts\python.exe' -m tools.v3_replace_expressions build/v3/manual-import --manual-sources '..\claude pet\assets\sprites\raw\v3\v3.1'
& '..\claude pet\.venv\Scripts\python.exe' -m tools.v3_cheek
```

`tools.v3_cheek_check` 仍提供几何极限截图；反应完整流程以新检查脚本为准。纹理在完整设备分辨率以预乘透明度采样，头发连续网格和局部脸颊网格的低分辨率部分仅用于坐标计算。

人工验收：轻捏/长捏/大力拉、早松手、回弹重抓、10 秒内连捏 3–4 次、恢复原表情、参数变化、关闭普通动画后的衔接，以及实际 FPS。验收后再本地提交，不 push。


2026-11-08 性能阶段：用户已通过表情/捏脸视觉验收。相同环境 60 秒离屏持续拉脸从 41.64 FPS 提升到 57.30–59.49 FPS，普通动画 59.92 FPS；持续拉脸稳定 60 仍未确认，需真实窗口复验。保持完整分辨率、原网格和反应节奏；采样并行及缓存不添加显示延迟队列。完整画面对照最大预乘通道差 1、静止完全一致。性能资料位于 `build/v3/performance/`。
