"""Task-level constraints: requirements that come from the EVALUATOR, not from the spec.

They sit next to the spec requirements in the resolved IR, so the planner and
the traceability matrix treat them exactly like FR/NFR/ASR.
"""

TASK_CONSTRAINTS = [
    {"id": "C-1", "text": "The generated game is a desktop application, not a web application",
     "source": "evaluator email", "realised_by": "Electron shell around the Express app; packaged as a Windows .exe"},
    {"id": "C-2", "text": "Total LLM token cost per run stays under 1 USD on DeepSeek",
     "source": "evaluator email", "realised_by": "ArchForge budget guard (archforge/llm.py)"},
    {"id": "C-3", "text": "The LLM is deepseek-v4-pro via the official API",
     "source": "Task1-EN.docx", "realised_by": "archforge/config.py default model"},
    {"id": "C-4", "text": "Outputs: project layout + full source, dependency manifest, README, tests, optional Dockerfile",
     "source": "Task1-EN.docx", "realised_by": "planner deliverables checklist"},
    {"id": "C-5", "text": "Follow the architecture's stack where proportionate: Node.js 18 + Express 4",
     "source": "Architecture_Documentation.md (recommended stack)", "realised_by": "selected stack (SL-21)"},
]
