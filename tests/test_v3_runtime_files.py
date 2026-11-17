"""打包清单取证：源码下跑完 V3 全部状态 / 两侧 / 三个 scene / 五种手势 / 周报 / 图标，
实际读过的素材必须等于 spec 收的清单，实际加载过的 scipy 模块不能落在 spec 排除的子包里。

取证在新进程里做（tools/v3_runtime_trace.py，约 3～4 分钟）；结果放 build/v300/r4/trace.json 供人查看。
"""
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from tools.v3_bundle_files import TOOL_ONLY, runtime_files, v3_files

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def trace(tmp_path_factory):
    out = tmp_path_factory.mktemp("trace") / "trace.json"
    done = subprocess.run([sys.executable, "-m", "tools.v3_runtime_trace", str(out)], cwd=ROOT,
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_trace_covers_everything_it_claims(trace):
    from shion.pet_window import STATES
    assert trace["ran"] == {"states": 2 * len(STATES), "gestures": 10}


def test_shipped_assets_equal_the_files_actually_opened(trace):
    opened = {p for p in trace["files"] if p.startswith(("assets/sprites/", "assets/weekly/"))}
    shipped = set(runtime_files(ROOT))
    assert opened - shipped == set(), "运行期读了清单里没有的文件，包里会缺"
    assert shipped - opened == set(), "清单里有运行期从不读的文件，白占体积"


def test_qt_cpp_loads_are_seen(trace):
    # Python 钩子看不到 Qt 在 C++ 里读的文件；这些必须由 Qt 子类记录到
    assert {"assets/sprites/fx_z.png", "assets/weekly/idle.png", "assets/icon/shion.png"} <= set(trace["qt_files"])


def test_never_opened_files_are_not_in_the_list_and_not_runtime(trace):
    opened = set(trace["files"])
    for name in ("parts_map.json", "sources.json", "scene_map.json"):
        assert not any(p.endswith("/" + name) for p in opened), name
    assert not any(p.startswith("assets/sprites/v3/parts/") or p.startswith("assets/sprites/raw") for p in opened)
    assert not any(TOOL_ONLY.fullmatch(Path(p).name) for p in v3_files(ROOT) if "/expressions/" in p)


def test_scipy_excludes_never_overlap_loaded_modules(trace):
    spec = (ROOT / "Shion.spec").read_text(encoding="utf-8")
    excluded = re.findall(r'"(scipy\.[a-z_]+)"', spec)
    assert excluded and '"scipy",' not in spec and '"PIL",' not in spec
    loaded = trace["scipy_modules"]
    assert any(m.startswith("scipy.ndimage") for m in loaded)
    for sub in excluded:
        assert not [m for m in loaded if m == sub or m.startswith(sub + ".")], sub


def test_spec_datas_match_the_list_and_skip_sources():
    from tools.v3_bundle_files import spec_datas
    datas = spec_datas(ROOT)
    assert len(datas) == len(runtime_files(ROOT))
    assert all(Path(src).is_file() for src, _ in datas)
    assert not any("/raw" in dest or "parts" in dest.split("/")[-1] for _, dest in datas)
