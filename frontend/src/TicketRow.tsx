import { memo } from "react";
import { ago, shortFio, shortId, statusName, type Ticket } from "./workspace-model";

type Props = {
  ticket: Ticket;
  selected: boolean;
  onSelect: (ticketId: string) => void;
};

// Memoized queue row (decomposition round 2026-11-17): with ~200 rows the
// queue used to re-render on every App state tick; now only the changed
// row does.
function TicketRowImpl({ ticket, selected, onSelect }: Props) {
  // Owner (2026-11-18): one dot + one status label per row. The earlier
  // "double В работе" was a leftover duplicated meta block, not the tab.
  const statusLabel =
    !ticket.assignee_id && ticket.status !== "AI_PROCESSING"
      ? "Не назначен"
      : statusName[ticket.status];
  const person =
    ticket.tags.length
      ? ticket.tags.join(" · ")
      : ticket.user_name
        ? shortFio(ticket.user_name)
        : `Пользователь ${shortId(ticket.user_id)}`;
  return (
    <button
      key={ticket.ticket_id}
      className={`ticket-row ${selected ? "active" : ""} ${!ticket.assignee_id ? "unassigned" : ""}`}
      onClick={() => onSelect(ticket.ticket_id)}
    >
      <div className="ticket-topline">
        <span className="ticket-number">#{shortId(ticket.ticket_id)}</span>
        <span className="ticket-time">{ago(ticket.updated_at)}</span>
      </div>
      <div className="ticket-preview">
        <span className="ticket-preview-name">{person}</span>
      </div>
      <div className="ticket-meta">
        <span
          className={`status-dot ${ticket.status.toLowerCase()}`}
          title={statusName[ticket.status]}
        />
        {statusLabel && (
          <span className={`status-text ${ticket.status.toLowerCase()}`}>
            {statusLabel}
          </span>
        )}
        {!!ticket.unread_from_user && (
          <span
            className="unread-badge"
            title="Новых сообщений от пользователя"
          >
            {ticket.unread_from_user}
          </span>
        )}
      </div>
    </button>
  );
}

export const TicketRow = memo(TicketRowImpl);
