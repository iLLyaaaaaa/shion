"""V3 内存分项：离屏建一个 V3 窗口，等预热做完，按缓存统计图片/数组字节数。

python -m tools.v3_mem                    # 260 高、DPR1.5，结果写 build/v3/integrate/s7/mem/
python -m tools.v3_mem --height 320 --dpr 1.5 --wait 20 --out build/x

统计方法：从 rig、渲染器、窗口出发按属性名逐层走（dict/list/tuple/OrderedDict 展开），
numpy 数组记 nbytes、PIL 图记 宽×高×通道、QImage 记 sizeInBytes；同一个对象只记一次
（按第一次遇到的路径归类）。进程工作集 / 私有字节用 Windows GetProcessMemoryInfo。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

OUT = Path('build/v3/integrate/s7/mem')


def process_memory() -> dict:
    if sys.platform != 'win32':
        return {}
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
                    ('PrivateUsage', ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    psapi = ctypes.WinDLL('psapi')
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    mb = 1024 * 1024
    return {'working_set_mb': round(pmc.WorkingSetSize / mb, 1),
            'peak_working_set_mb': round(pmc.PeakWorkingSetSize / mb, 1),
            'private_mb': round(pmc.PrivateUsage / mb, 1)}


def sizeof_image(obj) -> int | None:
    import numpy as np
    from PIL import Image
    from PySide6.QtGui import QImage
    if isinstance(obj, np.ndarray):
        # 视图不单独记（base 会被记到）
        return 0 if obj.base is not None and isinstance(obj.base, np.ndarray) else int(obj.nbytes)
    if isinstance(obj, Image.Image):
        return obj.width * obj.height * len(obj.getbands())
    if isinstance(obj, QImage):
        return int(obj.sizeInBytes())
    return None


def walk(root, label: str, totals: dict, seen: set, depth: int = 0, max_depth: int = 6) -> None:
    if id(root) in seen or depth > max_depth:
        return
    seen.add(id(root))
    size = sizeof_image(root)
    if size is not None:
        totals[label] += size
        return
    if isinstance(root, dict):
        for v in list(root.values()):
            walk(v, label, totals, seen, depth + 1, max_depth)
    elif isinstance(root, (list, tuple, set, frozenset)):
        for v in list(root):
            walk(v, label, totals, seen, depth + 1, max_depth)
    elif hasattr(root, '__dict__') and type(root).__module__.split('.')[0] in ('v3proto', 'shion'):
        for name, v in list(vars(root).items()):
            walk(v, f'{label}.{name}' if depth < 3 else label, totals, seen, depth + 1, max_depth)


def breakdown(win) -> dict:
    from shion import v3_window
    totals: dict = defaultdict(int)
    seen: set = set()
    # 先走窗口里的渲染器（缓存都挂在渲染器/头部表面上），再走 rig（源图），最后窗口自身。
    for key, renderer in win._v3_renderers.items():
        tag = f'renderer{list(key)}'
        surface = renderer.head_surface
        for name in ('frames', '_v3_qframes', 'fields', 'meshes', 'cheek', 'reaction_face'):
            if hasattr(surface, name):
                walk(getattr(surface, name), f'{tag}.head_surface.{name}', totals, seen, 1)
        walk(surface, f'{tag}.head_surface(其它)', totals, seen, 3)
        walk(renderer, tag, totals, seen, 1)
    for side, rig in v3_window._RIGS.items():
        walk(rig, f'rig[{side}]', totals, seen, 1)
    walk(win, 'window', totals, seen, 1)
    return {k: v for k, v in sorted(totals.items(), key=lambda kv: -kv[1]) if v}


def counts(win) -> dict:
    out = {}
    for key, renderer in win._v3_renderers.items():
        s = renderer.head_surface
        frames = list(s.frames)
        out[str(list(key))] = {
            'frames': len(frames),
            'frames_by_expression': {e: sum(1 for k in frames if k[0] == e) for e in dict.fromkeys(k[0] for k in frames)},
            'qframes': len(getattr(s, '_v3_qframes', {})),
            'cheek_done': sorted(getattr(s, '_v3_cheek_done', ())),
            'reaction_cache': len(s.reaction_face.cache),
            'frame_px': [s.w, s.h],
        }
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--height', type=int, default=260)
    p.add_argument('--dpr', type=float, default=1.5)
    p.add_argument('--wait', type=float, default=20.0, help='预热等待秒数')
    p.add_argument('--blink', default='', help='逗号分隔：依次切到这些状态各待 3 秒（让眨眼帧补齐）')
    p.add_argument('--out', default=str(OUT))
    a = p.parse_args(argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    base = process_memory()
    from shion.v3_window import V3PetWindow
    win = V3PetWindow(height=a.height, debug=False)
    win.set_device_pixel_ratio(a.dpr)
    win.show()
    states = [s for s in a.blink.split(',') if s]
    result = {'height': a.height, 'dpr': a.dpr, 'empty_process': base}

    def step():
        if states:
            win.set_state(states.pop(0), animate=False)
            QTimer.singleShot(3000, step)
            return
        result['after_window'] = process_memory()
        result['breakdown_mb'] = {k: round(v / 1024 / 1024, 2) for k, v in breakdown(win).items()}
        result['counts'] = counts(win)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f'mem-{a.height}-{a.dpr}.json').write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                          encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        app.quit()

    started = time.perf_counter()
    QTimer.singleShot(int(a.wait * 1000), step)
    app.exec()
    return started


if __name__ == '__main__':
    main()
