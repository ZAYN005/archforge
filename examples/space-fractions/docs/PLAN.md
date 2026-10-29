# Implementation plan (Architect)

The system is an Express 4 desktop game served to an Electron shell. The core domain owns fraction value comparison, the legal game state machine, and seed questions, while a swappable store (memory or atomic JSON file) preserves data. Game routes call GameService to start games, serve shuffled options without revealing the correct answer, score answers by value, and expose pause/resume/quit transitions. Admin routes require x-admin-token and use QuestionService to list or replace the question bank. Electron serves the public UI flow: intro movie, main menu, questions, and ending feedback.

## Modules

| Path | Work package | Exports | Reqs |
|---|---|---|---|
| `src/app.js` | core | createApp(options) -> Express app: configures app, uses options.store or createFileStore(process.env.DATA_FILE || 'data/store.json'), sets adminToken, serves public/ and GET /help // @req NFR-1 FR-4 ASR-2 | NFR-1, FR-4, ASR-2 |
| `src/server.js` | core | start(port) -> Promise<{server, port}>: listens on `port ?? process.env.PORT ?? 3000`, resolves with actual bound port; direct run starts app // @req NFR-1 | NFR-1 |
| `src/domain/fraction.js` | core | parseFraction(value) -> {numerator, denominator}: parses 'n/d' or integer string, throws INVALID_FRACTION on malformed input // @req FR-1<br>areEquivalent(a, b) -> boolean: compares fraction values, so 1/2 equals 2/4 // @req FR-1 | FR-1 |
| `src/domain/gameStateMachine.js` | core | transition(state, event) -> nextState: allows PLAYING -> PAUSED, PAUSED -> PLAYING, PLAYING -> GAME_OVER, PAUSED -> GAME_OVER; throws ILLEGAL_TRANSITION otherwise // @req FR-1 | FR-1 |
| `src/domain/seedQuestions.js` | core | seedQuestions -> Question[]: the eight planned grade-6 fraction questions // @req FR-1 | FR-1 |
| `src/domain/questionPresenter.js` | core | shuffleOptions(options, rng) -> string[]: returns options in a shuffled order // @req FR-1<br>presentQuestion(question, game) -> {prompt, options}: returns prompt and shuffled options, never correctAnswer // @req FR-1 | FR-1 |
| `src/store/memoryStore.js` | core | createMemoryStore({empty}) -> Store: creates store; if empty is true starts empty, otherwise starts with seedQuestions // @req ASR-1 FR-1 | ASR-1, FR-1 |
| `src/store/fileStore.js` | core | createFileStore(filePath) -> Store: loads existing JSON, writes through temp file then rename, seeds new files // @req ASR-1 FR-1 | ASR-1, FR-1 |
| `src/components/question/questionService.js` | question | listQuestions(store) -> Question[]: returns all questions with ids and correct answers // @req FR-3<br>replaceQuestions(store, questions) -> {count}: validates and atomically replaces the question bank // @req FR-3<br>validateQuestions(questions) -> void: throws INVALID_QUESTIONS if any question is  | FR-3 |
| `src/components/admin/adminRoutes.js` | admin | createAdminRouter({questionService, adminToken}) -> Express Router: mounts GET /admin/questions and PUT /admin/questions; checks header token // @req FR-3 ASR-2 | FR-3, ASR-2 |
| `src/components/game/gameService.js` | game | createGame(store) -> PublicGame: creates a game with shuffled question/option order and returns first question // @req FR-1<br>getCurrentQuestion(store, gameId) -> PublicQuestion: returns current prompt/options // @req FR-1<br>submitAnswer(store, gameId, answerText) -> AnswerResult: validates fracti | FR-1, FR-2 |
| `src/components/game/gameRoutes.js` | game | createGameRouter({gameService}) -> Express Router: mounts GET /play, GET /games/:gameId/question, POST /games/:gameId/answers, GET /games/:gameId/score, POST /games/:gameId/pause, POST /games/:gameId/resume, POST /games/:gameId/quit // @req FR-1 FR-2 | FR-1, FR-2 |
| `src/components/user/userService.js` | user | createPlayer() -> User: creates a local anonymous player // @req FR-1<br>getPlayer(id) -> User|undefined: returns a player by id // @req FR-1 | FR-1 |
| `electron/main.js` | ui | createWindow() -> BrowserWindow: creates the Electron BrowserWindow and loads the app URL from the running Express server // @req FR-5 | FR-5 |
| `electron/preload.js` | ui | exposeDesktopBridge() -> void: exposes a minimal frozen desktop API through contextBridge // @req FR-5 | FR-5 |

