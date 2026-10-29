# Assumptions and Decisions

Everything the generated project does that the spec does NOT literally say is listed here, with the lint finding that forced the decision. Raw spec facts are in `ir.raw.json`; the version the code is generated from is `ir.resolved.json`.

## Task constraints (from the evaluator)

| ID | Constraint | Source | Realised by |
|---|---|---|---|
| C-1 | The generated game is a desktop application, not a web application | evaluator email | Electron shell around the Express app; packaged as a Windows .exe |
| C-2 | Total LLM token cost per run stays under 1 USD on DeepSeek | evaluator email | ArchForge budget guard (archforge/llm.py) |
| C-3 | The LLM is deepseek-v4-pro via the official API | Task1-EN.docx | archforge/config.py default model |
| C-4 | Outputs: project layout + full source, dependency manifest, README, tests, optional Dockerfile | Task1-EN.docx | planner deliverables checklist |
| C-5 | Follow the architecture's stack where proportionate: Node.js 18 + Express 4 | Architecture_Documentation.md (recommended stack) | selected stack (SL-21) |

## Decisions from Spec Lint

**A-01** (F-01, SL-01) Traceability points to 'sql/question_ddl.sql', which is not a declared deliverable

- Decision: Generate BOTH files: sql/game_ddl.sql (games table, as declared) and sql/question_ddl.sql (new questions table). Traceability for this requirement keeps pointing to sql/question_ddl.sql.
- IR change: `added deliverable sql/question_ddl.sql`
- IR change: `added table 'questions' (id, prompt, options, correct_answer) in sql/question_ddl.sql`

**A-02** (F-02, SL-02) ASR-2 (security) is used but missing from the traceability matrix

- Decision: Add ASR-2 to the generated traceability matrix, mapped to UserComponent (authentication/authorization) and the admin-only API routes.
- IR change: `added traceability row for ASR-2 -> UserComponent`

**A-03** (F-03, SL-05) Testing matrix is empty

- Decision: Generate a filled matrix: unit + integration tests for every component, contract tests for every API route, one E2E test for the full game flow; chaos testing replaced by failure-injection tests.
- IR change: `filled testing matrix for all components (see testing.resolved_matrix)`

**A-04** (F-04, SL-11) Question cannot 'check answer': it has no answer data

- Decision: Add Question.correctAnswer (a fraction, stored as 'n/d') and Question.checkAnswer() which compares fractions by value (1/2 == 2/4).
- IR change: `Question: added attribute correctAnswer and method checkAnswer()`

**A-05** (F-05, SL-13) SLO 99.99% implies an error budget of 0.01%, not 1%

- Decision: Record the corrected budget (0.01%) in the README; the desktop build has no SLO monitoring, so this is documentation-only.
- IR change: `error budget 1% -> 0.01% (= 100% - 99.99%)`

**A-06** (F-06, SL-04) AdminComponent appears in diagrams but not in the architecture text

- Decision: Keep it as its own module. Responsibility inferred from the use-case diagram: 'handles update questions for the Admin actor'.
- IR change: `AdminComponent.responsibility = 'handles update questions for the Admin actor' (inferred from use cases)`

**A-07** (F-07, SL-06) 5 of 12 stack justifications do not support the cited requirement

- Decision: Ignore these justifications. Stack is chosen by scope instead (see SL-21) and each choice gets a real rationale in the generated README.
- IR change: `marked 5 stack justifications as unreliable`

**A-08** (F-08, SL-07) 3 use cases have no requirement ID

- Decision: Create inferred requirements (FR-2, FR-3, FR-4), marked origin='inferred', each traced to code and tests like spec requirements.
- IR change: `inferred requirement FR-2 'View Score' from use case ViewScore`
- IR change: `inferred requirement FR-3 'Update Questions' from use case UpdateQuestions`
- IR change: `inferred requirement FR-4 'View Help' from use case ViewHelp`

**A-09** (F-09, SL-08) Intro movie, main menu and ending scene are in the summary but in no diagram or API

- Decision: Add an inferred requirement for the full experience flow and generate one UI screen per step (intro animation, menu, question screen, ending with feedback).
- IR change: `inferred requirement FR-5 (experience flow) and 4 UI screens`

**A-10** (F-10, SL-09) OpenAPI defines 1 endpoint, diagrams need 8 more

