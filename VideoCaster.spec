# Build on Windows with build-windows.ps1 to isolate DLL lookup from other tools.
import os
import ssl
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
console = os.environ.get("VIDEOCASTER_BUILD_CONSOLE") == "1"
datas, binaries, hiddenimports = [], [], []
# Both libraries load protocol/controller modules dynamically. Include them even
# when static import analysis cannot discover a device-specific code path.
for package in ("pyatv", "pychromecast", "zeroconf"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("pyatv", recursive=True)
# The logo (window and taskbar icon); tools/make_icon.py draws it.
datas.append((str(root / "app" / "assets"), "assets"))
# Some Python runtimes ship an additional trust-policy file beside ssl.py.
# ssl.SSLContext reads it relative to __file__, including inside a frozen app.
# Preserve it rather than changing or disabling certificate validation.
ssl_policy = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
if ssl_policy.is_file():
    datas.append((str(ssl_policy), "."))

a = Analysis(
    [str(root / "app" / "main.py")],
    pathex=[str(root / "app")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VideoCaster-debug" if console else "VideoCaster",
    debug=False,
    strip=False,
    upx=False,
    console=console,
    icon=str(root / "app" / "assets" / "videocaster.ico"),
)
