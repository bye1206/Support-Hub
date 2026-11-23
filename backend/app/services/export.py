"""Owner (2026-11-23, plan item 6): .xlsx export of the ticket list.

The history page search results download as an Excel workbook — the
columns the owner asked for: ID, Создано, Обновлено, Закрыто (plus
status/user/operator for context). The closed time comes from the
ticket's STATUS history: the latest transition to RESOLVED/CLOSED.
"""

import io
import uuid
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Operator, TicketStatus, TicketStatusHistory, User
from app.repositories.tickets import TicketRepository

_STATUS_LABELS: dict[str, str] = {
    TicketStatus.NEW.value: "Новый",
    TicketStatus.AI_PROCESSING.value: "Обработка ИИ",
    TicketStatus.OPEN.value: "Открыт",
    TicketStatus.PENDING_USER.value: "Ожидает пользователя",
    TicketStatus.RESOLVED.value: "Решён",
    TicketStatus.CLOSED.value: "Таймаут",
}

_COLUMNS = ("ID", "Статус", "Пользователь", "Оператор", "Создано", "Обновлено", "Закрыто")


def _fmt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else ""


async def build_tickets_xlsx(
    session: AsyncSession, *, limit: int = 5000, offset: int = 0, **filters: object
) -> tuple[bytes, str]:
    """Fetch the filtered tickets and render the workbook.

    Returns (xlsx_bytes, ascii_filename) for the Content-Disposition header.
    """
    tickets = await TicketRepository().list_filtered(
        session, limit=limit, offset=offset, **filters  # type: ignore[arg-type]
    )
    closed_at: dict[uuid.UUID, datetime] = {}
    user_names: dict[uuid.UUID, str] = {}
    operator_names: dict[uuid.UUID, str] = {}
    if tickets:
        history_rows = await session.execute(
            select(
                TicketStatusHistory.ticket_id, func.max(TicketStatusHistory.changed_at)
            )
            .where(
                TicketStatusHistory.ticket_id.in_([t.id for t in tickets]),
                TicketStatusHistory.to_status.in_(
                    [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]
                ),
            )
            .group_by(TicketStatusHistory.ticket_id)
        )
        closed_at = dict(history_rows.all())
        user_ids = {t.user_id for t in tickets}
        for user in await session.scalars(select(User).where(User.id.in_(user_ids))):
            user_names[user.id] = user.display_name or str(user.id)[:8]
        operator_ids = {t.assignee_id for t in tickets if t.assignee_id}
        if operator_ids:
            for operator in await session.scalars(
                select(Operator).where(Operator.id.in_(operator_ids))
            ):
                operator_names[operator.id] = (
                    operator.display_name or operator.email.split("@")[0]
                )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Обращения"
    sheet.append(_COLUMNS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for ticket in tickets:
        sheet.append(
            (
                str(ticket.id),
                _STATUS_LABELS.get(ticket.status.value, ticket.status.value),
                user_names.get(ticket.user_id, ""),
                operator_names.get(ticket.assignee_id, "") if ticket.assignee_id else "",
                _fmt(ticket.created_at),
                _fmt(ticket.updated_at),
                _fmt(closed_at.get(ticket.id)),
            )
        )
    widths = (38, 22, 28, 28, 18, 18, 18)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    return buffer.getvalue(), f"tickets_export_{stamp}.xlsx"