- Decision: Keep GET /play exactly as specified (contract compatibility) and add the derived endpoints, each marked origin='derived' with the diagram element it came from.
- IR change: `derived endpoint GET /games/{gameId}/question  <- SequenceDiagram1: Game->Question getPrompt()`
- IR change: `derived endpoint POST /games/{gameId}/answers  <- SequenceDiagram1: User->Game submit answer`
- IR change: `derived endpoint PUT /admin/questions  <- SequenceDiagram2: Admin->Question update()`
- IR change: `derived endpoint GET /games/{gameId}/score  <- use case ViewScore`
- IR change: `derived endpoint GET /admin/questions  <- use case UpdateQuestions`
- IR change: `derived endpoint GET /help  <- use case ViewHelp`
- IR change: `derived endpoint POST /games/{gameId}/pause  <- state transition Playing --pause()--> Paused`
- IR change: `derived endpoint POST /games/{gameId}/resume  <- state transition Paused --resume()--> Playing`

**A-11** (F-11, SL-10) ID types disagree between the class diagram and the contracts

- Decision: Use integer IDs everywhere: the external contracts (OpenAPI, proto) and the SQL DDL agree on integers, and contracts win over the class diagram.
- IR change: `Game.id: string -> int`
- IR change: `Question.id: string -> int`
- IR change: `User.id: string -> int`
- IR change: `Admin.id: string -> int`

**A-12** (F-12, SL-12) Admin calls Question.update(), which Question does not define

- Decision: Implement it in QuestionComponent as updateQuestions(questions), called by the admin route; the Admin class method is the entry point.
- IR change: `Question: added service method updateQuestions(questions)`

**A-13** (F-13, SL-14) State machine has no final state; dead end: GameOver

- Decision: Mark GameOver as final; add Paused --quit()--> GameOver so a paused game can be ended; illegal transitions (e.g. resume() while Playing) return HTTP 409.
- IR change: `marked GameOver as final state (GameOver --> [*])`
- IR change: `added transition Paused --quit()--> GameOver`
- IR change: `derived endpoint POST /games/{gameId}/quit`

**A-14** (F-15, SL-17) Microservices style, but deployment is a single container

- Decision: Build a modular monolith: one module per component with its own router, service and repository, talking only through interfaces, so each could be split into a service later. One Dockerfile with a pinned version tag; the k8s manifest is regenerated with that tag.
- IR change: `deployment model: modular monolith, 1 image, pinned tag`

**A-15** (F-21, SL-21) Recommended stack has 11 technologies for 1 table and 1 endpoint

- Decision: Use Node.js 18, Express.js 4, PostgreSQL 14 (DDL) + in-memory repository, Docker. The rest is listed in the README as out of scope with the reason, and the repository interface keeps PostgreSQL a drop-in option.
- IR change: `selected MVP stack; 7 infrastructure items documented as out of scope`

## Noted, no change needed

- F-14 (SL-15) ObjectDiagram: object diagram uses 'participant' (sequence-diagram keyword); expected 'object'. Parsed tolerantly: participants treated as objects. Diagram meaning is unchanged.
- F-16 (SL-16) SequenceDiagram1 and CollaborationDiagram1 are identical. Treated as one interaction; no extra behaviour derived.
- F-17 (SL-16) SequenceDiagram2 and CollaborationDiagram2 are identical. Treated as one interaction; no extra behaviour derived.
- F-18 (SL-16) Document says 11 PlantUML diagrams; the view file has 13. All blocks are parsed; duplicates merged.
- F-19 (SL-18) Question is inside package Game, but QuestionComponent is a separate component. Follow the component diagram (3 views agree): QuestionComponent is its own module.
- F-20 (SL-20) 'Requirements document' is referenced but was not provided. Requirement texts are taken from the traceability table, QA table and diagrams; anything inferred is marked origin='inferred'.

## Requirement set used for generation

| ID | Text | Origin |
|---|---|---|
| ASR-1 | Data durability | spec |
| ASR-2 | security | spec |
| FR-1 | Play game | spec |
| NFR-1 | Performance | spec |
| FR-2 | View Score | inferred |
| FR-3 | Update Questions | inferred |
| FR-4 | View Help | inferred |
| FR-5 | Experience flow: introductory movie -> main menu -> series of fraction questions -> ending scene with feedback | inferred |

4 of 8 requirements are inferred.