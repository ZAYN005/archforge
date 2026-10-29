"""Acceptance probe: an INDEPENDENT judge for any generated project (code only, no LLM).

It starts the generated REST server as a real process and checks behaviour from the outside
(black box), so every variant - full pipeline, ablations, single-agent baseline - is scored by the
same 13 checks. The probe never reads the generated tests, so it cannot be fooled by weak tests.

Server start: package.json "server" script (if it is `node <file>`), else src/server.js, server.js,
index.js or app.js; with PORT, DATA_FILE (temp file) and ADMIN_TOKEN set; secrets removed from env.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from ..agent.sandbox import SECRET_ENV

TOKEN = "probe-admin-secret"

# Talk to 127.0.0.1 DIRECTLY. urllib otherwise uses the system/VPN proxy (Windows Internet settings or
# HTTP_PROXY), and many proxies refuse loopback requests -> "WinError 10061 connection refused".
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CHECKS = [
    ("C01", "spec contract: GET /play -> 200 with integer gameId"),
    ("C02", "fresh install playable: first question has >= 2 options and no correctAnswer leak"),
    ("C03", "answer endpoint judges an answer (POST /games/:id/answers -> correct: boolean)"),
    ("C04", "score endpoint (GET /games/:id/score -> numeric score)"),
    ("C05", "pause works and blocks questions (pause 200, question 409)"),
    ("C06", "resume works (Paused -> Playing)"),
    ("C07", "quit from Paused ends the game; resume afterwards is rejected (409)"),
    ("C08", "help (GET /help -> 200)"),
    ("C09", "admin security: no token -> 401/403, correct token -> 200"),
    ("C10", "admin can replace the question bank and new games use it"),
    ("C11", "fair play: correct answer is not always in the same option position"),
    ("C12", "durability: question bank survives a server restart (same data file)"),
    ("C13", "error format: unknown game -> 404 with {error: {code}}"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server_cmd(root: str) -> list[str] | None:
    node = shutil.which("node") or "node"
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
            script = json.load(f).get("scripts", {}).get("server", "")
        m = re.match(r"^\s*node\s+(\S+)\s*$", script)
        if m and os.path.exists(os.path.join(root, m.group(1))):
            return [node, m.group(1)]
    except (OSError, ValueError):
        pass
    for cand in ("src/server.js", "server.js", "src/index.js", "index.js", "app.js"):
        if os.path.exists(os.path.join(root, cand)):
            return [node, cand]
    return None


class Server:
    def __init__(self, root: str, data_file: str):
        self.root, self.data_file, self.proc, self.port = root, data_file, None, _free_port()

    def __enter__(self):
        cmd = _server_cmd(self.root)
        if not cmd:
            raise RuntimeError("no server entry point found")
        env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
        env.update(PORT=str(self.port), DATA_FILE=self.data_file, ADMIN_TOKEN=TOKEN, NODE_ENV="production")
        self.proc = subprocess.Popen(cmd, cwd=self.root, env=env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        deadline = time.time() + 25
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited with code {self.proc.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return self
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("server did not listen on PORT within 25 s")

    def __exit__(self, *a):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def req(self, method: str, path: str, body=None, token: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if token:
            r.add_header("x-admin-token", token)
        try:
            with _DIRECT.open(r, timeout=6) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        try:
            return status, json.loads(raw.decode() or "null")
        except ValueError:
            return status, None


def _gid(body):
    if isinstance(body, dict):
        for k in ("gameId", "id"):
            if isinstance(body.get(k), int):
                return body[k]
        if isinstance(body.get("game"), dict):
            return _gid(body["game"])
    return None


def _question(body):
    if isinstance(body, dict):
        q = body.get("question", body)
        if isinstance(q, dict) and isinstance(q.get("options"), list):
            return q
    return None


BANK = [{"prompt": f"Probe Q{i}: which equals {i}/{i + 1}?",
         "options": [f"{2 * i}/{2 * i + 2}", f"{i + 1}/{i + 2}", f"{i}/{i + 3}", f"{i + 2}/{i + 1}"],
         "correctAnswer": f"{i}/{i + 1}"} for i in range(1, 9)]


def run_probe(root: str) -> dict:
    res = {cid: {"id": cid, "name": name, "ok": False, "detail": ""} for cid, name in CHECKS}

    def mark(cid, ok, detail=""):
        res[cid]["ok"], res[cid]["detail"] = bool(ok), str(detail)[:160]

    tmp = tempfile.mkdtemp(prefix="af-probe-")
    data_file = os.path.join(tmp, "store.json")
    started = True
    try:
        with Server(root, data_file) as s:
            st, b = s.req("GET", "/play")
            g = _gid(b)
            mark("C01", st == 200 and g is not None, f"{st} {b}")
            if g is not None:
                st, b = s.req("GET", f"/games/{g}/question")
                q = _question(b)
                mark("C02", st == 200 and q and len(q["options"]) >= 2 and "correctAnswer" not in q, f"{st}")
                if q:
                    st, b = s.req("POST", f"/games/{g}/answers", {"answer": q["options"][0]})
                    mark("C03", st == 200 and isinstance(b, dict) and isinstance(b.get("correct"), bool), f"{st} {b}")
                st, b = s.req("GET", f"/games/{g}/score")
                mark("C04", st == 200 and isinstance(b, dict) and isinstance(b.get("score"), (int, float)), f"{st} {b}")
            st, b = s.req("GET", "/play")
            g2 = _gid(b)
            if g2 is not None:
                p1, _ = s.req("POST", f"/games/{g2}/pause")
                q1, _ = s.req("GET", f"/games/{g2}/question")
                mark("C05", p1 == 200 and q1 == 409, f"pause {p1}, question while paused {q1}")
                r1, _ = s.req("POST", f"/games/{g2}/resume")
                mark("C06", r1 == 200, f"resume {r1}")
                s.req("POST", f"/games/{g2}/pause")
                qt, _ = s.req("POST", f"/games/{g2}/quit")
                r2, _ = s.req("POST", f"/games/{g2}/resume")
                mark("C07", qt == 200 and r2 == 409, f"quit {qt}, resume after quit {r2}")
            st, _ = s.req("GET", "/help")
            mark("C08", st == 200, st)
            no, _ = s.req("GET", "/admin/questions")
            yes, _ = s.req("GET", "/admin/questions", token=TOKEN)
            mark("C09", no in (401, 403) and yes == 200, f"no token {no}, token {yes}")
            put, _ = s.req("PUT", "/admin/questions", {"questions": BANK}, token=TOKEN)
            st, b = s.req("GET", "/play")
            g3 = _gid(b)
            positions, used_bank = [], False
            if put == 200 and g3 is not None:
                by_prompt = {x["prompt"]: x for x in BANK}
                for _ in range(12):
                    st, b = s.req("GET", f"/games/{g3}/question")
                    q = _question(b)
                    if st != 200 or not q:
                        break
                    item = by_prompt.get(q.get("prompt"))
                    if not item:
                        break
                    used_bank = True
                    pos = q["options"].index(item["options"][0]) if item["options"][0] in q["options"] else -1
                    positions.append(pos)
                    st, b = s.req("POST", f"/games/{g3}/answers", {"answer": item["options"][0]})
                    if st != 200 or (isinstance(b, dict) and b.get("gameOver")):
                        break
            mark("C10", put == 200 and used_bank, f"PUT {put}, new game uses bank: {used_bank}")
            mark("C11", len(positions) >= 4 and len(set(positions)) > 1, f"correct-answer positions {positions}")
            st, b = s.req("GET", "/games/987654/question")
            mark("C13", st == 404 and isinstance(b, dict) and isinstance(b.get("error"), dict)
                 and "code" in b["error"], f"{st} {b}")
        if res["C10"]["ok"]:
            with Server(root, data_file) as s2:
                st, b = s2.req("GET", "/admin/questions", token=TOKEN)
                text = json.dumps(b)
                mark("C12", st == 200 and BANK[0]["prompt"] in text, f"after restart: {st}")
        else:
            mark("C12", False, "skipped: bank could not be replaced")
    except Exception as e:
        started = False
        for r in res.values():
            if not r["detail"]:
                r["detail"] = f"server problem: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    checks = list(res.values())
    return {"score": sum(c["ok"] for c in checks), "max": len(checks), "server_started": started, "checks": checks}
