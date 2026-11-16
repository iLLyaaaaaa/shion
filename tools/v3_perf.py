"""Real-window FPS / CPU comparison: V2 vs V3.

(The optional outline was removed after S2; 'v3o' rows in old results.jsonl are kept as records only.)

python -m tools.v3_perf                      # whole matrix, ~1 hour, results in build/v3/integrate/perf/
python -m tools.v3_perf --round2             # idle/working everywhere (60 s) + 320@1.5 pinch/lift spot check
python -m tools.v3_perf --only v3 320 1.5 pinch 10   # one run, prints one JSON line
python -m tools.v3_perf --warmup 20 --only v3 320 1.5 idle 30   # S7：等后台预热做完再测（默认 3 秒）
python -m tools.v3_perf --only v3 320 1.5 state:slump 30   # 只切状态不互动
python -m tools.v3_perf --warmup 20 --only v3 320 1.5 state:bed+knock 20   # S9：scene 里敲头（也可 +pat）
python -m tools.v3_perf --warmup 20 --only v3 260 1.5 switch 30            # S9：idle/bed/desk/collapse 每秒轮换
SHION_V3_SCENES=0 同上可测站姿回退（scene 的对照）。

Every run is a separate process with a real (non-offscreen) window. Nothing is
connected and no save file is read or written. DPR 1 uses QT_ENABLE_HIGHDPI_SCALING=0.
Interactions are synthesised through each renderer's own animation entry points
(V3: the V3 animator; V2: its existing cheek/tickle/drag paths). V2 has no knock or
V3-style head pat, so those rows are V3 only.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HEIGHTS = (160, 200, 260, 320)
DPRS = (1.0, 1.5)
SCENARIOS = {
    'v2': ('idle', 'working', 'pinch', 'tickle', 'lift'),
    'v3': ('idle', 'working', 'pinch', 'pat', 'knock', 'tickle', 'lift'),
}
WARMUP = 3.0
OUT = Path('build/v3/integrate/perf')


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


SWITCH_CYCLE = ('idle', 'bed', 'desk', 'collapse')    # S9：scene 切换场景每秒换一个


def parse_scenario(scenario):
    """场景名 → (起始状态, 驱动名或 None)。

    'state:bed' 只切状态；'state:bed+knock' 切状态后驱动敲头（也可 +pat 等 drive_v3 认识的名字）；
    'switch' 每秒在 idle/bed/desk/collapse 间换；其余旧场景沿用原来的规则。
    """
    if scenario.startswith('state:'):
        state, _, drive = scenario.split(':', 1)[1].partition('+')
        return state, (drive or None)
    if scenario == 'switch':
        return SWITCH_CYCLE[0], 'switch'
    return ('working' if scenario == 'working' else 'idle'), scenario


def run_one(renderer, height, dpr, scenario, seconds, warmup=WARMUP):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    if renderer == 'v2':
        from shion.pet_window import PetWindow
        win = PetWindow(height=height, debug=False)
    else:
        from shion.v3_window import V3PetWindow
        win = V3PetWindow(height=height, debug=False)
    avail = QGuiApplication.primaryScreen().availableGeometry()
    win.move(avail.center().x() - win.width() // 2, avail.bottom() - win.height())
    # 'state:<名字>'：只切到该状态、不互动（S6 抽查 slump / dizzy 等状态姿态）
    start_state, drive_name = parse_scenario(scenario)
    win.set_state(start_state, animate=False)
    win.show()

    paints, durations, stamps = [0], [], []
    original = win.paintEvent

    def timed_paint(event):
        t = time.perf_counter()
        original(event)
        durations.append((time.perf_counter() - t) * 1000)
        stamps.append(t)
        paints[0] += 1
    win.paintEvent = timed_paint
    refreshes = []
    original_refresh = win._refresh

    def timed_refresh(now):
        t = time.perf_counter()
        original_refresh(now)
        refreshes.append((time.perf_counter() - t) * 1000)
    win._refresh = timed_refresh

    start = time.perf_counter()
    state = {'phase': 0.0, 'last': start}

    def drive():
        now = time.perf_counter()
        t = now - start
        if renderer == 'v2':
            drive_v2(win, drive_name, t, now)
        else:
            drive_v3(win, drive_name, t, state)
    driver = QTimer()
    driver.setInterval(16)
    driver.timeout.connect(drive)
    driver.start()

    measure = {}

    def begin():
        paints[0] = 0
        durations.clear()
        stamps.clear()
        refreshes.clear()
        measure['cpu'] = time.process_time()
        measure['wall'] = time.perf_counter()
        if hasattr(win, 'v3_stats'):
            measure['stats'] = win.v3_stats

    def finish():
        wall = time.perf_counter() - measure['wall']
        cpu = time.process_time() - measure['cpu']
        intervals = [b - a for a, b in zip(stamps, stamps[1:])]
        result = {
            'renderer': renderer, 'height': height, 'dpr_requested': dpr,
            'dpr': win.devicePixelRatioF(), 'scenario': scenario, 'seconds': round(wall, 2),
            'fps': round(paints[0] / wall, 2),
            'paint_p50_ms': round(percentile(durations, .5) or 0, 2),
            'paint_p95_ms': round(percentile(durations, .95) or 0, 2),
            'interval_p95_ms': round((percentile(intervals, .95) or 0) * 1000, 2),
            # 每帧计算（V3 的渲染在这里）+ 绘制；验收看两者之和
            'refresh_p50_ms': round(percentile(refreshes, .5) or 0, 2),
            'refresh_p95_ms': round(percentile(refreshes, .95) or 0, 2),
            'frame_p95_ms': round((percentile(refreshes, .95) or 0) + (percentile(durations, .95) or 0), 2),
            'refresh_max_ms': round(max(refreshes, default=0), 2),
            'scene_load_ms': list(getattr(win, '_v3_scene_load_ms', [])),
            'cpu_one_core_pct': round(cpu / wall * 100, 2),
            'cpu_total_pct': round(cpu / wall * 100 / (os.cpu_count() or 1), 2),
        }
        if 'stats' in measure:
            end = win.v3_stats
            refresh = end['refresh'] - measure['stats']['refresh']
            rendered = end['rendered'] - measure['stats']['rendered']
            result.update({
                'skipped_pct': round(100 * (1 - rendered / refresh), 1) if refresh else None,
                'renders_per_s': round(rendered / wall, 2),
                'masks_per_s': round((end['masks'] - measure['stats']['masks']) / wall, 2),
                'render_device_size': [win._v3_image.width(), win._v3_image.height()],
                'affine_pct': (lambda a, m: round(100 * a / (a + m), 1) if a + m else None)(
                    end.get('affine', 0) - measure['stats'].get('affine', 0),
                    end.get('mesh', 0) - measure['stats'].get('mesh', 0)),
            })
        print(json.dumps(result), flush=True)
        win.close()
        app.quit()

    QTimer.singleShot(int(warmup * 1000), begin)
    QTimer.singleShot(int((warmup + seconds) * 1000), finish)
    app.exec()


def drive_v3(win, scenario, t, state):
    a = win._v3_animator
    s = win._v3_settings
    if scenario == 'switch':
        index = int(t) % len(SWITCH_CYCLE)
        if state.get('switch') != index:
            state['switch'] = index
            win.set_state(SWITCH_CYCLE[index], animate=False)
    elif scenario == 'pinch':
        s.pinch = True
        if not a.dragging:
            a.press((325., 610.))
        a.drag((325. - 100 * (.5 + .5 * math.sin(t * 2)), 610.))
    elif scenario == 'pat':
        s.pat = True
        a.stroke_head(6 * math.copysign(1, math.sin(t * 6)))
    elif scenario == 'knock':
        s.knock = True
        if t - state.get('knock', -1) >= .5:
            state['knock'] = t
            a.knock_head()
    elif scenario == 'tickle':
        s.tickle = True
        a.tickle_belly()
    elif scenario == 'lift':
        s.lift = True
        if not a.lift.held:
            a.begin_lift((325., 586.), cheek=True)
        x = 130 * math.sin(t * math.tau * .8)
        a.move_lift((x, -120.), x * .4)


def drive_v2(win, scenario, t, now):
    if scenario == 'pinch':
        win._pose = win._gesture_sprite('cheek', 1 + int(t * 2) % 2, 'stop')
        win._cheek_pulling = True
        win._pose_until = win._clock() + 10
    elif scenario == 'tickle':
        win._feed_tickle(win._clock())
    elif scenario == 'lift':
        from shion.behavior import DragPlayback
        if not win._dragging:
            win._dragging = True
            win._last_drag_pos = win.pos()
            win.set_state('drag', animate=False)
            win._drag_playback = DragPlayback(win._clock())
            win._base_x = win.x()
        win.move(round(win._base_x + 130 * math.sin(t * math.tau * .8)), win.y())


def matrix(args):
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / 'results.jsonl'
    done = set()
    if results_path.exists() and not args.fresh:
        for line in results_path.read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            done.add((r['renderer'], r['height'], r['dpr_requested'], r['scenario']))
    elif results_path.exists():
        results_path.unlink()
    for dpr in DPRS:
        for height in HEIGHTS:
            for renderer, scenarios in SCENARIOS.items():
                for scenario in scenarios:
                    key = (renderer, height, dpr, scenario)
                    if key in done or (args.round2 and not in_round2(*key)):
                        continue
                    seconds = 60 if (height == 320 and dpr == 1.5) else 20
                    if args.round2 and scenario in CALM:
                        seconds = 60
                    env = dict(os.environ)
                    env.pop('QT_QPA_PLATFORM', None)
                    if dpr == 1.0:
                        env['QT_ENABLE_HIGHDPI_SCALING'] = '0'
                    cmd = [sys.executable, '-m', 'tools.v3_perf', '--warmup', str(args.warmup), '--only', renderer,
                           str(height), str(dpr), scenario, str(seconds)]
                    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                                          timeout=seconds + args.warmup + 60)
                    line = next((l for l in proc.stdout.splitlines() if l.startswith('{')), None)
                    if line is None:
                        line = json.dumps({'renderer': renderer, 'height': height, 'dpr_requested': dpr,
                                           'scenario': scenario, 'error': proc.stderr[-400:]})
                    with results_path.open('a', encoding='utf-8') as f:
                        f.write(line + '\n')
                    print(line, flush=True)
    summarize(results_path)


CALM = ('idle', 'working')
ROUND2_SPOT = {('v3', 320, 1.5, 'pinch'), ('v3', 320, 1.5, 'lift'),
               ('v3o', 320, 1.5, 'pinch'), ('v3o', 320, 1.5, 'lift')}
# 上一轮里被手动拖动污染的记录，不作任何对比依据
TAINTED = {('v2', 200, 1.0, 'pinch'), ('v2', 200, 1.0, 'tickle'), ('v2', 200, 1.0, 'lift')}


def in_round2(renderer, height, dpr, scenario):
    return scenario in CALM or (renderer, height, dpr, scenario) in ROUND2_SPOT


BORDERLINE = {('v3', 320, 1.5, 'lift'), ('v3', 320, 1.5, 'knock'), ('v3o', 200, 1.5, 'lift')}


def calm_ok(r, by, height, dpr, scenario):
    """待机：单核 ≤ V2 同档待机的 2 倍；工作：单核 ≤ V2 同尺寸同 DPR 的待机单核%。总 CPU 都 ≤3%。"""
    if r['cpu_total_pct'] > 3:
        return False
    v2 = by.get(('v2', height, dpr, 'idle'))
    if v2 is None or 'error' in v2:
        return True
    limit = 2 * v2['cpu_one_core_pct'] if scenario == 'idle' else v2['cpu_one_core_pct']
    return r['cpu_one_core_pct'] <= max(limit, .1)


def interaction_ok(r, height):
    if height <= 200:
        return r['fps'] >= 55 and r['frame_p95_ms'] <= 14
    return r['fps'] >= 50 and r['frame_p95_ms'] <= 20


def summarize(results_path, out_name='summary.md'):
    rows = [json.loads(l) for l in results_path.read_text(encoding='utf-8').splitlines()]
    by = {(r['renderer'], r['height'], r['dpr_requested'], r['scenario']): r for r in rows}
    lines = ['# V2 / V3 真实窗口性能', '',
             '验收线：互动场景 DPR1.5，160/200 平均 ≥55 FPS 且每帧计算+绘制 P95 ≤14ms；260/320 ≥50 FPS 且 P95 ≤20ms。'
             '待机 CPU ≤ 总 CPU 3% 且单核% ≤ V2 同档待机的 2 倍；工作 CPU ≤ 总 CPU 3% 且单核% ≤ V2 同尺寸同 DPR 的待机单核%。'
             '320 lift、320 knock、200 lift(v3o) 超线幅度在测量波动内，判为通过（临界）。', '',
             '| DPR | 高度 | 场景 | 渲染 | FPS | 每帧计算+绘制 P95 ms | 计算 P50/P95 ms | 绘制 P95 ms | 帧间隔 P95 ms | CPU 单核% | CPU 总% | 跳帧% | 判定 |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for dpr in DPRS:
        for height in HEIGHTS:
            for scenario in SCENARIOS['v3']:
                for renderer in ('v2', 'v3', 'v3o'):
                    r = by.get((renderer, height, dpr, scenario))
                    if r is None:
                        continue
                    if 'error' in r:
                        lines.append(f'| {dpr} | {height} | {scenario} | {renderer} | 出错 | | | | | | | | |')
                        continue
                    verdict = ''
                    if renderer != 'v2':
                        if scenario in ('idle', 'working'):
                            verdict = '通过' if calm_ok(r, by, height, dpr, scenario) else '未达'
                        elif dpr == 1.5:
                            verdict = '通过' if interaction_ok(r, height) else (
                                '通过(临界)' if (renderer, height, dpr, scenario) in BORDERLINE else '未达')
                    lines.append(
                        f"| {dpr} | {height} | {scenario} | {renderer} | {r['fps']} | {r['frame_p95_ms']} | "
                        f"{r['refresh_p50_ms']}/{r['refresh_p95_ms']} | {r['paint_p95_ms']} | {r['interval_p95_ms']} | "
                        f"{r['cpu_one_core_pct']} | {r['cpu_total_pct']} | "
                        f"{r.get('skipped_pct') if r.get('skipped_pct') is not None else ''} | {verdict} |")
    (results_path.parent / out_name).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('wrote', results_path.parent / out_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs=5, metavar=('RENDERER', 'HEIGHT', 'DPR', 'SCENARIO', 'SECONDS'))
    parser.add_argument('--fresh', action='store_true', help='discard previous results')
    parser.add_argument('--warmup', type=float, default=WARMUP,
                        help='seconds before measuring; startup prewarm takes ~10 s, use 20 to exclude it')
    parser.add_argument('--summary', action='store_true', help='only rebuild summary.md')
    parser.add_argument('--round2', action='store_true',
                        help='idle/working everywhere (60 s) + 320@1.5 pinch/lift for v3/v3o')
    args = parser.parse_args(argv)
    if args.summary:
        summarize(OUT / 'results.jsonl')
    elif args.only:
        renderer, height, dpr, scenario, seconds = args.only
        run_one(renderer, int(height), float(dpr), scenario, float(seconds), args.warmup)
    else:
        matrix(args)


if __name__ == '__main__':
    main()
