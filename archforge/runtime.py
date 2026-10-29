"""Runtime environment helpers for the packaged app.

* resource_path()  files bundled inside the .exe (PyInstaller unpacks them to sys._MEIPASS)
* setup_node()     find Node.js: system install first, else the portable Node shipped next to
                   ArchForge.exe (node/ folder). The found folder is put first on PATH, so the
                   sandbox's shutil.which("npm") finds it. Without Node the agent can still
                   generate code, but cannot run the tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def app_dir() -> str:
    """Folder of ArchForge.exe when frozen, else the project root."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", app_dir())
    return os.path.join(base, *parts)


def _version(node: str) -> str:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip()
    except Exception:
        return ""


def setup_node() -> dict:
    """Returns {found, source, path, version}."""
    system = shutil.which("node")
    if system and _version(system):
        return {"found": True, "source": "system", "path": system, "version": _version(system)}
    for cand in (os.path.join(app_dir(), "node"), resource_path("node")):
        exe = os.path.join(cand, "node.exe" if os.name == "nt" else "bin/node")
        if os.path.exists(exe):
            bindir = os.path.dirname(exe)
            os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
            return {"found": True, "source": "bundled", "path": exe, "version": _version(exe)}
    return {"found": False, "source": "missing", "path": "", "version": ""}
