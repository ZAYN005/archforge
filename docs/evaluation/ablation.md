# ArchForge evaluation

All variants: same two input documents, model deepseek-v4-pro, same sandbox, same per-run budget cap. Scored by an **independent acceptance probe** (13 black-box HTTP checks against the running server; it never reads the generated tests).

| Variant | Probe (of 13) | Own tests | Cost | Minutes | LLM calls | Cache hit | Status |
|---|---|---|---|---|---|---|---|
| **full** | **12** | 44/45 | $0.397 | 18.7 | 145 | 89% | done |
| **no-lint** | **2** | 52/52 | $0.294 | 12.2 | 145 | 91% | done |
| **no-tests** | **12** | 0/- | $0.283 | 11.9 | 131 | 92% | done |
| **single-agent** | **1** | 28/28 | $0.073 | 4.0 | 50 | 98% | done |

## Probe checks per variant

| Check | full | no-lint | no-tests | single-agent |
|---|---|---|---|---|
| C01 spec contract: GET /play -> 200 with integer gameId | pass | **fail** | pass | **fail** |
| C02 fresh install playable: first question has >= 2 options and no correctAnswer leak | pass | **fail** | pass | **fail** |
| C03 answer endpoint judges an answer (POST /games/:id/answers -> correct: boolean) | pass | **fail** | pass | **fail** |
| C04 score endpoint (GET /games/:id/score -> numeric score) | pass | **fail** | pass | **fail** |
| C05 pause works and blocks questions (pause 200, question 409) | **fail** | **fail** | pass | **fail** |
| C06 resume works (Paused -> Playing) | pass | **fail** | pass | **fail** |
| C07 quit from Paused ends the game; resume afterwards is rejected (409) | pass | **fail** | pass | **fail** |
| C08 help (GET /help -> 200) | pass | **fail** | pass | **fail** |
| C09 admin security: no token -> 401/403, correct token -> 200 | pass | pass | pass | pass |
| C10 admin can replace the question bank and new games use it | pass | **fail** | pass | **fail** |
| C11 fair play: correct answer is not always in the same option position | pass | **fail** | **fail** | **fail** |
| C12 durability: question bank survives a server restart (same data file) | pass | **fail** | pass | **fail** |
| C13 error format: unknown game -> 404 with {error: {code}} | pass | pass | pass | **fail** |

## Failure details

**full**: C05 (pause 200, question while paused 200)
**no-lint**: C01 (200 {'gameId': '35787cbd-570d-457e-90b6-d988fc371069', 'score': 0, 'state': 'PLAYING', 'totalQuestions': 8, 'answered': 0, 'question': {'id': 'q8', 'prompt': 'W); C02 (); C03 (); C04 (); C05 (); C06 (); C07 (); C08 (404); C10 (PUT 400, new game uses bank: False); C11 (correct-answer positions []); C12 (skipped: bank could not be replaced)
**no-tests**: C11 (correct-answer positions [0, 0, 0, 0, 0, 0, 0, 0])
**single-agent**: C01 (404 None); C02 (); C03 (); C04 (); C05 (); C06 (); C07 (); C08 (404); C10 (PUT 404, new game uses bank: False); C11 (correct-answer positions []); C12 (skipped: bank could not be replaced); C13 (404 None)
