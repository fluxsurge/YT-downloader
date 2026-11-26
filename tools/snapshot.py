"""打包项目快照，便于回退。

用法：
    python tools/snapshot.py              # 自动用 app/__init__.py 里的版本号
    python tools/snapshot.py 修完音频分页   # 带备注
    python tools/snapshot.py --no-dist     # 不包含 dist/ 里的 exe 产物

产出：archives/v<版本>_<时间>[_备注].zip
包含：全部源码、assets、docs、HANDOFF.md、README.md、config.json、MANIFEST.txt，
      以及 dist/ 下已打包的 exe 绿色版（存在则自动带上）
排除：.venv、__pycache__、archives、build、*.pyc
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVES = os.path.join(ROOT, "archives")
EXCLUDE_DIRS = {".venv", "__pycache__", "archives", ".git", "build", ".idea"}


def read_version() -> str:
    path = os.path.join(ROOT, "app", "__init__.py")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip('"\'')
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _run(cmd: list[str]) -> str:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=20,
                            creationflags=0x08000000 if os.name == "nt" else 0)
        return ((cp.stdout or "") + (cp.stderr or "")).strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return "（未检测到）"


def build_manifest(version: str, files: int, size: int, has_dist: bool, dist_size: int) -> str:
    ytdlp = os.path.join(ROOT, "yt-dlp.exe")
    lines = [
        "YT 下载器 — 项目快照",
        "=" * 40,
        f"版本号      : {version}",
        f"打包时间    : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"文件数      : {files}",
        f"压缩后大小  : {size / 1024 / 1024:.1f} MB",
        "",
        "运行环境",
        f"  Python    : {sys.version.split()[0]}",
        f"  PySide6   : {_pyside_version()}",
        f"  yt-dlp    : {_run([ytdlp, '--version']) if os.path.isfile(ytdlp) else '（未找到 yt-dlp.exe）'}",
        f"  ffmpeg    : {_run(['ffmpeg', '-version'])}",
        f"  deno      : {_run(['deno', '--version'])}",
        "",
        "内容说明",
        "  - 源码：main.py / app/ / tools/",
        "  - 文档：HANDOFF.md（交接）/ README.md（使用）/ docs/yt-dlp-feature-map.md（功能地图）",
        "  - 资源：assets/（图标、下拉箭头）、docs/screenshot.png",
        "  - 配置：config.json（当前偏好，可直接覆盖回去）",
        (
            f"  - EXE：已包含 dist/ 下的绿色版（{dist_size / 1024 / 1024:.1f} MB），解压即可运行"
            if has_dist
            else "  - EXE：本次未包含（跑 tools/build_exe.py 后重新打包即可带上）"
        ),
        "",
        "回退方法（源码方式）",
        "  1. 解压到新目录",
        "  2. 把旧的 .venv 一起保留（或重跑 setup.bat）",
        "  3. 双击 run.bat",
        "回退方法（exe 方式）",
        "  1. 解压后进 dist/YT下载器/",
        "  2. 双击 YT下载器.exe，无需 Python 环境",
    ]
    return "\n".join(lines)


def _pyside_version() -> str:
    exe = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(exe):
        return "（无 .venv）"
    try:
        cp = subprocess.run([exe, "-c", "import PySide6;print(PySide6.__version__)"],
                            capture_output=True, text=True, timeout=30,
                            creationflags=0x08000000 if os.name == "nt" else 0)
        return (cp.stdout or "").strip() or "（未知）"
    except Exception:  # noqa: BLE001
        return "（未知）"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    include_dist = "--no-dist" not in sys.argv
    tag = "_".join(args).strip()
    version = read_version()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    safe_tag = "".join(c for c in tag if c not in '\\/:*?"<>|').strip()
    name = f"v{version}_{stamp}" + (f"_{safe_tag}" if safe_tag else "") + ".zip"
    os.makedirs(ARCHIVES, exist_ok=True)
    target = os.path.join(ARCHIVES, name)

    dist_dir = os.path.join(ROOT, "dist")
    has_dist = include_dist and os.path.isdir(dist_dir)
    dist_size = 0
    if has_dist:
        for dirpath, _dirnames, filenames in os.walk(dist_dir):
            for filename in filenames:
                try:
                    dist_size += os.path.getsize(os.path.join(dirpath, filename))
                except OSError:
                    pass

    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            if os.path.abspath(dirpath).startswith(os.path.abspath(dist_dir)) and not has_dist:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for filename in filenames:
                if filename.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, ROOT)
                zf.write(full, rel)
                count += 1
    # zip 关闭后才知道真实体积，所以 MANIFEST 最后追加
    size = os.path.getsize(target)
    with zipfile.ZipFile(target, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "MANIFEST.txt",
            build_manifest(version, count + 1, size, has_dist, dist_size),
        )

    print(f"已生成：{target}")
    print(f"包含 {count} 个文件" + (f"，其中 exe 产物 {dist_size / 1024 / 1024:.1f} MB" if has_dist else "（未含 exe）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
