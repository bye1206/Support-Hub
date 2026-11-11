"""SQLAlchemy models. Import registers all tables on Base.metadata."""

from app.models.ai_handoff import AiHandoff, HandoffReason
from app.models.ai_run import AiProcessingRun, AiRunStatus
from app.models.audit import AuditActorType, AuditLog
from app.models.base import Base
from app.models.category import TicketCategory
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
from app.models.note import InternalNote
from app.models.operator import Operator, OperatorRole, PresenceStatus
from app.models.outbox import (
    IntegrationEvent,
    IntegrationEventStatus,
    OutboxEvent,
    OutboxStatus,
)
from app.models.tag import Tag, TicketTag
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
    "InternalNote",
    "Message",
    "MessageAuthorType",
    "MessageDeliveryState",
    "Operator",
    "OperatorRole",
    "PresenceStatus",
    "OutboxEvent",
    "OutboxStatus",
    "SessionStatus",
    "Tag",
    "Ticket",
    "TicketCategory",
    "TicketStatus",
    "TicketTag",
    "User",
    "UserIdentity",
]
