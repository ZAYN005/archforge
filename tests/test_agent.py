"""Phase 4 tests: sandbox, tools and the agent loop (scripted fake LLM, no API cost)."""

import json
import os
import sys
from types import SimpleNamespace as NS

import pytest

from archforge.agent.loop import AgentLoop
from archforge.agent.sandbox import Sandbox, SandboxError, truncate
from archforge.agent.tools import ToolBox, ToolContext
from archforge.events import EventLog
from archforge.llm import BudgetExceeded


@pytest.fixture
def sb(tmp_path):
    return Sandbox(str(tmp_path / "ws"), extra_programs={"python": sys.executable})


@pytest.fixture
def box(sb):
    return ToolBox(ToolContext(sb))


def call(box, name, **args):
    return box.execute(name, json.dumps(args))


# ------------------------------------------------------------------ path jail
@pytest.mark.parametrize("bad", ["../escape.txt", "a/../../escape.txt", "/etc/passwd", "C:/Windows/win.ini"])
def test_paths_outside_workspace_are_denied(sb, bad):
    with pytest.raises(SandboxError):
        sb.resolve(bad)


def test_symlink_escape_is_denied(sb, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    link = os.path.join(sb.root, "link.txt")
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system")
    with pytest.raises(SandboxError):
        sb.resolve("link.txt")


# ------------------------------------------------------------------ command policy
@pytest.mark.parametrize("cmd", [
    "rm -rf /", "powershell -c dir", "cmd /c dir", "node a.js && del x", "node a.js | more",
    "node a.js > out.txt", "npm exec evil", "npx some-random-package", "node %APPDATA%/x.js",
    "node ../outside.js", "curl http://x"])
def test_dangerous_commands_are_refused(sb, cmd):
    with pytest.raises(SandboxError):
        sb.check_command(cmd)


@pytest.mark.parametrize("cmd", ["node test.js", "npm test", "npm install --save-dev jest", "npx jest --json",
                                 "npm run build", "npm -v"])
def test_allowed_commands_pass_the_policy(sb, cmd):
    assert sb.check_command(cmd)


def test_child_process_cannot_see_the_api_key(sb, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-" + "x" * 40)
    monkeypatch.setenv("SOME_TOKEN", "abc")
    sb.write_text("env_probe.py", "import os\nprint(os.environ.get('DEEPSEEK_API_KEY'), os.environ.get('SOME_TOKEN'))\n")
    res = sb.run("python env_probe.py")
    assert res.exit_code == 0 and res.output.strip() == "None None"


def test_timeout_kills_process(sb):
    sb.write_text("sleepy.py", "import time\ntime.sleep(10)\n")
    res = sb.run("python sleepy.py", timeout=1)
    assert res.timed_out and res.seconds < 8


def test_truncate_keeps_head_and_tail():
    t = truncate("A" * 10000 + "B" * 10000, limit=2000)
    assert t.startswith("A") and t.endswith("B") and "truncated" in t


# ------------------------------------------------------------------ tools
def test_write_then_edit_requires_read(box):
    assert call(box, "write_file", path="src/a.js", content="let x = 1;\n")[0]
    # new ToolContext = an agent that never read the file
    fresh = ToolBox(ToolContext(box.ctx.sandbox))
    ok, msg = call(fresh, "edit_file", path="src/a.js", old_string="1", new_string="2")
    assert not ok and "must read_file" in msg
    ok, msg = call(fresh, "write_file", path="src/a.js", content="overwrite")
    assert not ok and "must read_file" in msg


def test_edit_detects_external_change(box):
    call(box, "write_file", path="a.txt", content="one\n")
    call(box, "read_file", path="a.txt")
    full = box.ctx.sandbox.resolve("a.txt")
    with open(full, "w") as f:
        f.write("changed by someone else\n")
    os.utime(full, (1, 1))
    ok, msg = call(box, "edit_file", path="a.txt", old_string="changed", new_string="x")
    assert not ok and "changed on disk" in msg


def test_edit_uniqueness_and_replace_all(box):
    call(box, "write_file", path="a.js", content="return null;\nreturn null;\n")
    call(box, "read_file", path="a.js")
    ok, msg = call(box, "edit_file", path="a.js", old_string="return null;", new_string="return 0;")
    assert not ok and "2 times" in msg
    ok, _ = call(box, "edit_file", path="a.js", old_string="return null;", new_string="return 0;", replace_all=True)
    assert ok and box.ctx.sandbox.read_text("a.js") == "return 0;\nreturn 0;\n"


def test_edit_not_found_and_noop(box):
    call(box, "write_file", path="a.js", content="const a = 1;\n")
    call(box, "read_file", path="a.js")
    assert "not found" in call(box, "edit_file", path="a.js", old_string="const b", new_string="x")[1]
    assert "identical" in call(box, "edit_file", path="a.js", old_string="a", new_string="a")[1]


def test_edit_preserves_crlf(box):
    full = box.ctx.sandbox.resolve("w.js")
    with open(full, "wb") as f:
        f.write(b"line1\r\nline2\r\n")
    call(box, "read_file", path="w.js")
    assert call(box, "edit_file", path="w.js", old_string="line1\nline2", new_string="L1\nL2")[0]
    with open(full, "rb") as f:
        assert f.read() == b"L1\r\nL2\r\n"


def test_read_only_box_has_no_write_tools(sb):
    ro = ToolBox(ToolContext(sb), permission="read-only")
    assert set(ro.tools) == {"read_file", "list_dir", "grep", "todo_write"}
    ok, msg = call(ro, "write_file", path="x", content="y")
    assert not ok and "unknown tool" in msg


def test_model_mistakes_become_error_text(box):
    assert "not valid JSON" in box.execute("read_file", "{bad json")[1]
    assert "missing" in call(box, "read_file")[1]
    assert "unknown tool" in call(box, "delete_everything", path="/")[1]
    assert call(box, "read_file", path="../../x")[1].startswith("DENIED")


def test_todo_write_rules(box):
    ok, out = call(box, "todo_write", todos=[{"content": "a", "status": "done"}, {"content": "b", "status": "in_progress"}])
    assert ok and "[x] a" in out and "[>] b" in out
    ok, out = call(box, "todo_write", todos=[{"content": "a", "status": "in_progress"},
                                             {"content": "b", "status": "in_progress"}])
    assert not ok


# ------------------------------------------------------------------ agent loop with a scripted LLM
def tc(i, name, **args):
    return NS(id=f"call_{i}", function=NS(name=name, arguments=json.dumps(args)))


class ScriptedLLM:
    """Plays back a fixed list of model replies; records what it was sent."""
    def __init__(self, replies, events):
        self.replies, self.events, self.sent = list(replies), events, []

    def chat(self, messages, **kw):
        self.sent.append(json.loads(json.dumps(messages)))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        content, calls = r
        return NS(content=content, tool_calls=calls or None, reasoning_content=None), None, 0.0


def make_loop(tmp_path, replies, **kw):
    ev = EventLog(str(tmp_path / "events.jsonl"))
    sb = Sandbox(str(tmp_path / "ws"), extra_programs={"python": sys.executable})
    llm = ScriptedLLM(replies, ev)
    return AgentLoop(llm, ToolBox(ToolContext(sb)), "SYSTEM", **kw), llm, tmp_path / "events.jsonl"


def test_loop_write_run_fix_done(tmp_path):
    replies = [
        ("plan", [tc(1, "write_file", path="t.py", content="import sys\nsys.exit(1)\n")]),
        (None, [tc(2, "run_command", command="python t.py")]),
        (None, [tc(3, "read_file", path="t.py")]),
        (None, [tc(4, "edit_file", path="t.py", old_string="sys.exit(1)", new_string="print('ok')")]),
        (None, [tc(5, "run_command", command="python t.py")]),
        ("Done: t.py prints ok.", None),
    ]
    loop, llm, ev = make_loop(tmp_path, replies)
    res = loop.run("make t.py print ok")
    assert res.status == "done" and res.turns == 6 and res.tool_calls == 5
    assert "exit code 1" in llm.sent[2][-1]["content"]          # model saw the failure
    assert "exit code 0" in llm.sent[5][-1]["content"] and "ok" in llm.sent[5][-1]["content"]
    kinds = [json.loads(l)["kind"] for l in ev.read_text().splitlines()]
    assert kinds[0] == "agent_start" and kinds[-1] == "agent_stop" and "tool_result" in kinds


def test_tool_results_follow_call_order_with_parallel_reads(tmp_path):
    replies = [(None, [tc(1, "write_file", path="a.txt", content="A"), tc(2, "write_file", path="b.txt", content="B")]),
               (None, [tc(3, "read_file", path="a.txt"), tc(4, "read_file", path="b.txt"), tc(5, "list_dir")]),
               ("ok", None)]
    loop, llm, _ = make_loop(tmp_path, replies)
    loop.run("x")
    tool_msgs = [m for m in llm.sent[2] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_1", "call_2", "call_3", "call_4", "call_5"]
    assert "a.txt" in tool_msgs[2]["content"] and "b.txt" in tool_msgs[3]["content"]


def test_stuck_guard_nudges_after_three_identical_failures(tmp_path):
    bad = lambda i: (None, [tc(i, "read_file", path="missing.js")])
    loop, llm, _ = make_loop(tmp_path, [bad(1), bad(2), bad(3), ("giving up", None)])
    loop.run("x")
    assert any("same failing call 3 times" in m["content"] for m in llm.sent[3] if m["role"] == "user")


def test_max_turns_and_budget_stop(tmp_path):
    loop, _, _ = make_loop(tmp_path, [(None, [tc(i, "list_dir")]) for i in range(5)], max_turns=3)
    assert loop.run("x").status == "max_turns"
    loop, _, _ = make_loop(tmp_path, [BudgetExceeded("limit")])
    assert loop.run("x").status == "budget"


def test_microcompact_clears_old_results_only(tmp_path):
    loop, _, _ = make_loop(tmp_path, [], compact_at_tokens=100, keep_recent_results=2)
    msgs = [{"role": "system", "content": "s"}] + \
           [{"role": "tool", "tool_call_id": str(i), "content": "x" * 2000} for i in range(5)]
    freed = loop.microcompact(msgs)
    assert freed == 3 * 2000
    assert all(m["content"].startswith("[cleared") for m in msgs[1:4])
    assert msgs[4]["content"] == "x" * 2000 and msgs[5]["content"] == "x" * 2000


@pytest.mark.parametrize("cmd", ['node -e "1"', "node --eval=1", 'node -p "1"', "node --print 1", "node -i", "node -"])
def test_node_inline_code_is_refused(sb, cmd):
    with pytest.raises(SandboxError):
        sb.check_command(cmd)
