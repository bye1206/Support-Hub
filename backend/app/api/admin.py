"""Administrative read models and role management (stage 9, D-047)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from app.api.operator import _user_login_map
from app.auth.operators import require_role
from app.errors import ApiError
from app.models import (
    AuditActorType,
    AuditLog,
    Operator,
    OperatorPresenceLog,
    OperatorRole,
    Tag,
    Ticket,
    TicketCategory,
    TicketHistoryKind,
    TicketRating,
    TicketStatus,
    TicketStatusHistory,
)
from app.repositories.ratings import TicketRatingRepository

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class RoleUpdate(BaseModel):
    role: OperatorRole


class OperatorDeactivation(BaseModel):
    reassign_to: uuid.UUID | None = None


class OperatorLimit(BaseModel):
    max_active_tickets: int = Field(ge=1, le=100)


class CategoryWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None


class TagWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def _operator_view(operator: Operator, avg_rating: float | None = None) -> dict[str, object]:
    return {
        "operator_id": str(operator.id),
        "email": operator.email,
        "display_name": operator.display_name,
        "role": operator.role.value,
        "is_active": operator.is_active,
        "presence_status": operator.presence_status.value,
        "max_active_tickets": operator.max_active_tickets,
        # Owner (2026-11-20): the golden-crown rating in the Сотрудники tab.
        "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
        "created_at": operator.created_at.isoformat(),
    }


@router.get("/overview")
async def overview(
    request: Request,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, int]:
    """Return small operational counts without exposing message contents."""
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
        active_operators = await session.scalar(
            select(func.count()).select_from(Operator).where(Operator.is_active.is_(True))
        )
    return {"tickets": ticket_count or 0, "active_operators": active_operators or 0}


@router.get("/operators")
async def list_operators(
    request: Request,
    _actor: Annotated[Operator, Depends(require_role(OperatorRole.ADMIN))],
) -> dict[str, list[dict[str, object]]]:
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        operators = (
            await session.scalars(select(Operator).order_by(Operator.email))
        ).all()
        averages = await TicketRatingRepository().avg_by_operators(
            session, {operator.id for operator in operators}
        )
    return {
        "operators": [
            _operator_view(operator, averages.get(operator.id))
            for operator in operators
        ]
    }


@router.get("/categories")
async def list_categories(
    request: Request,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, list[dict[str, str | bool | None]]]:
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        rows = (
            await session.scalars(
                select(TicketCategory).order_by(TicketCategory.name, TicketCategory.id)
            )
        ).all()
    return {
        "categories": [
            {
                "category_id": str(row.id),
                "name": row.name,
                "parent_id": str(row.parent_id) if row.parent_id else None,
                "is_active": row.is_active,
            }
            for row in rows
        ]
    }


@router.post("/categories", status_code=201)
async def create_category(
    payload: CategoryWrite,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, str | bool | None]:
    name = payload.name.strip()
    if not name:
        raise ApiError("INVALID_CATEGORY", "Category name cannot be blank", status_code=422)
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        if payload.parent_id is not None:
            parent = await session.get(TicketCategory, payload.parent_id)
            if parent is None or not parent.is_active:
                raise ApiError("INVALID_PARENT", "Parent category is unavailable", status_code=422)
            if parent.parent_id is not None:
                # Owner rule: strictly two levels — category -> theme.
                raise ApiError(
                    "CATEGORY_DEPTH",
                    "Only two levels are allowed: a category and its themes",
                    status_code=409,
                )
        duplicate = await session.scalar(
            select(TicketCategory.id).where(
                TicketCategory.parent_id == payload.parent_id,
                func.lower(TicketCategory.name) == name.lower(),
            )
        )
        if duplicate:
            raise ApiError(
                "CATEGORY_EXISTS",
                "A category with this name already exists at this level",
                status_code=409,
            )
        category = TicketCategory(name=name, parent_id=payload.parent_id)
        session.add(category)
        await session.flush()
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="category.created", entity_type="ticket_category",
            entity_id=category.id, details={"name": name},
        ))
        await session.flush()
        result = {"category_id": str(category.id), "name": category.name,
                  "parent_id": str(category.parent_id) if category.parent_id else None,
                  "is_active": category.is_active}
    return result


@router.put("/categories/{category_id}")
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryWrite,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, str | bool | None]:
    name = payload.name.strip()
    if not name:
        raise ApiError("INVALID_CATEGORY", "Category name cannot be blank", status_code=422)
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        category = await session.scalar(
            select(TicketCategory).where(TicketCategory.id == category_id).with_for_update()
        )
        if category is None:
            raise ApiError("CATEGORY_NOT_FOUND", "Category was not found", status_code=404)
        if payload.parent_id == category.id:
            raise ApiError("CATEGORY_CYCLE", "A category cannot be its own parent", status_code=409)
        if payload.parent_id is not None:
            parent = await session.get(TicketCategory, payload.parent_id)
            if parent is None or not parent.is_active:
                raise ApiError("INVALID_PARENT", "Parent category is unavailable", status_code=422)
            if parent.parent_id is not None:
                # Owner rule: strictly two levels — category -> theme.
                raise ApiError(
                    "CATEGORY_DEPTH",
                    "Only two levels are allowed: a category and its themes",
                    status_code=409,
                )
            has_children = await session.scalar(
                select(func.count()).select_from(TicketCategory).where(
                    TicketCategory.parent_id == category.id
                )
            )
            if has_children:
                raise ApiError(
                    "CATEGORY_HAS_CHILDREN",
                    "A category with themes cannot become a theme itself",
                    status_code=409,
                )
            all_categories = (await session.scalars(select(TicketCategory))).all()
            parents = {item.id: item.parent_id for item in all_categories}
            cursor = parent.id
            while cursor is not None:
                if cursor == category.id:
                    raise ApiError(
                        "CATEGORY_CYCLE",
                        "Moving this category would create a cycle",
                        status_code=409,
                    )
                cursor = parents.get(cursor)
        duplicate = await session.scalar(
            select(TicketCategory.id).where(
                TicketCategory.id != category.id,
                TicketCategory.parent_id == payload.parent_id,
                func.lower(TicketCategory.name) == name.lower(),
            )
        )
        if duplicate:
            raise ApiError(
                "CATEGORY_EXISTS",
                "A category with this name already exists at this level",
                status_code=409,
            )
        previous = {
            "name": category.name,
            "parent_id": str(category.parent_id) if category.parent_id else None,
        }
        category.name, category.parent_id = name, payload.parent_id
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="category.updated", entity_type="ticket_category",
            entity_id=category.id, details={"from": previous, "name": name},
        ))
        await session.flush()
        result = {"category_id": str(category.id), "name": category.name,
                  "parent_id": str(category.parent_id) if category.parent_id else None,
                  "is_active": category.is_active}
    return result


@router.post("/categories/{category_id}/deactivate")
async def deactivate_category(
    category_id: uuid.UUID,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, bool]:
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        category = await session.scalar(
            select(TicketCategory).where(TicketCategory.id == category_id).with_for_update()
        )
        if category is None:
            raise ApiError("CATEGORY_NOT_FOUND", "Category was not found", status_code=404)
        children = await session.scalar(
            select(func.count()).select_from(TicketCategory).where(
                TicketCategory.parent_id == category.id, TicketCategory.is_active.is_(True)
            )
        )
        if children:
            raise ApiError(
                "CATEGORY_HAS_CHILDREN",
                "Deactivate child categories first",
                status_code=409,
            )
        category.is_active = False
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="category.deactivated", entity_type="ticket_category", entity_id=category.id,
        ))
    return {"is_active": False}


@router.post("/categories/{category_id}/activate")
async def activate_category(
    category_id: uuid.UUID,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, bool]:
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        category = await session.scalar(
            select(TicketCategory).where(TicketCategory.id == category_id).with_for_update()
        )
        if category is None:
            raise ApiError("CATEGORY_NOT_FOUND", "Category was not found", status_code=404)
        if category.parent_id is not None:
            parent = await session.get(TicketCategory, category.parent_id)
            if parent is None or not parent.is_active:
                raise ApiError(
                    "INVALID_PARENT",
                    "Activate the parent category first",
                    status_code=409,
                )
        category.is_active = True
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="category.activated", entity_type="ticket_category", entity_id=category.id,
        ))
    return {"is_active": True}


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: uuid.UUID,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, bool]:
    """Remove the category. A category already used by tickets is kept for
    the history (D-010: tickets must keep their category) and merely
    deactivated; unused ones are deleted outright, subcategories too."""
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        category = await session.scalar(
            select(TicketCategory).where(TicketCategory.id == category_id).with_for_update()
        )
        if category is None:
            raise ApiError("CATEGORY_NOT_FOUND", "Category was not found", status_code=404)
        children = (
            await session.scalars(
                select(TicketCategory).where(TicketCategory.parent_id == category.id)
            )
        ).all()
        subject_ids = [category.id, *(child.id for child in children)]
        used = await session.scalar(
            select(func.count()).select_from(Ticket).where(
                Ticket.category_id.in_(subject_ids)
            )
        )
        if used:
            for subject in [category, *children]:
                subject.is_active = False
            session.add(AuditLog(
                actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
                action="category.deactivated", entity_type="ticket_category",
                entity_id=category.id,
                details={"reason": "delete_requested_in_use", "tickets": used},
            ))
            return {"deleted": False, "deactivated": True}
        for child in children:
            await session.delete(child)
        await session.delete(category)
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="category.deleted", entity_type="ticket_category",
            entity_id=category.id,
        ))
    return {"deleted": True, "deactivated": False}


@router.get("/tags")
async def list_tags(
    request: Request,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, list[dict[str, str | bool]]]:
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        tags = (await session.scalars(select(Tag).order_by(func.lower(Tag.name)))).all()
    return {
        "tags": [
            {"tag_id": str(tag.id), "name": tag.name, "is_active": tag.is_active}
            for tag in tags
        ]
    }


@router.post("/tags", status_code=201)
async def create_tag(
    payload: TagWrite,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, str | bool]:
    name = payload.name.strip()
    if not name:
        raise ApiError("INVALID_TAG", "Tag name cannot be blank", status_code=422)
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        existing = await session.scalar(
            select(Tag).where(func.lower(Tag.name) == name.lower()).with_for_update()
        )
        if existing:
            if existing.is_active:
                raise ApiError("TAG_EXISTS", "A tag with this name already exists", status_code=409)
            existing.is_active = True
            tag = existing
            action = "tag.reactivated"
        else:
            tag = Tag(name=name)
            session.add(tag)
            action = "tag.created"
        await session.flush()
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action=action, entity_type="tag", entity_id=tag.id, details={"name": name},
        ))
        await session.flush()
        result = {"tag_id": str(tag.id), "name": tag.name, "is_active": tag.is_active}
    return result


@router.put("/tags/{tag_id}")
async def update_tag(
    tag_id: uuid.UUID,
    payload: TagWrite,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, str | bool]:
    name = payload.name.strip()
    if not name:
        raise ApiError("INVALID_TAG", "Tag name cannot be blank", status_code=422)
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        tag = await session.scalar(select(Tag).where(Tag.id == tag_id).with_for_update())
        if tag is None:
            raise ApiError("TAG_NOT_FOUND", "Tag was not found", status_code=404)
        duplicate = await session.scalar(
            select(Tag.id).where(Tag.id != tag.id, func.lower(Tag.name) == name.lower())
        )
        if duplicate:
            raise ApiError("TAG_EXISTS", "A tag with this name already exists", status_code=409)
        previous_name = tag.name
        tag.name = name
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="tag.renamed", entity_type="tag", entity_id=tag.id,
            details={"from": previous_name, "to": name},
        ))
        await session.flush()
        result = {"tag_id": str(tag.id), "name": tag.name, "is_active": tag.is_active}
    return result


@router.post("/tags/{tag_id}/deactivate")
async def deactivate_tag(
    tag_id: uuid.UUID,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, bool]:
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        tag = await session.scalar(select(Tag).where(Tag.id == tag_id).with_for_update())
        if tag is None:
            raise ApiError("TAG_NOT_FOUND", "Tag was not found", status_code=404)
        tag.is_active = False
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="tag.deactivated", entity_type="tag", entity_id=tag.id,
        ))
    return {"is_active": False}


@router.post("/tags/{tag_id}/activate")
async def activate_tag(
    tag_id: uuid.UUID,
    request: Request,
    actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, bool]:
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        tag = await session.scalar(select(Tag).where(Tag.id == tag_id).with_for_update())
        if tag is None:
            raise ApiError("TAG_NOT_FOUND", "Tag was not found", status_code=404)
        tag.is_active = True
        session.add(AuditLog(
            actor_type=AuditActorType.OPERATOR, actor_id=actor.id,
            action="tag.activated", entity_type="tag", entity_id=tag.id,
        ))
    return {"is_active": True}


@router.patch("/operators/{operator_id}/role")
async def update_operator_role(
    operator_id: uuid.UUID,
    payload: RoleUpdate,
    request: Request,
    actor: Annotated[Operator, Depends(require_role(OperatorRole.ADMIN))],
) -> dict[str, object]:
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        target = await session.scalar(
            select(Operator).where(Operator.id == operator_id).with_for_update()
        )
        if target is None:
            raise ApiError(
                "OPERATOR_NOT_FOUND", "Operator was not found", status_code=404
            )
        if target.id == actor.id and payload.role != OperatorRole.ADMIN:
            remaining_admins = await session.scalar(
                select(func.count())
                .select_from(Operator)
                .where(
                    Operator.is_active.is_(True),
                    Operator.role == OperatorRole.ADMIN,
                    Operator.id != actor.id,
                )
            )
            if not remaining_admins:
                raise ApiError(
                    "LAST_ADMIN",
                    "The last active administrator cannot demote itself",
                    status_code=409,
                )
        previous_role = target.role
        target.role = payload.role
        session.add(
            AuditLog(
                actor_type=AuditActorType.OPERATOR,
                actor_id=actor.id,
                action="operator.role_changed",
                entity_type="operator",
                entity_id=target.id,
                details={"from": previous_role.value, "to": payload.role.value},
            )
        )
        await session.flush()
        result = _operator_view(target)
    return result


@router.patch("/operators/{operator_id}/limit")
async def update_operator_limit(
    operator_id: uuid.UUID,
    payload: OperatorLimit,
    request: Request,
    actor: Annotated[Operator, Depends(require_role(OperatorRole.ADMIN))],
) -> dict[str, object]:
    """Set the per-operator auto-assignment capacity (D-031 refinement)."""
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        target = await session.scalar(
            select(Operator).where(Operator.id == operator_id).with_for_update()
        )
        if target is None:
            raise ApiError(
                "OPERATOR_NOT_FOUND", "Operator was not found", status_code=404
            )
        previous = target.max_active_tickets
        target.max_active_tickets = payload.max_active_tickets
        session.add(
            AuditLog(
                actor_type=AuditActorType.OPERATOR,
                actor_id=actor.id,
                action="operator.limit_changed",
                entity_type="operator",
                entity_id=target.id,
                details={"from": previous, "to": payload.max_active_tickets},
            )
        )
        await session.flush()
        result = _operator_view(target)
    return result


@router.post("/operators/{operator_id}/deactivate")
async def deactivate_operator(
    operator_id: uuid.UUID,
    payload: OperatorDeactivation,
    request: Request,
    actor: Annotated[Operator, Depends(require_role(OperatorRole.ADMIN))],
) -> dict[str, object]:
    """Deactivate only after active assignments have a valid destination."""
    db = request.app.state.deps.db
    async with db.session_factory() as session, session.begin():
        target = await session.scalar(
            select(Operator).where(Operator.id == operator_id).with_for_update()
        )
        if target is None:
            raise ApiError(
                "OPERATOR_NOT_FOUND", "Operator was not found", status_code=404
            )
        if not target.is_active:
            return _operator_view(target)
        if target.role == OperatorRole.ADMIN:
            admins = await session.scalar(
                select(func.count())
                .select_from(Operator)
                .where(
                    Operator.is_active.is_(True),
                    Operator.role == OperatorRole.ADMIN,
                )
            )
            if admins == 1:
                raise ApiError(
                    "LAST_ADMIN",
                    "The last active administrator cannot be deactivated",
                    status_code=409,
                )
        active_tickets = (
            await session.scalars(
                select(Ticket)
                .where(
                    Ticket.assignee_id == target.id,
                    Ticket.status.not_in(("RESOLVED", "CLOSED")),
                )
                .with_for_update()
            )
        ).all()
        replacement: Operator | None = None
        if active_tickets:
            if payload.reassign_to is None:
                raise ApiError(
                    "ACTIVE_ASSIGNMENTS",
                    "Choose an active operator to receive this operator's open tickets",
                    status_code=409,
                    details={"ticket_count": len(active_tickets)},
                )
            replacement = await session.scalar(
                select(Operator)
                .where(Operator.id == payload.reassign_to)
                .with_for_update()
            )
            if replacement is None or not replacement.is_active or replacement.id == target.id:
                raise ApiError(
                    "INVALID_REASSIGNEE",
                    "The selected replacement must be a different active operator",
                    status_code=422,
                )
            for ticket in active_tickets:
                ticket.assignee_id = replacement.id
                ticket.updated_at = datetime.now(UTC)
                session.add(
                    AuditLog(
                        actor_type=AuditActorType.OPERATOR,
                        actor_id=actor.id,
                        action="ticket.reassigned",
                        entity_type="ticket",
                        entity_id=ticket.id,
                        details={
                            "from_operator_id": str(target.id),
                            "to_operator_id": str(replacement.id),
                            "reason": "operator.deactivated",
                        },
                    )
                )
        target.is_active = False
        session.add(
            AuditLog(
                actor_type=AuditActorType.OPERATOR,
                actor_id=actor.id,
                action="operator.deactivated",
                entity_type="operator",
                entity_id=target.id,
                details={"reassigned_tickets": len(active_tickets)},
            )
        )
        await session.flush()
        result = _operator_view(target)
    return result


@router.get("/audit")
async def list_audit(
    request: Request,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, list[dict[str, str | None]]]:
    """List audit metadata only; arbitrary details can contain sensitive data."""
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        entries = (
            await session.scalars(
                select(AuditLog).order_by(desc(AuditLog.created_at)).limit(100)
            )
        ).all()
    return {
        "entries": [
            {
                "audit_id": str(entry.id),
                "actor_type": entry.actor_type.value,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": str(entry.entity_id) if entry.entity_id else None,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in entries
        ]
    }


@router.get("/stats/operators")
async def operator_stats(
    request: Request,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
    date: str = "",
) -> dict[str, list[dict[str, object]]]:
    """Per-operator workload and satisfaction (owner request, 2026-11-20).

    dialogs_total = dialogs RESOLVED/CLOSED while assigned to the operator;
    dialogs_day = the same limited to one day via ?date=YYYY-MM-DD
    (updated_at day); the ratings and free-text reviews come from
    ticket_ratings; sla_breached counts the breach events on the dialogs
    assigned to the operator.
    """
    from datetime import date as date_type

    from sqlalchemy import Date, cast

    db = request.app.state.deps.db
    async with db.session_factory() as session:
        operators = (
            await session.scalars(select(Operator).order_by(Operator.display_name))
        ).all()
        terminal = [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]
        day: date_type | None = None
        if date:
            try:
                day = date_type.fromisoformat(date)
            except ValueError:
                raise ApiError(
                    code="VALIDATION_ERROR", message="date must be YYYY-MM-DD"
                ) from None
        rows: list[dict[str, object]] = []
        for operator in operators:
            base = select(func.count()).select_from(Ticket).where(
                Ticket.assignee_id == operator.id,
                Ticket.status.in_(terminal),
            )
            dialogs_total = await session.scalar(base) or 0
            dialogs_day = 0
            if day is not None:
                dialogs_day = (
                    await session.scalar(
                        base.where(cast(Ticket.updated_at, Date) == day)
                    )
                ) or 0
            rating_rows = (
                await session.scalars(
                    select(TicketRating)
                    .where(TicketRating.operator_id == operator.id)
                    .order_by(desc(TicketRating.created_at))
                )
            ).all()
            avg = (
                sum(r.score for r in rating_rows) / len(rating_rows)
                if rating_rows
                else None
            )
            sla_breached = await session.scalar(
                select(func.count())
                .select_from(TicketStatusHistory)
                .join(Ticket, Ticket.id == TicketStatusHistory.ticket_id)
                .where(
                    Ticket.assignee_id == operator.id,
                    TicketStatusHistory.kind == TicketHistoryKind.SLA_BREACHED.value,
                )
            ) or 0
            rows.append(
                {
                    "operator_id": str(operator.id),
                    "name": operator.display_name or operator.email,
                    "email": operator.email,
                    "dialogs_total": dialogs_total,
                    "dialogs_day": dialogs_day,
                    "avg_rating": round(avg, 2) if avg is not None else None,
                    "ratings_count": len(rating_rows),
                    "sla_breached": sla_breached,
                    "ratings": [
                        {
                            "score": r.score,
                            "review": r.review_text,
                            "created_at": r.created_at.isoformat(),
                        }
                        for r in rating_rows
                    ],
                }
            )
    return {"operators": rows}


@router.get("/stats/operator/{operator_id}/presence")
async def operator_stats_presence(
    request: Request,
    operator_id: uuid.UUID,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
    period: str = "all",
    date: str = "",
    month: str = "",
) -> dict[str, float]:
    """How long the operator was ACTIVE / LUNCH / BREAK / OFFLINE (owner
    request, 2026-11-20): closed intervals from the presence log plus the
    still-running interval from operators.presence_since. Seconds; the
    period parameter clips the intervals to a day / month (owner,
    2026-11-20: "за смену или за всё время?")."""
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        operator = await session.get(Operator, operator_id)
        if operator is None:
            raise ApiError(
                code="NOT_FOUND", message="Оператор не найден", status_code=404
            )
        rng = _period_range(period, date, month)
        now = datetime.now(UTC)
        rows = await session.execute(
            select(
                OperatorPresenceLog.status,
                OperatorPresenceLog.started_at,
                OperatorPresenceLog.ended_at,
            ).where(OperatorPresenceLog.operator_id == operator_id)
        )
        durations = {"ACTIVE": 0.0, "LUNCH": 0.0, "BREAK": 0.0, "OFFLINE": 0.0}

        def clip(started: datetime, ended: datetime) -> tuple[datetime, datetime]:
            low, high = rng if rng is not None else (started, ended)
            return max(started, low), min(ended, high)

        for status, started, ended in rows:
            lo, hi = clip(started, ended)
            durations[status] = durations.get(status, 0.0) + max(
                0.0, (hi - lo).total_seconds()
            )
        if operator.presence_since is not None:
            lo, hi = clip(operator.presence_since, now)
            durations[str(operator.presence_status)] = durations.get(
                str(operator.presence_status), 0.0
            ) + max(0.0, (hi - lo).total_seconds())
    return {key: round(value) for key, value in durations.items()}


def _period_range(period: str, date: str, month: str) -> tuple[datetime, datetime] | None:
    """[start, end) for the card periods: day / month / all time."""
    from datetime import date as date_type
    from datetime import timedelta

    try:
        if period == "day" and date:
            day = date_type.fromisoformat(date)
            start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            return start, start + timedelta(days=1)
        if period == "month" and month:
            year, mon = (int(part) for part in month.split("-"))
            start = datetime(year, mon, 1, tzinfo=UTC)
            nxt_year, nxt_mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
            return start, datetime(nxt_year, nxt_mon, 1, tzinfo=UTC)
    except ValueError:
        raise ApiError(
            code="VALIDATION_ERROR", message="Bad period parameters"
        ) from None
    return None


@router.get("/stats/operator/{operator_id}")
async def operator_stats_detail(
    request: Request,
    operator_id: uuid.UUID,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
    period: str = "all",
    date: str = "",
    month: str = "",
) -> dict[str, object]:
    """One operator's counters for a card period (owner request, 2026-11-20):
    chats closed, average rating + the rating list, SLA breach events."""
    from sqlalchemy import Date, cast

    db = request.app.state.deps.db
    async with db.session_factory() as session:
        operator = await session.get(Operator, operator_id)
        if operator is None:
            raise ApiError(
                code="NOT_FOUND", message="Оператор не найден", status_code=404
            )
        rng = _period_range(period, date, month)
        terminal = [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]
        chat_base = select(func.count()).select_from(Ticket).where(
            Ticket.assignee_id == operator.id,
            Ticket.status.in_(terminal),
        )
        if rng is not None:
            chat_base = chat_base.where(cast(Ticket.updated_at, Date) >= rng[0].date())
            chat_base = chat_base.where(cast(Ticket.updated_at, Date) < rng[1].date())
        chats = await session.scalar(chat_base) or 0
        rating_query = select(TicketRating).where(
            TicketRating.operator_id == operator.id
        )
        if rng is not None:
            rating_query = rating_query.where(
                TicketRating.created_at >= rng[0],
                TicketRating.created_at < rng[1],
            )
        rating_rows = (
            await session.scalars(rating_query.order_by(desc(TicketRating.created_at)))
        ).all()
        avg = (
            sum(r.score for r in rating_rows) / len(rating_rows)
            if rating_rows
            else None
        )
        sla_query = (
            select(TicketStatusHistory)
            .join(Ticket, Ticket.id == TicketStatusHistory.ticket_id)
            .where(
                Ticket.assignee_id == operator.id,
                TicketStatusHistory.kind == TicketHistoryKind.SLA_BREACHED.value,
            )
        )
        if rng is not None:
            sla_query = sla_query.where(
                TicketStatusHistory.changed_at >= rng[0],
                TicketStatusHistory.changed_at < rng[1],
            )
        sla_rows = (
            await session.scalars(sla_query.order_by(desc(TicketStatusHistory.changed_at)))
        ).all()
    return {
        "chats": chats,
        "avg_rating": round(avg, 2) if avg is not None else None,
        "ratings_count": len(rating_rows),
        "ratings": [
            {
                "score": r.score,
                "review": r.review_text,
                "created_at": r.created_at.isoformat(),
            }
            for r in rating_rows
        ],
        "sla_breached": len(sla_rows),
        "breach_events": [r.changed_at.isoformat() for r in sla_rows],
    }


@router.get("/stats/operator/{operator_id}/dialogs")
async def operator_stats_dialogs(
    request: Request,
    operator_id: uuid.UUID,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
    limit: int = 10,
    date: str = "",
    min_score: int | None = None,
    max_score: int | None = None,
) -> dict[str, list[dict[str, object]]]:
    """The operator's closed dialogs for the mini history table (owner,
    2026-11-20): filters by day and by score range, newest first."""
    from datetime import date as date_type

    from sqlalchemy import Date, cast

    db = request.app.state.deps.db
    async with db.session_factory() as session:
        day: date_type | None = None
        if date:
            try:
                day = date_type.fromisoformat(date)
            except ValueError:
                raise ApiError(
                    code="VALIDATION_ERROR", message="date must be YYYY-MM-DD"
                ) from None
        query = (
            select(Ticket)
            .outerjoin(TicketRating, TicketRating.ticket_id == Ticket.id)
            .where(
                Ticket.assignee_id == operator_id,
                Ticket.status.in_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]),
            )
        )
        if day is not None:
            query = query.where(cast(Ticket.updated_at, Date) == day)
        if min_score is not None:
            query = query.where(TicketRating.score >= min_score)
        if max_score is not None:
            query = query.where(TicketRating.score <= max_score)
        # Owner (2026-11-20): the table shows the user's login.
        user_logins = await _user_login_map(
            session,
            list(
                await session.scalars(
                    select(Ticket.user_id)
                    .where(Ticket.assignee_id == operator_id)
                    .distinct()
                )
            ),
        )
        rows = (
            await session.execute(
                query.add_columns(
                    TicketRating.score, TicketRating.review_text
                ).order_by(desc(Ticket.updated_at)).limit(min(max(limit, 1), 100))
            )
        ).all()
    return {
        "dialogs": [
            {
                "ticket_id": str(ticket.id),
                "status": str(getattr(ticket.status, "value", ticket.status)),
                "user_login": user_logins.get(ticket.user_id, ""),
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
                "score": score,
                "review": review,
            }
            for ticket, score, review in rows
        ]
    }


@router.get("/stats/ai")
async def ai_stats(
    request: Request,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, object]:
    """AI bot satisfaction and handoff counts (owner request, 2026-11-20)."""
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        ai_ratings = (
            await session.scalars(
                select(TicketRating)
                .where(TicketRating.target == "AI")
                .order_by(desc(TicketRating.created_at))
            )
        ).all()
        avg = (
            sum(r.score for r in ai_ratings) / len(ai_ratings)
            if ai_ratings
            else None
        )
        terminal = [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]
        closed_total = await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.status.in_(terminal))
        ) or 0
        # Dialogs the AI handed to operators: distinct conversations with a
        # handoff.accepted event.
        handed_off = await session.scalar(
            select(func.count(func.distinct(AuditLog.entity_id)))
            .select_from(AuditLog)
            .where(
                AuditLog.action == "handoff.accepted",
                AuditLog.entity_type == "conversation",
            )
        ) or 0
    return {
        "avg_rating": round(avg, 2) if avg is not None else None,
        "ratings_count": len(ai_ratings),
        "ratings": [
            {
                "score": r.score,
                "review": r.review_text,
                "created_at": r.created_at.isoformat(),
            }
            for r in ai_ratings
        ],
        "chats_closed": closed_total,
        "chats_no_handoff": max(0, closed_total - handed_off),
        "handoffs": handed_off,
    }
