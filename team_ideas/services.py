from __future__ import annotations

import logging
from typing import List

import httpx
from sqlalchemy.orm import Session

from app.models import User
from .models import TeamIdea

logger = logging.getLogger(__name__)


def submit_idea(db: Session, user: User, text: str) -> TeamIdea:
    idea = TeamIdea(user_id=user.id, idea_text=text, status="new")
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


def list_ideas(db: Session, user: User) -> List[TeamIdea]:
    return db.query(TeamIdea).filter(TeamIdea.user_id == user.id).order_by(TeamIdea.created_at.desc()).all()


def summarize_for_tasks(ideas: List[TeamIdea]) -> str:
    bullet_lines = [f"- {idea.idea_text}" for idea in ideas]
    return "Summarize and convert the following ideas into actionable engineering tasks:\n" + "\n".join(bullet_lines)


def create_github_issue(token: str, repo: str, title: str, body: str) -> None:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/issues"
    r = httpx.post(url, headers=headers, json={"title": title, "body": body})
    if r.status_code >= 300:
        logger.error("Failed to create issue: %s %s", r.status_code, r.text)
        r.raise_for_status()
