# ArchForge evaluation

All variants: same two input documents, model deepseek-v4-pro, same sandbox, same per-run budget cap. Scored by an **independent acceptance probe** (13 black-box HTTP checks against the running server; it never reads the generated tests).

| Variant | Probe (of 13) | Own tests | Cost | Minutes | LLM calls | Cache hit | Status |
|---|---|---|---|---|---|---|---|
| **gen-20261025-203406** | **10** | 51/51 | - | - | - | - | - |
| **gen-20261026-213607** | **11** | 63/63 | - | - | - | - | - |
| **gen-20261026-221421** | **13** | 65/65 | - | - | - | - | - |

## Probe checks per variant

| Check | gen-20261025-203406 | gen-20261026-213607 | gen-20261026-221421 |
|---|---|---|---|
| C01 spec contract: GET /play -> 200 with integer gameId | pass | pass | pass |
| C02 fresh install playable: first question has >= 2 options and no correctAnswer leak | **fail** | pass | pass |
| C03 answer endpoint judges an answer (POST /games/:id/answers -> correct: boolean) | **fail** | pass | pass |
| C04 score endpoint (GET /games/:id/score -> numeric score) | pass | pass | pass |
| C05 pause works and blocks questions (pause 200, question 409) | pass | **fail** | pass |
| C06 resume works (Paused -> Playing) | pass | pass | pass |
| C07 quit from Paused ends the game; resume afterwards is rejected (409) | pass | pass | pass |
| C08 help (GET /help -> 200) | pass | pass | pass |
| C09 admin security: no token -> 401/403, correct token -> 200 | pass | pass | pass |
| C10 admin can replace the question bank and new games use it | pass | pass | pass |
| C11 fair play: correct answer is not always in the same option position | **fail** | **fail** | pass |
| C12 durability: question bank survives a server restart (same data file) | pass | pass | pass |
| C13 error format: unknown game -> 404 with {error: {code}} | pass | pass | pass |

## Failure details

**gen-20261025-203406**: C02 (404); C03 (); C11 (correct-answer positions [0, 0, 0, 0, 0, 0, 0, 0])
**gen-20261026-213607**: C05 (pause 200, question while paused 200); C11 (correct-answer positions [0, 0, 0, 0, 0, 0, 0, 0])
