"""ArchForge desktop GUI (PySide6).

Layout
  left   : configuration - API key, input files, output folder, options, Run / Stop
  right  : live run view - phase stepper, cost meter vs. budget, test status, and tabs
           (Live log | Spec Lint | Traceability | Result)

Threading
  The pipeline runs in a QThread (Worker). It never touches widgets: every event from the
  EventLog is forwarded through a Qt signal, which Qt delivers on the GUI thread. That is the
  standard, safe way to update a Qt UI from a background job, and why the window never freezes.

Security
  The key field is a password field. The key is passed to the pipeline in memory only,
  registered with the redactor, optionally stored in Windows Credential Manager (keyring),
  and never written to a file or shown in the log.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__, config
from ..runtime import resource_path, setup_node

PHASES = [("spec", "Spec + Lint"), ("plan", "Plan"), ("scaffold", "Scaffold"), ("tests", "Tests"),
          ("code", "Code"), ("verify_repair", "Verify + Repair"), ("review", "Review"), ("trace", "Trace")]

C = {"bg": "#0f1424", "panel": "#161d33", "panel2": "#1c2540", "line": "#2a3558", "text": "#e6e9f5",
     "muted": "#8d97b8", "accent": "#7c5cff", "accent2": "#22c3a6", "warn": "#f2b84b", "err": "#ff6b6b",
     "ok": "#3ddc97"}

QSS = f"""
* {{ font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 10pt; color: {C['text']}; }}
QMainWindow, QWidget#root {{ background: {C['bg']}; }}
QFrame#panel {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 12px; }}
QLabel#h1 {{ font-size: 18pt; font-weight: 700; }}
QLabel#sub {{ color: {C['muted']}; }}
QLabel#section {{ color: {C['muted']}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }}
QLineEdit, QDoubleSpinBox {{ background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 8px;
    padding: 7px 9px; selection-background-color: {C['accent']}; }}
QLineEdit:focus, QDoubleSpinBox:focus {{ border-color: {C['accent']}; }}
QPushButton {{ background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 8px; padding: 7px 12px; }}
QPushButton:hover {{ border-color: {C['accent']}; }}
QPushButton:disabled {{ color: {C['muted']}; }}
QPushButton#run {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {C['accent']}, stop:1 #5a8cff);
    border: none; font-size: 11pt; font-weight: 700; padding: 11px; }}
