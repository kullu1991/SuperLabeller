"""Build dist/SuperLabeller.exe with PyInstaller (single file, no console window).

    pip install -r requirements.txt pyinstaller
    python build.py

Also used by the GitHub Actions workflow.
"""
import os
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from superlabeller import APP_NAME, AUTHOR, EXE_NAME, __version__  # noqa: E402

BUILD = os.path.join(ROOT, "build")
os.makedirs(BUILD, exist_ok=True)


def version_file():
    """Windows file properties (Product name, version, copyright) for the EXE."""
    parts = (__version__.split(".") + ["0", "0", "0"])[:4]
    nums = ", ".join(str(int(p)) for p in parts)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{AUTHOR}'),
      StringStruct('FileDescription', '{APP_NAME} - TSPL label designer'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', '{EXE_NAME}'),
      StringStruct('LegalCopyright', 'Copyright (C) 2026 {AUTHOR}. GPL-3.0'),
      StringStruct('OriginalFilename', '{EXE_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = os.path.join(BUILD, "version_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main():
    sep = ";" if os.name == "nt" else ":"
    icon = os.path.join(ROOT, "assets", "icon.ico")
    args = [
        os.path.join(ROOT, "main.py"),
        "--name", EXE_NAME,
        "--onefile", "--windowed", "--noconfirm", "--clean",
        "--icon", icon,
        "--add-data", f"{icon}{sep}assets",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", BUILD,
        "--specpath", BUILD,
    ]
    if os.name == "nt":
        args += ["--version-file", version_file(), "--hidden-import", "win32print"]
    for mod in ("tkinter", "matplotlib", "numpy", "PyQt5.QtWebEngineWidgets", "PyQt5.QtQml",
                "PyQt5.QtQuick", "PyQt5.QtMultimedia", "PyQt5.QtSql", "PyQt5.QtNetwork"):
        args += ["--exclude-module", mod]
    PyInstaller.__main__.run(args)
    print(f"\nBuilt dist/{EXE_NAME}{'.exe' if os.name == 'nt' else ''}  (version {__version__})")


if __name__ == "__main__":
    main()
