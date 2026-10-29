# Video script (~9 minutes)

## Before recording: checklist
- [ ] The key comes from `DEEPSEEK_API_KEY`: **leave the key field empty and never click "Show"**.
- [ ] Close PowerShell windows that show earlier commands; close WeChat and notifications (Focus Assist on).
- [ ] Desktop: `dist\ArchForge\ArchForge.exe` ready, the final project and `SpaceFractions.exe` already built (backup in case the live build is slow).
- [ ] Open in tabs: the GitHub repo README, `EVALUATION.md`, a generated `docs/spec/lint_report.md`.
- [ ] Recorder: OBS or Xbox Game Bar (Win+Alt+R), 1080p, microphone check.
- [ ] Start the live run first (it takes ~15 min) and talk over it; cut the waiting parts in editing.

---

### 1. Intro (0:00–0:40)
"Hi, I'm Zain Ali from Nanjing Tech University. This is **ArchForge**, my solution to Task 1: a Claude-Code-style
coding agent that turns an architecture specification into a working, tested desktop application, using DeepSeek
v4-pro, for under one dollar per run. One idea guided the whole design: the LLM writes, code checks."

### 2. The input is flawed (0:40–1:40) - show lint_report.md
"Before generating anything, ArchForge reads the two documents into a structured JSON IR, with every fact pointing
back to its file and line. Then 21 lint rules check the spec. They found 21 defects. Three examples:
- the SLO says 99.99 % uptime but a 1 % error budget; it should be 0.01 %;
- the sequence diagram says 'check answer', but the Question class has no correct answer to check against;
- the OpenAPI has 1 endpoint while the diagrams need 10.
Every finding has evidence and a resolution, and every resolution is logged in assumptions.md, so every decision in
the generated code is traceable."

### 3. Live run (1:40–4:00) - ArchForge.exe
Double-click `ArchForge.exe`. "No Python or Node needed, both are bundled." Empty key field → Check key → Generate.
While it runs, point at things on screen:
- **Phases**: "Architect plans a contract; code validates it."
- **Tester first**: "Tests are written from the spec before any code exists, then locked with SHA-256."
- **Coders**: "Six sub-agents with fresh context and write scopes, like Claude Code's sub-agents with claw-code's
  permission modes. Here a coder is DENIED writing a test file."
- **Cost meter**: "Every call is metered; the budget guard refuses a call before it can cross one dollar. The
  cache hit rate is about 90 %: all agents share one prompt prefix. Without caching this run would cost $1.86."
- **Tool loop**: "The model only requests tools; edits are exact-string replacements that must match once, and the
  agent must read a file before editing it."

### 4. Result (4:00–5:00)
Result tab: tests, traceability all PASS, conformance, reviewer, tamper count, cost. Open TRACEABILITY.md:
"Requirement → code → test → result, built by scanning, not by asking the LLM."

### 5. The game (5:00–6:00)
Click **Build SpaceFractions .exe** (or use the prebuilt one). Double-click → intro → menu → play 3 questions
(show that the right answer moves position) → pause/resume → ending feedback → Admin screen.
"The generated game is a real desktop application, as you required."

### 6. Evidence (6:00–8:00) - EVALUATION.md
"I didn't want to trust the agent's own tests, so I wrote an independent judge: 13 black-box checks against the
running server.
- History: every run passed all of its own tests, yet the judge found real bugs: an empty question bank on first
  launch, the correct answer always in position one, questions served while paused. Each became a rule in ArchForge.
- Ablation: full pipeline 12 of 13; without Spec Lint 2 of 13, with 52 green tests; a single agent with the same
  tools 1 of 13. Green tests do not mean a correct system: the spec analysis and the pipeline matter."

### 7. Security & honesty (8:00–8:45)
"The key never touches disk or logs, and child processes cannot see it. In one run the repair agent bypassed my
file tools with `node -e`, so I blocked inline code and added the SHA-256 test lock that reverts any change. It's
a policy sandbox, not OS isolation, and the README says so."

### 8. Close (8:45–9:00)
"Everything is on GitHub: source, 94 tests, the Windows build workflow and an example output. Thank you."
