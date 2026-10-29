# Spec Lint Report: Space Fractions

Sources: `Architecture_Documentation.md` (sha256 6855cebc7fe63f64), `Architecture_View.md` (sha256 d8977790af9a015f)

**21 findings**: 5 errors, 10 warnings, 6 info. **15** are auto-resolved (see `assumptions.md`).

## Rules checked

| Rule | Check | Result |
|---|---|---|
| SL-01 | Traceability artifacts exist in deliverables | fail (1) |
| SL-02 | Every requirement ID appears in traceability | fail (1) |
| SL-03 | Traceability table and CSV agree | pass |
| SL-04 | Components in diagrams are described in the text | fail (1) |
| SL-05 | Testing matrix is filled and covers all components | fail (1) |
| SL-06 | Stack justifications match the cited requirement | fail (1) |
| SL-07 | Every use case is covered by a requirement | fail (1) |
| SL-08 | User-facing experience in the summary is covered by the design | fail (1) |
| SL-09 | API contract covers the interactions in the diagrams | fail (1) |
| SL-10 | Identifier types agree across views and contracts | fail (1) |
| SL-11 | Behaviour in diagrams has the data it needs | fail (1) |
| SL-12 | Sequence messages call methods that exist | fail (1) |
| SL-13 | SLO and error budget are consistent | fail (1) |
| SL-14 | State machine has a final state and no dead ends | fail (1) |
| SL-15 | PlantUML syntax is valid for each diagram type | fail (1) |
| SL-16 | No duplicate diagrams; declared count matches | fail (3) |
| SL-17 | Deployment manifests match the architectural style | fail (1) |
| SL-18 | Package grouping agrees with component boundaries | fail (1) |
| SL-19 | Duplicated contract blocks are identical | pass |
| SL-20 | Referenced inputs are provided | fail (1) |
| SL-21 | Recommended stack is proportionate to the system's scope | fail (1) |

## Findings

### F-01 [ERROR] Traceability points to 'sql/question_ddl.sql', which is not a declared deliverable
*Rule SL-01*

**Problem.** Traceability references sql/question_ddl.sql; deliverables list only has ['sql/game_ddl.sql']. Also, no 'questions' table is defined anywhere, although QuestionComponent owns question persistence.

**Evidence.** `Architecture_Documentation.md:35`, `Architecture_Documentation.md:307`, `Architecture_Documentation.md:238`

**Resolution.** Generate BOTH files: sql/game_ddl.sql (games table, as declared) and sql/question_ddl.sql (new questions table). Traceability for this requirement keeps pointing to sql/question_ddl.sql.

### F-02 [ERROR] ASR-2 (security) is used but missing from the traceability matrix
*Rule SL-02*

**Problem.** ASR-2 is mentioned 6 times (QA table, stack justifications) but has no row in the traceability matrix, so nothing maps it to a component or artifact.

**Evidence.** `Architecture_Documentation.md:26`, `Architecture_Documentation.md:54`, `Architecture_Documentation.md:57`, `Architecture_Documentation.md:59`

**Resolution.** Add ASR-2 to the generated traceability matrix, mapped to UserComponent (authentication/authorization) and the admin-only API routes.

### F-03 [ERROR] Testing matrix is empty
*Rule SL-05*

**Problem.** 10 of 10 cells are empty, and the matrix has no column for UserComponent, AdminComponent.

**Evidence.** `Architecture_Documentation.md:191`

**Resolution.** Generate a filled matrix: unit + integration tests for every component, contract tests for every API route, one E2E test for the full game flow; chaos testing replaced by failure-injection tests.

### F-04 [ERROR] Question cannot 'check answer': it has no answer data
*Rule SL-11*

**Problem.** SequenceDiagram1 sends 'check answer' to Question, but Question only has attributes ['id', 'prompt', 'options']. There is nothing to check the answer against.

**Evidence.** `Architecture_View.md:106`, `Architecture_View.md:31`

**Resolution.** Add Question.correctAnswer (a fraction, stored as 'n/d') and Question.checkAnswer() which compares fractions by value (1/2 == 2/4).

### F-05 [ERROR] SLO 99.99% implies an error budget of 0.01%, not 1%
*Rule SL-13*

