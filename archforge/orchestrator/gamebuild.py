"""Package the GENERATED project as a Windows desktop .exe (electron-builder, portable target).

Runs `npm run dist` inside the sandbox (same policy: npm only, no shell, key-free env).
In China the Electron binaries come from the npmmirror mirrors. Code signing is switched off
in package.json (signAndEditExecutable: false), so no extra signing tools are downloaded.
Result: dist/<Product Name> <version>.exe - a single portable .exe, double-click to play.
"""

from __future__ import annotations

import glob
import os

from ..agent.sandbox import Sandbox

CN_MIRRORS = {
    "ELECTRON_MIRROR": "https://npmmirror.com/mirrors/electron/",
    "ELECTRON_BUILDER_BINARIES_MIRROR": "https://npmmirror.com/mirrors/electron-builder-binaries/",
}


def build_game_exe(project_dir: str, events=None, china_mirror: bool = True, timeout: int = 1500) -> dict:
    env = dict(CN_MIRRORS) if china_mirror else {}
    env["ELECTRON_SKIP_BINARY_DOWNLOAD"] = ""           # electron-builder must be allowed to fetch Electron
    sb = Sandbox(project_dir, extra_env=env, max_timeout=timeout,
                 npm_registry="https://registry.npmmirror.com" if china_mirror else None)
    emit = (lambda k, **d: events.emit(k, **d)) if events else (lambda k, **d: None)
    emit("game_build_start", project=project_dir)
    res = sb.run("npm run dist", timeout=timeout)
    exes = sorted(glob.glob(os.path.join(project_dir, "dist", "*.exe")), key=os.path.getmtime)
    ok = res.exit_code == 0 and bool(exes)
    out = {"ok": ok, "exe": exes[-1] if exes else "", "seconds": round(res.seconds, 1),
           "log_tail": res.output[-2500:]}
    emit("game_build_end", ok=ok, exe=out["exe"], seconds=out["seconds"])
    return out
