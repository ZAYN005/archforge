# Traceability Matrix

**11 PASS, 2 FAIL, 0 UNTESTED, 0 NOT IMPLEMENTED** (13 requirements and constraints). Built by scanning `@req` tags in the code and requirement IDs in Jest test names, combined with the Jest results.

| Req | Origin | Requirement | Code | Tests (passed/total) | Status |
|---|---|---|---|---|---|
| ASR-1 | spec | Data durability | `src/store/fileStore.js`<br>`src/store/memoryStore.js` | 3/3 | **PASS** |
| ASR-2 | spec | security | `src/components/admin/adminRoutes.js` | 6/6 | **PASS** |
| FR-1 | spec | Play game | `src/components/game/gameRoutes.js`<br>`src/components/game/gameService.js`<br>`src/components/user/userService.js`<br>`src/domain/fraction.js`<br>`src/domain/gameStateMachine.js`<br>`src/domain/questionPresenter.js` | 30/31 | **FAIL** |
| NFR-1 | spec | Performance | `src/app.js`<br>`src/server.js` | 1/1 | **PASS** |
| FR-2 | inferred | View Score | `src/components/game/gameRoutes.js`<br>`src/components/game/gameService.js` | 4/5 | **FAIL** |
| FR-3 | inferred | Update Questions | `src/components/admin/adminRoutes.js`<br>`src/components/question/questionService.js` | 2/2 | **PASS** |
| FR-4 | inferred | View Help | `src/app.js` | 1/1 | **PASS** |
| FR-5 | inferred | Experience flow: introductory movie -> main menu -> series of fraction | `electron/main.js`<br>`electron/preload.js` | 3/3 | **PASS** |
| C-1 | constraint | The generated game is a desktop application, not a web application | `electron/main.js` | 1/1 | **PASS** |
| C-2 | constraint | Total LLM token cost per run stays under 1 USD on DeepSeek | - | 1/1 | **PASS** |
| C-3 | constraint | The LLM is deepseek-v4-pro via the official API | - | 1/1 | **PASS** |
| C-4 | constraint | Outputs: project layout + full source, dependency manifest, README, te | - | 1/1 | **PASS** |
| C-5 | constraint | Follow the architecture's stack where proportionate: Node.js 18 + Expr | - | 1/1 | **PASS** |

## Tests per requirement

**ASR-1**: file store durability (ASR-1) ASR-1: a new file store seeds the seed questions; file store durability (ASR-1) ASR-1: data written to a file store survives re-creation on the same file; file store durability (ASR-1) ASR-1: a game persisted via the file store is readable after re-creation
**ASR-2**: admin security (ASR-2) ASR-2: GET /admin/questions without token returns 401 ADMIN_TOKEN_MISSING; admin security (ASR-2) ASR-2: PUT /admin/questions without token returns 401 ADMIN_TOKEN_MISSING; admin security (ASR-2) ASR-2: GET /admin/questions with wrong token returns 403 ADMIN_TOKEN_INVALID; admin security (ASR-2) ASR-2: PUT /admin/questions with wrong token returns 403 ADMIN_TOKEN_INVALID; admin security (ASR-2) ASR-2/FR-3: GET /admin/questions with valid token returns 200 with the question bank; admin security (ASR-2) ASR-2/FR-3: PUT /admin/questions with valid token returns 200 with count
**FR-1**: API contract: one test per endpoint FR-1: GET /play returns 200 and a new playable game payload; API contract: one test per endpoint FR-1: GET /games/:id/question returns 200 with prompt and 4 options; API contract: one test per endpoint FR-1: GET /games/:id/question returns 404 GAME_NOT_FOUND for unknown id; API contract: one test per endpoint FR-1/FR-2: POST /games/:id/answers returns 200 with feedback and score; API contract: one test per endpoint FR-1: POST /games/:id/answers returns 400 INVALID_ANSWER for missing/bad answer; API contract: one test per endpoint FR-1: POST /games/:id/answers returns 404 GAME_NOT_FOUND for unknown id; API contract: one test per endpoint FR-1: POST /games/:id/answers returns 409 NOT_PLAYING when paused; API contract: one test per endpoint FR-1: POST /games/:id/answers on a finished game returns 409 GAME_OVER; API contract: one test per endpoint FR-1: POST /games/:id/pause returns 200 with state PAUSED; API contract: one test per endpoint FR-1: POST /games/:id/pause on a paused game returns 409 ILLEGAL_TRANSITION; API contract: one test per endpoint FR-1: POST /games/:id/pause returns 404 for unknown id; API contract: one test per endpoint FR-1: POST /games/:id/resume returns 200 with state PLAYING
**NFR-1**: performance (NFR-1) NFR-1: 100 sequential GET /games/:id/question calls finish in under 2000 ms
**FR-2**: API contract: one test per endpoint FR-1/FR-2: POST /games/:id/answers returns 200 with feedback and score; API contract: one test per endpoint FR-2: GET /games/:id/score returns 200 with score, percent and state; API contract: one test per endpoint FR-2: GET /games/:id/score returns 404 GAME_NOT_FOUND for unknown id; full game flow via the API FR-1/FR-2/FR-5: start -> answer all questions -> score -> game over; full game flow via the API FR-1/FR-2: pausing and resuming mid-game preserves progress
**FR-3**: admin security (ASR-2) ASR-2/FR-3: GET /admin/questions with valid token returns 200 with the question bank; admin security (ASR-2) ASR-2/FR-3: PUT /admin/questions with valid token returns 200 with count
**FR-4**: API contract: one test per endpoint FR-4: GET /help returns 200 with title, rules and controls
**FR-5**: full game flow via the API FR-1/FR-2/FR-5: start -> answer all questions -> score -> game over; first launch experience FR-1/FR-5: a brand-new file store is immediately playable with 4 options per question; first launch experience FR-5: start(0) binds a real port and serves the HTML UI at /
**C-1**: static check: electron/main.js + public/index.html exist; package.json main = electron/main.js
**C-2**: cost meter: CNY 2.8199 of 3.55 budget
**C-3**: model used: deepseek-v4-pro
**C-4**: static check: package.json, README.md, Dockerfile, tests/ present
**C-5**: package.json pins express 4 on node >= 18