QPushButton#run:disabled {{ background: {C['line']}; }}
QPushButton#stop {{ border-color: {C['err']}; color: {C['err']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {C['line']};
    background: {C['panel2']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
QProgressBar {{ background: {C['panel2']}; border: none; border-radius: 6px; height: 12px; text-align: center;
    font-size: 8pt; }}
QProgressBar::chunk {{ border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 {C['accent2']}, stop:1 {C['accent']}); }}
QTabWidget::pane {{ border: 1px solid {C['line']}; border-radius: 10px; background: {C['panel']}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {C['muted']}; padding: 8px 16px; border: none; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['accent']}; }}
QPlainTextEdit {{ background: #0b1020; border: none; font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 9pt; padding: 8px; }}
QTableWidget {{ background: #0b1020; border: none; gridline-color: {C['line']}; }}
QHeaderView::section {{ background: {C['panel2']}; color: {C['muted']}; border: none; padding: 6px;
    font-weight: 600; }}
QSplitter::handle {{ background: {C['bg']}; }}
"""


def make_icon() -> QIcon:
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 256, 256)
    g.setColorAt(0, QColor(C["accent"]))
    g.setColorAt(1, QColor(C["accent2"]))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(8, 8, 240, 240, 56, 56)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 96, QFont.Black)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "AF")
    p.end()
    return QIcon(pm)


# ====================================================================== worker
class Worker(QObject):
    event = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, args: dict):
        super().__init__()
        self.args = args
        self.cancel = threading.Event()

    def run(self):
        from ..__main__ import run_pipeline
        from ..events import EventLog
        from ..redact import redact
        try:
            out = self.args["out"]
            events = EventLog(os.path.join(out, ".archforge", "events.jsonl"))
            events.subscribe(self.event.emit)                     # queued to the GUI thread by Qt
            orch, st = run_pipeline(self.args["doc"], self.args["view"], out, explicit_key=self.args["key"],
                                    registry=self.args["registry"], review=self.args["review"], events=events,
                                    cancel=self.cancel, budget_usd=self.args["budget"])
            m = orch.llm.meter
            self.finished.emit({
                "status": st.status, "out": out, "tests": st.tests.summary() if st.tests else "no tests ran",
                "matrix": st.matrix, "cost_cny": m.spent_cny, "cost_usd": m.spent_cny / orch.llm.s.usd_to_cny,
                "calls": m.calls, "hit": m.usage.hit_rate, "notes": st.notes, "tamper": st.tamper,
                "conformance": st.conformance, "review": st.review.get("verdict")})
        except BaseException as e:            # incl. SystemExit from a missing key
            self.failed.emit(redact(f"{type(e).__name__}: {e}"))


class GameBuild(QObject):
    done = Signal(dict)

    def __init__(self, project, mirror):
        super().__init__()
        self.project, self.mirror = project, mirror

    def run(self):
        from ..orchestrator.gamebuild import build_game_exe
        try:
            self.done.emit(build_game_exe(self.project, china_mirror=self.mirror))
        except Exception as e:
            self.done.emit({"ok": False, "error": str(e)})


class KeyCheck(QObject):
    done = Signal(bool, str)

    def __init__(self, key):
        super().__init__()
        self.key = key

    def run(self):
        from openai import OpenAI
        from ..redact import redact
        try:
            s = config.load_settings(explicit_key=self.key)
            ids = [m.id for m in OpenAI(api_key=s.api_key, base_url=s.base_url, timeout=20,
                                        max_retries=0).models.list().data]
            self.done.emit("deepseek-v4-pro" in ids, "models: " + ", ".join(ids))
        except Exception as e:
            self.done.emit(False, redact(str(e))[:160])


# ====================================================================== widgets
class Stepper(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.chips = {}
        for key, name in PHASES:
            l = QLabel(name)
            l.setAlignment(Qt.AlignCenter)
            l.setMinimumHeight(30)
            l.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.chips[key] = l
            lay.addWidget(l)
        self.reset()

    def set(self, key, state, extra=""):
        colors = {"pending": (C["panel2"], C["muted"], C["line"]), "active": ("#2a2350", C["text"], C["accent"]),
                  "done": ("#123a33", C["ok"], "#1f6b57"), "fail": ("#3a1820", C["err"], C["err"])}
        bg, fg, border = colors[state]
        name = dict(PHASES)[key]
        chip = self.chips[key]
        chip.setText(f"{'✓ ' if state == 'done' else '● ' if state == 'active' else ''}{name}")
        chip.setToolTip(extra)
        chip.setStyleSheet(f"background:{bg};color:{fg};border:1px solid {border};border-radius:15px;"
                           f"font-size:8.5pt;font-weight:600;padding:0 6px;")

    def reset(self):
        for k, _ in PHASES:
            self.set(k, "pending")


def file_row(label_text, placeholder, pick):
    box = QVBoxLayout()
    box.setSpacing(4)
    lab = QLabel(label_text)
    lab.setObjectName("section")
    row = QHBoxLayout()
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    btn = QPushButton("Browse…")
    btn.clicked.connect(lambda: pick(edit))
    row.addWidget(edit, 1)
    row.addWidget(btn)
    box.addWidget(lab)
    box.addLayout(row)
    return box, edit


# ====================================================================== main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ArchForge {__version__} - Architecture-to-Code Agent")
        self.setWindowIcon(make_icon())
        scr = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        if scr is not None:                       # fit the screen at any display scaling
            self.resize(min(1360, int(scr.width() * 0.92)), min(860, int(scr.height() * 0.9)))
        else:
            self.resize(1360, 860)
        self.thread = None
        self.worker = None
        self.node = setup_node()
        self.hits = self.miss = 0
        self.t0 = 0.0

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self._left())
        scroll.setMinimumWidth(400)
        split.addWidget(scroll)
        split.addWidget(self._right())
        split.setSizes([420, 940])
        self._load_defaults()

    # ------------------------------------------------------------ left panel
    def _left(self):
        panel = QFrame(objectName="panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(QSize(44, 44)))
        titles = QVBoxLayout()
        t = QLabel("ArchForge", objectName="h1")
        st = QLabel("Architecture docs  →  tested desktop app", objectName="sub")
        titles.addWidget(t)
        titles.addWidget(st)
        head.addWidget(logo)
        head.addLayout(titles, 1)
        lay.addLayout(head)

        # --- API key
        lab = QLabel("DEEPSEEK API KEY", objectName="section")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-…  (empty = use DEEPSEEK_API_KEY / saved key)")
        show = QPushButton("Show")
        show.setCheckable(True)
        show.toggled.connect(lambda on: (self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText("Hide" if on else "Show")))
        krow = QHBoxLayout()
        krow.addWidget(self.key, 1)
        krow.addWidget(show)
        self.remember = QCheckBox("Remember in Windows Credential Manager")
        self.key_status = QLabel(objectName="sub")
        self.check_btn = QPushButton("Check key (free)")
        self.check_btn.clicked.connect(self.check_key)
        kst = QHBoxLayout()
        kst.addWidget(self.key_status, 1)
        kst.addWidget(self.check_btn)
        for w in (lab,):
            lay.addWidget(w)
        lay.addLayout(krow)
        lay.addWidget(self.remember)
        lay.addLayout(kst)

        # --- inputs / output
        def pick_file(edit):
            f, _ = QFileDialog.getOpenFileName(self, "Choose file", edit.text() or os.path.expanduser("~"),
                                               "Markdown (*.md);;All files (*)")
            if f:
                edit.setText(f)

        def pick_dir(edit):
            d = QFileDialog.getExistingDirectory(self, "Choose output folder", edit.text() or os.path.expanduser("~"))
            if d:
                edit.setText(d)

        b1, self.doc = file_row("ARCHITECTURE DOCUMENTATION", "Architecture_Documentation.md", pick_file)
        b2, self.view = file_row("ARCHITECTURE VIEWS (PlantUML)", "Architecture_View.md", pick_file)
        b3, self.outdir = file_row("OUTPUT FOLDER", "where the generated project goes", pick_dir)
        for b in (b1, b2, b3):
            lay.addLayout(b)

        # --- options
        lab = QLabel("OPTIONS", objectName="section")
        lay.addWidget(lab)
        grid = QGridLayout()
        grid.addWidget(QLabel("Token budget"), 0, 0)
        self.budget = QDoubleSpinBox()
        self.budget.setRange(0.10, 1.00)
        self.budget.setSingleStep(0.05)
        self.budget.setValue(1.00)
        self.budget.setPrefix("$ ")
        self.budget.setFocusPolicy(Qt.StrongFocus)
        self.budget.wheelEvent = lambda ev: ev.ignore()      # scrolling the panel must not change the budget
        grid.addWidget(self.budget, 0, 1)
        self.mirror = QCheckBox("Use China npm mirror (npmmirror.com)")
        self.mirror.setChecked(True)
        self.review = QCheckBox("Reviewer agent (read-only review)")
        self.review.setChecked(True)
        grid.addWidget(self.mirror, 1, 0, 1, 2)
        grid.addWidget(self.review, 2, 0, 1, 2)
        lay.addLayout(grid)

        n = self.node
        self.node_label = QLabel(
            f"Node.js {n['version']} ({n['source']})" if n["found"] else
            "Node.js not found - code will be generated but tests cannot run", objectName="sub")
        self.node_label.setStyleSheet(f"color:{C['ok'] if n['found'] else C['warn']}")
        lay.addWidget(self.node_label)

        lay.addStretch(1)
        self.run_btn = QPushButton("▶  Generate project", objectName="run")
        self.run_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop after current step", objectName="stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        lay.addWidget(self.run_btn)
        lay.addWidget(self.stop_btn)
        return panel

    # ------------------------------------------------------------ right panel
    def _right(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        top = QFrame(objectName="panel")
        tl = QVBoxLayout(top)
        tl.setContentsMargins(16, 14, 16, 14)
        tl.setSpacing(10)
        self.stepper = Stepper()
        tl.addWidget(self.stepper)

        stats = QHBoxLayout()
        self.cost_bar = QProgressBar()
        self.cost_bar.setRange(0, 1000)
        self.cost_bar.setValue(0)
        self.cost_bar.setFormat("")
        cost_box = QVBoxLayout()
        self.cost_label = QLabel("Cost  $0.000 / $1.00", objectName="sub")
        cost_box.addWidget(self.cost_label)
        cost_box.addWidget(self.cost_bar)
        stats.addLayout(cost_box, 3)
        self.kpi_tests = self._kpi("TESTS", "-")
        self.kpi_cache = self._kpi("CACHE HIT", "-")
        self.kpi_time = self._kpi("ELAPSED", "-")
        for k in (self.kpi_tests, self.kpi_cache, self.kpi_time):
            stats.addWidget(k[0], 1)
        tl.addLayout(stats)
        lay.addWidget(top)

        self.tabs = QTabWidget()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.lint = self._table(["ID", "Severity", "Rule", "Finding", "Resolution"])
        self.trace = self._table(["Req", "Origin", "Requirement", "Code", "Tests", "Status"])
        self.result = QWidget()
        rl = QVBoxLayout(self.result)
        self.result_text = QLabel("Run the agent to see the result here.")
        self.result_text.setWordWrap(True)
        self.result_text.setTextFormat(Qt.RichText)
        self.result_text.setAlignment(Qt.AlignTop)
        rl.addWidget(self.result_text, 1)
        btns = QHBoxLayout()
        self.open_btns = []
        for text, rel in (("Open project folder", ""), ("README", "README.md"),
                          ("Traceability", "docs/TRACEABILITY.md"), ("Spec lint report", "docs/spec/lint_report.md")):
            b = QPushButton(text)
            b.setEnabled(False)
            b.clicked.connect(lambda _=False, r=rel: self.open_rel(r))
            btns.addWidget(b)
            self.open_btns.append(b)
        rl.addLayout(btns)
        self.game_btn = QPushButton("Build SpaceFractions .exe (desktop game)")
        self.game_btn.setEnabled(False)
        self.game_btn.clicked.connect(self.build_game)
        self.game_status = QLabel(objectName="sub")
        self.game_status.setWordWrap(True)
        rl.addWidget(self.game_btn)
        rl.addWidget(self.game_status)
        self.tabs.addTab(self.log, "Live log")
        self.tabs.addTab(self.lint, "Spec Lint")
        self.tabs.addTab(self.trace, "Traceability")
        self.tabs.addTab(self.result, "Result")
        lay.addWidget(self.tabs, 1)
        return w

    def _kpi(self, title, value):
        f = QFrame()
        f.setStyleSheet(f"background:{C['panel2']};border-radius:10px;")
        l = QVBoxLayout(f)
        l.setContentsMargins(12, 6, 12, 6)
        t = QLabel(title, objectName="section")
        v = QLabel(value)
        v.setStyleSheet("font-size:14pt;font-weight:700;background:transparent;")
        t.setStyleSheet("background:transparent;" + t.styleSheet())
        l.addWidget(t)
        l.addWidget(v)
        return f, v

    def _table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setWordWrap(True)
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        if len(headers) == 5:                      # lint table: wide finding column, resolution fills the rest
            h.setSectionResizeMode(3, QHeaderView.Interactive)
            t.setColumnWidth(3, 360)
            h.setSectionResizeMode(4, QHeaderView.Stretch)
        else:                                      # traceability table: requirement text fills the rest
            h.setSectionResizeMode(2, QHeaderView.Stretch)
        return t

    # ------------------------------------------------------------ defaults / key
    def _load_defaults(self):
        for edit, name in ((self.doc, "Architecture_Documentation.md"), (self.view, "Architecture_View.md")):
            p = resource_path("inputs", name)
            if os.path.exists(p):
                edit.setText(p)
        self.outdir.setText(os.path.join(os.path.expanduser("~"), "Documents", "ArchForge"))
        s = config.load_settings()
        self.key_status.setText(f"Key: {config.describe_key(s)}" if s.has_key() else "Key: not set yet")

    def check_key(self):
        self.check_btn.setEnabled(False)
        self.key_status.setText("Checking… (listing models is free)")
        self._kc_thread = QThread()
        self._kc = KeyCheck(self.key.text().strip() or None)
        self._kc.moveToThread(self._kc_thread)
        self._kc_thread.started.connect(self._kc.run)
        self._kc.done.connect(self._key_checked)
        self._kc.done.connect(self._kc_thread.quit)
        self._kc_thread.start()

    def _key_checked(self, ok, msg):
        self.check_btn.setEnabled(True)
        self.key_status.setText(("✓ Key works - " if ok else "✗ ") + msg)
        self.key_status.setStyleSheet(f"color:{C['ok'] if ok else C['err']}")

    # ------------------------------------------------------------ run control
    def start(self):
        doc, view, base = self.doc.text().strip(), self.view.text().strip(), self.outdir.text().strip()
        for p, what in ((doc, "documentation file"), (view, "view file")):
            if not os.path.isfile(p):
                QMessageBox.warning(self, "ArchForge", f"Please choose the {what}.")
                return
        if not base:
            QMessageBox.warning(self, "ArchForge", "Please choose an output folder.")
            return
        key = self.key.text().strip() or None
        if not key and not config.load_settings().has_key():
            QMessageBox.warning(self, "ArchForge", "Please enter your DeepSeek API key.")
            return
        if key and self.remember.isChecked():
            config.save_key_to_keyring(key)
        out = os.path.join(base, "gen-" + time.strftime("%Y%m%d-%H%M%S"))
        self.current_out = out
        self._reset_view()
        self.append(f"Output: {out}", C["muted"])
        args = {"doc": doc, "view": view, "out": out, "key": key, "review": self.review.isChecked(),
                "registry": "https://registry.npmmirror.com" if self.mirror.isChecked() else None,
                "budget": float(self.budget.value())}
        self.thread = QThread()
        self.worker = Worker(args)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.event.connect(self.on_event)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self._lock_inputs(True)
        self.stop_btn.setEnabled(True)
        self.t0 = time.time()
        self.stepper.set("spec", "active")
        self.thread.start()

    def _lock_inputs(self, running: bool):
        for wdg in (self.key, self.remember, self.doc, self.view, self.outdir, self.budget, self.mirror,
                    self.review, self.run_btn, self.check_btn):
            wdg.setEnabled(not running)

    def stop(self):
        if self.worker:
            self.worker.cancel.set()
            self.stop_btn.setEnabled(False)
            self.append("Stop requested: the run stops before the next model call.", C["warn"])

    def _reset_view(self):
        self.stepper.reset()
        self.log.clear()
        self.lint.setRowCount(0)
        self.trace.setRowCount(0)
        self.hits = self.miss = 0
        self.cost_bar.setValue(0)
        self.kpi_tests[1].setText("-")
        self.kpi_cache[1].setText("-")
        for b in self.open_btns:
            b.setEnabled(False)
        self.tabs.setCurrentIndex(0)

    # ------------------------------------------------------------ events (GUI thread)
    def append(self, text, color=None):
        el = f"{time.time() - self.t0:6.1f}s " if self.t0 else ""
        color = color or C["text"]
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log.appendHtml(f'<span style="color:{C["muted"]}">{el}</span><span style="color:{color}">{safe}</span>')

    def on_event(self, e: dict):
        k, role = e.get("kind"), e.get("role", "")
        self.kpi_time[1].setText(f"{time.time() - self.t0:.0f}s")
        if k == "spec_linted":
            self.stepper.set("spec", "done", f"{e['findings']} findings")
            s = e["summary"]
            self.append(f"Spec Lint: {e['findings']} findings ({s['error']} errors, {s['warning']} warnings, "
                        f"{s['info']} info), {e['resolutions']} resolutions", C["accent2"])
            self._load_lint()
        elif k == "phase_start":
            self.stepper.set(e["phase"], "active")
            self.append(f"=== {e['phase'].upper()} ===", C["accent"])
        elif k == "phase_end":
            self.stepper.set(e["phase"], "done" if e.get("ok") else "fail", f"{e['seconds']}s, CNY {e['cost_cny']}")
            self.append(f"{e['phase']} done in {e['seconds']}s, CNY {e['cost_cny']:.4f}", C["muted"])
        elif k == "llm_call":
            t = e["tokens"]
            self.hits += t["cache_hit"]
            self.miss += t["cache_miss"]
            spent, budget = e["spent_cny"], e["budget_cny"]
            rate = spent / budget if budget else 0
            fx = config.Settings().usd_to_cny
            self.cost_bar.setValue(int(rate * 1000))
            self.cost_label.setText(f"Cost  ${spent / fx:.3f} / ${budget / fx:.2f}   "
                                    f"(CNY {spent:.3f} / {budget:.2f})")
            if self.hits + self.miss:
                self.kpi_cache[1].setText(f"{self.hits / (self.hits + self.miss):.0%}")
        elif k == "agent_start":
            self.append(f"[{role}] started ({e.get('permission')})", C["accent2"])
        elif k == "agent_stop":
            self.append(f"[{role}] {e['status']} after {e['turns']} turns", C["accent2"])
        elif k == "tool_call":
            self.append(f"  {role:>14} › {e['tool']}({e['args'][:90]})")
        elif k == "tool_result" and not e.get("ok"):
            self.append(f"  {role:>14}   {e['preview'][:110]}", C["warn"])
        elif k == "tests":
            self.kpi_tests[1].setText(f"{e['passed']}/{e['total']}")
            self.append(f"TESTS after {e['after']}: {e['summary']}", C["ok"] if e["passed"] == e["total"] else C["warn"])
        elif k == "tamper":
            self.append(f"TEST TAMPERING by {e['after']}: {e['file']} {e['change']} -> reverted", C["err"])
        elif k == "conformance":
            self.append(f"Plan conformance: {e['present']}/{e['planned']} modules; missing {e['missing']}; "
                        f"removed {e['removed']}", C["accent2"])
        elif k in ("plan_validated", "npm_install", "llm_retry", "compact", "stuck_nudge"):
            self.append(f"{k}: " + json.dumps({x: y for x, y in e.items()
                                               if x not in ("ts", "run_id", "seq", "kind", "output")})[:180],
                        C["muted"])

    def _load_lint(self):
        p = os.path.join(self.current_out, ".archforge", "spec", "lint_report.json")
        try:
            with open(p, encoding="utf-8") as f:
                findings = json.load(f)["findings"]
        except Exception:
            return
        col = {"error": C["err"], "warning": C["warn"], "info": C["accent2"]}
        self.lint.setRowCount(len(findings))
        for i, x in enumerate(findings):
            for j, v in enumerate((x["id"], x["severity"].upper(), x["rule"], x["title"], x["resolution"])):
                it = QTableWidgetItem(v)
                it.setToolTip(x["detail"] + "\n\nEvidence: " + ", ".join(x["evidence"]))
                if j == 1:
                    it.setForeground(QColor(col[x["severity"]]))
                self.lint.setItem(i, j, it)
        self.lint.resizeRowsToContents()

    def on_finished(self, r: dict):
        self._lock_inputs(False)
        self.stop_btn.setEnabled(False)
        col = {"PASS": C["ok"], "FAIL": C["err"], "UNTESTED": C["warn"], "NOT_IMPLEMENTED": C["err"]}
        rows = r["matrix"]
        self.trace.setRowCount(len(rows))
        for i, x in enumerate(rows):
            tests = f"{x['passed']}/{x['passed'] + x['failed']}" if x["tests"] else "-"
            for j, v in enumerate((x["id"], x["origin"], x["text"], ", ".join(x["code"][:3]), tests, x["status"])):
                it = QTableWidgetItem(v)
                if j == 5:
                    it.setForeground(QColor(col.get(v, C["text"])))
                self.trace.setItem(i, j, it)
        self.trace.resizeRowsToContents()
        n = {s: sum(x["status"] == s for x in rows) for s in col}
        ok = r["status"] == "done"
        conf = r.get("conformance") or {}
        self.result_text.setText(
            f"<h2 style='color:{C['ok'] if ok else C['warn']}'>{'Done' if ok else r['status']}</h2>"
            f"<p><b>Tests:</b> {r['tests']}<br>"
            f"<b>Traceability:</b> {n['PASS']} PASS, {n['FAIL']} FAIL, {n['UNTESTED']} untested, "
            f"{n['NOT_IMPLEMENTED']} not implemented<br>"
            f"<b>Plan conformance:</b> {conf.get('present', '-')}/{conf.get('planned', '-')} modules<br>"
            f"<b>Reviewer:</b> {r.get('review') or 'n/a'}<br>"
            f"<b>Test tampering detected:</b> {len(r['tamper'])}<br>"
            f"<b>Cost:</b> ${r['cost_usd']:.3f} (CNY {r['cost_cny']:.3f}), {r['calls']} model calls, "
            f"cache hit {r['hit']:.0%}<br><b>Time:</b> {time.time() - self.t0:.0f}s</p>"
            f"<p><b>Project:</b> {r['out']}</p>"
            f"<p style='color:{C['muted']}'>To play: open a terminal in the project folder and run "
            f"<code>npm start</code> (first time: <code>npm install</code> downloads Electron).</p>"
            + "".join(f"<p style='color:{C['warn']}'>note: {x}</p>" for x in r["notes"]))
        for b in self.open_btns:
            b.setEnabled(True)
        self.game_btn.setEnabled(r["status"] == "done")
        self.tabs.setCurrentWidget(self.result)
        self.append(f"RESULT: {r['status']} - {r['tests']} - ${r['cost_usd']:.3f}", C["ok"] if ok else C["warn"])

    def build_game(self):
        self.game_btn.setEnabled(False)
        self.game_status.setText("Building the game .exe with electron-builder (first time 3-8 min: downloads "
                                 "Electron)…")
        self.game_status.setStyleSheet(f"color:{C['muted']}")
        self._gb_thread = QThread()
        self._gb = GameBuild(self.current_out, self.mirror.isChecked())
        self._gb.moveToThread(self._gb_thread)
        self._gb_thread.started.connect(self._gb.run)
        self._gb.done.connect(self._game_built)
        self._gb.done.connect(self._gb_thread.quit)
        self._gb_thread.start()

    def _game_built(self, r: dict):
        self.game_btn.setEnabled(True)
        if r.get("ok"):
            self.game_status.setText(f"✓ Built in {r['seconds']:.0f}s: {r['exe']}  (double-click to play)")
            self.game_status.setStyleSheet(f"color:{C['ok']}")
            self.append(f"Game .exe built: {r['exe']}", C["ok"])
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(r["exe"])))
        else:
            self.game_status.setText("✗ Build failed - see Live log")
            self.game_status.setStyleSheet(f"color:{C['err']}")
            self.append("Game build failed:\n" + r.get("log_tail", r.get("error", "")), C["err"])

    def on_failed(self, msg: str):
        self._lock_inputs(False)
        self.stop_btn.setEnabled(False)
        self.append("FAILED: " + msg, C["err"])
        QMessageBox.critical(self, "ArchForge", msg)

    def open_rel(self, rel):
        target = os.path.join(self.current_out, rel) if rel else self.current_out
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def closeEvent(self, ev):
        if self.thread and self.thread.isRunning():
            if QMessageBox.question(self, "ArchForge", "A run is in progress. Stop it and quit?") != QMessageBox.Yes:
                ev.ignore()
                return
            self.worker.cancel.set()
            self.thread.quit()
            self.thread.wait(3000)
        ev.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ArchForge")
    app.setStyleSheet(QSS)
    app.setWindowIcon(make_icon())
    w = MainWindow()
    w.show()
    return app.exec()
