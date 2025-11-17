# Agent Factory (Incremental Components)

New pieces only; they do not regenerate existing Run Trainer logic.

- `watchdog.py`: polls for newly created conversations to trigger downstream processing.
- `auditor.py`: validates agent proposals (name/description/capabilities) before generation.
- `prompt_generator.py`: builds a Codex coding prompt (targeting GPT-5.1) without restating existing architecture.
- `registry.py`: lightweight API router for agent registration; in-memory registry by default.

To wire into FastAPI, include `registry_router` in your app startup, or back it with persistent storage.
