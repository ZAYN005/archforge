"""Scan files for anything that looks like an API key before committing to GitHub.

Usage:  python scripts/check_secrets.py            (scans the whole project)
Exit code 1 if something suspicious is found, so it can block a git commit.
Also checks for the exact value of DEEPSEEK_API_KEY if it is set.
"""

import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "runs", ".pytest_cache"}
PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")


def main(root: str = ".") -> int:
    real_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    for n, line in enumerate(f, 1):
                        if PATTERN.search(line) or (real_key and real_key in line):
                            hits.append(f"{path}:{n}")
            except OSError:
                continue
    if hits:
        print("POSSIBLE SECRET FOUND (not printed):")
        for h in hits:
            print("  " + h)
        return 1
    print("No secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
