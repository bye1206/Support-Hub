import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import "./App.css";
type Status =
  | "NEW"
  | "OPEN"
  | "AI_PROCESSING"
  | "PENDING_USER"
  | "RESOLVED"
  | "CLOSED";
type Ticket = {
  ticket_id: string;
  conversation_id: string;
  user_id: string;
  status: Status;
  priority: string;
  assignee_id: string | null;
  category_id: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
  messages?: Message[];
};
type Message = {
  message_id: string;
  sequence_no: number;
  author_type: string;
  text: string;
  created_at: string;
};
type Note = {
  note_id: string;
  conversation_id: string;
  author_id: string;
  body: string;
  created_at: string;
};
type Credentials = { token: string };
type Category = { category_id: string; name: string; parent_id: string | null };
type AssignmentEvent = {
  actor_id: string | null;
  assignee_id: string | null;
  created_at: string;
};
type TicketTag = { tag_id: string; name: string };
type OperatorProfile = {
  operator_id: string;
  email: string;
  display_name: string;
  role: string;
};
type Filter =
  | "all"
  | "mine"
  | "unassigned"
  | "new"
  | "working"
  | "waiting"
  | "resolved";
const filters: { key: Filter; label: string; icon: string }[] = [
  { key: "all", label: "Все обращения", icon: "▤" },
  { key: "mine", label: "Мои", icon: "◉" },
  { key: "unassigned", label: "Без назначения", icon: "○" },
  { key: "new", label: "Новые", icon: "✳" },
  { key: "working", label: "В работе", icon: "◷" },
  { key: "waiting", label: "Ожидают пользователя", icon: "◌" },
  { key: "resolved", label: "Решённые", icon: "✓" },
];
const priorityName: Record<string, string> = {
  LOW: "Низкий",
  NORMAL: "Обычный",
  HIGH: "Высокий",
  URGENT: "Срочный",
};
const statusName: Record<Status, string> = {
  NEW: "Новый",
  OPEN: "Открыт",
  AI_PROCESSING: "ИИ обрабатывает",
  PENDING_USER: "Ждём пользователя",
  RESOLVED: "Решён",
  CLOSED: "Закрыт",
};
const readCredentials = (): Credentials => {
  try {
    const parsed = JSON.parse(sessionStorage.getItem("support-hub-operator") || "null");
    return typeof parsed?.token === "string" ? { token: parsed.token } : { token: "" };
  } catch {
    return { token: "" };
  }
};
const initials = (value: string) =>
  value
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((x) => x[0].toUpperCase())
    .join("") || "SH";
