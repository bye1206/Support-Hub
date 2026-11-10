"""SQLAlchemy models. Import registers all tables on Base.metadata."""

from app.models.ai_handoff import AiHandoff, HandoffReason
from app.models.ai_run import AiProcessingRun, AiRunStatus
from app.models.audit import AuditActorType, AuditLog
from app.models.base import Base
from app.models.channel import Channel
from app.models.conversation import (
    Conversation,
    ConversationSession,
    DialogMode,
    SessionStatus,
)
from app.models.message import (
    Message,
    MessageAuthorType,
    MessageDeliveryState,
)
from app.models.outbox import (
    IntegrationEvent,
    IntegrationEventStatus,
    OutboxEvent,
    OutboxStatus,
)
from app.models.ticket import Ticket, TicketStatus
from app.models.user import CorporateAccount, User, UserIdentity

__all__ = [
    "AiHandoff",
    "AiProcessingRun",
    "AiRunStatus",
    "AuditActorType",
    "AuditLog",
    "Base",
    "Channel",
    "Conversation",
    "ConversationSession",
    "CorporateAccount",
    "DialogMode",
    "HandoffReason",
    "IntegrationEvent",
    "IntegrationEventStatus",
    "Message",
    "MessageAuthorType",
    "MessageDeliveryState",
    "OutboxEvent",
    "OutboxStatus",
    "SessionStatus",
    "Ticket",
    "TicketStatus",
    "User",
    "UserIdentity",
]
