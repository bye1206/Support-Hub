import { memo, useEffect, useState } from "react";
import {
  initials,
  type Message,
  type MessageAttachmentInfo,
} from "./workspace-model";

export type TimelineEntry =
  | { kind: "message"; createdAt: string; item: Message }
  | { kind: "note"; createdAt: string; item: Note };

type Note = {
  note_id: string;
  conversation_id: string;
  author_id: string;
  author_name?: string | null;
  body: string;
  created_at: string;
};

type Props = {
  entries: TimelineEntry[];
  userLabel: string;
  operatorName: string;
  // Owner (2026-11-19): downloads need the auth header, so the parent does
  // the fetch; the timeline only renders the cards.
  onDownloadAttachment: (attachment: MessageAttachmentInfo) => void;
  fetchAttachment: (attachment: MessageAttachmentInfo) => Promise<Blob>;
};

const formatSize = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
    : `${(bytes / 1024).toFixed(0)} КБ`;

// Owner (2026-11-19): screenshots and photos open right in the dialog.
function AttachmentImage({
  attachment,
  fetchAttachment,
  onOpen,
}: {
  attachment: MessageAttachmentInfo;
  fetchAttachment: Props["fetchAttachment"];
  onOpen: (attachment: MessageAttachmentInfo) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    fetchAttachment(attachment)
      .then((blob) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.id, fetchAttachment]);
  if (failed) return null;
  if (!url)
    return (
      <div className="message-image message-image-loading">Загрузка…</div>
    );
  return (
    <button
      type="button"
      className="message-image-link"
      title="Открыть изображение"
      onClick={() => onOpen(attachment)}
    >
      <img className="message-image" src={url} alt={attachment.file_name} />
    </button>
  );
}

// Owner (2026-11-19): the full-screen photo viewer — zoom in/out, reset,
// download. The backdrop click closes; the photo fetches its own blob so
// the viewer survives the inline preview unmounting.
function ImageViewer({
  attachment,
  fetchAttachment,
  onClose,
}: {
  attachment: MessageAttachmentInfo;
  fetchAttachment: Props["fetchAttachment"];
  onClose: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    fetchAttachment(attachment)
      .then((blob) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.id, fetchAttachment]);
  return (
    <div className="image-viewer" onClick={onClose} role="dialog">
      <div
        className="image-viewer-toolbar"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          aria-label="Приблизить"
          title="Приблизить"
          onClick={() => setZoom((z) => Math.min(5, z + 0.25))}
        >
          +
        </button>
        <button
          type="button"
          aria-label="Отдалить"
          title="Отдалить"
          onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}
        >
          −
        </button>
        <button
          type="button"
          title="Сбросить масштаб"
          onClick={() => setZoom(1)}
        >
          1:1
        </button>
        {url && (
          <a href={url} download={attachment.file_name} title="Скачать">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 3v12" />
              <path d="m7 10 5 5 5-5" />
              <path d="M5 21h14" />
            </svg>
          </a>
        )}
        <button type="button" aria-label="Закрыть" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="image-viewer-stage">
        {url ? (
          <img
            src={url}
            alt={attachment.file_name}
            style={{ transform: `scale(${zoom})` }}
          />
        ) : (
          <div className="image-viewer-loading">Загрузка…</div>
        )}
      </div>
    </div>
  );
}

