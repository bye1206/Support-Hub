import { memo, useState, type FormEvent } from "react";

type Mode = "reply" | "note";

type Props = {
  disabled: boolean;
  // Return true when the message actually went through — the draft is
  // cleared only then.
  onSend: (mode: Mode, text: string) => Promise<boolean>;
};

// Owns its own draft state (decomposition round 2026-11-17): typing used to
// re-render the whole App (queue of ~200 rows, all modals) per keystroke.
function ComposerImpl({ disabled, onSend }: Props) {
  const [mode, setMode] = useState<Mode>("reply");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || sending) return;
    setSending(true);
    const sent = await onSend(mode, text.trim());
    setSending(false);
    if (sent) setText("");
  };
  return (
    <section className={`composer ${mode === "note" ? "note-mode" : ""}`}>
      <div className="composer-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={mode === "reply"}
          className={mode === "reply" ? "active" : ""}
          onClick={() => setMode("reply")}
        >
          <span>↗</span> Публичный ответ
        </button>
        <button
          role="tab"
          aria-selected={mode === "note"}
          className={mode === "note" ? "active" : ""}
          onClick={() => setMode("note")}
        >
          <span>▤</span> Внутренняя заметка
        </button>
      </div>
      <form onSubmit={submit}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={disabled}
          placeholder={
            disabled
              ? "Чат не назначен сотруднику — печатать нельзя"
              : mode === "reply"
                ? "Напишите ответ пользователю…"
                : "Заметка видна только команде поддержки…"
          }
          rows={3}
          maxLength={10000}
          aria-label={mode === "reply" ? "Публичный ответ" : "Внутренняя заметка"}
        />
        <div className="composer-bottom">
          <div className="composer-hint">
            {disabled ? (
              <>
                <span className="private-icon">🔒</span> Сначала назначьте
                сотрудника в распределении
              </>
            ) : mode === "reply" ? (
              <>
                <span className="public-icon">↗</span> Будет отправлено
                пользователю
              </>
            ) : (
              <>
                <span className="private-icon">▤</span> Только для сотрудников
              </>
            )}
            <span className="character-count">{text.length}/10000</span>
          </div>
          <button
            className={mode === "note" ? "note-send" : "send-button"}
            disabled={disabled || !text.trim() || sending}
          >
            {sending
              ? "Сохраняем…"
              : mode === "reply"
                ? "Отправить ответ ↗"
                : "Добавить заметку ↗"}
          </button>
        </div>
      </form>
    </section>
  );
}

export const Composer = memo(ComposerImpl);
