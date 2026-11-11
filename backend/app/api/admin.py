"""Administrative read models and role management (stage 9, D-047)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from app.auth.operators import require_role
from app.errors import ApiError
from app.models import (
    AuditActorType,
    AuditLog,
    Operator,
    OperatorRole,
    Tag,
    Ticket,
    TicketCategory,
)

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


def _operator_view(operator: Operator) -> dict[str, str | bool | int | None]:
    return {
        "operator_id": str(operator.id),
        "email": operator.email,
        "display_name": operator.display_name,
        "role": operator.role.value,
        "is_active": operator.is_active,
        "max_active_tickets": operator.max_active_tickets,
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
) -> dict[str, list[dict[str, str | bool | int | None]]]:
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        operators = (
            await session.scalars(select(Operator).order_by(Operator.email))
        ).all()
    return {"operators": [_operator_view(operator) for operator in operators]}


@router.get("/categories")
async def list_categories(
    request: Request,
    _actor: Annotated[
        Operator, Depends(require_role(OperatorRole.SUPERVISOR, OperatorRole.ADMIN))
    ],
) -> dict[str, list[dict[str, str | bool | int | None]]]:
    db = request.app.state.deps.db
    async with db.session_factory() as session:
        rows = (
            await session.scalars(
                select(Operator).order_by(Operator.created_at)
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
) -> dict[str, str | bool | int | None]:
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
) -> dict[str, str | bool | int | None]:
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
) -> dict[str, str | bool | int | None]:
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
