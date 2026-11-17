import { memo } from "react";
import { initials, type Message } from "./workspace-model";

export type TimelineEntry =
  | { kind: "message"; createdAt: string; item: Message }
  | { kind: "note"; createdAt: string; item: Note };

type Note = {
  note_id: string;
  conversation_id: string;
  author_id: string;
  body: string;
  created_at: string;
};

type Props = {
  entries: TimelineEntry[];
  userShortId: string;
  operatorName: string;
};

// Memoized conversation history (decomposition round 2026-11-17): the
// timeline used to re-render wholesale on every poll/sync tick.
function TimelineImpl({ entries, userShortId, operatorName }: Props) {
  return (
    <div className="message-list">
      {entries.map((entry) => {
        if (entry.kind === "note")
          return (
            <article className="note-card" key={entry.item.note_id}>
              <div className="note-icon">✎</div>
              <div>
                <div className="message-heading">
                  <strong>Внутренняя заметка</strong>
                  <time>
                    {new Intl.DateTimeFormat("ru-RU", {
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    }).format(new Date(entry.item.created_at))}
                  </time>
                </div>
                <p>{entry.item.body}</p>
              </div>
            </article>
          );
        const m = entry.item;
        return (
          <article
            key={m.message_id}
            className={
              m.author_type.toUpperCase() === "OPERATOR"
                ? "message from-operator"
                : "message"
            }
          >
            <div
              className={
                m.author_type.toUpperCase() === "AI"
                  ? "message-avatar ai"
                  : "message-avatar user"
              }
            >
              {m.author_type.toUpperCase() === "AI" ? "✦" : initials(userShortId)}
            </div>
            <div className="message-content">
              <div className="message-heading">
                <strong>
                  {m.author_type.toUpperCase() === "USER"
                    ? "Пользователь " + userShortId
                    : m.author_type.toUpperCase() === "AI"
                      ? "AI-помощник"
                      : operatorName}
                </strong>
                <time>
                  {new Intl.DateTimeFormat("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(m.created_at))}
                </time>
              </div>
              <div className="message-bubble">{m.text}</div>
            </div>
          </article>
        );
      })}
      {!entries.length && <div className="empty-history">Сообщений пока нет</div>}
    </div>
  );
}

export const Timeline = memo(TimelineImpl);
