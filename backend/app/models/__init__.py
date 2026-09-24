"""SQLAlchemy models exported for easy imports."""

from .user import User, UserRole
from .oidc_identity import OidcIdentity
from .data_source import DataSource
from .conversation import Conversation
from .provider import ProviderApp, UserProviderToken
from .activity import (
    Activity,
    ActivitySource,
    ActivityTrainingEvidence,
    IngestRun,
    IngestDecision,
)
from .sleep import SleepSession
from .sync import SyncJob, SyncCheckpoint
from .dossier import DossierJob, DossierArtifact
from .archive_import import ArchiveImportJob, ArchiveImportObject
from .refresh_token import RefreshTokenSession
from .coaching import AthleteGoal, AthleteGoalEvent, AthleteGoalObjective, NextSessionPlan

__all__ = [
    "User",
    "UserRole",
    "OidcIdentity",
    "DataSource",
    "Conversation",
    "ProviderApp",
    "UserProviderToken",
    "Activity",
    "ActivitySource",
    "ActivityTrainingEvidence",
    "IngestRun",
    "IngestDecision",
    "SleepSession",
    "SyncJob",
    "SyncCheckpoint",
    "DossierJob",
    "DossierArtifact",
    "ArchiveImportJob",
    "ArchiveImportObject",
    "RefreshTokenSession",
    "AthleteGoal",
    "AthleteGoalEvent",
    "AthleteGoalObjective",
    "NextSessionPlan",
]
