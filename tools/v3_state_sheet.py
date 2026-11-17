"""S1 acceptance sheets: every formal state shown with the V3 puppet.

python -m tools.v3_state_sheet [--out build/v3/integrate/s1]

- states-dpr1.png / states-dpr1.5.png: rows = heights 160/200/260/320, columns = states.
- size-compare.png: V2 idle next to V3 idle on one floor line for each height (DPR 1).
- metrics.json: texture scale, rendered device size, renderer build and frame times.
"""
import argparse
import json
import os
import time
from pathlib import Path

HEIGHTS = (160, 200, 260, 320)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('build/v3/integrate/s1'))
    args = parser.parse_args(argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PIL import Image, ImageDraw
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from shion.pet_window import PROP_STATES, STATES
    from shion.v3_window import V3PetWindow as PetWindow
    from shion.v3_window import V3PetWindow, shared_rig
    from v3proto.render import to_pil

    args.out.mkdir(parents=True, exist_ok=True)
    states = [s for s in STATES] + list(PROP_STATES)
    clock = [100.0]

    def window(cls, height, dpr):
        w = cls(height=height, clock=lambda: clock[0], autostart=False, debug=False, pixel_ratio=dpr)
        w.setAttribute(Qt.WA_DontShowOnScreen)
        return w

    def shot(w, state, dpr):
        clock[0] += 1.0
        w.set_state(state, animate=False)
        clock[0] += .5
        w.advance_to(clock[0])
        image = to_pil(w.render_frame(dpr))
        bg = Image.new('RGBA', image.size, '#eee9e5')
        bg.alpha_composite(image)
        return bg.convert('RGB')

    shared_rig('left')
    metrics = {}
    for dpr in (1, 1.5):
        rows = []
        for height in HEIGHTS:
            t = time.perf_counter()
            w = window(V3PetWindow, height, dpr)
            build = time.perf_counter() - t
            tiles = [(s, shot(w, s, dpr)) for s in states]
            w.set_state('idle', animate=False)
            for _ in range(60):  # warm the per-angle mesh caches first
                clock[0] += 1 / 60
                w.advance_to(clock[0])
            t = time.perf_counter()
            for _ in range(120):
                clock[0] += 1 / 60
                w.advance_to(clock[0])
            frame_ms = (time.perf_counter() - t) / 120 * 1000
            metrics[f'{height}@{dpr}'] = {
                'texture_scale': round(w.v3_texture_scale, 4),
                'window_logical': [w.width(), w.height()],
                'render_device_size': [w._v3_image.width(), w._v3_image.height()],
                'window_build_s': round(build, 3),
                'refresh_ms': round(frame_ms, 2),
            }
            w.close()
            rows.append((height, tiles))
        cell_w = max(t.width for _, tiles in rows for _, t in tiles)
        cell_h = max(t.height for _, tiles in rows for _, t in tiles) + 18
        sheet = Image.new('RGB', (cell_w * len(states) + 60, cell_h * len(rows)), '#ddd8d3')
        draw = ImageDraw.Draw(sheet)
        for r, (height, tiles) in enumerate(rows):
            draw.text((6, r * cell_h + cell_h // 2), str(height), fill='black')
            for c, (state, tile) in enumerate(tiles):
                x, y = 60 + c * cell_w, r * cell_h
                sheet.paste(tile, (x, y + 18 + (cell_h - 18 - tile.height)))
                draw.text((x + 4, y + 3), state, fill='black')
        path = args.out / f'states-dpr{dpr}.png'
        sheet.save(path)
        print('wrote', path)
    # Size comparison on one floor line (DPR 1).
    pairs = []
    for height in HEIGHTS:
        for cls in (PetWindow, V3PetWindow):
            w = window(cls, height, 1)
            pairs.append((f'{height} {"V3" if cls is V3PetWindow else "V2"}', shot(w, 'idle', 1)))
            w.close()
    width = sum(t.width for _, t in pairs) + 10 * len(pairs)
    height = max(t.height for _, t in pairs) + 20
    sheet = Image.new('RGB', (width, height), '#ddd8d3')
    draw = ImageDraw.Draw(sheet)
    x = 0
    for label, tile in pairs:
        sheet.paste(tile, (x, height - tile.height))
        draw.text((x + 4, 3), label, fill='black')
        x += tile.width + 10
    sheet.save(args.out / 'size-compare.png')
    (args.out / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(metrics))


if __name__ == '__main__':
    main()
