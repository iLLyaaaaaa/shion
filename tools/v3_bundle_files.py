"""打包要带的 V3 运行素材清单：Shion.spec、运行期取证测试和 bundle_smoke 共用，避免多份清单漂移。

只带运行期读的文件；不带 raw、parts、parts_map.json、sources.json、scenes/scene_map.json
（取证见 tests/test_v3_runtime_files.py）。
"""
from __future__ import annotations

from pathlib import Path
import re

V3_JSON = ("rig.json", "slice_map.json", "scenes/scenes.json")
V3_PNG_DIRS = ("expressions", "interactions", "slices", "underlays", "right", "scenes")
# 取证（build/v300/r4/trace.json）确认运行期从不读的 expressions 文件：
# 整脸源图 expr_<表情>.png（只有 rig.json 的 expression_sources 记来源，运行读的是 _eye_l/_eye_r/_mouth 零件）
# 和旧的 pink_cleanup.png（rig 实际用 manual_reference_patch.png）。
TOOL_ONLY = re.compile(r"expr_[a-z]+\.png|pink_cleanup\.png")


def v3_files(root: Path) -> list[str]:
    """相对 root 的 posix 路径，按字母序。"""
    sprites = root / "assets" / "sprites"
    files = [f"assets/sprites/v3/{name}" for name in V3_JSON]
    for directory in V3_PNG_DIRS:
        files += [f"assets/sprites/v3/{directory}/{p.name}"
                  for p in sorted((sprites / "v3" / directory).glob("*.png"))
                  if not (directory == "expressions" and TOOL_ONLY.fullmatch(p.name))]
    return sorted(files)


def runtime_files(root: Path) -> list[str]:
    """包内 assets/sprites、assets/weekly 下全部应有的文件（相对 root）。"""
    files = v3_files(root)
    files.append("assets/sprites/fx_z.png")
    files += [f"assets/weekly/{p.name}" for p in sorted((root / "assets" / "weekly").glob("*.png"))]
    return sorted(files)


def spec_datas(root: Path) -> list[tuple[str, str]]:
    """PyInstaller datas：(源文件, 包内目录)，目录保持源目录结构。"""
    return [(str(root / rel), str(Path(rel).parent).replace("\\", "/")) for rel in runtime_files(root)]
