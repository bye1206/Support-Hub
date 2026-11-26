import { memo, useEffect, useRef, useState, type FormEvent } from "react";

type Mode = "reply" | "note";

type KbArticle = {
  article_id: string;
  title: string;
  body: string;
  attachments?: {
    attachment_id: string;
    file_name: string;
    mime_type: string;
  }[];
};

type Props = {
  disabled: boolean;
  // Return true when the message actually went through — the draft is
  // cleared only then.
  onSend: (mode: Mode, text: string, files: File[]) => Promise<boolean>;
  // Owner (2026-11-19): files dropped anywhere on the dialog window land
  // here (the parent forwards them); the composer merges them into chips.
  droppedFiles?: File[];
  onDroppedFilesConsumed?: () => void;
  // Owner (2026-11-23, plan item 8): knowledge base articles for the
  // auto-reply insert and the typing hints.
  kbArticles?: KbArticle[];
  // Owner (2026-11-26): the parent downloads the inserted article's
  // attachments and queues them as outgoing files (the raw
  // `attachment:<id>` markers are stripped from the reply text).
  onKbArticleInsert?: (article: KbArticle) => void;
};

// Owns its own draft state (decomposition round 2026-11-17): typing used to
// re-render the whole App (queue of ~200 rows, all modals) per keystroke.
function ComposerImpl({
  disabled,
  onSend,
  droppedFiles = [],
  onDroppedFilesConsumed,
  kbArticles = [],
  onKbArticleInsert,
}: Props) {
  const [mode, setMode] = useState<Mode>("reply");
  const [text, setText] = useState("");
  // Owner (2026-11-19): several files at once — via the picker or drag&drop.
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [sending, setSending] = useState(false);
  // Owner (2026-11-23, plan item 8): typing hints from the knowledge base.
  // The toggle is personal and survives reloads (localStorage).
  const [hintsOff, setHintsOff] = useState(() => {
    try {
      return localStorage.getItem("sh-kb-hints-off") === "1";
    } catch {
      return false;
    }
  });
  const toggleHints = () => {
    setHintsOff((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("sh-kb-hints-off", next ? "1" : "0");
      } catch {
        // storage unavailable — the toggle still works for the session
      }
      return next;
    });
  };
  const needle = text.trim().toLowerCase();
  const suggestions =
    !hintsOff && mode === "reply" && !disabled && needle.length >= 2
      ? kbArticles
          .filter(
            (article) =>
              article.title.toLowerCase().includes(needle) ||
              article.body.toLowerCase().includes(needle),
          )
          .slice(0, 4)
      : [];
  // Owner (2026-11-18): Telegram-style input — starts pill-narrow, grows
  // upward while typing up to ~half the screen, then scrolls its contents.
  // The scrollbar appears ONLY once the cap is reached.
  const areaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (!droppedFiles.length) return;
    setFiles((prev) => [...prev, ...droppedFiles]);
    onDroppedFilesConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [droppedFiles]);
  useEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const maxHeight = Math.floor(window.innerHeight * 0.45);
    const needed = el.scrollHeight + 2;
    el.style.height = `${Math.min(needed, maxHeight)}px`;
    el.style.overflowY = needed > maxHeight ? "auto" : "hidden";
  }, [text, mode]);
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if ((!text.trim() && files.length === 0) || sending) return;
    setSending(true);
    const sent = await onSend(mode, text.trim(), files);
    setSending(false);
    if (sent) {
      setText("");
      setFiles([]);
    }
  };
  return (
    <section
      className={[
        "composer",
        mode === "note" ? "note-mode" : "",
        dragOver && !disabled && mode === "reply" ? "drag-over" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation(); // the panel-level dropzone already routed it
        setDragOver(false);
        if (disabled || mode !== "reply") return;
        // Owner (2026-11-19): files can be dragged right onto the composer.
        const dropped = Array.from(e.dataTransfer.files ?? []);
        if (dropped.length) setFiles((prev) => [...prev, ...dropped]);
      }}
    >
      <form onSubmit={submit}>
        {files.length > 0 && (
          <div className="composer-file-chips">
            {files.map((file, index) => (
              <div
                className="composer-file-chip"
                key={`${file.name}-${index}`}
              >
                <span className="composer-file-name" title={file.name}>
                  {file.name}
                </span>
                <span className="composer-file-size">
                  {(file.size / 1024).toFixed(0)} КБ
                </span>
                <button
                  type="button"
                  className="composer-file-remove"
                  aria-label="Убрать вложение"
                  onClick={() =>
                    setFiles((prev) => prev.filter((_, i) => i !== index))
                  }
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        {suggestions.length > 0 && (
          <div className="composer-kb" role="listbox" aria-label="Подсказки базы знаний">
            {suggestions.map((article) => (
              <button
                type="button"
                key={article.article_id}
                role="option"
                aria-selected={false}
                className="composer-kb-item"
                onClick={() => {
                  setText(
                    article.body.replace(/ ?attachment:[0-9a-fA-F-]{36}/g, ""),
                  );
                  onKbArticleInsert?.(article);
                  areaRef.current?.focus();
                }}
              >
                <strong>{article.title}</strong>
                <span>{article.body}</span>
              </button>
            ))}
          </div>
        )}
        <div className="composer-row">
          <div className="composer-modes" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "reply"}
              aria-label="Публичный ответ"
              title="Публичный ответ"
              className={
                mode === "reply" ? "composer-mode-btn active" : "composer-mode-btn"
              }
              onClick={() => setMode("reply")}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "note"}
              aria-label="Внутренняя заметка"
              title="Внутренняя заметка"
              className={
                mode === "note" ? "composer-mode-btn active" : "composer-mode-btn"
              }
              onClick={() => setMode("note")}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
            </button>
            {!disabled && mode === "reply" && (
              <button
                type="button"
                aria-label="Прикрепить файл"
                title="Прикрепить файл (до 25 МБ)"
                className="composer-mode-btn"
                onClick={() => fileInputRef.current?.click()}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
              </button>
            )}
            <input
              ref={fileInputRef}
              type="file"
              hidden
              multiple
              onChange={(e) => {
                const selected = Array.from(e.target.files ?? []);
                if (selected.length)
                  setFiles((prev) => [...prev, ...selected]);
                e.target.value = "";
              }}
            />
          </div>
          <textarea
            ref={areaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Owner (2026-11-18): Enter sends, Shift+Enter = new line.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            disabled={disabled}
            placeholder={
              disabled
                ? "Чат не назначен сотруднику — печатать нельзя"
                : mode === "reply"
                  ? "Напишите ответ пользователю…"
                  : "Заметка видна только команде поддержки…"
            }
            rows={1}
            maxLength={10000}
            aria-label="Текст сообщения"
          />
          <button
            type="submit"
            className={mode === "note" ? "note-send" : "send-button"}
            disabled={disabled || (!text.trim() && files.length === 0) || sending}
            aria-label={mode === "reply" ? "Отправить ответ" : "Добавить заметку"}
            title={mode === "reply" ? "Отправить ответ" : "Добавить заметку"}
          >
            {sending ? (
              "…"
            ) : (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M22 2 11 13" />
                <path d="M22 2 15 22l-4-9-9-4Z" />
              </svg>
            )}
          </button>
        </div>
        <div className="composer-bottom">
          <div className="composer-hint">
            {disabled ? (
              <>Сначала назначьте сотрудника в распределении</>
            ) : mode === "reply" ? (
              <>Будет отправлено пользователю</>
            ) : (
              <>Только для сотрудников</>
            )}
            <span className="character-count">{text.length}/10000</span>
          </div>
          {mode === "reply" && !disabled && (
            <button
              type="button"
              className={`composer-kb-toggle ${hintsOff ? "off" : ""}`}
              title={
                hintsOff
                  ? "Подсказки из базы знаний выключены — включить"
                  : "Подсказки из базы знаний включены — выключить"
              }
              aria-pressed={!hintsOff}
              onClick={toggleHints}
            >
              {/* Owner (2026-11-26): a pen writing on paper instead of the
                  text button. ON = black, OFF = muted dashed. */}
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 3h10l4 4v14H5V3Z" />
                <path d="M15 3v4h4" />
                <path
                  d="M8.5 16.5l6.8-6.8 2 2-6.8 6.8H8.5v-2Z"
                  fill="currentColor"
                  stroke="none"
                />
              </svg>
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

export const Composer = memo(ComposerImpl);
