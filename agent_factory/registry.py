from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db


class AgentRegistration(BaseModel):
    agent_id: str
    name: str
    description: str
    capabilities: List[str]


registry_router = APIRouter(prefix="/api/agents", tags=["agents"])

# In-memory registry for simplicity; replace with persistent store if needed.
AGENT_REGISTRY: Dict[str, AgentRegistration] = {}


@registry_router.post("/register")
def register_agent(body: AgentRegistration, user=Depends(get_current_user), db: Session = Depends(get_db)):
    if body.agent_id in AGENT_REGISTRY:
        raise HTTPException(status_code=400, detail="Agent already registered")
    AGENT_REGISTRY[body.agent_id] = body
    return {"status": "registered", "agent_id": body.agent_id}
