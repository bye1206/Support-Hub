import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import "./App.css";
import { AdminPanel } from "./AdminPanel";
import { Composer } from "./Composer";
import { TicketRow } from "./TicketRow";
import { Timeline } from "./Timeline";
import {
  ago,
  initials,
  messageHeading,
  shortId,
  statusName,
  type Ticket,
} from "./workspace-model";
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
  presence_status?: string;
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
  demo?: boolean;
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
type Category = {
  category_id: string;
  name: string;
  parent_id: string | null;
  is_active: boolean;
};
type AssignmentEvent = {
  action: string;
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
type Theme = "light" | "dark";
type AdSearchResult = {
  login: string;
  full_name: string;
  email: string;
  title: string;
  department: string;
  company: string;
  phone: string;
  mobile?: string;
  manager?: string;
  disabled: boolean;
  locked?: boolean;
  groups: string[];
  password_changed_at: string | null;
  password_expires_at: string | null;
  demo?: boolean;
};
type HistorySearchType = "name" | "login" | "email" | "text" | "id";
type HistoryFilters = {
  from: string;
  to: string;
  query: string;
  searchType: HistorySearchType;
  operator: string;
};
const emptyHistoryFilters: HistoryFilters = {
  from: "",
  to: "",
  query: "",
  searchType: "name",
  operator: "",
};
const historySearchLabels: Record<HistorySearchType, string> = {
  name: "По ФИО",
  login: "По логину",
  email: "По email",
  text: "По тексту в сообщении",
  id: "По ID обращения",
};
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
function HistoryCalendar({
  from,
  to,
  onApply,
}: {
  from: string;
  to: string;
  onApply: (from: string, to: string) => void;
}) {
  const initial = from || to || new Date().toISOString().slice(0, 10);
  const [month, setMonth] = useState(() => {
    const [y, m] = initial.split("-").map(Number);
    return new Date(y, (m || 1) - 1, 1);
  });
  // First click anchors the range, second click completes it.
  const [anchor, setAnchor] = useState<string | null>(null);
  const year = month.getFullYear();
  const monthIndex = month.getMonth();
  const offset = (new Date(year, monthIndex, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const monthLabel = month.toLocaleDateString("ru-RU", {
    month: "long",
    year: "numeric",
  });
  const click = (iso: string) => {
    if (!anchor) {
      setAnchor(iso);
      onApply(iso, iso);
      return;
    }
    const [start, end] = anchor <= iso ? [anchor, iso] : [iso, anchor];
    setAnchor(null);
    onApply(start, end);
  };
  return (
    <div className="range-calendar">
      <div className="range-head">
        <button
          type="button"
          aria-label="Предыдущий месяц"
          onClick={() => setMonth(new Date(year, monthIndex - 1, 1))}
        >
          ‹
        </button>
        <strong>{monthLabel}</strong>
        <button
          type="button"
          aria-label="Следующий месяц"
          onClick={() => setMonth(new Date(year, monthIndex + 1, 1))}
        >
          ›
        </button>
      </div>
      <div className="range-grid">
        {WEEKDAYS.map((day) => (
          <span key={day} className="range-dow">
            {day}
          </span>
        ))}
        {Array.from({ length: offset }, (_, index) => (
          <span key={`pad-${index}`} />
        ))}
        {Array.from({ length: daysInMonth }, (_, index) => {
          const day = index + 1;
          const iso = `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
          const classes = ["range-day"];
          if (from && to && iso >= from && iso <= to) classes.push("in-range");
          if (iso === from) classes.push("range-start");
          if (iso === to) classes.push("range-end");
          return (
            <button
              key={iso}
              type="button"
              className={classes.join(" ")}
              onClick={() => click(iso)}
            >
              {day}
            </button>
          );
        })}
      </div>
      <div className="range-hint">
        {from || to
          ? `${from || "…"} — ${to || "…"}`
          : "Выберите первую дату, затем вторую — период подсветится"}
      </div>
    </div>
  );
}
function ThemeIcon({ theme }: { theme: Theme }) {
  return theme === "dark" ? (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.3A8.4 8.4 0 0 1 8.7 3.8 8.5 8.5 0 1 0 20.2 15.3Z" /><path d="M16.5 3.5v4M14.5 5.5h4" /></svg>
  ) : (
    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3 11.3 1.42 1.42" /></svg>
  );
}
const priorityName: Record<string, string> = {
  LOW: "Низкий",
  NORMAL: "Обычный",
  HIGH: "Высокий",
  URGENT: "Срочный",
};
const readCredentials = (): Credentials => {
  try {
    const parsed = JSON.parse(sessionStorage.getItem("support-hub-operator") || "null");
    return typeof parsed?.token === "string" ? { token: parsed.token } : { token: "" };
  } catch {
    return { token: "" };
  }
};
const fmtDuration = (ms: number) => {
  const total = Math.floor(ms / 60000);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return hours > 0 ? `${hours} ч ${minutes} мин` : `${minutes} мин`;
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
    [colleagues, setColleagues] = useState<Colleague[]>([]),
    [team, setTeam] = useState<TeamMember[]>([]),
    [teamOpen, setTeamOpen] = useState(false),
    [teamMember, setTeamMember] = useState<TeamMember | null>(null),
    [teamTickets, setTeamTickets] = useState<Ticket[]>([]),
    [teamTicket, setTeamTicket] = useState<Ticket | null>(null),
    [profileMenuOpen, setProfileMenuOpen] = useState(false),
    [transferOpen, setTransferOpen] = useState(false),
    [transferConfirm, setTransferConfirm] = useState<Colleague | null>(null),
    [movesOpen, setMovesOpen] = useState(false),
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
    [opPhoto, setOpPhoto] = useState<string | null>(null),
    [notes, setNotes] = useState<Note[]>([]),
    [historyPage, setHistoryPage] = useState(false),
    [historyFilters, setHistoryFilters] = useState<HistoryFilters>(emptyHistoryFilters),
    [historyResults, setHistoryResults] = useState<Ticket[]>([]),
    [historyPopover, setHistoryPopover] = useState<
      "date" | "search" | "operator" | null
    >(null),
    [historyPageTicket, setHistoryPageTicket] = useState<Ticket | null>(null),
    [resolveOpen, setResolveOpen] = useState(false),
    [resolveCategoryId, setResolveCategoryId] = useState(""),
    [resolveThemeId, setResolveThemeId] = useState(""),
    [historyLoading, setHistoryLoading] = useState(false),
    [historySearched, setHistorySearched] = useState(false),
    [queueTab, setQueueTab] = useState<"mine" | "queue">("mine"),
    [queueGroup, setQueueGroup] = useState("all"),
    [visibleCount, setVisibleCount] = useState(100),
    [adOpen, setAdOpen] = useState(false),
    [adQuery, setAdQuery] = useState(""),
    [adResults, setAdResults] = useState<AdSearchResult[]>([]),
    [adDetail, setAdDetail] = useState<AdSearchResult | null>(null),
    [adSearching, setAdSearching] = useState(false),
    [adSearched, setAdSearched] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [mobile, setMobile] = useState<"queue" | "conversation" | "details">(
      "queue",
    ),
    [details, setDetails] = useState(true);
  const socket = useRef<WebSocket | null>(null),
    retry = useRef<number>(),
    history = useRef<HTMLDivElement>(null),
    historySearchRef = useRef<HTMLInputElement>(null),
    selectedRef = useRef<string | null>(null),
    adPhotosRef = useRef<Record<string, string>>({});
  // Perf round (2026-11-17): WS event bursts coalesce into one sync.
  const syncInFlight = useRef(false),
    syncQueued = useRef(false),
    syncRef = useRef<() => void>(() => {}),
    syncTimer = useRef(0),
    // Guards the async AD card against overwriting a switched-away ticket.
    adUserRef = useRef<string | null>(null);
  const scheduleSync = useCallback(() => {
    window.clearTimeout(syncTimer.current);
    syncTimer.current = window.setTimeout(() => syncRef.current(), 400);
  }, []);
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
  const loadQueue = useCallback(async () => {
    if (!ready) return;
    try {
      const data = await api<{ tickets: Ticket[] }>("/tickets?limit=200", auth);
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
  }, [auth, ready]);
  const loadAdInfo = async (userId: string) => {
    // Employee card (P-29): graceful degradation - on any failure the
    // details panel shows the plain user block.
    // Perf/UX (2026-11-17): a slow answer for the PREVIOUS ticket must not
    // overwrite the card of the currently selected one.
    try {
      const info = await api<AdInfo>(`/users/${userId}/ad-info`, auth);
      if (adUserRef.current !== userId) return;
      setAdInfo(info);
      if (info.available && info.photo_url && !adPhotosRef.current[userId]) {
        const response = await fetch(info.photo_url, {
          headers: { Authorization: `Bearer ${auth.token}` },
        });
        if (response.ok) {
          const blob = await response.blob();
          adPhotosRef.current[userId] = URL.createObjectURL(blob);
          setAdPhotos({ ...adPhotosRef.current });
        }
      }
    } catch {
      if (adUserRef.current === userId) setAdInfo(null);
    }
  };
  const loadTicket = useCallback(
    async (id: string) => {
      if (!ready) return;
      setLoading(true);
      try {
        const ticket = await api<Ticket>(`/tickets/${id}`, auth);
        adUserRef.current = ticket.user_id;
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
    // Perf (2026-11-17): overlapping syncs (WS bursts + reconnects) used to
    // fire parallel /tickets?limit=200 storms; serialize and coalesce.
    if (syncInFlight.current) {
      syncQueued.current = true;
      return;
    }
    syncInFlight.current = true;
    try {
      await loadQueue();
      if (selectedRef.current) await loadTicket(selectedRef.current);
    } finally {
      syncInFlight.current = false;
      if (syncQueued.current) {
        syncQueued.current = false;
        scheduleSync();
      }
    }
  }, [loadQueue, loadTicket, scheduleSync]);
  useEffect(() => {
    syncRef.current = () => void sync();
  }, [sync]);
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
    // Own AD photo for the session footer avatar (absent -> initials).
    if (!ready) return;
    let active = true;
    void fetch("/api/v1/operator/me/photo", {
      headers: { Authorization: `Bearer ${auth.token}` },
    })
      .then(async (response) => {
        if (!active || !response.ok) return;
        const blob = await response.blob();
        setOpPhoto(URL.createObjectURL(blob));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [auth, ready]);
  useEffect(() => {
    if (!profileMenuOpen) return;
    // Close the profile popover on any click outside of it.
    const onDoc = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        !target.closest(".profile-button") &&
        !target.closest(".profile-menu")
      )
        setProfileMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [profileMenuOpen]);
  useEffect(() => {
    if (!sessionOpen) return;
    // Owner request 2026-11-13: the session-duration popover must close on
    // any click outside of it (same behaviour as the profile menu).
    const onDoc = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && !target.closest(".session-wrap")) setSessionOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [sessionOpen]);
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
      ws.onopen = () => {};
      ws.onmessage = (e) => {
        try {
          const v = JSON.parse(e.data);
          if (v.type !== "ready" && v.type !== "ping") scheduleSync();
        } catch {
          scheduleSync();
        }
      };
      ws.onclose = () => {
        if (!stopped)
          retry.current = window.setTimeout(() => {
            scheduleSync();
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
  // Virtualization-lite (perf round 2026-11-17): render the queue windowed
  // — a full 200-row list is mounted only when the operator actually scrolls.
  useEffect(() => {
    setVisibleCount(100);
  }, [queueTab, queueGroup]);
  const columns = useMemo(() => {
    const active = tickets.filter(
      (t) => t.status !== "RESOLVED" && t.status !== "CLOSED",
    );
    const mine = active.filter((t) => t.assignee_id === operatorId);
    const mineWorking = mine.filter((t) => t.status === "OPEN");
    const mineWaiting = mine.filter((t) => t.status === "PENDING_USER");
    // Owner request 2026-11-13: a ticket assigned to me must never be
    // invisible — while the AI still holds the dialog it shows in its own
    // group instead of vanishing between "В работе" and "Ожидают".
    const mineAI = mine.filter((t) => t.status === "AI_PROCESSING");
    // "Очередь" = everything no operator has taken (any active status) plus
    // the dialogs still being processed by the AI.
    const unassigned = active.filter(
      (t) => !t.assignee_id && t.status !== "AI_PROCESSING",
    );
    const ai = active.filter(
      (t) => t.status === "AI_PROCESSING" && t.assignee_id !== operatorId,
    );
    return {
      mineWorking,
      mineWaiting,
      mineAI,
      mineAll: [...mineWorking, ...mineWaiting, ...mineAI],
      queueUnassigned: unassigned,
      queueAI: ai,
      queueAll: [...unassigned, ...ai],
    };
  }, [tickets, operatorId]);
  const runHistorySearch = async () => {
    setHistoryLoading(true);
    setHistorySearched(true);
    try {
      const q = new URLSearchParams({ limit: "100" });
      if (historyFilters.from) q.set("created_from", `${historyFilters.from}T00:00:00`);
      if (historyFilters.to) q.set("created_to", `${historyFilters.to}T23:59:59.999`);
      const query = historyFilters.query.trim();
      if (query) {
        if (historyFilters.searchType === "text") q.set("text", query);
        else if (historyFilters.searchType === "id") q.set("q", query);
        else q.set("user", query);
      }
      if (historyFilters.operator === "me") q.set("assignee", "me");
      else if (historyFilters.operator === "unassigned") q.set("assignee", "unassigned");
      else if (historyFilters.operator) q.set("assignee", historyFilters.operator);
      const data = await api<{ tickets: Ticket[] }>(`/tickets?${q}`, auth);
      setHistoryResults(data.tickets);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось выполнить поиск");
    } finally {
      setHistoryLoading(false);
    }
  };
  const searchAd = async (query: string) => {
    setAdSearching(true);
    setAdDetail(null);
    setAdSearched(true);
    try {
      const data = await api<{ results: AdSearchResult[] }>(
        `/ad/search?q=${encodeURIComponent(query)}`,
        auth,
      );
      setAdResults(data.results);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Поиск по AD недоступен");
      setAdResults([]);
    } finally {
      setAdSearching(false);
    }
  };
  const openAdDetail = async (login: string) => {
    setAdSearching(true);
    try {
      const card = await api<AdSearchResult>(
        `/ad/user?login=${encodeURIComponent(login)}`,
        auth,
      );
      setAdDetail(card);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть профиль AD");
    } finally {
      setAdSearching(false);
    }
  };
  // Owner request 2026-11-13: an unassigned chat is read-only for operators -
  // nobody may reply until the ticket has an assignee (grayed, composer off).
  const currentUnassigned = current !== null && !current.assignee_id;
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
  const send = useCallback(
    async (mode: "reply" | "note", body: string): Promise<boolean> => {
      if (!current) return false;
      try {
        if (mode === "reply") {
          await api(`/tickets/${current.ticket_id}/replies`, auth, {
            method: "POST",
            body: JSON.stringify({ text: body }),
          });
          setToast("Ответ отправлен в очередь доставки");
        } else {
          await api(`/conversations/${current.conversation_id}/notes`, auth, {
            method: "POST",
            body: JSON.stringify({ body }),
          });
          setToast("Внутренняя заметка сохранена");
        }
        await sync();
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Отправка не удалась");
        return false;
      }
    },
    [current, auth, sync],
  );
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
      if (kind !== "assign") {
        // Owner request 2026-11-13: a resolved/closed chat leaves this
        // workspace — close the dialog, details and queue selection.
        setResolveOpen(false);
        setSelectedId(null);
        setCurrent(null);
      }
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
      setTransferConfirm(null);
      // The chat leaves this workspace: close the dialog, details and queue
      // selection so nothing of it stays open here.
      setSelectedId(null);
      setCurrent(null);
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
  const openHistoryPageTicket = async (ticketId: string) => {
    try {
      const card = await api<Ticket>(`/tickets/${ticketId}`, auth);
      setHistoryPageTicket(card);
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
      // Presence change can release/reroute chats: refresh the queue at once.
      await loadQueue();
      setProfileMenuOpen(false);
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
  const assignmentName = (operatorId: string | null) => {
    if (!operatorId) return "сотрудника";
    const colleague = colleagues.find(
      (item) => item.operator_id === operatorId,
    );
    return colleague?.display_name || colleague?.email || shortId(operatorId);
  };
  return (
    <div
      className={`app-shell ${current ? (details ? "" : "details-collapsed") : "no-ticket"}`}
      data-theme={theme}
    >
      <aside className="rail">
        <div className="brand-mark small">
          s<span>•</span>
        </div>
        <button
          className={`rail-button ${!historyPage && !adminOpen ? "active" : ""}`}
          title="Очередь обращений"
          aria-label="Очередь обращений"
          onClick={() => {
            setHistoryPage(false);
            setAdminOpen(false);
          }}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 13h4l2 3h6l2-3h4" />
            <path d="M5 5h14l2 8v6H3v-6l2-8Z" />
          </svg>
        </button>
        <button
          className={`rail-button ${historyPage ? "active" : ""}`}
          title="История обращений"
          aria-label="История обращений"
          onClick={() => {
            setHistoryPage(true);
            setAdminOpen(false);
            setProfileMenuOpen(false);
          }}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3.5 2" />
          </svg>
        </button>
        <button className="rail-button" disabled title="База знаний (скоро)" aria-label="База знаний">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 19V6a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2Zm0 0a2 2 0 0 0 2 2h13" />
            <path d="M9 8h6M9 11h6" />
          </svg>
        </button>
        {operatorRole !== "OPERATOR" && (
          <button className={`rail-button ${adminOpen ? "active" : ""}`} title="Панель управления" aria-label="Открыть панель управления"           onClick={() => {
            setAdminOpen(true);
            setHistoryPage(false);
            setProfileMenuOpen(false);
          }}>
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
            <h1>Обращения</h1>
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
        <div className="queue-tabs" role="tablist" aria-label="Раздел очереди">
          <button
            role="tab"
            aria-selected={queueTab === "mine"}
            className={queueTab === "mine" ? "active" : ""}
            onClick={() => {
              setQueueTab("mine");
              setQueueGroup("all");
            }}
          >
            Мои обращения
            <span className="tab-count">{columns.mineAll.length}</span>
          </button>
          <button
            role="tab"
            aria-selected={queueTab === "queue"}
            className={queueTab === "queue" ? "active" : ""}
            onClick={() => {
              setQueueTab("queue");
              setQueueGroup("all");
            }}
          >
            Очередь
            <span className="tab-count">{columns.queueAll.length}</span>
          </button>
        </div>
        <div className="queue-tab-content">
          {(() => {
            const groups =
              queueTab === "mine"
                ? [
                    { key: "all", label: "Все обращения", items: columns.mineAll },
                    { key: "working", label: "В работе", items: columns.mineWorking },
                    {
                      key: "waiting",
                      label: "Ожидают пользователя",
                      items: columns.mineWaiting,
                    },
                    {
                      key: "mineAI",
                      label: "У ИИ-помощника",
                      items: columns.mineAI,
                    },
                  ]
                : [
                    { key: "all", label: "Все обращения", items: columns.queueAll },
                    {
                      key: "unassigned",
                      label: "Без назначения",
                      items: columns.queueUnassigned,
                    },
                    { key: "ai", label: "Обработка ИИ", items: columns.queueAI },
                  ];
            const selected =
              groups.find((group) => group.key === queueGroup) ?? groups[0];
            const visible = selected.items.slice(0, visibleCount);
            return (
              <>
                <div className="queue-groups" role="radiogroup" aria-label="Группа обращений">
                  {groups.map((group) => (
                    <button
                      key={group.key}
                      className={`group-chip ${selected.key === group.key ? "active" : ""}`}
                      onClick={() => setQueueGroup(group.key)}
                    >
                      {group.label}
                      <span className="chip-count">{group.items.length}</span>
                    </button>
                  ))}
                </div>
                <div
                  className="ticket-list"
                  onScroll={(e) => {
                    const el = e.currentTarget;
                    if (
                      visible.length < selected.items.length &&
                      el.scrollTop + el.clientHeight >= el.scrollHeight - 240
                    )
                      setVisibleCount((count) => count + 100);
                  }}
                >
                  {visible.map((ticket) => (
                    <TicketRow
                      key={ticket.ticket_id}
                      ticket={ticket}
                      selected={selectedId === ticket.ticket_id}
                      groupLabel={
                        selected.key === "all" ? undefined : selected.label
                      }
                      onSelect={(ticketId) => {
                        setSelectedId(ticketId);
                        setMobile("conversation");
                      }}
                    />
                  ))}
                  {visible.length < selected.items.length && (
                    <div className="queue-more">
                      Показано {visible.length} из {selected.items.length} —
                      прокрутите вниз
                    </div>
                  )}
                  {!selected.items.length && (
                    <div className="empty-queue">
                      <span className="empty-shush">🤫</span>
                      <strong>Здесь пока тихо</strong>
                      <p>Обращений в этой группе нет</p>
                    </div>
                  )}
                </div>
              </>
            );
          })()}
        </div>
        <footer className="queue-footer">
          <button
            className="profile-button"
            title="Статус и выход"
            onClick={() => setProfileMenuOpen((value) => !value)}
          >
            <span className="profile-avatar">
              {opPhoto ? (
                <img className="self-photo" src={opPhoto} alt="" />
              ) : (
                initials(profile?.display_name || profile?.email || "SH")
              )}
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
        className={`conversation-panel ${mobile === "conversation" ? "mobile-visible" : "mobile-hidden"} ${currentUnassigned ? "chat-locked" : ""}`}
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
                {!details && !adminOpen && (
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
                <Timeline
                  entries={timeline}
                  userShortId={shortId(current.user_id)}
                  operatorName={profile?.display_name || "Оператор"}
                />
              )}
            </div>
            <Composer
              key={current.ticket_id}
              disabled={currentUnassigned}
              onSend={send}
            />
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
            <button
              className="icon-button"
              title="Свернуть детали"
              aria-label="Свернуть детали"
              onClick={() => setDetails(false)}
            >
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
                  {adInfo.demo && <div className="ad-demo-note">Демо-данные: AD не подключён</div>}
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
                  {(adInfo.disabled || adInfo.locked) && (
                    <div className="ad-warning">
                      Учётная запись {adInfo.disabled ? "отключена" : "заблокирована"} в
                      AD
                    </div>
                  )}
                  <button
                    className="ad-full-button"
                    onClick={() => {
                      setAdOpen(true);
                      setAdDetail(null);
                      setAdResults([]);
                      setAdSearched(false);
                      const initial =
                        adInfo.login ||
                        (adInfo.email || "").split("@")[0] ||
                        (adInfo.full_name || "").split(" ")[0] ||
                        "";
                      setAdQuery(initial);
                      if (initial) void searchAd(initial);
                    }}
                  >
                    Полная информация
                  </button>
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
              <div className="detail-label spaced">SLA</div>
              <div className="sla-card">
                <span className="sla-clock">◷</span>
                <div>
                  <strong>
                    Открыто{" "}
                    {new Intl.DateTimeFormat("ru-RU", {
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    }).format(new Date(current.created_at))}
                  </strong>
                  <span>
                    В работе{" "}
                    {fmtDuration(Date.now() - new Date(current.created_at).getTime())}
                  </span>
                </div>
                <span className="sla-placeholder">SLA · этап 10</span>
              </div>
            </section>
            <section className="detail-section">
              <div className="detail-label">ПЕРЕМЕЩЕНИЯ</div>
              <div className="assignment-history">
                <span className="history-line" />
                {assignmentHistory.length ? (
                  assignmentHistory.slice(0, 3).map((event) => (
                    <div
                      className="history-event"
                      key={`${event.created_at}-${event.actor_id}`}
                    >
                      {event.action === "handoff.accepted"
                        ? "Принято у ИИ"
                        : event.action === "ticket.assignment_queued"
                          ? `Отложено: ожидает места у ${
                              assignmentName(event.assignee_id)
                            }`
                          : event.assignee_id
                            ? `Назначено оператору ${shortId(event.assignee_id)}`
                            : "Снято назначение"}
                      <time>{ago(event.created_at)}</time>
                    </div>
                  ))
                ) : (
                  <div className="history-event">
                    {current.assignee_id
                      ? `Назначено оператору ${shortId(current.assignee_id)}`
                      : "Перемещений пока не было"}
                  </div>
                )}
              </div>
              <button className="quiet-action" onClick={() => setMovesOpen(true)}>
                  Посмотреть полностью
                </button>
            </section>
            <section className="detail-section">
              <div className="detail-label">ТЕГИ</div>
              <div className="tag-list">
                {ticketTags.map((tag) => (
                  <span className="tag" key={tag.tag_id}>
                    {tag.name}
                  </span>
                ))}
              </div>
            </section>
            <section className="detail-section action-section">
              <button
                onClick={() => {
                  setResolveCategoryId("");
                  setResolveThemeId("");
                  setResolveOpen(true);
                }}
                disabled={
                  !current.assignee_id ||
                  current.status === "RESOLVED" ||
                  current.status === "CLOSED"
                }
                title={
                  !current.assignee_id
                    ? "Сначала назначьте оператора"
                    : "Обращение будет завершено; повторное сообщение пользователя создаст новое обращение"
                }
              >
                ✓ Решить обращение
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
          onRoleChange={(role) => {
            setOperatorRole(role);
            if (role === "OPERATOR") setAdminOpen(false);
          }}
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
            {(() => {
              const reachable = colleagues.filter(
                (colleague) => (colleague.presence_status ?? "ACTIVE") === "ACTIVE",
              );
              return reachable.length ? (
                reachable.map((colleague) => (
                  <button
                    key={colleague.operator_id}
                    className="colleague-row"
                    onClick={() => setTransferConfirm(colleague)}
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
              );
            })()}
            <button className="quiet-action" onClick={() => setTransferOpen(false)}>
              Закрыть
            </button>
          </div>
        </div>
      )}
      {transferConfirm && current && (
        <div
          className="modal-backdrop"
          onClick={() => setTransferConfirm(null)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-label="Подтверждение передачи"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">Передать обращение?</div>
            <p className="admin-muted" style={{ margin: 0 }}>
              Обращение #{shortId(current.ticket_id)} уйдёт сотруднику{" "}
              <strong>{transferConfirm.display_name || transferConfirm.email}</strong>.
              Чат закроется в вашем рабочем месте, и пользователь получит
              уведомление о назначении.
            </p>
            <button
              className="resolve-submit"
              onClick={() => void transferToPerson(transferConfirm.operator_id)}
            >
              Да, передать
            </button>
            <button className="quiet-action" onClick={() => setTransferConfirm(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
      {movesOpen && current && (
        <div
          className="modal-backdrop"
          onClick={() => setMovesOpen(false)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-label="Все перемещения обращения"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              Перемещения · #{shortId(current.ticket_id)}
            </div>
            <div className="moves-list">
              {assignmentHistory.map((event) => (
                <div
                  className="history-event"
                  key={`${event.created_at}-${event.actor_id}`}
                >
                  {event.action === "handoff.accepted"
                    ? "Принято у ИИ"
                    : event.action === "ticket.assignment_queued"
                      ? `Отложено: ожидает места у ${
                          assignmentName(event.assignee_id)
                        }`
                      : event.assignee_id
                        ? `Назначено оператору ${shortId(event.assignee_id)}`
                        : "Снято назначение"}
                  <time>
                    {new Date(event.created_at).toLocaleString("ru-RU")}
                  </time>
                </div>
              ))}
              {!assignmentHistory.length && (
                <div className="past-empty">Перемещений пока не было.</div>
              )}
            </div>
            <button className="quiet-action" onClick={() => setMovesOpen(false)}>
              Закрыть
            </button>
          </div>
        </div>
      )}
      {resolveOpen && current && (
        <div
          className="modal-backdrop"
          onClick={() => setResolveOpen(false)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-label="Решить обращение"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              Решить обращение · #{shortId(current.ticket_id)}
            </div>
            <label className="resolve-label" htmlFor="resolve-category">
              Категория обращения
              <select
                id="resolve-category"
                value={resolveCategoryId}
                onChange={(e) => {
                  setResolveCategoryId(e.target.value);
                  setResolveThemeId("");
                }}
              >
                <option value="">Выберите категорию</option>
                {categories
                  .filter((c) => c.is_active && !c.parent_id)
                  .map((category) => (
                    <option key={category.category_id} value={category.category_id}>
                      {category.name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="resolve-label" htmlFor="resolve-theme">
              Тема обращения
              <select
                id="resolve-theme"
                value={resolveThemeId}
                disabled={!resolveCategoryId}
                onChange={(e) => setResolveThemeId(e.target.value)}
              >
                <option value="">Без темы</option>
                {categories
                  .filter(
                    (c) =>
                      c.is_active && c.parent_id === resolveCategoryId,
                  )
                  .map((theme) => (
                    <option key={theme.category_id} value={theme.category_id}>
                      {theme.name}
                    </option>
                  ))}
              </select>
            </label>
            <button
              className="resolve-submit"
              disabled={!resolveCategoryId}
              onClick={() => {
                void (async () => {
                  try {
                    await updateCategory(resolveThemeId || resolveCategoryId);
                    await action("resolve");
                    setResolveOpen(false);
                  } catch (e) {
                    setError(
                      e instanceof Error ? e.message : "Не удалось решить обращение",
                    );
                  }
                })();
              }}
            >
              ✓ Решить
            </button>
            <button
              className="quiet-action"
              onClick={() => setResolveOpen(false)}
            >
              Отмена
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
                        <div className="message-heading">
                          <strong>
                            {messageHeading(message.author_type)}
                          </strong>
                          <time>
                            {new Date(message.created_at).toLocaleString(
                              "ru-RU",
                              { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" },
                            )}
                          </time>
                        </div>
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
                          <div className="message-heading">
                            <strong>
                              {messageHeading(message.author_type)}
                            </strong>
                            <time>
                              {new Date(message.created_at).toLocaleString(
                                "ru-RU",
                                { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" },
                              )}
                            </time>
                          </div>
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
      {adOpen && (
        <div
          className="modal-backdrop"
          onClick={() => {
            setAdOpen(false);
            setAdDetail(null);
          }}
          role="presentation"
        >
          <div
            className="modal wide"
            role="dialog"
            aria-label="Поиск по AD"
            onClick={(e) => e.stopPropagation()}
          >
            {adDetail ? (
              <>
                <button className="quiet-action" onClick={() => setAdDetail(null)}>
                  ← К результатам поиска
                </button>
                <div className="modal-title">
                  {adDetail.full_name || adDetail.login}
                </div>
                <div className="muted history-meta">
                  {[adDetail.title, adDetail.department, adDetail.company]
                    .filter(Boolean)
                    .join(" · ") || "Сотрудник"}
                  {adDetail.disabled || adDetail.locked
                    ? ` · учётная запись ${adDetail.disabled ? "отключена" : "заблокирована"}`
                    : ""}
                </div>
                <div className="ad-rows dialog-rows">
                  {adDetail.login && (
                    <div>
                      <span>Логин</span>
                      {adDetail.login}
                    </div>
                  )}
                  {adDetail.email && (
                    <div>
                      <span>Почта</span>
                      {adDetail.email}
                    </div>
                  )}
                  {adDetail.phone && (
                    <div>
                      <span>Тел.</span>
                      {adDetail.phone}
                    </div>
                  )}
                  {adDetail.mobile && (
                    <div>
                      <span>Моб.</span>
                      {adDetail.mobile}
                    </div>
                  )}
                  {adDetail.manager && (
                    <div>
                      <span>Руководитель</span>
                      {adDetail.manager}
                    </div>
                  )}
                  {adDetail.password_changed_at && (
                    <div>
                      <span>Пароль изменён</span>
                      {new Date(adDetail.password_changed_at).toLocaleDateString("ru-RU")}
                    </div>
                  )}
                  {adDetail.password_expires_at &&
                    new Date(adDetail.password_expires_at).getTime() > Date.now() && (
                      <div>
                        <span>Пароль истекает</span>
                        {Math.ceil(
                          (new Date(adDetail.password_expires_at).getTime() -
                            Date.now()) /
                            86400000,
                        )}{" "}
                        дн.
                      </div>
                    )}
                </div>
                <div className="modal-title small">Группы AD ({adDetail.groups.length})</div>
                {adDetail.groups.length ? (
                  <div className="tag-list dialog-groups">
                    {adDetail.groups.map((group) => (
                      <span className="tag" key={group} title={group}>
                        {group}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="past-empty">Группы не найдены.</div>
                )}
              </>
            ) : (
              <>
                <div className="modal-title">Поиск по AD</div>
                <form
                  className="ad-search-row"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (adQuery.trim()) void searchAd(adQuery.trim());
                  }}
                >
                  <input
                    autoFocus
                    placeholder="Логин, ФИО или e-mail"
                    value={adQuery}
                    onChange={(e) => setAdQuery(e.target.value)}
                  />
                  <button type="submit" disabled={adSearching || !adQuery.trim()}>
                    Найти
                  </button>
                </form>
                {adSearching && <div className="past-empty">Поиск…</div>}
                {!adSearching && !adResults.length && adSearched && (
                  <div className="past-empty">
                    Ничего не найдено. Введите логин, фамилию или e-mail.
                  </div>
                )}
                {adResults.map((result) => (
                  <button
                    key={result.login}
                    className="past-ticket"
                    onClick={() => void openAdDetail(result.login)}
                  >
                    <span>
                      {result.full_name || result.login}
                      {result.disabled ? " · отключён" : ""}
                      {result.demo ? " · демо" : ""}
                    </span>
                    <span className="muted">
                      {[result.login, result.department].filter(Boolean).join(" · ")}
                    </span>
                    <time>{result.title || "—"}</time>
                  </button>
                ))}
              </>
            )}
          </div>
        </div>
      )}
      {historyPage && (
        <div className="history-page" role="region" aria-label="История обращений">
          <header className="history-page-header">
            <div>
              <p className="eyebrow">SUPPORT HUB</p>
              <h1>История обращений</h1>
            </div>
          </header>
          <div className="history-tools">
            <div className="history-tool">
              <button
                type="button"
                className={`icon-button ${historyPopover === "date" ? "active-icon" : ""}`}
                title="Период дат"
                aria-label="Период дат"
                onClick={() =>
                  setHistoryPopover(historyPopover === "date" ? null : "date")
                }
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
                  <path d="M3.5 9.5h17M8 3v4m8-4v4" />
                </svg>
                {(historyFilters.from || historyFilters.to) && (
                  <i className="tool-dot" />
                )}
              </button>
              {historyPopover === "date" && (
                <div className="history-popover date-popover">
                  <HistoryCalendar
                    from={historyFilters.from}
                    to={historyFilters.to}
                    onApply={(from, to) => {
                      setHistoryFilters((f) => ({ ...f, from, to }));
                    }}
                  />
                  <button
                    type="button"
                    className="quiet-action"
                    onClick={() => setHistoryPopover(null)}
                  >
                    Готово
                  </button>
                </div>
              )}
            </div>
              <div
                className={`history-inline-search ${historyPopover === "search" ? "open" : ""}`}
              >
                <select
                  aria-label="Тип поиска"
                  tabIndex={historyPopover === "search" ? 0 : -1}
                  value={historyFilters.searchType}
                  onChange={(e) =>
                    setHistoryFilters({
                      ...historyFilters,
                      searchType: e.target.value as HistorySearchType,
                    })
                  }
                >
                  {(Object.keys(historySearchLabels) as HistorySearchType[]).map(
                    (type) => (
                      <option key={type} value={type}>
                        {historySearchLabels[type]}
                      </option>
                    ),
                  )}
                </select>
                <input
                  ref={historySearchRef}
                  tabIndex={historyPopover === "search" ? 0 : -1}
                  placeholder={
                    historyFilters.searchType === "name"
                      ? "Фамилия или имя"
                      : historyFilters.searchType === "login"
                        ? "логин"
                        : historyFilters.searchType === "email"
                          ? "email"
                          : historyFilters.searchType === "text"
                            ? "текст из сообщения"
                            : "первые символы ID"
                  }
                  value={historyFilters.query}
                  onChange={(e) =>
                    setHistoryFilters({ ...historyFilters, query: e.target.value })
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void runHistorySearch();
                  }}
                />
              </div>
              <div className="history-tool">
                <button
                  type="button"
                  className={`icon-button ${historyPopover === "search" ? "active-icon" : ""}`}
                  title="Поиск"
                  aria-label="Поиск"
                  onClick={() => {
                    const opening = historyPopover !== "search";
                    setHistoryPopover(opening ? "search" : null);
                    if (opening) {
                      requestAnimationFrame(() =>
                        requestAnimationFrame(() => historySearchRef.current?.focus()),
                      );
                    }
                  }}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="11" cy="11" r="6.5" />
                    <path d="m16 16 4.5 4.5" />
                  </svg>
                  {historyFilters.query.trim() && <i className="tool-dot" />}
                </button>
              </div>
              <div className="history-tool">
                <button
                  type="button"
                  className={`icon-button ${historyPopover === "operator" ? "active-icon" : ""}`}
                  title="Оператор"
                  aria-label="Оператор"
                  onClick={() =>
                    setHistoryPopover(
                      historyPopover === "operator" ? null : "operator",
                    )
                  }
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="12" cy="8" r="3.5" />
                    <path d="M5 19.5c.8-3.6 3.5-5.5 7-5.5s6.2 1.9 7 5.5" />
                  </svg>
                  {historyFilters.operator && <i className="tool-dot" />}
                </button>
                {historyPopover === "operator" && (
                  <div className="history-popover">
                    <label>
                      Оператор
                      <select
                        value={historyFilters.operator}
                        onChange={(e) =>
                          setHistoryFilters({
                            ...historyFilters,
                            operator: e.target.value,
                          })
                        }
                      >
                        <option value="">Все</option>
                        <option value="me">Только мои</option>
                        <option value="unassigned">Без назначения</option>
                        {colleagues.map((colleague) => (
                          <option
                            key={colleague.operator_id}
                            value={colleague.operator_id}
                          >
                            {colleague.display_name || colleague.email}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="quiet-action"
                      onClick={() => setHistoryPopover(null)}
                    >
                      Готово
                    </button>
                  </div>
                )}
              </div>
              <button
                type="button"
                className="history-find"
                disabled={historyLoading}
                onClick={() => void runHistorySearch()}
              >
                Найти
              </button>
              <button
                type="button"
                className="quiet-action"
                onClick={() => {
                  setHistoryFilters(emptyHistoryFilters);
                  setHistoryResults([]);
                  setHistorySearched(false);
                  setHistoryPageTicket(null);
                }}
              >
                Сбросить
              </button>
          </div>
          {historyPageTicket ? (
            <div className="history-detail">
              <div className="history-detail-chat">
                <button
                  className="quiet-action"
                  onClick={() => setHistoryPageTicket(null)}
                >
                  ← К результатам
                </button>
                <div className="modal-title">
                  #{shortId(historyPageTicket.ticket_id)} ·{" "}
                  {statusName[historyPageTicket.status]}
                </div>
                <div className="history-messages">
                  {(historyPageTicket.messages ?? []).map((message) => (
                    <div
                      key={message.message_id}
                      className={`message ${message.author_type === "OPERATOR" ? "from-operator" : ""}`}
                    >
                      <div className="message-content">
                        <div className="message-heading">
                          <strong>{messageHeading(message.author_type)}</strong>
                          <time>
                            {new Date(message.created_at).toLocaleString("ru-RU", {
                              day: "numeric",
                              month: "short",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </time>
                        </div>
                        <div className="message-bubble">{message.text}</div>
                      </div>
                    </div>
                  ))}
                  {!(historyPageTicket.messages ?? []).length && (
                    <div className="past-empty">Сообщений нет.</div>
                  )}
                </div>
              </div>
              <aside className="history-detail-info">
                <div className="detail-label">СТАТУС</div>
                <div className="detail-value">
                  <span
                    className={`status-dot ${historyPageTicket.status.toLowerCase()}`}
                  />
                  {statusName[historyPageTicket.status]}
                </div>
                <div className="detail-label spaced">ПРИОРИТЕТ</div>
                <div className="detail-value">
                  {priorityName[historyPageTicket.priority.toUpperCase()] ||
                    historyPageTicket.priority}
                </div>
                <div className="detail-label spaced">ПОЛЬЗОВАТЕЛЬ</div>
                <div className="detail-value">
                  {shortId(historyPageTicket.user_id)}
                </div>
                <div className="detail-label spaced">ОПЕРАТОР</div>
                <div className="detail-value">
                  {historyPageTicket.assignee_id
                    ? historyPageTicket.assignee_id === operatorId
                      ? "Я"
                      : shortId(historyPageTicket.assignee_id)
                    : "—"}
                </div>
                <div className="detail-label spaced">СОЗДАНО</div>
                <div className="detail-value">
                  {new Date(historyPageTicket.created_at).toLocaleString("ru-RU")}
                </div>
                <div className="detail-label spaced">ОБНОВЛЕНО</div>
                <div className="detail-value">
                  {new Date(historyPageTicket.updated_at).toLocaleString("ru-RU")}
                </div>
                {historyPageTicket.tags.length > 0 && (
                  <>
                    <div className="detail-label spaced">ТЕГИ</div>
                    <div className="tag-list">
                      {historyPageTicket.tags.map((tag) => (
                        <span className="tag" key={tag}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </aside>
            </div>
          ) : (
            <div className="history-table-wrap">
              {historyLoading && <div className="past-empty">Поиск…</div>}
              {!historyLoading && !historyResults.length && historySearched && (
                <div className="past-empty">Ничего не найдено по заданным фильтрам.</div>
              )}
              {!historyLoading && !historySearched && (
                <div className="past-empty">
                  Задайте период, поиск и оператора через иконки сверху и нажмите
                  «Найти».
                </div>
              )}
              {historyResults.length > 0 && (
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Статус</th>
                      <th>Приоритет</th>
                      <th>Пользователь</th>
                      <th>Оператор</th>
                      <th>Создано</th>
                      <th>Обновлено</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyResults.map((ticket) => (
                      <tr
                        key={ticket.ticket_id}
                        onClick={() => void openHistoryPageTicket(ticket.ticket_id)}
                      >
                        <td>#{shortId(ticket.ticket_id)}</td>
                        <td>{statusName[ticket.status]}</td>
                        <td>
                          {priorityName[ticket.priority.toUpperCase()] || ticket.priority}
                        </td>
                        <td>{shortId(ticket.user_id)}</td>
                        <td>
                          {ticket.assignee_id
                            ? ticket.assignee_id === operatorId
                              ? "Я"
                              : shortId(ticket.assignee_id)
                            : "—"}
                        </td>
                        <td>{new Date(ticket.created_at).toLocaleString("ru-RU")}</td>
                        <td>{new Date(ticket.updated_at).toLocaleString("ru-RU")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
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
