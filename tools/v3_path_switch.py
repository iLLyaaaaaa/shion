"""Frame-by-frame comparison around V3 render-path switches (affine <-> mesh).

python -m tools.v3_path_switch [--out build/v3/integrate/s2/switch]

Offscreen, DPR 1.5, heights 200 / 320. For three kinds of switch
(sway episode ends -> affine, affine -> sway starts, interaction ends -> affine)
it saves the 8 rendered frames before and after the switch as a strip (head crop),
and for the first frame on the new path: affine | forced mesh | |diff| x4.
Numbers go to switch.md.
"""
import argparse
import math
import os
from dataclasses import replace
from pathlib import Path

N = 8
KINDS = (('sway_end', 'mesh', 'affine'), ('sway_start', 'affine', 'mesh'),
         ('interaction_end', 'mesh', 'affine'))


def record(height, dpr):
    from PySide6.QtCore import Qt
    import shion.v3_window as vw
    from shion.v3_window import V3PetWindow
    clock = [100.0]
    w = V3PetWindow(height=height, clock=lambda: clock[0], autostart=False, debug=False,
                    pixel_ratio=dpr)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.set_state('idle', animate=False)
    frames = []
    last = {}
    renderer = w._v3_renderer
    original_render = renderer.render
    original_affine = vw.render_affine

    def mesh_render(settings, pose, **kw):
        last.setdefault('pose', pose)
        last.setdefault('path', 'mesh')
        return original_render(settings, pose, **kw)

    def affine_render(r, settings, pose):
        last['pose'], last['path'] = pose, 'affine'
        return original_affine(r, settings, pose)
    renderer.render = mesh_render
    vw.render_affine = affine_render

    def step(phase):
        clock[0] += w._timer.interval() / 1000
        last.clear()
        w.advance_to(clock[0])
        if 'pose' in last:
            frames.append(dict(t=clock[0], phase=phase, path=last['path'], pose=last['pose'],
                               image=w._v3_image.copy(),
                               angle=max(map(abs, last['pose'].angles.values()), default=0.)))
    try:
        end = clock[0] + 40
        while clock[0] < end:
            step('idle')
        # 摸头互动 1.5 秒，然后放手，等回到仿射路径
        a, s = w._v3_animator, w._v3_settings
        s.pat = True
        stop = clock[0] + 1.5
        while clock[0] < stop:
            a.stroke_head(6 * math.copysign(1, math.sin(clock[0] * 6)))
            step('interaction')
        stop = clock[0] + 20
        while clock[0] < stop:
            step('after')
            if frames[-1]['path'] == 'affine' and frames[-1]['phase'] == 'after':
                for _ in range(N):
                    step('after')
                break
    finally:
        vw.render_affine = original_affine
        renderer.render = original_render
    return w, frames


def find_switch(frames, kind, before, after):
    for i in range(1, len(frames)):
        a, b = frames[i - 1], frames[i]
        if (a['path'], b['path']) != (before, after):
            continue
        if kind == 'interaction_end' and b['phase'] != 'after':
            continue
        if kind != 'interaction_end' and b['phase'] != 'idle':
            continue
        if i >= N and i + N <= len(frames):
            return i
    return None


