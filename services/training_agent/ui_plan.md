## UI Refactor Plan (training_agent)

### Domains and Target Modules
- **Auth & Header Config**: Google sign-in, API key input, status banner  
  - Target: `services/training_agent/ui/auth_section.py`
- **Garmin Token Management**: token status, refresh/reconnect, scraper token helper  
  - Target: `services/training_agent/ui/garmin_tokens.py`
- **Garmin Ingestion Actions**: fetch self/all, test run toggle, test data summary/clear, logs/report modal  
  - Target: `services/training_agent/ui/garmin_ingest.py`
- **Garmin Category Tester**: load categories, per-category probes  
  - Target: `services/training_agent/ui/garmin_categories.py`
- **Generic Metrics Actions**: weekly summary, sleep, VO2, HRV, training logs, etc.  
  - Target: `services/training_agent/ui/metrics_panels.py`
- **Shared HTML/Layout/JS Utilities**: layout skeleton, styles, shared JS helpers (escapeHtml, banner, request helpers), endpoint list data  
  - Target: `services/training_agent/ui/base.py`
- **Routes Composition**: FastAPI routes that assemble the sections and serve pages (including helper pages)  
  - Target: `services/training_agent/ui/routes.py`

### Notes
- Extract sections incrementally from `services/training_agent/ui.py` into the above modules, then compose in `routes.py`.
- Keep `ui.py` in place until the new package is fully wired to avoid import breakage; once migrated, delete `ui.py` and update imports to the new package.
