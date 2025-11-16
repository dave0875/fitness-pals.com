# Team Ideas Pipeline (New)

- Model: `TeamIdea` stored alongside existing users; keeps `idea_text`, `status`, and timestamps.
- Routes (`team_ideas/routes.py`): submit (`POST /api/team-ideas`), list (`GET /api/team-ideas`), and a summarization prompt (`GET /api/team-ideas/summary`).
- Services: helpers to submit/list ideas, build a summarization prompt, and push GitHub issues (`create_github_issue`).
- Wire `router` into FastAPI as needed; add migrations for `team_ideas` table separately.
