import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import "./App.css";
import { AdminPanel } from "./AdminPanel";
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
  session?: { started_at: string; expires_at: string } | null;
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
type Colleague = {
  operator_id: string;
  display_name: string | null;
  email: string;
};
type AdInfo = {
  available: boolean;
  login?: string;
  full_name?: string;
  email?: string;
  title?: string;
  department?: string;
  company?: string;
  phone?: string;
  mobile?: string;
  manager?: string;
  disabled?: boolean;
  locked?: boolean;
  password_changed_at?: string | null;
  password_expires_at?: string | null;
  groups?: string[];
  photo_url?: string;
  synced_at?: string | null;
};
type TeamMember = {
  operator_id: string;
  display_name: string | null;
  email: string;
  presence_status: "ACTIVE" | "LUNCH" | "BREAK" | "OFFLINE";
  presence_since: string;
  open_tickets: number;
  max_active_tickets: number;
};
const presenceLabels = {
  ACTIVE: "Активен",
  LUNCH: "Обед",
  BREAK: "Перерыв",
  OFFLINE: "Офлайн",
} as const;
type Presence = keyof typeof presenceLabels;
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
  | "ai"
  | "working"
  | "waiting"
  | "resolved";
type Theme = "light" | "dark";
function ThemeIcon({ theme }: { theme: Theme }) {
  return theme === "dark" ? (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.3A8.4 8.4 0 0 1 8.7 3.8 8.5 8.5 0 1 0 20.2 15.3Z" /><path d="M16.5 3.5v4M14.5 5.5h4" /></svg>
  ) : (
    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" /></svg>
  );
}
const filters: { key: Filter; label: string; icon: string }[] = [
  { key: "all", label: "Все обращения", icon: "▤" },
  { key: "mine", label: "Мои", icon: "◉" },
  { key: "unassigned", label: "Без назначения", icon: "○" },
  { key: "ai", label: "Обработка ИИ", icon: "✳" },
  { key: "working", label: "В работе", icon: "◷" },
  { key: "waiting", label: "Ожидают пользователя", icon: "◌" },
  { key: "resolved", label: "Решённые", icon: "✓" },
];
function QueueIcon({ name }: { name: Filter }) {
  const shapes: Record<Filter, ReactNode> = {
    all: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 9h8M8 13h8M8 17h5" /></>,
    mine: <><circle cx="12" cy="8" r="3" /><path d="M5.5 20a6.5 6.5 0 0 1 13 0" /></>,
    unassigned: <><circle cx="9" cy="8" r="3" /><path d="M3.5 20a5.5 5.5 0 0 1 11 0M17 8h4m-2-2v4" /></>,
    ai: <path d="m12 3 1.5 6.5L20 12l-6.5 1.5L12 20l-1.5-6.5L4 12l6.5-2.5L12 3Z" />,
    working: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    waiting: <><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z" /></>,
    resolved: <><circle cx="12" cy="12" r="9" /><path d="m8 12 2.5 2.5L16 9" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{shapes[name]}</svg>;
}
const priorityName: Record<string, string> = {
  LOW: "Низкий",
  NORMAL: "Обычный",
  HIGH: "Высокий",
  URGENT: "Срочный",
};
const statusName: Record<Status, string> = {
  NEW: "Без назначения",
  OPEN: "В работе",
  AI_PROCESSING: "Обработка ИИ",
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
const fmtDuration = (ms: number) => {
  const total = Math.floor(ms / 60000);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return hours > 0 ? `${hours} ч ${minutes} мин` : `${minutes} мин`;
};
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
    if (response.status === 401) {
      // The session is gone (expired / backend restart): back to sign-in.
      sessionStorage.removeItem("support-hub-operator");
      window.location.reload();
      throw Error("Сессия истекла — войдите заново");
    }
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
  const [theme, setTheme] = useState<Theme>(() =>
    typeof localStorage !== "undefined" &&
    localStorage.getItem("support-hub-theme") === "dark" ? "dark" : "light",
  ),
    [auth, setAuth] = useState<Credentials>(readCredentials),
    [draftLogin, setDraftLogin] = useState(""),
    [draftPassword, setDraftPassword] = useState(""),
    [signingIn, setSigningIn] = useState(false),
    [filter, setFilter] = useState<Filter>("all"),
    [colleagues, setColleagues] = useState<Colleague[]>([]),
    [team, setTeam] = useState<TeamMember[]>([]),
    [teamOpen, setTeamOpen] = useState(false),
    [teamMember, setTeamMember] = useState<TeamMember | null>(null),
    [teamTickets, setTeamTickets] = useState<Ticket[]>([]),
    [teamTicket, setTeamTicket] = useState<Ticket | null>(null),
    [profileMenuOpen, setProfileMenuOpen] = useState(false),
    [transferOpen, setTransferOpen] = useState(false),
    [historyOpen, setHistoryOpen] = useState(false),
    [historyDetail, setHistoryDetail] = useState<Ticket | null>(null),
    [sessionOpen, setSessionOpen] = useState(false),
    [tickets, setTickets] = useState<Ticket[]>([]),
    [selectedId, setSelectedId] = useState<string | null>(null),
    [current, setCurrent] = useState<Ticket | null>(null),
    [operatorId, setOperatorId] = useState(""),
    [operatorRole, setOperatorRole] = useState<"OPERATOR" | "SUPERVISOR" | "ADMIN">("OPERATOR"),
    [adminOpen, setAdminOpen] = useState(false),
    [profile, setProfile] = useState<OperatorProfile | null>(null),
    [categories, setCategories] = useState<Category[]>([]),
    [assignmentHistory, setAssignmentHistory] = useState<AssignmentEvent[]>([]),
    [previousTickets, setPreviousTickets] = useState<Ticket[]>([]),
    [ticketTags, setTicketTags] = useState<TicketTag[]>([]),
    [adInfo, setAdInfo] = useState<AdInfo | null>(null),
    [adPhotos, setAdPhotos] = useState<Record<string, string>>({}),
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
    searchInput = useRef<HTMLInputElement>(null),
    selectedRef = useRef<string | null>(null),
    adPhotosRef = useRef<Record<string, string>>({});
  const ready = Boolean(auth.token);
  const meEntry = team.find((member) => member.operator_id === operatorId);
  const presence: Presence = meEntry?.presence_status ?? "ACTIVE";
  const presenceSince = meEntry?.presence_since ?? null;
  const [nowTs, setNowTs] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowTs(Date.now()), 30000);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    if (!ready) return;
    void api<{ colleagues: Colleague[] }>("/colleagues", auth)
      .then((data) => setColleagues(data.colleagues ?? []))
      .catch(() => setColleagues([]));
  }, [auth, ready]);
  useEffect(() => {
    if (!ready) return;
    const loadTeam = () =>
      void api<{ team: TeamMember[] }>("/team", auth)
        .then((data) => setTeam(data.team ?? []))
        .catch(() => {});
    loadTeam();
    const id = window.setInterval(loadTeam, 30000);
    return () => window.clearInterval(id);
  }, [auth, ready]);
  useEffect(() => {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem("support-hub-theme", theme);
  }, [theme]);
  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);
  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInput.current?.focus();
      }
      if (event.key === "Escape" && document.activeElement === searchInput.current)
        searchInput.current?.blur();
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);
  const loadQueue = useCallback(async () => {
    if (!ready) return;
    const q = new URLSearchParams({ limit: "100" });
    if (filter === "mine") q.set("assignee", "me");
    if (filter === "unassigned") q.set("assignee", "unassigned");
    const status: Partial<Record<Filter, Status>> = {
      ai: "AI_PROCESSING",
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
  const loadAdInfo = async (userId: string) => {
    // Employee card (P-29): graceful degradation - on any failure the
    // details panel shows the plain user block.
    try {
      const info = await api<AdInfo>(`/users/${userId}/ad-info`, auth);
      setAdInfo(info);
      if (info.available && info.photo_url && !adPhotosRef.current[userId]) {
        const response = await fetch(`/api/v1/operator${info.photo_url}`, {
          headers: { Authorization: `Bearer ${auth.token}` },
        });
        if (response.ok) {
          const blob = await response.blob();
          adPhotosRef.current[userId] = URL.createObjectURL(blob);
          setAdPhotos({ ...adPhotosRef.current });
        }
      }
    } catch {
      setAdInfo(null);
    }
  };
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
        await loadAdInfo(ticket.user_id);
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
          if (["OPERATOR", "SUPERVISOR", "ADMIN"].includes(data.role))
            setOperatorRole(data.role as "OPERATOR" | "SUPERVISOR" | "ADMIN");
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
  const timeline = useMemo(
    () => [
      ...(current?.messages ?? []).map((item) => ({
        kind: "message" as const,
        createdAt: item.created_at,
        item,
      })),
      ...notes.map((item) => ({
        kind: "note" as const,
        createdAt: item.created_at,
        item,
      })),
    ].sort(
      (a, b) =>
        new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
    ),
    [current?.messages, notes],
  );
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
  const transferToPerson = async (targetOperatorId: string) => {
    if (!current) return;
    try {
      await api(`/tickets/${current.ticket_id}/assign`, auth, {
        method: "POST",
        body: JSON.stringify({ assignee_id: targetOperatorId }),
      });
      setToast("Тикет передан сотруднику");
      setTransferOpen(false);
      await sync();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось передать тикет");
    }
  };
  const openHistoryDetail = async (ticketId: string) => {
    try {
      const card = await api<Ticket>(`/tickets/${ticketId}`, auth);
      setHistoryDetail(card);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть обращение");
    }
  };
  const openTeamMember = async (member: TeamMember) => {
    setTeamMember(member);
    setTeamTicket(null);
    setTeamTickets([]);
    try {
      const q = new URLSearchParams({
        assignee: member.operator_id,
        limit: "50",
      });
      const data = await api<{ tickets: Ticket[] }>(`/tickets?${q}`, auth);
      setTeamTickets(data.tickets);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить чаты");
    }
  };
  const openTeamTicket = async (ticketId: string) => {
    setTeamTicket(null);
    try {
      const card = await api<Ticket>(`/tickets/${ticketId}`, auth);
      setTeamTicket(card);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть обращение");
    }
  };
  const changePresence = async (status: Presence) => {
    try {
      await api("/presence", auth, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      const fresh = await api<{ team: TeamMember[] }>("/team", auth);
      setTeam(fresh.team ?? []);
      setToast(`Статус: ${presenceLabels[status]}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось изменить статус");
    }
  };
  const signOut = async () => {
    try {
      await api("/logout", auth, { method: "POST" });
    } catch {
      /* the session is being discarded regardless */
    }
    sessionStorage.removeItem("support-hub-operator");
    setAuth({ token: "" });
    setProfile(null);
    setProfileMenuOpen(false);
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
    <div
      className={`app-shell ${current ? (details ? "" : "details-collapsed") : "no-ticket"}`}
      data-theme={theme}
    >
      <aside className="rail">
        <div className="brand-mark small">
          s<span>•</span>
        </div>
        <button className="rail-button active" title="Очередь обращений" aria-label="Очередь обращений">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 13h4l2 3h6l2-3h4" />
            <path d="M5 5h14l2 8v6H3v-6l2-8Z" />
          </svg>
        </button>
        <button className="rail-button" disabled title="База знаний (скоро)" aria-label="База знаний">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 19V6a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2Zm0 0a2 2 0 0 0 2 2h13" />
            <path d="M9 8h6M9 11h6" />
          </svg>
        </button>
        {operatorRole !== "OPERATOR" && (
          <button className={`rail-button ${adminOpen ? "active" : ""}`} title="Панель управления" aria-label="Открыть панель управления" onClick={() => setAdminOpen((value) => !value)}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="3.2" />
              <path d="M19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.5-2-3.4-2.3 1a7.6 7.6 0 0 0-2.6-1.5L14 2.6h-4L9.5 5a7.6 7.6 0 0 0-2.6 1.5l-2.3-1-2 3.4 2 1.5a7.6 7.6 0 0 0 0 3l-2 1.5 2 3.4 2.3-1a7.6 7.6 0 0 0 2.6 1.5l.5 2.7h4l.5-2.7a7.6 7.6 0 0 0 2.6-1.5l2.3 1 2-3.4-2-1.5Z" />
            </svg>
          </button>
        )}
        <div className="rail-spacer" />
        <button
          className="rail-button theme-toggle"
          title={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
          aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
          onClick={() => setTheme((value) => (value === "dark" ? "light" : "dark"))}
        >
          <ThemeIcon theme={theme} />
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
          <button
            className="icon-button"
            title="Команда: статусы и нагрузка"
            aria-label="Команда: статусы и нагрузка"
            onClick={() => setTeamOpen(true)}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="8.5" cy="8" r="3" />
              <circle cx="16.5" cy="9.5" r="2.4" />
              <path d="M3 19c.5-3 2.7-4.8 5.5-4.8S13.5 16 14 19" />
              <path d="M15.5 14.6c2.4.2 4.3 1.7 5 4.4" />
            </svg>
          </button>
        </header>
        <div className="queue-search">
          <span>⌕</span>
          <input
            ref={searchInput}
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
              <span className="nav-icon"><QueueIcon name={item.key} /></span>
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
                {t.assignee_id && (
                  <span
                    className={`mine-pill ${t.assignee_id === operatorId ? "mine" : "taken"}`}
                  >
                    {t.assignee_id === operatorId ? "Моё" : "В работе"}
                  </span>
                )}
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
          <button
            className="profile-button"
            title="Статус и выход"
            onClick={() => setProfileMenuOpen((value) => !value)}
          >
            <span className="profile-avatar">
              {initials(profile?.display_name || profile?.email || "SH")}
            </span>
            <span className="profile-copy">
              <strong>{profile?.display_name || "Оператор"}</strong>
              <span>
                <i className={`presence-dot ${presence.toLowerCase()}`} />{" "}
                {presenceLabels[presence]}
                {presenceSince
                  ? ` · ${fmtDuration(nowTs - new Date(presenceSince).getTime())}`
                  : ""}
              </span>
            </span>
          </button>
          {profileMenuOpen && profile && (
            <div className="profile-menu" role="menu">
              {(Object.keys(presenceLabels) as Array<keyof typeof presenceLabels>).map(
                (status) => (
                  <button
                    key={status}
                    className={status === presence ? "active" : ""}
                    onClick={() => void changePresence(status)}
                  >
                    <i className={`presence-dot ${status.toLowerCase()}`} />
                    {presenceLabels[status]}
                    {status === presence && presenceSince && (
                      <span> · {fmtDuration(nowTs - new Date(presenceSince).getTime())}</span>
                    )}
                  </button>
                ),
              )}
              <button
                className="logout"
                onClick={() => {
                  if (
                    window.confirm(
                      "Точно хотите выйти? Активные обращения останутся в очереди.",
                    )
                  )
                    void signOut();
                }}
              >
                Выйти
              </button>
            </div>
          )}
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
                {current?.session && (
                  <span className="session-wrap">
                    <button
                      className={`icon-button ${sessionOpen ? "open" : ""}`}
                      title="Длительность сессии диалога"
                      aria-label="Длительность сессии диалога"
                      onClick={() => setSessionOpen((value) => !value)}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <circle cx="12" cy="12" r="9" />
                        <path d="M12 7v5l3.5 2" />
                      </svg>
                    </button>
                    {sessionOpen && (
                      <span className="session-pop">
                        <strong>Сессия диалога</strong>
                        <span>
                          Идёт{" "}
                          {fmtDuration(
                            nowTs -
                              new Date(current.session.started_at).getTime(),
                          )}
                        </span>
                        <span>
                          Осталось{" "}
                          {fmtDuration(
                            new Date(current.session.expires_at).getTime() -
                              nowTs,
                          )}
                        </span>
                        <span className="muted">
                          Сессия диалога длится ровно 3 часа
                        </span>
                      </span>
                    )}
                  </span>
                )}
                <button
                  className="icon-button"
                  title="Передать сотруднику"
                  aria-label="Передать сотруднику"
                  onClick={() => setTransferOpen(true)}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="9" cy="8" r="3.2" />
                    <path d="M3.5 19c.6-3.2 2.9-5 5.5-5 1 0 2 .3 2.8.8" />
                    <path d="M15 13h6m0 0-2.5-2.5M21 13l-2.5 2.5" />
                  </svg>
                </button>
                <button
                  className="icon-button"
                  title="Прошлые обращения пользователя"
                  aria-label="Прошлые обращения пользователя"
                  onClick={() => {
                    setHistoryDetail(null);
                    setHistoryOpen(true);
                  }}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M4 19V6a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2Zm0 0a2 2 0 0 0 2 2h13" />
                    <path d="M12 7.5a4.5 4.5 0 1 1-4.36 5.64M12 7.5H9.5M12 7.5V10" />
                  </svg>
                </button>
                <button
                  className="icon-button mobile-details"
                  title="Открыть детали обращения"
                  aria-label="Открыть детали обращения"
                  onClick={() => { setDetails(true); setMobile("details"); }}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8h.01" /></svg>
                </button>
                {details ? (
                  <button className="icon-button desktop-details-toggle" title="Свернуть детали" aria-label="Свернуть детали" onClick={() => setDetails(false)}>
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
                  </button>
                ) : (
                  <button className="icon-button desktop-details-toggle" title="Открыть детали" aria-label="Открыть детали" onClick={() => setDetails(true)}>
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
                  </button>
                )}
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
                {adPhotos[current.user_id] ? (
                  <img
                    className="user-photo large"
                    src={adPhotos[current.user_id]}
                    alt=""
                  />
                ) : (
                  <div className="user-avatar large">
                    {initials(adInfo?.full_name || shortId(current.user_id))}
                  </div>
                )}
                <h3>
                  {adInfo?.available && adInfo.full_name
                    ? adInfo.full_name
                    : `Пользователь ${shortId(current.user_id)}`}
                </h3>
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
                  {timeline.map((entry) => {
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
                    );
                  })}
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
              {adPhotos[current.user_id] ? (
                <img
                  className="user-photo"
                  src={adPhotos[current.user_id]}
                  alt=""
                />
              ) : (
                <div className="user-avatar">
                  {initials(adInfo?.full_name || shortId(current.user_id))}
                </div>
              )}
              {adInfo?.available ? (
                <>
                  <h3>{adInfo.full_name || adInfo.login}</h3>
                  <p>
                    {[adInfo.title, adInfo.department, adInfo.company]
                      .filter(Boolean)
                      .join(" · ") || "Сотрудник"}
                  </p>
                  <div className="ad-rows">
                    {adInfo.phone && (
                      <div>
                        <span>Тел.</span>
                        {adInfo.phone}
                      </div>
                    )}
                    {adInfo.mobile && (
                      <div>
                        <span>Моб.</span>
                        {adInfo.mobile}
                      </div>
                    )}
                    {adInfo.email && (
                      <div>
                        <span>Почта</span>
                        {adInfo.email}
                      </div>
                    )}
                    {adInfo.manager && (
                      <div>
                        <span>Руководитель</span>
                        {adInfo.manager}
                      </div>
                    )}
                    {adInfo.password_changed_at && (
                      <div>
                        <span>Пароль изменён</span>
                        {new Date(adInfo.password_changed_at).toLocaleDateString("ru-RU")}
                      </div>
                    )}
                    {adInfo.password_expires_at &&
                      new Date(adInfo.password_expires_at).getTime() > Date.now() && (
                        <div>
                          <span>Пароль истекает</span>
                          {Math.ceil(
                            (new Date(adInfo.password_expires_at).getTime() -
                              Date.now()) /
                              86400000,
                          )}{" "}
                          дн.
                        </div>
                      )}
                  </div>
                  {adInfo.groups?.length ? (
                    <div className="tag-list">
                      {adInfo.groups.slice(0, 6).map((group) => (
                        <span className="tag" key={group} title={group}>
                          {group}
                        </span>
                      ))}
                      {adInfo.groups.length > 6 && (
                        <span className="tag" title={adInfo.groups.join(", ")}>
                          +{adInfo.groups.length - 6}
                        </span>
                      )}
                    </div>
                  ) : null}
                  {(adInfo.disabled || adInfo.locked) && (
                    <div className="ad-warning">
                      Учётная запись {adInfo.disabled ? "отключена" : "заблокирована"} в
                      AD
                    </div>
                  )}
                </>
              ) : (
                <>
                  <h3>Пользователь {shortId(current.user_id)}</h3>
                  <p>Корпоративный пользователь</p>
                </>
              )}
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
                  disabled={
                    !operatorId ||
                    current.status === "RESOLVED" ||
                    current.status === "CLOSED"
                  }
                  title={
                    current.status === "RESOLVED" || current.status === "CLOSED"
                      ? "Обращение завершено — открыть нельзя"
                      : undefined
                  }
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
      {adminOpen && operatorRole !== "OPERATOR" && (
        <AdminPanel
          auth={auth}
          selfId={operatorId}
          role={operatorRole}
          theme={theme}
          onToggleTheme={() => setTheme((value) => value === "dark" ? "light" : "dark")}
          onRoleChange={(role) => {
            setOperatorRole(role);
            if (role === "OPERATOR") setAdminOpen(false);
          }}
          onClose={() => setAdminOpen(false)}
        />
      )}
      {transferOpen && current && (
        <div
          className="modal-backdrop"
          onClick={() => setTransferOpen(false)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-label="Передать обращение сотруднику"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">Передать обращение сотруднику</div>
            {colleagues.length ? (
              colleagues.map((colleague) => (
                <button
                  key={colleague.operator_id}
                  className="colleague-row"
                  onClick={() => void transferToPerson(colleague.operator_id)}
                >
                  <span className="profile-avatar small">
                    {initials(colleague.display_name || colleague.email)}
                  </span>
                  <span className="colleague-name">
                    {colleague.display_name || colleague.email}
                    <span className="muted">{colleague.email}</span>
                  </span>
                </button>
              ))
            ) : (
              <div className="past-empty">Нет активных сотрудников.</div>
            )}
            <button className="quiet-action" onClick={() => setTransferOpen(false)}>
              Закрыть
            </button>
          </div>
        </div>
      )}
      {historyOpen && current && (
        <div
          className="modal-backdrop"
          onClick={() => setHistoryOpen(false)}
          role="presentation"
        >
          <div
            className="modal wide"
            role="dialog"
            aria-label="Прошлые обращения пользователя"
            onClick={(e) => e.stopPropagation()}
          >
            {historyDetail ? (
              <>
                <button
                  className="quiet-action"
                  onClick={() => setHistoryDetail(null)}
                >
                  ← К списку обращений
                </button>
                <div className="modal-title">
                  #{shortId(historyDetail.ticket_id)} ·{" "}
                  {statusName[historyDetail.status]}
                </div>
                <div className="muted history-meta">
                  Открыто{" "}
                  {new Date(historyDetail.created_at).toLocaleString("ru-RU")}
                  {historyDetail.tags.length
                    ? ` · ${historyDetail.tags.join(" · ")}`
                    : ""}
                  {historyDetail.assignee_id
                    ? ` · Оператор #${shortId(historyDetail.assignee_id)}`
                    : ""}
                </div>
                <div className="history-messages">
                  {(historyDetail.messages ?? []).map((message) => (
                    <div
                      key={message.message_id}
                      className={`message ${message.author_type === "OPERATOR" ? "from-operator" : ""}`}
                    >
                      <div className="message-content">
                        <div className="message-bubble">{message.text}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="modal-title">
                  Прошлые обращения этого пользователя
                </div>
                {previousTickets.length ? (
                  previousTickets.map((ticket) => (
                    <button
                      key={ticket.ticket_id}
                      className="past-ticket"
                      onClick={() => void openHistoryDetail(ticket.ticket_id)}
                    >
                      <span>
                        #{shortId(ticket.ticket_id)} · {statusName[ticket.status]}
                      </span>
                      <span className="muted">
                        {ticket.tags.length ? ticket.tags.join(" · ") : "Без тегов"}
                      </span>
                      <time>{new Date(ticket.updated_at).toLocaleDateString("ru-RU")}</time>
                    </button>
                  ))
                ) : (
                  <div className="past-empty">Других обращений нет.</div>
                )}
              </>
            )}
          </div>
        </div>
      )}
      {teamOpen && (
        <div
          className="modal-backdrop"
          onClick={() => {
            setTeamOpen(false);
            setTeamMember(null);
            setTeamTicket(null);
          }}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-label="Команда"
            onClick={(e) => e.stopPropagation()}
          >
            {teamMember ? (
              teamTicket ? (
                <>
                  <button
                    className="quiet-action"
                    onClick={() => setTeamTicket(null)}
                  >
                    ← К чатам {teamMember.display_name || teamMember.email}
                  </button>
                  <div className="modal-title">
                    #{shortId(teamTicket.ticket_id)} ·{" "}
                    {statusName[teamTicket.status]}
                  </div>
                  <div className="muted history-meta">
                    Открыто{" "}
                    {new Date(teamTicket.created_at).toLocaleString("ru-RU")}
                    {teamTicket.tags.length
                      ? ` · ${teamTicket.tags.join(" · ")}`
                      : ""}
                  </div>
                  <div className="history-messages">
                    {(teamTicket.messages ?? []).map((message) => (
                      <div
                        key={message.message_id}
                        className={`message ${message.author_type === "OPERATOR" ? "from-operator" : ""}`}
                      >
                        <div className="message-content">
                          <div className="message-bubble">{message.text}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <button
                    className="quiet-action"
                    onClick={() => setTeamMember(null)}
                  >
                    ← К команде
                  </button>
                  <div className="modal-title">
                    {teamMember.display_name || teamMember.email}
                  </div>
                  <div className="muted history-meta">
                    {teamMember.email}
                    {" · "}
                    {presenceLabels[teamMember.presence_status]}
                    {" · "}
                    {fmtDuration(
                      nowTs - new Date(teamMember.presence_since).getTime(),
                    )}
                  </div>
                  <div className="team-member-load">
                    <span
                      className={`count-pill ${teamMember.open_tickets >= teamMember.max_active_tickets ? "full" : ""}`}
                    >
                      {teamMember.open_tickets}/{teamMember.max_active_tickets}
                    </span>
                    <span className="muted">активных обращений</span>
                  </div>
                  <div className="modal-title small">Текущие чаты</div>
                  {teamTickets.length ? (
                    teamTickets.map((ticket) => (
                      <button
                        key={ticket.ticket_id}
                        className="past-ticket"
                        onClick={() => void openTeamTicket(ticket.ticket_id)}
                      >
                        <span>
                          #{shortId(ticket.ticket_id)} ·{" "}
                          {statusName[ticket.status]}
                        </span>
                        <span className="muted">
                          {ticket.tags.length
                            ? ticket.tags.join(" · ")
                            : "Без тегов"}
                        </span>
                        <time>{ago(ticket.updated_at)}</time>
                      </button>
                    ))
                  ) : (
                    <div className="past-empty">Активных чатов нет.</div>
                  )}
                </>
              )
            ) : (
              <>
                <div className="modal-title">
                  Команда · статусы и нагрузка
                </div>
                {team.map((member) => (
                  <button
                    key={member.operator_id}
                    className="team-row clickable"
                    onClick={() => void openTeamMember(member)}
                    title="Открыть чаты и нагрузку сотрудника"
                  >
                    <span className="profile-avatar small">
                      {initials(member.display_name || member.email)}
                    </span>
                    <span className="colleague-name">
                      {member.display_name || member.email}
                      <span className="muted">{member.email}</span>
                    </span>
                    <span className="team-presence">
                      <i
                        className={`presence-dot ${member.presence_status.toLowerCase()}`}
                      />
                      {presenceLabels[member.presence_status]}
                      <span className="muted">
                        {fmtDuration(
                          nowTs - new Date(member.presence_since).getTime(),
                        )}
                      </span>
                    </span>
                    <span
                      className={`count-pill ${member.open_tickets >= member.max_active_tickets ? "full" : ""}`}
                      title="Активных обращений из лимита"
                    >
                      {member.open_tickets}/{member.max_active_tickets}
                    </span>
                  </button>
                ))}
              </>
            )}
            <button className="quiet-action" onClick={() => setTeamOpen(false)}>
              Закрыть
            </button>
          </div>
        </div>
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