## API contract

| Endpoint | Module | Response | Errors | Reqs |
|---|---|---|---|---|
| `GET /play` | `src/components/game/gameRoutes.js` | 200 OK {gameId: number, state: 'PLAYING', score: 0, totalQuestions: number, question: {prompt: string, options: string[]}} | 404 NO_QUESTIONS when question bank is empty | FR-1 |
| `GET /games/{gameId}/question` | `src/components/game/gameRoutes.js` | 200 OK {prompt: string, options: string[], questionNumber: number, totalQuestions: number} | 404 GAME_NOT_FOUND when gameId does not exist; 409 GAME_OVER when the game has already ended | FR-1 |
| `POST /games/{gameId}/answers` | `src/components/game/gameRoutes.js` | 200 OK {correct: boolean, submittedAnswer: string, correctAnswer: string, score: number, totalQuestions: number, state: 'PLAYING'|'GAME_OVER', nextQuestion: {prompt, options}|null, finalFeedback: string|null} | 400 INVALID_ANSWER when answer missing or not a valid fraction/integer; 404 GAME_NOT_FOUND when gameId does not exist; 409 GAME_OVER when game has already ended; 409 NOT_PLAYING when game is paused | FR-1, FR-2 |
| `PUT /admin/questions` | `src/components/admin/adminRoutes.js` | 200 OK {count: number} | 400 INVALID_QUESTIONS when questions invalid; 401 ADMIN_TOKEN_MISSING when x-admin-token header missing; 403 ADMIN_TOKEN_INVALID when x-admin-token does not match options.adminToken | FR-3, ASR-2 |
| `GET /games/{gameId}/score` | `src/components/game/gameRoutes.js` | 200 OK {gameId: number, score: number, totalQuestions: number, percent: number, state: 'PLAYING'|'PAUSED'|'GAME_OVER'} | 404 GAME_NOT_FOUND when gameId does not exist | FR-2 |
| `GET /admin/questions` | `src/components/admin/adminRoutes.js` | 200 OK {questions: [{id: number, prompt: string, options: string[], correctAnswer: string}]} | 401 ADMIN_TOKEN_MISSING when x-admin-token header missing; 403 ADMIN_TOKEN_INVALID when x-admin-token does not match options.adminToken | FR-3, ASR-2 |
| `GET /help` | `src/app.js` | 200 OK {title: string, rules: string[], controls: string[]} |  | FR-4 |
| `POST /games/{gameId}/pause` | `src/components/game/gameRoutes.js` | 200 OK {gameId: number, state: 'PAUSED'} | 404 GAME_NOT_FOUND when gameId does not exist; 409 ILLEGAL_TRANSITION when current state is not PLAYING | FR-1 |
| `POST /games/{gameId}/resume` | `src/components/game/gameRoutes.js` | 200 OK {gameId: number, state: 'PLAYING'} | 404 GAME_NOT_FOUND when gameId does not exist; 409 ILLEGAL_TRANSITION when current state is not PAUSED | FR-1 |
| `POST /games/{gameId}/quit` | `src/components/game/gameRoutes.js` | 200 OK {gameId: number, state: 'GAME_OVER'} | 404 GAME_NOT_FOUND when gameId does not exist; 409 ILLEGAL_TRANSITION when current state is not PAUSED | FR-1 |