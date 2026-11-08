# V3 动起来的原型

独立 PySide6 预览，不导入 `shion/`，不读个人设置，不加依赖。当前素材使用用户手工修改的 v3.1；运行只读生成后的 rig v2，不访问 raw。

在 `shion-v3rig` worktree 根目录运行：

```powershell
& '..\claude pet\.venv\Scripts\python.exe' -m v3proto
```

窗口标题包含 `v3.1 · 被捏反应`，旧窗口需要关闭后重新运行。默认 0.4 倍，支持八款原表情、呼吸、眨眼、头发摆动、只看垫底及 FPS。点头发仍是拨动；敲头、摸头未实现。

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
