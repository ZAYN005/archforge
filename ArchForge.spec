# PyInstaller build recipe for ArchForge.exe  (run via build_exe.ps1, or: pyinstaller ArchForge.spec)
#
# One-folder build (dist/ArchForge/ArchForge.exe + _internal/): starts in ~2 s, unlike a one-file
# .exe that unpacks itself to a temp folder on every launch. build_exe.ps1 then adds portable
# Node.js next to the .exe and zips everything into release/ArchForge-win64.zip.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = (collect_submodules("openai")          # the SDK loads parts lazily; collect them all
          + collect_submodules("keyring.backends")
          + ["win32ctypes.core", "yaml"])

a = Analysis(
    ["ArchForge.py"],
    pathex=["."],
    datas=[("inputs/Architecture_Documentation.md", "inputs"),
           ("inputs/Architecture_View.md", "inputs"),
           ("assets/archforge.png", "assets")]
          + collect_data_files("certifi"),
    hiddenimports=hidden,
    # numpy/pandas/scipy are only OPTIONAL extras of the openai SDK; without this they would add ~250 MB
    excludes=["numpy", "pandas", "scipy", "matplotlib", "PIL", "IPython", "sounddevice",
              "pytest", "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ArchForge",
    icon="assets/archforge.ico",
    console=False,            # GUI app: no black console window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ArchForge", upx=False)
