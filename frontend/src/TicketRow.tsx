import { memo } from "react";
import { ago, shortId, statusName, type Ticket } from "./workspace-model";

type Props = {
  ticket: Ticket;
  selected: boolean;
  groupLabel?: string;
  onSelect: (ticketId: string) => void;
};

// Memoized queue row (decomposition round 2026-11-17): with ~200 rows the
// queue used to re-render on every App state tick; now only the changed
// row does.
function TicketRowImpl({ ticket, selected, groupLabel, onSelect }: Props) {
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
        {ticket.tags.length
          ? ticket.tags.join(" · ")
          : `Пользователь ${shortId(ticket.user_id)}`}
      </div>
      <div className="ticket-meta">
        <span className={`status-dot ${ticket.status.toLowerCase()}`} />
        <span className={`status-text ${ticket.status.toLowerCase()}`}>
          {groupLabel ?? statusName[ticket.status]}
        </span>
      </div>
    </button>
  );
}

export const TicketRow = memo(TicketRowImpl);
