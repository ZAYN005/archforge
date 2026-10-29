"""Entry point for the packaged desktop app (PyInstaller builds ArchForge.exe from this file).

    ArchForge.exe            open the GUI
    ArchForge.exe --smoke    offline self-check for a fresh machine (no API key, no cost):
                             imports everything, runs the spec pipeline on the bundled inputs,
                             checks Node.js; writes the report to %TEMP%\\archforge_smoke.txt
"""
import os
import sys
import tempfile
import traceback


def smoke() -> int:
    lines, ok = [], True
    try:
        from archforge import __version__
        from archforge.gui.app import MainWindow  # noqa: F401  (GUI code imports in the frozen app)
        from archforge.orchestrator import Orchestrator  # noqa: F401
        from archforge.runtime import resource_path, setup_node
        from archforge.spec.__main__ import run as run_spec
        lines.append(f"ArchForge {__version__} frozen={getattr(sys, 'frozen', False)}")
        out = os.path.join(tempfile.gettempdir(), "archforge_smoke_spec")
        res = run_spec(resource_path("inputs", "Architecture_Documentation.md"),
                       resource_path("inputs", "Architecture_View.md"), out)
        lines.append(f"spec pipeline: {len(res['findings'])} lint findings, "
                     f"{len(res['resolved']['api']['endpoints'])} endpoints (expected 21 / 10)")
        ok &= len(res["findings"]) == 21
        node = setup_node()
        lines.append(f"node: {node}")
        ok &= node["found"]
        import keyring
        lines.append(f"keyring backend: {type(keyring.get_keyring()).__name__}")
        import openai
        lines.append(f"openai sdk: {openai.__version__}")
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("SMOKE " + ("OK" if ok else "FAILED"))
    path = os.path.join(tempfile.gettempdir(), "archforge_smoke.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if sys.stdout:
        print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(smoke())
    from archforge.gui.app import main
    sys.exit(main())