// Owner (2026-11-19): shared renderer for read-only message lists (history
// modal, history page, team modal) — mirrors the workspace rules: operator
// right, user left, AI/system centered, real names + attachments shown.
export function HistoryMessages({
  messages,
  onDownload,
}: {
  messages: Message[];
  onDownload: (attachment: MessageAttachmentInfo) => void;
}) {
  return (
    <>
      {messages.map((message) => {
        const author = message.author_type.toUpperCase();
        const heading =
          author === "USER"
            ? message.author_name || "Пользователь"
            : author === "OPERATOR"
              ? message.author_name || "Оператор"
              : author === "AI"
                ? "AI-помощник"
                : "";
        return (
          <div
            key={message.message_id}
            className={[
              "message",
              author === "OPERATOR" ? "from-operator" : "",
              author === "SYSTEM" ? "system" : "",
              author === "AI" ? "history-ai" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <div className="message-content">
              <div className="message-heading">
                <strong>{heading}</strong>
                <time>
                  {new Intl.DateTimeFormat("ru-RU", {
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(message.created_at))}
                </time>
              </div>
              <div className="message-bubble">{message.text}</div>
              {message.attachments && message.attachments.length > 0 && (
                <div className="message-files">
                  {message.attachments.map((attachment) => (
                    <button
                      type="button"
                      key={attachment.id}
                      className="message-file"
                      onClick={() => onDownload(attachment)}
                      title="Скачать вложение"
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M12 3v12" />
                        <path d="m7 10 5 5 5-5" />
                        <path d="M5 21h14" />
                      </svg>
                      <span className="message-file-name">
                        {attachment.file_name}
                      </span>
                      <span className="message-file-size">
                        {formatSize(attachment.size_bytes)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </>
  );
}

// Memoized conversation history (decomposition round 2026-11-17): the
// timeline used to re-render wholesale on every poll/sync tick.
function TimelineImpl({
  entries,
  userLabel,
  operatorName,
  onDownloadAttachment,
  fetchAttachment,
}: Props) {
  // Owner (2026-11-19): the open full-screen photo, if any.
  const [viewer, setViewer] = useState<MessageAttachmentInfo | null>(null);
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
                {/* Owner (2026-11-18): the timeline must show which operator
                    wrote the note. */}
                <p className="note-author">
                  {entry.item.author_name || operatorName}
                </p>
              </div>
            </article>
          );
        const m = entry.item;
        const author = m.author_type.toUpperCase();
        return (
          <article
            key={m.message_id}
            className={
              author === "OPERATOR"
                ? "message from-operator"
                : // Owner (2026-11-18): system phrases are neither user nor
                  // operator — they get a centered system style.
                  author === "SYSTEM"
                  ? "message system"
                  : "message"
            }
          >
            {author !== "SYSTEM" && (
              <div
                className={
                  author === "AI" ? "message-avatar ai" : "message-avatar user"
                }
              >
                {author === "AI" ? "✦" : initials(userLabel)}
              </div>
            )}
            <div className="message-content">
              <div className="message-heading">
                <strong>
                  {author === "USER"
                    ? userLabel
                    : author === "AI"
                      ? "AI-помощник"
                      : author === "SYSTEM"
                        ? ""
                        : operatorName}
                </strong>
                <time>
                  {new Intl.DateTimeFormat("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(m.created_at))}
                </time>
              </div>
              <div className="message-bubble">
                {m.text}
                {m.attachments && m.attachments.length > 0 && (
                  <div className="message-files">
                    {m.attachments.map((attachment) =>
                      // Owner (2026-11-19): images open right in the dialog.
                      attachment.mime_type.toLowerCase().startsWith("image/") ? (
                        <AttachmentImage
                          key={attachment.id}
                          attachment={attachment}
                          fetchAttachment={fetchAttachment}
                          onOpen={setViewer}
                        />
                      ) : (
                        <button
                          type="button"
                          key={attachment.id}
                          className="message-file"
                          onClick={() => onDownloadAttachment(attachment)}
                          title="Скачать вложение"
                        >
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M12 3v12" />
                            <path d="m7 10 5 5 5-5" />
                            <path d="M5 21h14" />
                          </svg>
                          <span className="message-file-name">
                            {attachment.file_name}
                          </span>
                          <span className="message-file-size">
                            {formatSize(attachment.size_bytes)}
                          </span>
                        </button>
                      ),
                    )}
                  </div>
                )}
              </div>
            </div>
          </article>
        );
      })}
      {!entries.length && <div className="empty-history">Сообщений пока нет</div>}
      {viewer && (
        <ImageViewer
          attachment={viewer}
          fetchAttachment={fetchAttachment}
          onClose={() => setViewer(null)}
        />
      )}
    </div>
  );
}

export const Timeline = memo(TimelineImpl);