const shortId = (value: string) => value.slice(0, 8).toUpperCase();
const ago = (value: string) => {
  const n = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 60000),
  );
  return n < 1
    ? "только что"
    : n < 60
      ? `${n} мин назад`
      : n < 1440
        ? `${Math.floor(n / 60)} ч назад`
        : new Intl.DateTimeFormat("ru-RU", {
            day: "numeric",
            month: "short",
          }).format(new Date(value));
};
async function api<T>(
  path: string,
  auth: Credentials,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api/v1/operator${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${auth.token}`,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let msg = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      msg = body?.error?.message || body?.detail || msg;
    } catch {
      /* no response body */
    }
    throw Error(msg);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export default function App() {
  const [auth, setAuth] = useState<Credentials>(readCredentials),
    [draftLogin, setDraftLogin] = useState(""),
    [draftPassword, setDraftPassword] = useState(""),
    [signingIn, setSigningIn] = useState(false),
    [filter, setFilter] = useState<Filter>("all"),
    [tickets, setTickets] = useState<Ticket[]>([]),
    [selectedId, setSelectedId] = useState<string | null>(null),
    [current, setCurrent] = useState<Ticket | null>(null),
    [operatorId, setOperatorId] = useState(""),
    [profile, setProfile] = useState<OperatorProfile | null>(null),
    [categories, setCategories] = useState<Category[]>([]),
    [assignmentHistory, setAssignmentHistory] = useState<AssignmentEvent[]>([]),
    [previousTickets, setPreviousTickets] = useState<Ticket[]>([]),
    [ticketTags, setTicketTags] = useState<TicketTag[]>([]),
    [notes, setNotes] = useState<Note[]>([]),
    [mode, setMode] = useState<"reply" | "note">("reply"),
    [text, setText] = useState(""),
    [search, setSearch] = useState(""),
    [loading, setLoading] = useState(false),
    [sending, setSending] = useState(false),
    [connected, setConnected] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [mobile, setMobile] = useState<"queue" | "conversation" | "details">(
      "queue",
    ),
    [details, setDetails] = useState(true);
  const socket = useRef<WebSocket | null>(null),
    retry = useRef<number>(),
    history = useRef<HTMLDivElement>(null),
    selectedRef = useRef<string | null>(null);
  const ready = Boolean(auth.token);
  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);
  const loadQueue = useCallback(async () => {
    if (!ready) return;
    const q = new URLSearchParams({ limit: "100" });
    if (filter === "mine") q.set("assignee", "me");
    if (filter === "unassigned") q.set("assignee", "unassigned");
    const status: Partial<Record<Filter, Status>> = {
      new: "NEW",
      working: "OPEN",
      waiting: "PENDING_USER",
      resolved: "RESOLVED",
    };
    if (status[filter]) q.set("status", status[filter]!);
    try {
      const data = await api<{ tickets: Ticket[] }>(`/tickets?${q}`, auth);
      setTickets(data.tickets);
      setError("");
      if (
        selectedRef.current &&
        !data.tickets.some((t) => t.ticket_id === selectedRef.current)
      )
        setSelectedId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить очередь");
    }
  }, [auth, filter, ready]);
  const loadTicket = useCallback(
    async (id: string) => {
      if (!ready) return;
      setLoading(true);
      try {
        const ticket = await api<Ticket>(`/tickets/${id}`, auth);
        const [noteData, categoryData, historyData, pastData, tagData] =
          await Promise.all([
            api<{ notes: Note[] }>(
              `/conversations/${ticket.conversation_id}/notes`,
              auth,
            ),
            api<{ categories: Category[] }>("/categories", auth),
            api<{ events: AssignmentEvent[] }>(
              `/tickets/${id}/assignment-history`,
              auth,
            ),
            api<{ tickets: Ticket[] }>(
              `/users/${ticket.user_id}/tickets?limit=20`,
              auth,
            ),
            api<{ tags: TicketTag[] }>(`/tickets/${id}/tag-details`, auth),
          ]);
        setCurrent(ticket);
        setNotes(noteData.notes);
        setCategories(categoryData.categories);
        setAssignmentHistory(historyData.events);
        setPreviousTickets(
          pastData.tickets.filter(
            (item) => item.ticket_id !== ticket.ticket_id,
          ),
        );
        setTicketTags(tagData.tags);
        setError("");
      } catch (e) {
        setError(
          e instanceof Error ? e.message : "Не удалось загрузить обращение",
        );
      } finally {
        setLoading(false);
      }
    },
    [auth, ready],
  );
  const sync = useCallback(async () => {
    await loadQueue();
    if (selectedRef.current) await loadTicket(selectedRef.current);
  }, [loadQueue, loadTicket]);
  useEffect(() => {
    if (ready) void loadQueue();
  }, [ready, loadQueue]);
  useEffect(() => {
    if (ready)
      void api<OperatorProfile>("/me", auth)
        .then((data) => {
          setProfile(data);
          setOperatorId(data.operator_id);
        })
        .catch((e) =>
          setError(
            e instanceof Error ? e.message : "Не удалось определить оператора",
          ),
        );
  }, [auth, ready]);
  useEffect(() => {
    if (selectedId) void loadTicket(selectedId);
    else {
      setCurrent(null);
      setNotes([]);
    }
  }, [selectedId, loadTicket]);
  useEffect(() => {
    if (history.current)
      history.current.scrollTop = history.current.scrollHeight;
  }, [current?.messages?.length, notes.length]);
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(""), 3200);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    if (!ready) return;
    let stopped = false;
    const connect = () => {
      if (stopped) return;
      const scheme = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(
        `${scheme}//${location.host}/ws?token=${encodeURIComponent(auth.token)}`,
      );
      socket.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        try {
          const v = JSON.parse(e.data);
          if (v.type !== "ready" && v.type !== "ping") void sync();
        } catch {
          void sync();
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stopped)
          retry.current = window.setTimeout(() => {
            void sync();
            connect();
          }, 2500);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry.current);
      socket.current?.close();
      socket.current = null;
    };
  }, [auth.token, ready, sync]);
  const visible = useMemo(() => {
    const q = search.trim().toLocaleLowerCase("ru-RU");
    return tickets.filter(
      (t) =>
        !q ||
        `${t.user_id} ${t.ticket_id} ${t.tags.join(" ")}`
          .toLocaleLowerCase("ru-RU")
          .includes(q),
    );
  }, [search, tickets]);
  const signIn = async (e: FormEvent) => {
    e.preventDefault();
    if (!draftLogin.trim() || !draftPassword || signingIn) return;
    setSigningIn(true);
    try {
      // UTF-8 Basic: domain logins/passwords may contain non-Latin letters.
      const bytes = new TextEncoder().encode(
        `${draftLogin.trim()}:${draftPassword}`,
      );
      let binary = "";
      bytes.forEach((b) => {
        binary += String.fromCharCode(b);
      });
      const data = await api<{ session_token: string }>("/auth/session", { token: "" }, {
        method: "POST",
        headers: { Authorization: `Basic ${btoa(binary)}` },
      });
      const next = { token: data.session_token };
      sessionStorage.setItem("support-hub-operator", JSON.stringify(next));
      setAuth(next);
      setDraftPassword("");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Вход не выполнен");
    } finally {
      setSigningIn(false);
    }
  };
  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!current || !text.trim() || sending) return;
    setSending(true);
    try {
      if (mode === "reply") {
        await api(`/tickets/${current.ticket_id}/replies`, auth, {
          method: "POST",
          body: JSON.stringify({ text: text.trim() }),
        });
        setToast("Ответ отправлен в очередь доставки");
      } else {
        await api(`/conversations/${current.conversation_id}/notes`, auth, {
          method: "POST",
          body: JSON.stringify({ body: text.trim() }),
        });
        setToast("Внутренняя заметка сохранена");
      }
      setText("");
      await sync();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Отправка не удалась");
    } finally {
      setSending(false);
    }
  };
  const addTag = async () => {
    if (!current) return;
    const name = window.prompt("Название тега");
    if (!name?.trim()) return;
    try {
      await api(`/tickets/${current.ticket_id}/tags`, auth, {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      await sync();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Не удалось добавить тег",
      );
    }
  };
  const removeTag = async (tagId: string) => {
    if (!current) return;
    try {
      await api(`/tickets/${current.ticket_id}/tags/${tagId}`, auth, {
        method: "DELETE",
      });
      await sync();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Не удалось удалить тег",
      );
    }
  };
  const updateCategory = async (categoryId: string) => {
    if (!current) return;
    try {
      await api(`/tickets/${current.ticket_id}/category`, auth, {
        method: "PATCH",
        body: JSON.stringify({ category_id: categoryId || null }),
      });
      await sync();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Не удалось обновить категорию",
      );
    }
  };
  const action = async (kind: "assign" | "resolve" | "close") => {
    if (!current) return;
    try {
      await api(`/tickets/${current.ticket_id}/${kind}`, auth, {
        method: "POST",
        ...(kind === "assign"
          ? { body: JSON.stringify({ assignee_id: operatorId }) }
          : {}),
      });
      setToast(
        kind === "assign"
          ? "Тикет взят в работу"
          : kind === "resolve"
            ? "Тикет решён"
            : "Тикет закрыт",
      );
      await sync();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Действие не выполнено");
    }
  };
  if (!ready)
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="brand-mark">
            s<span>•</span>
          </div>
          <p className="eyebrow">SUPPORT HUB · OPERATOR</p>
          <h1>Рабочее место оператора</h1>
          <p className="auth-copy">
            Войдите доменным логином и паролем. Данные доступны только в
            текущей сессии браузера.
          </p>
          <form className="auth-form" onSubmit={signIn}>
            <label>
              Доменный логин
              <input
                autoComplete="username"
                required
                placeholder="ivanov"
                value={draftLogin}
                onChange={(e) => setDraftLogin(e.target.value)}
              />
            </label>
            <label>
              Пароль
              <input
                type="password"
                required
                autoComplete="current-password"
                placeholder="Пароль доменной учётной записи"
                value={draftPassword}
                onChange={(e) => setDraftPassword(e.target.value)}
              />
            </label>
            {error && <p className="auth-error">{error}</p>}
            <button className="primary-button" disabled={signingIn}>
              {signingIn ? "Проверяем…" : "Открыть очередь"} <span>→</span>
            </button>
          </form>
          <p className="auth-footnote">
            Авторизация через LDAP/AD (D-047); сессия закрывается по истечении
            срока.
          </p>
        </section>
      </main>
    );
  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="brand-mark small">
          s<span>•</span>
        </div>
        <button className="rail-button active" title="Рабочее место">
          ▦
        </button>
        <button className="rail-button" disabled title="База знаний">
          ▧
        </button>
        <div className="rail-spacer" />
        <button className="avatar rail-avatar">
          {initials(profile?.display_name || profile?.email || "SH")}
        </button>
      </aside>
      <aside
        className={`queue-panel ${mobile === "queue" ? "mobile-visible" : "mobile-hidden"}`}
      >
        <header className="queue-header">
          <div>
            <p className="eyebrow">SUPPORT HUB</p>
            <h1>
              Обращения <span className="count-pill">{tickets.length}</span>
            </h1>
          </div>
          <button
            className="icon-button"
            title="Обновить"
            onClick={() => void sync()}
          >
            ↻
          </button>
        </header>
        <div className="queue-search">
          <span>⌕</span>
          <input
            aria-label="Поиск обращений"
            placeholder="Поиск по обращениям"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd>⌘ K</kbd>
        </div>
        <nav className="queue-nav" aria-label="Фильтры очереди">
          {filters.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${filter === item.key ? "selected" : ""}`}
              onClick={() => setFilter(item.key)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.key === "all" && (
                <span className="nav-count">{tickets.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="section-label">
          <span>ОБЩАЯ ОЧЕРЕДЬ</span>
          <span
            className={`live-dot ${connected ? "online" : ""}`}
            title={connected ? "Realtime подключён" : "Нет realtime соединения"}
          />
        </div>
        <div className="ticket-list">
          {visible.map((t) => (
            <button
              key={t.ticket_id}
              className={`ticket-row ${selectedId === t.ticket_id ? "active" : ""}`}
              onClick={() => {
                setSelectedId(t.ticket_id);
                setMobile("conversation");
              }}
            >
              <div className="ticket-topline">
                <span className="ticket-number">#{shortId(t.ticket_id)}</span>
                <span className="ticket-time">{ago(t.updated_at)}</span>
              </div>
              <div className="ticket-subject">Обращение пользователя</div>
              <div className="ticket-preview">
                {t.tags.length
                  ? t.tags.join(" · ")
                  : `Пользователь ${shortId(t.user_id)}`}
              </div>
              <div className="ticket-meta">
                <span className={`status-dot ${t.status.toLowerCase()}`} />
                <span className={`status-text ${t.status.toLowerCase()}`}>
                  {statusName[t.status]}
                </span>
                <span className="priority-mark">
                  {t.priority === "HIGH" || t.priority === "URGENT" ? "↑" : ""}
                </span>
              </div>
            </button>
          ))}
          {!visible.length && (
            <div className="empty-queue">
              <span>◌</span>
              <strong>Здесь пока тихо</strong>
              <p>Новые обращения появятся в очереди</p>
            </div>
          )}
        </div>
        <footer className="queue-footer">
          <div className="profile-avatar">
            {initials(profile?.display_name || profile?.email || "SH")}
          </div>
          <div className="profile-copy">
            <strong>{profile?.display_name || "Оператор"}</strong>
            <span>{profile?.email}</span>
          </div>
          <button
            className="icon-button"
            title="Выйти"
            onClick={() => {
              sessionStorage.removeItem("support-hub-operator");
              setAuth({ token: "" });
              setProfile(null);
            }}
          >
            ↪
          </button>
        </footer>
      </aside>
      <main
        className={`conversation-panel ${mobile === "conversation" ? "mobile-visible" : "mobile-hidden"}`}
      >
        {current ? (
          <>
            <header className="conversation-header">
              <button
                className="mobile-back"
                onClick={() => setMobile("queue")}
              >
                ←
              </button>
              <div className="conversation-title">
                <span className="ticket-number">
                  #{shortId(current.ticket_id)}
                </span>
                <h2>Обращение пользователя</h2>
                <span
                  className={`status-badge ${current.status.toLowerCase()}`}
                >
                  {statusName[current.status]}
                </span>
              </div>
              <div className="header-actions">
                <span
                  className={`connection-label ${connected ? "" : "offline"}`}
                >
                  <i />
                  {connected ? "Live" : "Переподключение"}
                </span>
                <button
                  className="icon-button mobile-details"
                  onClick={() => setMobile("details")}
                >
                  ⓘ
                </button>
                <button
                  className="icon-button"
                  title="Свернуть детали"
                  onClick={() => setDetails((v) => !v)}
                >
                  •••
                </button>
              </div>
            </header>
            {error && (
              <div className="error-banner">
                <span>!</span>
                {error}
                <button onClick={() => setError("")}>×</button>
              </div>
            )}
            <div className="conversation-scroll" ref={history}>
              <div className="conversation-start">
                <div className="user-avatar large">
                  {initials(shortId(current.user_id))}
                </div>
                <h3>Пользователь {shortId(current.user_id)}</h3>
                <p>
                  Обращение создано{" "}
                  {new Intl.DateTimeFormat("ru-RU", {
                    dateStyle: "long",
                  }).format(new Date(current.created_at))}
                </p>
                <span className="conversation-id">
                  Диалог · {shortId(current.conversation_id)}
                </span>
              </div>
              <div className="day-divider">
                <span>История переписки</span>
              </div>
              {loading ? (
                <div className="loading-state">Загружаем переписку…</div>
              ) : (
                <div className="message-list">
                  {current.messages
                    ?.slice()
                    .sort((a, b) => a.sequence_no - b.sequence_no)
                    .map((m) => (
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
                          {m.author_type.toUpperCase() === "AI"
                            ? "✦"
                            : initials(shortId(current.user_id))}
                        </div>
                        <div className="message-content">
                          <div className="message-heading">
                            <strong>
                              {m.author_type.toUpperCase() === "USER"
                                ? "Пользователь " + shortId(current.user_id)
                                : m.author_type.toUpperCase() === "AI"
                                  ? "AI-помощник"
                                  : profile?.display_name || "Оператор"}
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
                    ))}
                  {notes.map((n) => (
                    <article className="note-card" key={n.note_id}>
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
                            }).format(new Date(n.created_at))}
                          </time>
                        </div>
                        <p>{n.body}</p>
                      </div>
                    </article>
                  ))}
                  {!current.messages?.length && !notes.length && (
                    <div className="empty-history">Сообщений пока нет</div>
                  )}
                </div>
              )}
            </div>
            <section
              className={`composer ${mode === "note" ? "note-mode" : ""}`}
            >
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
              <form onSubmit={send}>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    mode === "reply"
                      ? "Напишите ответ пользователю…"
                      : "Заметка видна только команде поддержки…"
                  }
                  rows={3}
                  maxLength={10000}
                  aria-label={
                    mode === "reply" ? "Публичный ответ" : "Внутренняя заметка"
                  }
                />
                <div className="composer-bottom">
                  <div className="composer-hint">
                    {mode === "reply" ? (
                      <>
                        <span className="public-icon">↗</span> Будет отправлено
                        пользователю
                      </>
                    ) : (
                      <>
                        <span className="private-icon">▤</span> Только для
                        сотрудников
                      </>
                    )}
                    <span className="character-count">{text.length}/10000</span>
                  </div>
                  <button
                    className={mode === "note" ? "note-send" : "send-button"}
                    disabled={!text.trim() || sending}
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
          </>
        ) : (
          <div className="welcome-state">
            <div className="welcome-art">
              <span>✦</span>
              <i>✧</i>
              <b>↗</b>
            </div>
            <p className="eyebrow">РАБОЧЕЕ МЕСТО</p>
            <h2>{tickets.length ? "Выберите обращение" : "Очередь готова"}</h2>
            <p>
              {tickets.length
                ? "Переписка и детали появятся здесь"
                : "Новые обращения появятся здесь, когда пользователь напишет в поддержку"}
            </p>
            {error && (
              <div className="error-banner centered">
                {error}
                <button onClick={() => setError("")}>×</button>
              </div>
            )}
          </div>
        )}
      </main>
      {current && (
        <aside
          className={`details-panel ${details ? "" : "collapsed"} ${mobile === "details" ? "mobile-visible" : "mobile-hidden"}`}
        >
          <header className="details-header">
            <button
              className="mobile-back"
              onClick={() => setMobile("conversation")}
            >
              ←
            </button>
            <h3>Детали обращения</h3>
            <button className="icon-button" onClick={() => setDetails(false)}>
              ×
            </button>
          </header>
          <div className="details-scroll">
            <section className="customer-card">
              <div className="user-avatar">
                {initials(shortId(current.user_id))}
              </div>
              <h3>Пользователь {shortId(current.user_id)}</h3>
              <p>Корпоративный пользователь</p>
              <span className="text-action">Профиль пользователя</span>
            </section>
            <section className="detail-section">
              <div className="detail-label">СТАТУС</div>
              <div className="detail-value">
                <span
                  className={`status-dot ${current.status.toLowerCase()}`}
                />
                {statusName[current.status]}
              </div>
              <div className="detail-label spaced">ПРИОРИТЕТ</div>
              <div className="priority-control">
                <span className="priority-stars">✦</span>
                <span>
                  {priorityName[current.priority.toUpperCase()] ||
                    current.priority}
                </span>
              </div>
              <div className="detail-label spaced">SLA</div>
              <div className="sla-card">
                <span className="sla-clock">◷</span>
                <div>
                  <strong>Контроль SLA</strong>
                  <span>Расчёт появится на этапе 10</span>
                </div>
                <span className="sla-placeholder">—</span>
              </div>
            </section>
            <section className="detail-section">
              <div className="detail-heading">
                <div className="detail-label">НАЗНАЧЕНИЕ</div>
                <button
                  className="text-action"
                  disabled={!operatorId}
                  onClick={() => void action("assign")}
                >
                  {current.assignee_id === operatorId
                    ? "Ваша очередь"
                    : "Взять себе"}
                </button>
              </div>
              <div className="assignee-row">
                <div className="profile-avatar purple">
                  {current.assignee_id ? "О" : "?"}
                </div>
                <span>
                  {current.assignee_id
                    ? `Оператор ${shortId(current.assignee_id)}`
                    : "Без назначения"}
                </span>
              </div>
              <div className="assignment-history">
                <span className="history-line" />
                {assignmentHistory.length
                  ? assignmentHistory.slice(0, 5).map((event) => (
                      <div
                        className="history-event"
                        key={`${event.created_at}-${event.actor_id}`}
                      >
                        {event.assignee_id
                          ? `Назначено оператору ${shortId(event.assignee_id)}`
                          : "Снято назначение"}
                        <time>{ago(event.created_at)}</time>
                      </div>
                    ))
                  : "История назначений пока пуста"}
              </div>
            </section>
            <section className="detail-section">
              <div className="detail-heading">
                <div className="detail-label">ТЕГИ</div>
                <button className="text-action" onClick={() => void addTag()}>
                  + Добавить
                </button>
              </div>
              <div className="tag-list">
                {ticketTags.length ? (
                  ticketTags.map((tag) => (
                    <span className="tag removable" key={tag.tag_id}>
                      {tag.name}
                      <button
                        aria-label={`Удалить тег ${tag.name}`}
                        onClick={() => void removeTag(tag.tag_id)}
                      >
                        ×
                      </button>
                    </span>
                  ))
                ) : (
                  <span className="muted">Нет тегов</span>
                )}
              </div>
              <label
                className="detail-label spaced category-label"
                htmlFor="ticket-category"
              >
                КАТЕГОРИЯ
              </label>
              <select
                id="ticket-category"
                className="category-select"
                value={current.category_id || ""}
                onChange={(event) => void updateCategory(event.target.value)}
              >
                <option value="">Не выбрана</option>
                {categories.map((category) => (
                  <option
                    key={category.category_id}
                    value={category.category_id}
                  >
                    {category.name}
                  </option>
                ))}
              </select>
            </section>
            <section className="detail-section history-section">
              <div className="detail-heading">
                <div className="detail-label">ПРОШЛЫЕ ОБРАЩЕНИЯ</div>
                <span className="history-count">{previousTickets.length}</span>
              </div>
              {previousTickets.length ? (
                previousTickets.slice(0, 5).map((ticket) => (
                  <button
                    className="past-ticket"
                    key={ticket.ticket_id}
                    onClick={() => {
                      setFilter("all");
                      setSelectedId(ticket.ticket_id);
                      setMobile("conversation");
                    }}
                  >
                    <span>
                      #{shortId(ticket.ticket_id)} · {statusName[ticket.status]}
                    </span>
                    <time>{ago(ticket.updated_at)}</time>
                  </button>
                ))
              ) : (
                <div className="past-empty">Других обращений пока нет.</div>
              )}
            </section>
            <section className="detail-section action-section">
              <button
                onClick={() => void action("resolve")}
                disabled={
                  current.status === "RESOLVED" || current.status === "CLOSED"
                }
              >
                ✓ Решить обращение
              </button>
              <button
                className="quiet-action"
                onClick={() => void action("close")}
                disabled={current.status === "CLOSED"}
              >
                Закрыть тикет
              </button>
            </section>
          </div>
        </aside>
      )}
      {toast && (
        <div className="toast">
          <span>✓</span>
          {toast}
        </div>
      )}
    </div>
  );
}