**Problem.** Error budget = 100% - SLO. 99.99% uptime allows 0.01% downtime (about 4.3 min/month); the document says 1% (~432 min/month), 100x more.

**Evidence.** `Architecture_Documentation.md:180`, `Architecture_Documentation.md:181`

**Resolution.** Record the corrected budget (0.01%) in the README; the desktop build has no SLO monitoring, so this is documentation-only.

### F-06 [WARN] AdminComponent appears in diagrams but not in the architecture text
*Rule SL-04*

**Problem.** AdminComponent is in the Component diagram (also package Admin, node AdminClient, container AdminContainer) but section C lists no responsibility for it.

**Evidence.** `Architecture_View.md:170`

**Resolution.** Keep it as its own module. Responsibility inferred from the use-case diagram: 'handles update questions for the Admin actor'.

### F-07 [WARN] 5 of 12 stack justifications do not support the cited requirement
*Rule SL-06*

**Problem.** Language/runtime 'Node.js 18-20' justified by ASR-1 (data durability); RPC/HTTP 'RESTful API' justified by ASR-2 (security); Messaging 'RabbitMQ 3-4' justified by ASR-2 (security); CI/CD 'Jenkins 2-3' justified by ASR-1 (data durability); Container runtime 'Docker 20-21' justified by ASR-1 (data durability)

**Evidence.** `Architecture_Documentation.md:52`, `Architecture_Documentation.md:54`, `Architecture_Documentation.md:57`, `Architecture_Documentation.md:61`, `Architecture_Documentation.md:62`

**Resolution.** Ignore these justifications. Stack is chosen by scope instead (see SL-21) and each choice gets a real rationale in the generated README.

### F-08 [WARN] 3 use cases have no requirement ID
*Rule SL-07*

**Problem.** Only FR-1 'Play game' exists. Use cases 'View Score', 'Update Questions', 'View Help' have no FR, so nothing would force them to be built or tested.

**Evidence.** `Architecture_View.md:4`, `Architecture_Documentation.md:33`

**Resolution.** Create inferred requirements (FR-2, FR-3, FR-4), marked origin='inferred', each traced to code and tests like spec requirements.

### F-09 [WARN] Intro movie, main menu and ending scene are in the summary but in no diagram or API
*Rule SL-08*

**Problem.** Summary promises: introductory movie; main menu; series of fraction questions; ending scene with feedback. Not covered anywhere: introductory movie; main menu; ending scene with feedback.

**Evidence.** `Architecture_Documentation.md:7`

**Resolution.** Add an inferred requirement for the full experience flow and generate one UI screen per step (intro animation, menu, question screen, ending with feedback).

### F-10 [WARN] OpenAPI defines 1 endpoint, diagrams need 8 more
*Rule SL-09*

**Problem.** openapi.yaml only has GET /play. Sequence/use-case/state diagrams require: GET /games/{gameId}/question, POST /games/{gameId}/answers, PUT /admin/questions, GET /games/{gameId}/score, GET /admin/questions, GET /help, POST /games/{gameId}/pause, POST /games/{gameId}/resume.

**Evidence.** `Architecture_Documentation.md:83`, `Architecture_View.md:102`

**Resolution.** Keep GET /play exactly as specified (contract compatibility) and add the derived endpoints, each marked origin='derived' with the diagram element it came from.

### F-11 [WARN] ID types disagree between the class diagram and the contracts
*Rule SL-10*

**Problem.** class Game.id = string; class Question.id = string; class User.id = string; class Admin.id = string; OpenAPI gameId = integer; proto PlayRequest.gameId = int32; proto PlayResponse.gameId = int32; SQL games.id = SERIAL.

**Evidence.** `Architecture_Documentation.md:106`, `Architecture_Documentation.md:120`, `Architecture_Documentation.md:83`, `Architecture_View.md:25`, `Architecture_View.md:31`, `Architecture_View.md:38`, `Architecture_View.md:44`

**Resolution.** Use integer IDs everywhere: the external contracts (OpenAPI, proto) and the SQL DDL agree on integers, and contracts win over the class diagram.

### F-12 [WARN] Admin calls Question.update(), which Question does not define
*Rule SL-12*

**Problem.** SequenceDiagram2 calls update() on Question; class Question has methods ['getPrompt', 'getOptions']. The caller Admin has ['updateQuestions'].

