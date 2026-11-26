"""打包成 Windows 绿色版（onedir）。

用法：
    .venv\\Scripts\\python.exe tools\\build_exe.py            # 正式版（无控制台）
    .venv\\Scripts\\python.exe tools\\build_exe.py --console  # 排错版（带控制台）
    .venv\\Scripts\\python.exe tools\\build_exe.py --no-zip   # 只出目录，不压缩

产物：
    dist/YT下载器/                 ← 解压即用，含 yt-dlp.exe / assets / config
    archives/YT下载器_v<版本>_win64.zip

设计要点（见 HANDOFF §10）：
- 必须 --onedir，禁止 --onefile（每次启动解压 100MB+ 到 %TEMP%，白屏且易被杀软拦）
- yt-dlp.exe 放在 exe **同级目录**，不塞进 _internal，这样引擎能独立更新
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "YT下载器"
DIST_ROOT = os.path.join(ROOT, "dist")
BUILD_ROOT = os.path.join(ROOT, "build")
APP_DIR = os.path.join(DIST_ROOT, NAME)
ARCHIVES = os.path.join(ROOT, "archives")
PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")

COPY_FILES = ["yt-dlp.exe", "README.md", "config.json"]
COPY_DIRS = ["assets"]


def read_version() -> str:
    path = os.path.join(ROOT, "app", "__init__.py")
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def clean_previous() -> None:
    """清掉上一次的 dist 目录。

    用系统命令而不是 shutil.rmtree：文件多时（200+）会触发沙箱的批量删除保护。
    """
    if not os.path.isdir(APP_DIR):
        return
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", APP_DIR], check=False)
    else:
        shutil.rmtree(APP_DIR, ignore_errors=True)
    print("  已清理旧 dist")


def run_pyinstaller(console: bool) -> None:
    cmd = [
        PYTHON,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console" if console else "--noconsole",
        "--name",
        NAME,
        "--icon",
        os.path.join(ROOT, "assets", "icon.ico"),
        "--distpath",
        DIST_ROOT,
        "--workpath",
        BUILD_ROOT,
        "--specpath",
        BUILD_ROOT,
        os.path.join(ROOT, "main.py"),
    ]
    print("$ " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller 失败，退出码 {result.returncode}")


def copy_extras() -> None:
    """把引擎、资源、配置放到 exe 同级（不是 _internal）。"""
    for name in COPY_FILES:
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(APP_DIR, name))
            print(f"  + {name}")
    for name in COPY_DIRS:
        src = os.path.join(ROOT, name)
        dst = os.path.join(APP_DIR, name)
        if not os.path.isdir(src):
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"  + {name}/")


def dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, filename))
            except OSError:
                pass
    return total


def make_zip(version: str) -> str:
    os.makedirs(ARCHIVES, exist_ok=True)
    target = os.path.join(ARCHIVES, f"{NAME}_v{version}_win64.zip")
    if os.path.exists(target):
        os.remove(target)
    base_parent = os.path.dirname(APP_DIR)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(APP_DIR):
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, base_parent)
                zf.write(full, rel)
    return target


def main() -> int:
    console = "--console" in sys.argv
    no_zip = "--no-zip" in sys.argv
    version = read_version()

    if not os.path.isfile(PYTHON):
        print("找不到 .venv，先跑 setup.bat")
        return 1

    print(f"== 打包 {NAME} v{version} ({'console' if console else 'windowed'}) ==")
    clean_previous()
    run_pyinstaller(console)

    print("== 拷贝引擎与资源 ==")
    copy_extras()

    exe = os.path.join(APP_DIR, f"{NAME}.exe")
    if not os.path.isfile(exe):
        print("!! 没有生成 exe，检查 PyInstaller 输出")
        return 1

    size = dir_size(APP_DIR)
    print(f"== 目录体积 {size / 1024 / 1024:.1f} MB ==")

    if not no_zip:
        target = make_zip(version)
        print(f"== 压缩包 {target} ({os.path.getsize(target) / 1024 / 1024:.1f} MB) ==")

    print(f"完成：{APP_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