def arrays(image):
    from shion.v3_window import _premultiplied
    return _premultiplied(image).astype(int)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('build/v3/integrate/s2/switch'))
    args = parser.parse_args(argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import numpy as np
    from PIL import Image, ImageDraw
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from v3proto.render import to_pil
    args.out.mkdir(parents=True, exist_ok=True)
    report = ['# V3 渲染路径切换逐帧对比（DPR 1.5，离屏）', '',
              '相邻帧差：本帧与上一帧逐像素差（0–255）。切换那一帧（★）的相邻差应与前后的呼吸差同量级。',
              '同姿态差：切换后第一帧，仿射路径 vs 同一姿态强制网格路径。', '']
    for height in (200, 320):
        w, frames = record(height, 1.5)
        r, s = w._v3_renderer, w._v3_settings
        for kind, before, after in KINDS:
            i = find_switch(frames, kind, before, after)
            report.append(f'## {height} · {kind}（{before} → {after}）')
            if i is None:
                report.append('没有找到这种切换。')
                report.append('')
                continue
            window = frames[i - N:i + N]
            report.append('| 帧 | 时刻 s | 路径 | 头发最大角° | 眼睛开合 | 相邻帧差 平均/最大 |')
            report.append('|---|---|---|---|---|---|')
            prev = arrays(frames[i - N - 1]['image']) if i - N - 1 >= 0 else None
            for k, f in enumerate(window):
                cur = arrays(f['image'])
                if prev is not None and prev.shape == cur.shape:
                    d = np.abs(cur - prev)
                    diff = f'{d.mean():.3f} / {d.max()}'
                else:
                    diff = '—'
                prev = cur
                mark = '★' if k == N else ''
                report.append(f"| {k - N:+d}{mark} | {f['t'] - frames[0]['t']:.3f} | {f['path']} | "
                              f"{f['angle']:.3f} | {f['pose'].eye_scale:.2f} | {diff} |")
            # 同姿态：取切换两侧中走仿射的那一帧
            f = frames[i] if after == 'affine' else frames[i - 1]
            pose = f['pose']
            forced = replace(pose, head_roll=pose.head_roll or 1e-9)
            affine_im = to_pil(f['image']) if f['path'] == 'affine' else None
            from shion.v3_layers import render_affine
            affine_q = render_affine(r, s, pose)
            import v3proto.surface as surface_module
            calls = []
            warp = surface_module.warp_mesh
            surface_module.warp_mesh = lambda *x: calls.append(1) or warp(*x)
            try:
                mesh_q = r.render(s, forced)
            finally:
                surface_module.warp_mesh = warp
            assert calls, '强制网格没有走网格变形'
            a, m = arrays(affine_q), arrays(mesh_q)
            d = np.abs(a - m)
            report.append('')
            report.append(f'同姿态差（仿射 vs 强制网格）：平均 {d.mean():.4f}，最大 {d.max()}，'
                          f'差 >2 的像素 {int((d.max(-1) > 2).sum())} 个')
            report.append('')
            # 条带：头部裁切
            crop_h = int(window[0]['image'].height() * .55)
            tiles = []
            for k, fr in enumerate(window):
                im = to_pil(fr['image'])
                bg = Image.new('RGBA', im.size, '#ffffff')
                bg.alpha_composite(im)
                tile = bg.convert('RGB').crop((0, 0, im.width, crop_h))
                tiles.append((f"{k - N:+d}{'*' if k == N else ''} {fr['path']}", tile))
            cw, ch = tiles[0][1].size
            sheet = Image.new('RGB', (cw * N, (ch + 16) * 2), '#ddd8d3')
            draw = ImageDraw.Draw(sheet)
            for k, (label, tile) in enumerate(tiles):
                x, y = (k % N) * cw, (k // N) * (ch + 16)
                sheet.paste(tile, (x, y + 16))
                draw.text((x + 3, y + 2), label, fill='black')
            sheet.save(args.out / f'{height}-{kind}-strip.png')
            trio = []
            for label, q in (('affine', affine_q), ('mesh (forced)', mesh_q)):
                im = to_pil(q)
                bg = Image.new('RGBA', im.size, '#ffffff')
                bg.alpha_composite(im)
                trio.append((label, bg.convert('RGB')))
            heat = np.clip(d.max(-1) * 4, 0, 255).astype(np.uint8)
            trio.append(('|diff| x4', Image.fromarray(255 - heat).convert('RGB')))
            tw, th = trio[0][1].size
            sheet = Image.new('RGB', (tw * 3, th + 16), '#ddd8d3')
            draw = ImageDraw.Draw(sheet)
            for k, (label, tile) in enumerate(trio):
                sheet.paste(tile, (k * tw, 16))
                draw.text((k * tw + 3, 2), label, fill='black')
            sheet.save(args.out / f'{height}-{kind}-same-pose.png')
            del affine_im
        stats = w.v3_stats
        report.append(f"{height}：整段 {stats['affine']} 帧仿射、{stats['mesh']} 帧网格。")
        report.append('')
        w.close()
    (args.out / 'switch.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print('wrote', args.out / 'switch.md')
    app.quit()


if __name__ == '__main__':
    main()