**Evidence.** `Architecture_View.md:115`, `Architecture_View.md:31`

**Resolution.** Implement it in QuestionComponent as updateQuestions(questions), called by the admin route; the Admin class method is the entry point.

### F-13 [WARN] State machine has no final state; dead end: GameOver
*Rule SL-14*

**Problem.** States ['Playing', 'Paused', 'GameOver'], initial Playing, no '--> [*]'. GameOver has no outgoing transition and is not marked final. A paused game cannot be ended (no Paused -> GameOver).

**Evidence.** `Architecture_View.md:68`

**Resolution.** Mark GameOver as final; add Paused --quit()--> GameOver so a paused game can be ended; illegal transitions (e.g. resume() while Playing) return HTTP 409.

### F-14 [WARN] ObjectDiagram: object diagram uses 'participant' (sequence-diagram keyword); expected 'object'
*Rule SL-15*

**Problem.** 4 problem line(s) in ObjectDiagram (object diagram).

**Evidence.** `Architecture_View.md:56`, `Architecture_View.md:57`, `Architecture_View.md:58`

**Resolution.** Parsed tolerantly: participants treated as objects. Diagram meaning is unchanged.

### F-15 [WARN] Microservices style, but deployment is a single container
*Rule SL-17*

**Problem.** 4 containers in the Container diagram but only 1 image (spacefractions:latest) in the k8s manifest; image uses the mutable ':latest' tag.

**Evidence.** `Architecture_Documentation.md:9`, `Architecture_Documentation.md:133`, `Architecture_View.md:193`

**Resolution.** Build a modular monolith: one module per component with its own router, service and repository, talking only through interfaces, so each could be split into a service later. One Dockerfile with a pinned version tag; the k8s manifest is regenerated with that tag.

### F-16 [INFO] SequenceDiagram1 and CollaborationDiagram1 are identical
*Rule SL-16*

**Problem.** Same participants and messages (only the note differs). A collaboration diagram should show links between objects, not repeat the sequence.

**Evidence.** `Architecture_View.md:97`, `Architecture_View.md:121`

**Resolution.** Treated as one interaction; no extra behaviour derived.

### F-17 [INFO] SequenceDiagram2 and CollaborationDiagram2 are identical
*Rule SL-16*

**Problem.** Same participants and messages (only the note differs). A collaboration diagram should show links between objects, not repeat the sequence.

**Evidence.** `Architecture_View.md:112`, `Architecture_View.md:137`

**Resolution.** Treated as one interaction; no extra behaviour derived.

### F-18 [INFO] Document says 11 PlantUML diagrams; the view file has 13
*Rule SL-16*

**Problem.** 13 @startuml blocks under 11 numbered diagram types (2 of them duplicates).

**Evidence.** `Architecture_Documentation.md:3`

**Resolution.** All blocks are parsed; duplicates merged.

### F-19 [INFO] Question is inside package Game, but QuestionComponent is a separate component
*Rule SL-18*

**Problem.** Package diagram puts class Question in package Game; the component, deployment and container diagrams give it its own QuestionComponent / QuestionServer / QuestionContainer.

**Evidence.** `Architecture_View.md:168`

**Resolution.** Follow the component diagram (3 views agree): QuestionComponent is its own module.

### F-20 [INFO] 'Requirements document' is referenced but was not provided
*Rule SL-20*

**Problem.** The analysis plan aligns with a Requirements document that is not among the inputs, so original requirement texts beyond the IDs are unknown.

**Evidence.** `Architecture_Documentation.md:3`

**Resolution.** Requirement texts are taken from the traceability table, QA table and diagrams; anything inferred is marked origin='inferred'.

### F-21 [INFO] Recommended stack has 11 technologies for 1 table and 1 endpoint
*Rule SL-21*

**Problem.** Redis, RabbitMQ, Elasticsearch, OAuth2, Prometheus, Jenkins and Terraform are recommended for a single-player fraction game whose specified data model is one table.

**Evidence.** `Architecture_Documentation.md:66`, `Architecture_Documentation.md:76`

**Resolution.** Use Node.js 18, Express.js 4, PostgreSQL 14 (DDL) + in-memory repository, Docker. The rest is listed in the README as out of scope with the reason, and the repository interface keeps PostgreSQL a drop-in option.
