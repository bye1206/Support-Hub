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
import { HistoryMessages, Timeline } from "./Timeline";
import {
  ago,
  initials,
  shortFio,
  shortId,
  statusName,
  type MessageAttachmentInfo,
  type SlaHistoryEvent,
  type Ticket,
} from "./workspace-model";
type Note = {
  note_id: string;
  conversation_id: string;
  author_id: string;
  author_name?: string | null;
  body: string;
  created_at: string;
};

// Owner (2026-11-19): the status card carries a one-line human hint so the
// state of the dialog is obvious without decoding the status name.

// Owner (2026-11-19): per-status durations for the SLA modal — computed
// from the transition history; the last interval is open while the ticket
// is not terminal.
const slaDurationRows = (events: SlaHistoryEvent[], currentStatus: string) => {
  const statusEvents = events
    .filter((event) => event.kind === "status")
    .sort(
      (a, b) =>
        new Date(a.changed_at).getTime() - new Date(b.changed_at).getTime(),
    );
  const durations = new Map<string, number>();
  const push = (status: string, from: number, to: number) => {
    if (to <= from) return;
    durations.set(status, (durations.get(status) ?? 0) + (to - from));
  };
  statusEvents.forEach((event, index) => {
    const from = new Date(event.changed_at).getTime();
    const next = statusEvents[index + 1];
    const to = next
      ? new Date(next.changed_at).getTime()
      : ["RESOLVED", "CLOSED"].includes(event.to_status ?? "")
        ? from
        : Date.now();
    push(event.to_status ?? "", from, to);
  });
  if (!statusEvents.length && currentStatus) {
    // A ticket may have no transitions yet (NEW): count from creation —
    // not available here, so show zero state via empty rows list.
    return [];
  }
  return [...durations.entries()]
    .map(([status, ms]) => ({ status, duration: fmtDuration(ms) }))
    .sort((a, b) => b.duration.localeCompare(a.duration));
};

// Owner (2026-11-19): shared download for read-only history lists — the
// auth header is required, so the blob is fetched here.
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
  groups?: AdGroup[];
  photo_url?: string;
  synced_at?: string | null;
  demo?: boolean;
  // Owner (2026-11-20): why a manual refresh produced nothing — the button
  // used to report success even when AD returned no card.
  refresh_error?: "not_configured" | "no_identity" | "not_found" | "unavailable";
};

const adRefreshErrors: Record<string, string> = {
  not_configured: "AD не подключён: нет сервисной учётки",
  no_identity: "Нет логина для поиска в AD",
  not_found: "Не найден в AD — проверьте логин в Тэге",
  unavailable: "AD недоступен, попробуйте позже",
};
type TeamMember = {
  operator_id: string;
  display_name: string | null;
  email: string;
  presence_status: "ACTIVE" | "LUNCH" | "BREAK" | "OFFLINE";
  presence_since: string;
  open_tickets: number;
  max_active_tickets: number;
  // Owner (2026-11-20): the golden-crown rating next to the profile.
  avg_rating?: number | null;
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
  actor_name?: string | null;
  assignee_id: string | null;
  assignee_name?: string | null;
  // Owner (2026-11-25): specialist invite/leave events.
  specialist_name?: string | null;
  created_at: string;
};
// Shared move renderer: the details panel (3 last), the full moves modal
// and the history page all speak the same wording.
const moveText = (event: AssignmentEvent, fallbackName: (id: string) => string) => {
  if (event.action === "specialist.invited")
    return `${event.actor_name || "Оператор"} пригласил ${
      event.specialist_name || "коллегу"
    } специалистом`;
  if (event.action === "specialist.left")
    return `${event.specialist_name || event.actor_name || "Специалист"} покинул чат`;
  if (event.action === "handoff.accepted") return "Принято у ИИ";
  if (event.action === "ticket.assignment_queued")
    return `Отложено: ожидает места у ${
      event.assignee_name || fallbackName(event.assignee_id || "")
    }`;
  if (event.assignee_id)
    return `Назначено оператору ${
      event.assignee_name || fallbackName(event.assignee_id)
    }`;
  return "Снято назначение";
};
type TicketTag = { tag_id: string; name: string };
type OperatorProfile = {
  operator_id: string;
  email: string;
  display_name: string;
  role: string;
  // Owner (2026-11-20): the golden-crown rating in the footer.
  avg_rating?: number | null;
};
type Theme = "light" | "dark";
// Owner (2026-11-20): the average rating badge; above 4.7 a golden crown
// appears over the number.
function RatingBadge({ value }: { value?: number | null }) {
  if (value == null) return null;
  const gold = value > 4.7;
  return (
    <span className="rating-badge" title="Средняя оценка">
      {gold && (
        // Owner (2026-11-26): curls sweep toward the digits so the badge
        // reads as one ornamental golden emblem.
        <svg className="rating-flourish" viewBox="0 0 18 14" aria-hidden="true">
          <path
            d="M16.5 7c-2.6-5.4-8.2-5.8-10-1.6C5.2 8.5 7.6 10.6 9.6 9.4"
            fill="none"
            stroke="#d9a514"
            strokeWidth="1.7"
            strokeLinecap="round"
          />
          <circle cx="11" cy="8.6" r="1.15" fill="#d9a514" />
        </svg>
      )}
      <span className={gold ? "rating-value gold" : "rating-value"}>{value}</span>
      {gold && (
        <svg
          className="rating-flourish flip"
          viewBox="0 0 18 14"
          aria-hidden="true"
        >
          <path
            d="M16.5 7c-2.6-5.4-8.2-5.8-10-1.6C5.2 8.5 7.6 10.6 9.6 9.4"
            fill="none"
            stroke="#d9a514"
            strokeWidth="1.7"
            strokeLinecap="round"
          />
          <circle cx="11" cy="8.6" r="1.15" fill="#d9a514" />
        </svg>
      )}
    </span>
  );
}
type AdGroup = { name: string; description?: string };
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
  groups: AdGroup[];
  password_changed_at: string | null;
  password_expires_at: string | null;
  demo?: boolean;
  photo?: string;
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
// Owner (2026-11-17): audible ping for incoming user messages — WebAudio,
// no binary asset needed.
// Owner (2026-11-18): softer two-note "ding" (G5 -> C6, triangle) instead of
// the shrill sines — pleasant for frequent use, still noticeable.
const playPing = () => {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const play = (freq: number, at: number, dur: number, vol: number) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, at);
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(vol, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(at);
      osc.stop(at + dur + 0.05);
      osc.onended = () => void ctx.close();
    };
    const t0 = ctx.currentTime;
    play(784, t0, 0.35, 0.05);
    play(1046.5, t0 + 0.11, 0.5, 0.04);
  } catch {
    // sound is a nicety, never a failure
  }
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
type KbArticle = {
  article_id: string;
  title: string;
  body: string;
  updated_at: string;
  is_active?: boolean;
  created_by?: string | null;
  created_at?: string;
  updated_by?: string | null;
  deleted_by?: string | null;
  deleted_at?: string | null;
};
type KbHistoryEvent = {
  action: string;
  actor_name: string | null;
  created_at: string;
};

async function adminApi<T>(
  path: string,
  auth: Credentials,
  init?: RequestInit,
): Promise<T> {
  // Owner (2026-11-25): the knowledge base moved out of the admin panel
  // into the workspace rail — every operator manages it here, so the
  // workspace needs the admin endpoints too (they accept operator
  // tokens; write access is enforced server-side).
  const response = await fetch(`/api/v1/admin${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${auth.token}`,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    if (response.status === 401) {
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

async function api<T>(
  path: string,
  auth: Credentials,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api/v1/operator${path}`, {
    ...init,
    headers: {
      // FormData sets its own multipart boundary — never pre-set JSON.
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
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
    // Owner (2026-11-19): the SLA modal — status history + per-status
    // durations, opened by clicking the SLA card.
    // Owner (2026-11-19): the SLA modal works for any ticket (history too).
    [slaTicket, setSlaTicket] = useState<Ticket | null>(null),
    [slaEvents, setSlaEvents] = useState<SlaHistoryEvent[]>([]),
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
    // Owner (2026-11-19): moves for the history page details aside.
    [historyMoves, setHistoryMoves] = useState<AssignmentEvent[]>([]),
    [historyMovesExpanded, setHistoryMovesExpanded] = useState(false),
    [previousTickets, setPreviousTickets] = useState<Ticket[]>([]),
    [ticketTags, setTicketTags] = useState<TicketTag[]>([]),
    [adInfo, setAdInfo] = useState<AdInfo | null>(null),
    // Owner (2026-11-18): until the AD card for the CURRENT ticket arrives,
    // the header shows a skeleton instead of flashing the short queue name.
    [adInfoReadyFor, setAdInfoReadyFor] = useState<string | null>(null),
    // Owner (2026-11-18): while a freshly selected ticket is loading, the
    // details panel shows "Загрузка…" instead of the PREVIOUS ticket's data.
    [detailsStale, setDetailsStale] = useState(false),
    [adPhotos, setAdPhotos] = useState<Record<string, string>>({}),
    // Owner report (2026-11-20): when AD keeps no photo the avatar falls
    // back to the Tag profile image.
    [tagAvatars, setTagAvatars] = useState<Record<string, string>>({}),
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
    // Owner (2026-11-19): files dropped anywhere on the dialog window are
    // forwarded to the composer via this queue.
    [droppedFiles, setDroppedFiles] = useState<File[]>([]),
    // Owner (2026-11-23, plan item 8): knowledge base articles for hints.
    [kbArticles, setKbArticles] = useState<KbArticle[]>([]),
    // Owner (2026-11-25): the KB library lives in the workspace rail —
    // search, add, edit, delete, restore (out of the admin panel).
    [kbLibraryOpen, setKbLibraryOpen] = useState(false),
    [kbQuery, setKbQuery] = useState(""),
    [kbNewTitle, setKbNewTitle] = useState(""),
    [kbNewBody, setKbNewBody] = useState(""),
    [kbEditing, setKbEditing] = useState<KbArticle | null>(null),
    // Owner (2026-11-26): OneNote-style two-pane KB — the sidebar lists
    // pages, the pane shows/edits the selected one.
    [kbSelectedId, setKbSelectedId] = useState<string | null>(null),
    [kbCreating, setKbCreating] = useState(false),
    [kbArchive, setKbArchive] = useState<KbArticle[]>([]),
    // Owner (2026-11-26): the per-article history modal (audit log).
    [kbHistoryFor, setKbHistoryFor] = useState<KbArticle | null>(null),
    [kbHistory, setKbHistory] = useState<KbHistoryEvent[]>([]),
    [dragOverConversation, setDragOverConversation] = useState(false),
    [resolveCategoryId, setResolveCategoryId] = useState(""),
    [resolveThemeId, setResolveThemeId] = useState(""),
    [historyLoading, setHistoryLoading] = useState(false),
    [historySearched, setHistorySearched] = useState(false),
    [queueTab, setQueueTab] = useState<"mine" | "queue">("mine"),
    [queueGroup, setQueueGroup] = useState("all"),
    [visibleCount, setVisibleCount] = useState(100),
    [adOpen, setAdOpen] = useState(false),
    [adDetail, setAdDetail] = useState<AdSearchResult | null>(null),
    [adSearching, setAdSearching] = useState(false),
    [adRefreshing, setAdRefreshing] = useState(false),
    [adGroupQuery, setAdGroupQuery] = useState(""),
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
    adPhotosRef = useRef<Record<string, string>>({}),
    tagAvatarsRef = useRef<Record<string, string>>({});
  // Perf round (2026-11-17): WS event bursts coalesce into one sync.
  const syncInFlight = useRef(false),
    syncQueued = useRef(false),
    syncRef = useRef<() => void>(() => {}),
    syncTimer = useRef(0),
    // Guards the async AD card against overwriting a switched-away ticket.
    adUserRef = useRef<string | null>(null),
    adInfoReadyRef = useRef<string | null>(null),
    detailsTicketRef = useRef<string | null>(null),
    // Mirror of the queue for WS handlers (toasts need ticket names).
    ticketsRef = useRef<Ticket[]>([]),
    // Owner (2026-11-18): the queue view hides chats that got assigned to
    // someone else (AI handoff, auto-route, another operator's claim) —
    // the open dialog must close in that case too.
    operatorIdRef = useRef<string | null>(null),
    // History scroll behavior (owner 2026-11-17): keep the viewport pinned
    // to the bottom while reading the tail; never reset it mid-read.
    currentIdRef = useRef<string | null>(null),
    stickToBottom = useRef(true);
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
  // Owner report (2026-11-23): a colleague who just went ACTIVE appeared in
  // the team/transfer lists up to 30 s later (team polled every 30 s,
  // colleagues only on page load). Both lists now ride one 5 s poll with an
  // overlap guard; hidden tabs skip the roundtrip.
  useEffect(() => {
    if (!ready) return;
    let inFlight = false;
    const load = () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      void Promise.all([
        api<{ team: TeamMember[] }>("/team", auth)
          .then((data) => setTeam(data.team ?? []))
          .catch(() => {}),
        api<{ colleagues: Colleague[] }>("/colleagues", auth)
          .then((data) => setColleagues(data.colleagues ?? []))
          .catch(() => {}),
      ]).finally(() => {
        inFlight = false;
      });
    };
    load();
    const id = window.setInterval(load, 5000);
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
    currentIdRef.current = current?.ticket_id ?? null;
  }, [current]);
  useEffect(() => {
    operatorIdRef.current = operatorId;
  }, [operatorId]);
  const loadQueue = useCallback(async () => {
    if (!ready) return;
    try {
      const data = await api<{ tickets: Ticket[] }>("/tickets?limit=200", auth);
      ticketsRef.current = data.tickets;
      setTickets(data.tickets);
      setError("");
      // Owner (2026-11-23, plan item 8): knowledge base for the composer
      // hints — a nicety, never a failure.
      void api<{ articles: KbArticle[] }>("/kb", auth)
        // Owner (2026-11-26): a stub/odd response without `articles` used to
        // setKbArticles(undefined) and crash the whole render.
        .then((kb) => setKbArticles(kb.articles ?? []))
        .catch(() => undefined);
      const selected = selectedRef.current
        ? data.tickets.find((t) => t.ticket_id === selectedRef.current)
        : null;
      if (selectedRef.current && !selected) {
        // Owner (2026-11-18): when the chat leaves the queue (e.g. the
        // operator went on lunch), the open dialog and the details panel
        // must close too. Clear the ref synchronously, otherwise the
        // trailing sync() reloads the released ticket and re-opens it.
        selectedRef.current = null;
        setSelectedId(null);
        setCurrent(null);
        setNotes([]);
      } else if (
        selected &&
        selected.assignee_id &&
        operatorIdRef.current &&
        selected.assignee_id !== operatorIdRef.current &&
        // Owner (2026-11-25): an invited specialist KEEPS the dialog open —
        // the assignee is someone else on purpose, that is not a steal.
        !selected.is_specialist
      ) {
        // Owner (2026-11-18): the AI handed the chat off and it was routed
        // to another operator (or another operator claimed the unassigned
        // chat). The chat left MY visible queue — close dialog + details.
        selectedRef.current = null;
        setSelectedId(null);
        setCurrent(null);
        setNotes([]);
        setToast("Обращение взял другой оператор");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить очередь");
    }
  }, [auth, ready]);
  // Owner report (2026-11-20): when AD keeps no photo the avatar falls back
  // to the Tag profile image (the same picture the colleague sees in chat).
  const ensureTagAvatar = async (userId: string) => {
    if (tagAvatarsRef.current[userId]) return;
    try {
      const response = await fetch(`/api/v1/operator/users/${userId}/tag-avatar`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      });
      if (!response.ok) return;
      tagAvatarsRef.current[userId] = URL.createObjectURL(await response.blob());
      setTagAvatars({ ...tagAvatarsRef.current });
    } catch {
      // no Tag avatar either — initials stay
    }
  };
  const loadAdInfo = async (userId: string) => {
    // Employee card (P-29): graceful degradation - on any failure the
    // details panel shows the plain user block.
    // Perf/UX (2026-11-17): a slow answer for the PREVIOUS ticket must not
    // overwrite the card of the currently selected one.
    try {
      // Owner (2026-11-17): the panel card is fetched FRESH (force bypasses
      // the 24h cache) — position/department changes show up immediately.
      // When AD is unreachable the endpoint gracefully returns the cached
      // organizational copy.
      const info = await api<AdInfo>(
        `/users/${userId}/ad-info?force=true`,
        auth,
      );
      if (adUserRef.current !== userId) return;
      setAdInfo(info);
      adInfoReadyRef.current = userId;
      setAdInfoReadyFor(userId);
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
      if (!adPhotosRef.current[userId]) void ensureTagAvatar(userId);
    } catch {
      if (adUserRef.current === userId) {
        setAdInfo(null);
        adInfoReadyRef.current = userId;
        setAdInfoReadyFor(userId);
      }
      void ensureTagAvatar(userId);
    }
  };
  // Owner (2026-11-17): manual refresh — bypasses the 24h cache so a
  // promoted / moved / renamed employee shows up immediately.
  const refreshAdInfo = async (userId: string) => {
    if (adRefreshing) return;
    setAdRefreshing(true);
    try {
      const info = await api<AdInfo>(
        `/users/${userId}/ad-info?force=true`,
        auth,
      );
      if (adUserRef.current !== userId) return;
      setAdInfo(info);
      // Owner (2026-11-20): success only when AD actually returned a card;
      // otherwise say WHY nothing changed.
      setToast(
        info.available
          ? "Данные обновлены из AD"
          : adRefreshErrors[info.refresh_error ?? ""] ??
              "AD не вернул данные",
      );
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
      if (!adPhotosRef.current[userId]) void ensureTagAvatar(userId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось обновить из AD");
    } finally {
      setAdRefreshing(false);
    }
  };
  const loadTicket = useCallback(
    async (id: string) => {
      if (!ready) return;
      // Owner (2026-11-17): a background refresh of the OPEN ticket must not
      // flash the loading state — that collapsed the history and threw the
      // scroll to the top on every incoming message.
      if (currentIdRef.current !== id) setLoading(true);
      const switching = detailsTicketRef.current !== id;
      detailsTicketRef.current = id;
      if (switching) setDetailsStale(true);
      try {
        const ticket = await api<Ticket>(`/tickets/${id}`, auth);
        adUserRef.current = ticket.user_id;
        if (adInfoReadyRef.current !== ticket.user_id) setAdInfoReadyFor(null);
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
        // Owner (2026-11-18): a ticket closed by the session timeout must
        // leave the OPEN workspace immediately, not on the next refresh.
        if (ticket.status === "CLOSED") {
          setSelectedId(null);
          setToast("Диалог закрыт: время сессии ограничено (3 часа)");
        }
        // Owner (2026-11-18): the AD card is fetched once per user (switch /
        // manual refresh); background syncs skip the LDAP round-trip — it
        // made every live update feel frozen for a second.
        if (adInfoReadyRef.current !== ticket.user_id)
          await loadAdInfo(ticket.user_id);
        if (switching) setDetailsStale(false);
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
        // Owner (2026-11-20): AD sometimes serves a broken/placeholder
        // photo — show the initials avatar (like the Team rows) instead.
        const type = response.headers.get("content-type") || "";
        if (!active || !response.ok || !type.startsWith("image/")) return;
        const blob = await response.blob();
        if (blob.size < 1024) return;
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
          if (v.type !== "ready" && v.type !== "ping") {
            scheduleSync();
            // Owner (2026-11-18): toast names the person and only fires for
            // user messages. The event payload is nested ("payload"), the
            // flat v.conversation_id never existed.
            if (v.type === "message.user_received") {
              playPing();
              const sender = ticketsRef.current.find(
                (item) => item.conversation_id === v.payload?.conversation_id,
              );
              setToast(
                sender?.user_name
                  ? `Новое сообщение: ${shortFio(sender.user_name)}`
                  : "Новое сообщение от пользователя",
              );
            }
            // Owner (2026-11-25): the invitee learns about the invitation
            // right away — a personal toast (payload carries operator_id).
            if (
              v.type === "specialist.invited" &&
              v.payload?.operator_id === operatorIdRef.current
            ) {
              playPing();
              setToast(
                `${v.payload.invited_by || "Коллега"} пригласил вас специалистом в чат #${shortId(v.payload.ticket_id)}`,
              );
            }
          }
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
    // Owner (2026-11-18): safety poll — even if the WS silently dies behind
    // the dev proxy, the workspace self-heals every 15 s.
    const poll = window.setInterval(() => scheduleSync(), 15000);
    return () => {
      stopped = true;
      window.clearInterval(poll);
      clearTimeout(retry.current);
      socket.current?.close();
      socket.current = null;
    };
  }, [auth.token, ready, sync, scheduleSync]);
  // Virtualization-lite (perf round 2026-11-17): render the queue windowed
  // — a full 200-row list is mounted only when the operator actually scrolls.
  useEffect(() => {
    setVisibleCount(100);
  }, [queueTab, queueGroup]);
  const columns = useMemo(() => {
    const active = tickets.filter(
      (t) => t.status !== "RESOLVED" && t.status !== "CLOSED",
    );
    // Owner (2026-11-23, plan item 7): invited specialist chats land in
    // "Мои" too — the specialist works with them like the assignee, but
    // they are NOT counted in the routing load (no assignee change).
    // Owner (2026-11-25): invited chats get their OWN group — "Приглашённые"
    // — the assignee's "В работе"/"Ожидают" stay untouched.
    const mine = active.filter((t) => t.assignee_id === operatorId);
    const invited = active.filter(
      (t) => t.is_specialist && t.assignee_id !== operatorId,
    );
    // Owner (2026-11-18): a ticket claimed from the queue is in work even
    // before the first reply — status stays NEW until the user writes again,
    // and it must not fall out of "В работе".
    const mineWorking = mine.filter(
      (t) => t.status === "OPEN" || t.status === "NEW",
    );
    const mineWaiting = mine.filter((t) => t.status === "PENDING_USER");
    // Owner (2026-11-18): "Мои обращения" holds exactly two states — "В
    // работе" and "Ожидают пользователя"; the AI stage is not the
    // operator's business and never shows here. In the QUEUE the AI group
    // stays ("Обработка ИИ"), so unassigned must exclude AI_PROCESSING —
    // otherwise those tickets render twice in "Все обращения".
    const unassigned = active.filter(
      (t) => !t.assignee_id && t.status !== "AI_PROCESSING",
    );
    const ai = active.filter((t) => t.status === "AI_PROCESSING");
    return {
      mineWorking,
      mineWaiting,
      mineInvited: invited,
      mineAll: [...mineWorking, ...mineWaiting],
      queueUnassigned: unassigned,
      queueAI: ai,
      queueAll: [...unassigned, ...ai],
    };
  }, [tickets, operatorId]);
  // Owner (2026-11-23, plan item 6): download the search results as .xlsx —
  // the same filters as runHistorySearch, minus the 100-row page limit.
  const exportHistory = async () => {
    const q = new URLSearchParams({ limit: "5000" });
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
    const response = await fetch(`/api/v1/operator/tickets/export.xlsx?${q}`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    if (!response.ok) throw new Error("Не удалось выгрузить Excel");
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]+)"/.exec(disposition);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = match ? match[1] : "tickets_export.xlsx";
    link.click();
    URL.revokeObjectURL(link.href);
  };
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
  // Owner (2026-11-17): the groups table is filterable (magnifier input).
  const adGroupsFiltered = useMemo(() => {
    const groups = adDetail?.groups ?? [];
    const query = adGroupQuery.trim().toLowerCase();
    if (!query) return groups;
    return groups.filter(
      (group) =>
        group.name.toLowerCase().includes(query) ||
        (group.description || "").toLowerCase().includes(query),
    );
  }, [adDetail, adGroupQuery]);
  const openSlaHistory = async (ticket?: Ticket) => {
    const target = ticket ?? current;
    if (!target) return;
    try {
      const data = await api<{ events: SlaHistoryEvent[] }>(
        `/tickets/${target.ticket_id}/sla-history`,
        auth,
      );
      setSlaEvents(data.events ?? []);
      setSlaTicket(target);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось загрузить историю SLA",
      );
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
  // Owner (2026-11-23, plan item 7): a specialist can write too — locked
  // only when the chat has neither an assignee nor my participation.
  const currentUnassigned =
    current !== null && !current.assignee_id && !current.is_specialist;
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
  // Owner (2026-11-17): when reading the tail of the history, a new message
  // scrolls the view down; opening a ticket always lands at the bottom.
  useEffect(() => {
    const el = history.current;
    if (!el || typeof el.scrollTo !== "function") return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: stickToBottom.current ? "smooth" : "auto",
    });
  }, [timeline.length, current?.ticket_id]);
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
      // Owner (2026-11-23): the sign-in POST must NOT go through api() —
      // its 401 means "wrong credentials", not "session expired", and
      // api()'s reload made the error flash for a millisecond.
      const response = await fetch("/api/v1/operator/auth/session", {
        method: "POST",
        headers: { Authorization: `Basic ${btoa(binary)}` },
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
      const data = (await response.json()) as { session_token: string };
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
  // Owner (2026-11-19): shared attachment download (workspace + history).
  const downloadAttachment = useCallback(
    async (attachment: MessageAttachmentInfo) => {
      try {
        const response = await fetch(
          `/api/v1/operator/attachments/${attachment.id}/file`,
          { headers: { Authorization: `Bearer ${auth.token}` } },
        );
        if (!response.ok) throw Error("Файл недоступен");
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = attachment.file_name;
        link.click();
        URL.revokeObjectURL(url);
      } catch (cause) {
        setError(
          cause instanceof Error ? cause.message : "Не удалось скачать файл",
        );
      }
    },
    [auth.token],
  );
  const send = useCallback(
    async (
      mode: "reply" | "note",
      body: string,
      files: File[] = [],
    ): Promise<boolean> => {
      if (!current) return false;
      try {
        if (mode === "reply") {
          // Owner (2026-11-19): files are uploaded first (pending
          // attachments), then linked to the sent reply.
          const attachmentIds: string[] = [];
          for (const file of files) {
            const form = new FormData();
            form.append("file", file);
            const uploaded = await api<{ id: string }>(
              `/tickets/${current.ticket_id}/attachments`,
              auth,
              { method: "POST", body: form },
            );
            attachmentIds.push(uploaded.id);
          }
          await api(`/tickets/${current.ticket_id}/replies`, auth, {
            method: "POST",
            body: JSON.stringify({ text: body, attachment_ids: attachmentIds }),
          });
          setToast(
            attachmentIds.length
              ? `Ответ отправлен (${attachmentIds.length} влож.)`
              : "Ответ отправлен в очередь доставки",
          );
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
  // Owner (2026-11-23, plan item 7): invite a colleague as a specialist —
  // they keep their own voice in the chat and can leave; the user is not
  // notified (unlike a transfer).
  const inviteSpecialist = async (targetOperatorId: string) => {
    if (!current) return;
    try {
      await api(`/tickets/${current.ticket_id}/specialists`, auth, {
        method: "POST",
        body: JSON.stringify({ operator_id: targetOperatorId }),
      });
      setToast("Специалист приглашён в чат");
      setTransferOpen(false);
      setTransferConfirm(null);
      await sync();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось пригласить специалиста");
    }
  };
  const leaveAsSpecialist = async () => {
    if (!current) return;
    try {
      await api(`/tickets/${current.ticket_id}/leave`, auth, { method: "POST" });
      setToast("Вы покинули чат");
      setSelectedId(null);
      setCurrent(null);
      await sync();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось покинуть чат");
    }
  };

  // Owner (2026-11-25): the KB library in the rail — the same CRUD the
  // admin panel used to have, for every operator.
  const kbStamp = (value: string) =>
    new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  const openKbLibrary = () => {
    setKbLibraryOpen(true);
    void adminApi<{ articles: KbArticle[] }>("/kb", auth)
      .then((data) => {
        setKbArticles(data.articles);
        // Keep the selection if it survived; otherwise pick the first page
        // so the pane is never empty on entry.
        setKbSelectedId((current) =>
          current && data.articles.some((a) => a.article_id === current)
            ? current
            : data.articles[0]?.article_id ?? null,
        );
        setKbCreating(false);
        setKbEditing(null);
      })
      .catch(() => undefined);
    void adminApi<{ articles: KbArticle[] }>("/kb/archive", auth)
      .then((data) => setKbArchive(data.articles))
      .catch(() => undefined);
  };
  const saveKbArticle = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const article = await adminApi<KbArticle>("/kb", auth, {
        method: "POST",
        body: JSON.stringify({ title: kbNewTitle, body: kbNewBody }),
      });
      setKbArticles((items) =>
        [...items, article].sort((a, b) => a.title.localeCompare(b.title, "ru")),
      );
      setKbNewTitle("");
      setKbNewBody("");
      setKbCreating(false);
      setKbSelectedId(article.article_id);
      setToast("Статья добавлена");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Статья не сохранена");
    }
  };
  const updateKbArticle = async (event: FormEvent) => {
    event.preventDefault();
    if (!kbEditing) return;
    try {
      const updated = await adminApi<KbArticle>(
        `/kb/${kbEditing.article_id}`,
        auth,
        {
          method: "PUT",
          body: JSON.stringify({ title: kbEditing.title, body: kbEditing.body }),
        },
      );
      setKbArticles((items) =>
        items.map((item) =>
          item.article_id === updated.article_id ? updated : item,
        ),
      );
      setKbEditing(null);
      setToast("Статья обновлена");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Статья не обновлена");
    }
  };
  const deleteKbArticle = async (article: KbArticle) => {
    if (
      !window.confirm(
        `Удалить статью «${article.title}»? Её можно восстановить в течение 14 дней.`,
      )
    )
      return;
    try {
      await adminApi(`/kb/${article.article_id}`, auth, { method: "DELETE" });
      setKbArticles((items) =>
        items.filter((item) => item.article_id !== article.article_id),
      );
      setKbSelectedId((current) =>
        current === article.article_id ? null : current,
      );
      setKbArchive((items) => [
        {
          ...article,
          deleted_at: new Date().toISOString(),
          deleted_by: "вы",
        },
        ...items,
      ]);
      setToast("Статья удалена — 14 дней можно восстановить");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Статья не удалена");
    }
  };
  const restoreKbArticle = async (article: KbArticle) => {
    try {
      const restored = await adminApi<KbArticle>(
        `/kb/${article.article_id}/restore`,
        auth,
        { method: "POST" },
      );
      setKbArchive((items) =>
        items.filter((item) => item.article_id !== article.article_id),
      );
      setKbArticles((items) =>
        [...items, restored].sort((a, b) =>
          a.title.localeCompare(b.title, "ru"),
        ),
      );
      setKbSelectedId(restored.article_id);
      setToast("Статья восстановлена");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Статья не восстановлена");
    }
  };
  const kbSelected =
    (kbArticles ?? []).find((article) => article.article_id === kbSelectedId) ??
    null;
  const openKbHistory = async (article: KbArticle) => {
    setKbHistoryFor(article);
    setKbHistory([]);
    try {
      const data = await adminApi<{ events: KbHistoryEvent[] }>(
        `/kb/${article.article_id}/history`,
        auth,
      );
      setKbHistory(data.events);
    } catch {
      setKbHistory([]);
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
      // Owner (2026-11-19): the details-style aside shows the moves too.
      const moves = await api<{ events: AssignmentEvent[] }>(
        `/tickets/${ticketId}/assignment-history`,
        auth,
      );
      setHistoryMoves(moves.events ?? []);
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
      if (status !== "ACTIVE") {
        // Owner (2026-11-18): leaving ACTIVE releases the operator's chats
        // back to the queue (backend: release_operator_tickets). The released
        // dialog must close at once — waiting for the queue guard does not
        // work: the ticket stays in /tickets (just unassigned), only the
        // client-side "mine" filter hides it from the list.
        selectedRef.current = null;
        setSelectedId(null);
        setCurrent(null);
        setNotes([]);
      }
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
          <div className="brand-row">
            <div className="brand-mark">
              S<span>•</span>
            </div>
            <p className="eyebrow">UPPORT HUB · OPERATOR</p>
          </div>
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
          className={`rail-button ${!historyPage && !adminOpen && !kbLibraryOpen ? "active" : ""}`}
          title="Очередь обращений"
          aria-label="Очередь обращений"
          onClick={() => {
            setHistoryPage(false);
            setAdminOpen(false);
            setKbLibraryOpen(false);
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
            setKbLibraryOpen(false);
            setProfileMenuOpen(false);
          }}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3.5 2" />
          </svg>
        </button>
        <button
          className={`rail-button ${kbLibraryOpen ? "active" : ""}`}
          title="База знаний"
          aria-label="База знаний"
          onClick={() => {
            setKbLibraryOpen(true);
            setHistoryPage(false);
            setAdminOpen(false);
            setProfileMenuOpen(false);
            openKbLibrary();
          }}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 19V6a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2Zm0 0a2 2 0 0 0 2 2h13" />
            <path d="M9 8h6M9 11h6" />
          </svg>
        </button>
        {operatorRole === "ADMIN" && (
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
          <div className="header-actions">
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
          </div>
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
                    { key: "all", label: "Все обращения", items: [...columns.mineAll, ...columns.mineInvited] },
                    { key: "working", label: "В работе", items: columns.mineWorking },
                    {
                      key: "waiting",
                      label: "Ожидает пользователя",
                      items: columns.mineWaiting,
                    },
                    // Owner (2026-11-25): chats where I was invited as a
                    // specialist — separate from the ones I own.
                    {
                      key: "invited",
                      label: "Приглашённые",
                      items: columns.mineInvited,
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
              {/* Owner (2026-11-26): the rating sits next to the name and
                  must not shift the status / activity line below it. */}
              <strong>
                {profile?.display_name || "Оператор"}
                <RatingBadge value={profile?.avg_rating} />
              </strong>
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
        className={`conversation-panel ${mobile === "conversation" ? "mobile-visible" : "mobile-hidden"} ${currentUnassigned ? "chat-locked" : ""} ${dragOverConversation ? "drag-over" : ""}`}
        onDragOver={(e) => {
          // Owner (2026-11-19): files can be dropped anywhere on the dialog
          // window — not only on the composer.
          if (!current || currentUnassigned) return;
          e.preventDefault();
          setDragOverConversation(true);
        }}
        onDragLeave={(e) => {
          if (e.currentTarget === e.target) setDragOverConversation(false);
        }}
        onDrop={(e) => {
          if (!current || currentUnassigned) return;
          e.preventDefault();
          setDragOverConversation(false);
          const dropped = Array.from(e.dataTransfer.files ?? []);
          if (dropped.length) {
            setDroppedFiles((prev) => [...prev, ...dropped]);
            setMobile("conversation");
          }
        }}
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
                  title={
                    currentUnassigned
                      ? "Сначала назначьте сотрудника — чат никому не принадлежит"
                      : "Передать сотруднику"
                  }
                  aria-label="Передать сотруднику"
                  disabled={currentUnassigned}
                  onClick={() => {
                    setTransferOpen(true);
                    // Owner (2026-11-23): never show a stale list — pull the
                    // colleagues the moment the modal opens.
                    void api<{ colleagues: Colleague[] }>("/colleagues", auth)
                      .then((data) => setColleagues(data.colleagues ?? []))
                      .catch(() => {});
                  }}
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
                {current?.is_specialist && (
                  <button
                    className="specialist-leave"
                    title="Покинуть чат (пользователь не узнает)"
                    onClick={() => void leaveAsSpecialist()}
                  >
                    Покинуть чат
                  </button>
                )}
              </div>
            </header>
            {current?.specialists && current.specialists.length > 0 && (
              <div className="specialists-row" role="status">
                Специалисты: {current.specialists.join(", ")}
              </div>
            )}
            {presence !== "ACTIVE" && (
              // Owner request (2026-11-23): an operator who is not ACTIVE
              // receives no chats — say it right over the dialog, with a
              // one-click way back.
              <div className="offline-banner" role="status">
                <span>
                  Вы в статусе «{presenceLabels[presence]}» — новые чаты вам
                  не приходят.
                </span>
                <button onClick={() => void changePresence("ACTIVE")}>
                  Стать активным
                </button>
              </div>
            )}
            {error && (
              <div className="error-banner">
                <span>!</span>
                {error}
                <button onClick={() => setError("")}>×</button>
              </div>
            )}
            <div
              className="conversation-scroll"
              ref={history}
              onScroll={(e) => {
                const el = e.currentTarget;
                stickToBottom.current =
                  el.scrollTop + el.clientHeight >= el.scrollHeight - 120;
              }}
            >
              <div className="conversation-start">
                {adPhotos[current.user_id] ? (
                  <img
                    className="user-photo large"
                    src={adPhotos[current.user_id]}
                    alt=""
                  />
                ) : tagAvatars[current.user_id] ? (
                  <img
                    className="user-photo large"
                    src={tagAvatars[current.user_id]}
                    alt=""
                  />
                ) : (
                  <div className="user-avatar large">
                    {initials(adInfo?.full_name || shortId(current.user_id))}
                  </div>
                )}
                <h3>
                  {adInfoReadyFor === current.user_id &&
                  adInfo?.available &&
                  adInfo.full_name
                    ? adInfo.full_name
                    : adInfoReadyFor === current.user_id
                      ? current.user_name ||
                        `Пользователь ${shortId(current.user_id)}`
                      : "Загрузка карточки…"}
                </h3>
                <p>
                  Обращение создано{" "}
                  {new Intl.DateTimeFormat("ru-RU", {
                    dateStyle: "long",
                  }).format(new Date(current.created_at))}
                </p>
                <span className="conversation-id">
                  Обращение · #{shortId(current.ticket_id)}
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
                  userLabel={
                    adInfoReadyFor === current.user_id &&
                    adInfo?.available &&
                    adInfo.full_name
                      ? adInfo.full_name
                      : adInfoReadyFor === current.user_id
                        ? current.user_name || "Пользователь"
                        : "Пользователь"
                  }
                  operatorName={profile?.display_name || "Оператор"}
                  userAvatarUrl={
                    adPhotos[current.user_id] ||
                    tagAvatars[current.user_id] ||
                    null
                  }
                  fetchAttachment={async (attachment) => {
                    // Owner (2026-11-19): image previews and downloads both
                    // go through the authorized fetch.
                    const response = await fetch(
                      `/api/v1/operator/attachments/${attachment.id}/file`,
                      { headers: { Authorization: `Bearer ${auth.token}` } },
                    );
                    if (!response.ok) throw Error("Файл недоступен");
                    return response.blob();
                  }}
                  onDownloadAttachment={(attachment) => {
                    if (!current) return;
                    // Owner (2026-11-19): the download needs the auth
                    // header, so the parent fetches and saves the file.
                    void fetch(
                      `/api/v1/operator/attachments/${attachment.id}/file`,
                      { headers: { Authorization: `Bearer ${auth.token}` } },
                    )
                      .then(async (response) => {
                        if (!response.ok) throw Error("Файл недоступен");
                        const blob = await response.blob();
                        const url = URL.createObjectURL(blob);
                        const link = document.createElement("a");
                        link.href = url;
                        link.download = attachment.file_name;
                        link.click();
                        URL.revokeObjectURL(url);
                      })
                      .catch((cause: unknown) =>
                        setError(
                          cause instanceof Error
                            ? cause.message
                            : "Не удалось скачать файл",
                        ),
                      );
                  }}
                />
              )}
            </div>
            <Composer
              key={current.ticket_id}
              disabled={currentUnassigned}
              onSend={send}
              droppedFiles={droppedFiles}
              onDroppedFilesConsumed={() => setDroppedFiles([])}
              kbArticles={kbArticles}
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
            {presence !== "ACTIVE" && (
              // Owner request (2026-11-25): the same banner on the main
              // screen — an operator who just logged in or went offline
              // must see right away that chats are not coming.
              <div className="offline-banner centered" role="status">
                <span>
                  Вы в статусе «{presenceLabels[presence]}» — новые чаты вам
                  не приходят.
                </span>
                <button onClick={() => void changePresence("ACTIVE")}>
                  Стать активным
                </button>
              </div>
            )}
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
              <button
                className="ad-refresh-corner"
                title={adRefreshing ? "Обновляем из AD…" : "Обновить из AD"}
                aria-label="Обновить из AD"
                disabled={adRefreshing}
                onClick={() => void refreshAdInfo(current.user_id)}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" className={adRefreshing ? "spin" : ""}>
                  <path d="M20 11A8 8 0 0 0 5.6 6.4L4 8" />
                  <path d="M4 4v4h4" />
                  <path d="M4 13a8 8 0 0 0 14.4 4.6L20 16" />
                  <path d="M20 20v-4h-4" />
                </svg>
              </button>
              {adPhotos[current.user_id] ? (
                <img
                  className="user-photo"
                  src={adPhotos[current.user_id]}
                  alt=""
                />
              ) : tagAvatars[current.user_id] ? (
                <img
                  className="user-photo"
                  src={tagAvatars[current.user_id]}
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
                  <div className="ad-rows">
                    {adInfo.title && (
                      <div>
                        <span>Должность</span>
                        {adInfo.title}
                      </div>
                    )}
                    {adInfo.department && (
                      <div>
                        <span>Отдел</span>
                        {adInfo.department}
                      </div>
                    )}
                    {adInfo.company && (
                      <div>
                        <span>Компания</span>
                        {adInfo.company}
                      </div>
                    )}
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
                          через{" "}
                          {Math.ceil(
                            (new Date(adInfo.password_expires_at).getTime() -
                              Date.now()) /
                              86400000,
                          )}{" "}
                          дн.
                        </div>
                      )}
                    <div>
                      <span>Статус УЗ</span>
                      <b
                        className={
                          adInfo.disabled || adInfo.locked
                            ? "ad-status-bad"
                            : "ad-status-ok"
                        }
                      >
                        {adInfo.disabled
                          ? "Отключена"
                          : adInfo.locked
                            ? "Заблокирована"
                            : "Активна"}
                      </b>
                    </div>
                  </div>
                  {(adInfo.disabled || adInfo.locked) && (
                    <div className="ad-warning">
                      Учётная запись {adInfo.disabled ? "отключена" : "заблокирована"} в
                      AD
                    </div>
                  )}
                  <div className="ad-actions">
                    <button
                      className="ad-full-button"
                      onClick={() => {
                        // Owner (2026-11-17): the full card shows access data
                        // (groups, account status, password dates) — it must be
                        // FRESH from AD, never from the cached copy. The panel
                        // card keeps the cached organizational info only.
                        const login =
                          adInfo?.login || (adInfo?.email || "").split("@")[0] || "";
                        setAdOpen(true);
                        if (login) void openAdDetail(login);
                        else setAdDetail(null);
                      }}
                    >
                      Полная информация
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <h3>
                    {current.user_name || `Пользователь ${shortId(current.user_id)}`}
                  </h3>
                  <p>Корпоративный пользователь</p>
                </>
              )}
            </section>
            {detailsStale ? (
              <div className="ad-loading">
                <span className="ad-spinner" />
                Загружаем детали…
              </div>
            ) : (
              <>
            {/* Owner (2026-11-19): status and SLA are separate blocks with
                a divider line between them. The status card is self-titled —
                no label needed. */}
            <section className="detail-section">
              <div className={`status-card ${current.status.toLowerCase()}`}>
                <span className="status-card-dot" />
                <span className="status-card-name">
                  {statusName[current.status]}
                </span>
              </div>
            </section>
            <section className="detail-section">
              <div className="detail-label">SLA</div>
              <div
                className={`sla-card ${current.sla?.breached_at ? "breached" : ""} ${current.sla?.deadline && !current.sla?.breached_at ? "counting" : ""}`}
                onClick={() => void openSlaHistory()}
                title="История статусов и SLA"
              >
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
                <span className="sla-placeholder">
                  {current.sla?.breached_at
                    ? "SLA просрочен"
                    : current.sla?.deadline
                      ? `Ответ через ${Math.max(0, Math.ceil((new Date(current.sla.deadline).getTime() - Date.now()) / 60000))} мин`
                      : "SLA 15 мин"}
                </span>
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
                      {moveText(event, assignmentName)}
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
                Закрыть обращение
              </button>
            </section>
              </>
            )}
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
            className="modal ad-modal"
            role="dialog"
            aria-label="Передать обращение сотруднику"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close"
              aria-label="Закрыть"
              onClick={() => setTransferOpen(false)}
            >
              ×
            </button>
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
            <button
              className="resolve-submit secondary"
              onClick={() => void inviteSpecialist(transferConfirm.operator_id)}
            >
              Пригласить специалистом
            </button>
            <button className="quiet-action" onClick={() => setTransferConfirm(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
      {kbLibraryOpen && (
        // Owner (2026-11-26): the KB is a full page (like the queue and
        // the admin panel), not a modal on top of the workspace.
        <div className="kb-page" role="region" aria-label="База знаний">
          <aside className="kb-sidebar">
            <input
              className="kb-search"
              placeholder="Поиск по статьям"
              value={kbQuery}
              onChange={(event) => setKbQuery(event.target.value)}
            />
            <button
              className="kb-new"
              onClick={() => {
                setKbCreating(true);
                setKbSelectedId(null);
                setKbEditing(null);
                setKbNewTitle("");
                setKbNewBody("");
              }}
            >
              + Новая статья
            </button>
            <nav className="kb-list" aria-label="Статьи">
              {kbArticles
                .filter((article) => {
                  const needle = kbQuery.trim().toLowerCase();
                  if (!needle) return true;
                  return (
                    article.title.toLowerCase().includes(needle) ||
                    article.body.toLowerCase().includes(needle)
                  );
                })
                .map((article) => (
                  <button
                    key={article.article_id}
                    className={`kb-list-item ${kbSelectedId === article.article_id ? "active" : ""}`}
                    onClick={() => {
                      setKbSelectedId(article.article_id);
                      setKbCreating(false);
                      setKbEditing(null);
                    }}
                  >
                    <strong>{article.title}</strong>
                    <span>
                      {article.body.length > 64
                        ? `${article.body.slice(0, 64)}…`
                        : article.body}
                    </span>
                  </button>
                ))}
              {!kbArticles.length && (
                <p className="kb-empty">Статей пока нет</p>
              )}
            </nav>
            {kbArchive.length > 0 && (
              <div className="kb-archive">
                <p className="kb-archive-title">Недавно удалённые</p>
                {kbArchive.map((article) => (
                  <div key={article.article_id} className="kb-archive-item">
                    <span title={article.title}>{article.title}</span>
                    <button onClick={() => void restoreKbArticle(article)}>
                      Восстановить
                    </button>
                  </div>
                ))}
              </div>
            )}
          </aside>
          <section className="kb-content">
            {kbCreating ? (
              <form
                className="kb-editor"
                onSubmit={(event) => void saveKbArticle(event)}
              >
                <input
                  className="kb-editor-title"
                  required
                  maxLength={200}
                  placeholder="Заголовок статьи"
                  value={kbNewTitle}
                  onChange={(event) => setKbNewTitle(event.target.value)}
                />
                <textarea
                  className="kb-editor-body"
                  required
                  maxLength={10000}
                  placeholder="Текст ответа"
                  rows={14}
                  value={kbNewBody}
                  onChange={(event) => setKbNewBody(event.target.value)}
                />
                <div className="kb-editor-actions">
                  <button type="submit">Сохранить</button>
                  <button type="button" onClick={() => setKbCreating(false)}>
                    Отмена
                  </button>
                </div>
              </form>
            ) : kbSelected ? (
              kbEditing?.article_id === kbSelected.article_id ? (
                <form
                  className="kb-editor"
                  onSubmit={(event) => void updateKbArticle(event)}
                >
                  <input
                    className="kb-editor-title"
                    required
                    maxLength={200}
                    value={kbEditing.title}
                    onChange={(event) =>
                      setKbEditing({ ...kbEditing, title: event.target.value })
                    }
                  />
                  <textarea
                    className="kb-editor-body"
                    required
                    maxLength={10000}
                    rows={14}
                    value={kbEditing.body}
                    onChange={(event) =>
                      setKbEditing({ ...kbEditing, body: event.target.value })
                    }
                  />
                  <div className="kb-editor-actions">
                    <button type="submit">Сохранить</button>
                    <button type="button" onClick={() => setKbEditing(null)}>
                      Отмена
                    </button>
                  </div>
                </form>
              ) : (
                <article className="kb-view">
                  <h2>{kbSelected.title}</h2>
                  {(kbSelected.created_by || kbSelected.updated_by) && (
                    <p className="kb-attribution">
                      Создал: {kbSelected.created_by || "—"} ·{" "}
                      {kbSelected.created_at ? kbStamp(kbSelected.created_at) : "—"}
                      {kbSelected.updated_by
                        ? ` · Изменил: ${kbSelected.updated_by} · ${kbStamp(kbSelected.updated_at)}`
                        : ""}
                    </p>
                  )}
                  <div className="kb-view-body">{kbSelected.body}</div>
                  <div className="kb-editor-actions">
                    <button onClick={() => setKbEditing(kbSelected)}>
                      Изменить
                    </button>
                    <button
                      className="kb-danger"
                      onClick={() => void deleteKbArticle(kbSelected)}
                    >
                      Удалить
                    </button>
                    <button
                      className="kb-history-button"
                      title="Кто и когда создавал, изменял, удалял"
                      onClick={() => void openKbHistory(kbSelected)}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <circle cx="12" cy="12" r="9" />
                        <path d="M12 7v5l3.5 2" />
                      </svg>
                      История
                    </button>
                  </div>
                </article>
              )
            ) : (
              <div className="kb-empty-state">
                <h2>{kbArticles.length ? "Выберите статью" : "База знаний пуста"}</h2>
                <p>
                  Выберите статью слева или создайте новую — статьи
                  подставляются в подсказки композера.
                </p>
              </div>
            )}
          </section>
        </div>
      )}
      {kbHistoryFor && (
        <div
          className="modal-backdrop"
          onClick={() => setKbHistoryFor(null)}
          role="presentation"
        >
          <div
            className="modal kb-history-modal"
            role="dialog"
            aria-label="История статьи"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">История · {kbHistoryFor.title}</div>
            <div className="kb-history-list">
              {kbHistory.map((event, index) => (
                <div className="kb-history-row" key={index}>
                  <strong>{event.action}</strong>
                  <span>
                    {event.actor_name || "—"} · {kbStamp(event.created_at)}
                  </span>
                </div>
              ))}
              {!kbHistory.length && (
                <p className="admin-muted">
                  Событий нет — статья создана до ведения истории
                </p>
              )}
            </div>
            <button className="quiet-action" onClick={() => setKbHistoryFor(null)}>
              Закрыть
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
                  {moveText(event, assignmentName)}
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
      {slaTicket && (
        <div
          className="modal-backdrop"
          onClick={() => setSlaTicket(null)}
          role="presentation"
        >
          <div
            className="modal sla-modal"
            role="dialog"
            aria-label="История статусов и SLA"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close"
              aria-label="Закрыть"
              onClick={() => setSlaTicket(null)}
            >
              ×
            </button>
            <div className="modal-title">
              Статусы и SLA · #{shortId(slaTicket.ticket_id)}
            </div>
            <div className="sla-modal-summary">
              {slaTicket.sla?.breached_at ? (
                <span className="sla-breach-banner">
                  SLA просрочен — ответ оператора был позже 15 минут
                </span>
              ) : slaTicket.sla?.deadline ? (
                <span className="sla-ok-banner">
                  Ответ до{" "}
                  {new Intl.DateTimeFormat("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(slaTicket.sla.deadline))}
                </span>
              ) : (
                <span className="sla-idle-banner">Часы SLA не идут</span>
              )}
            </div>
            <div className="sla-durations">
              {slaDurationRows(slaEvents, slaTicket.status).map((row) => (
                <div className="sla-duration-row" key={row.status}>
                  <span
                    className={`status-dot ${row.status.toLowerCase()}`}
                  />
                  <strong>{statusName[row.status as Ticket["status"]]}</strong>
                  <span className="sla-duration-value">{row.duration}</span>
                </div>
              ))}
              {!slaEvents.length && (
                <div className="past-empty">Переходов пока не было.</div>
              )}
            </div>
            <div className="sla-events-title">События</div>
            <div className="sla-events">
              {slaEvents.map((event, index) => (
                <div className="sla-event" key={`${event.kind}-${index}`}>
                  <span>
                    {event.kind === "sla_breached"
                      ? "SLA просрочен"
                      : event.kind === "sla_met"
                        ? "Ответ оператора — SLA выполнен"
                        : `${statusName[(event.from_status || "") as Ticket["status"]] || event.from_status} → ${statusName[(event.to_status || "") as Ticket["status"]] || event.to_status}`}
                  </span>
                  <time>
                    {new Intl.DateTimeFormat("ru-RU", {
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    }).format(new Date(event.changed_at))}
                  </time>
                </div>
              ))}
              {!slaEvents.length && (
                <div className="past-empty">Событий пока нет.</div>
              )}
            </div>
            <button className="quiet-action" onClick={() => setSlaTicket(null)}>
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
            className="modal ad-modal"
            role="dialog"
            aria-label="Закрыть обращение"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              Закрыть обращение · #{shortId(current.ticket_id)}
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
              Закрыть
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
            className="modal wide ad-modal"
            role="dialog"
            aria-label="Прошлые обращения пользователя"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close"
              aria-label="Закрыть"
              onClick={() => setHistoryOpen(false)}
            >
              ×
            </button>
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
                  <HistoryMessages
                    messages={historyDetail.messages ?? []}
                    onDownload={(attachment) => void downloadAttachment(attachment)}
                  />
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
            className="modal team-modal"
            role="dialog"
            aria-label="Команда"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Owner (2026-11-20): a close button on the team window. */}
            <button
              className="modal-close"
              aria-label="Закрыть"
              onClick={() => {
                setTeamOpen(false);
                setTeamMember(null);
                setTeamTicket(null);
              }}
            >
              ×
            </button>
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
                    <HistoryMessages
                      messages={teamTicket.messages ?? []}
                      onDownload={(attachment) => void downloadAttachment(attachment)}
                    />
                  </div>
                </>
              ) : (
                <>
                  {/* Owner (2026-11-20): the arrow sits right above the
                      title, not in the far corner of the window. */}
                  <button
                    className="modal-arrow"
                    aria-label="К команде"
                    onClick={() => setTeamMember(null)}
                  >
                    ←
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
                    <RatingBadge value={teamMember.avg_rating} />
                  </div>
                  <div className="modal-title small">Текущие чаты</div>
                  {/* Owner (2026-11-20): only ACTIVE chats in the team
                      member view — closed ones live in История. */}
                  {teamTickets.filter(
                    (ticket) =>
                      !["RESOLVED", "CLOSED", "CANCELLED"].includes(ticket.status),
                  ).length ? (
                    teamTickets
                      .filter(
                        (ticket) =>
                          !["RESOLVED", "CLOSED", "CANCELLED"].includes(
                            ticket.status,
                          ),
                      )
                      .map((ticket) => (
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
                 {/* Owner (2026-11-25): OFFLINE colleagues are hidden —
                     only Активен / Обед / Перерыв are listed. */}
                {team
                  .filter((member) => member.presence_status !== "OFFLINE")
                  .map((member) => (
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
                {!team.some((member) => member.presence_status !== "OFFLINE") && (
                  <div className="past-empty">Все сотрудники сейчас офлайн.</div>
                )}
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
            className="modal wide ad-modal"
            role="dialog"
            aria-label="Полная информация из AD"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close"
              aria-label="Закрыть"
              onClick={() => setAdOpen(false)}
            >
              ×
            </button>
            {adDetail ? (
              <>
                <div className="ad-card-head">
                  {adDetail.photo ? (
                    <img className="ad-card-photo" src={adDetail.photo} alt="" />
                  ) : (
                    <span className="profile-avatar">
                      {initials(adDetail.full_name || adDetail.login)}
                    </span>
                  )}
                  <div>
                    <div className="modal-title">
                      {adDetail.full_name || adDetail.login}
                    </div>
                  </div>
                </div>
                <div className="ad-search-row">
                  <svg viewBox="0 0 24 24" aria-hidden="true" className="ad-search-icon">
                    <circle cx="11" cy="11" r="6.5" />
                    <path d="m20 20-4.4-4.4" />
                  </svg>
                  <input
                    placeholder="Поиск по группам…"
                    value={adGroupQuery}
                    onChange={(e) => setAdGroupQuery(e.target.value)}
                  />
                </div>
                <div className="modal-title small">Основные данные</div>
                <div className="ad-table">
                  {[
                    ["Должность", adDetail.title],
                    ["Отдел", adDetail.department],
                    ["Компания", adDetail.company],
                    ["Логин", adDetail.login],
                    ["Почта", adDetail.email],
                    ["Телефон", adDetail.phone],
                    ["Мобильный", adDetail.mobile],
                    ["Руководитель", adDetail.manager],
                    [
                      "Пароль изменён",
                      adDetail.password_changed_at
                        ? new Date(adDetail.password_changed_at).toLocaleDateString("ru-RU")
                        : "",
                    ],
                    [
                      "Пароль истекает",
                      adDetail.password_expires_at
                        ? `${Math.ceil(
                            (new Date(adDetail.password_expires_at).getTime() -
                              Date.now()) /
                              86400000,
                          )} дн.`
                        : "",
                    ],
                  ]
                    .filter(([, value]) => value)
                    .map(([label, value]) => (
                      <div className="ad-table-row" key={label}>
                        <span className="ad-table-label">{label}</span>
                        <span className="ad-table-value">{value}</span>
                      </div>
                    ))}
                  <div className="ad-table-row">
                    <span className="ad-table-label">Состояние УЗ</span>
                    <span
                      className={`ad-table-value ${adDetail.disabled || adDetail.locked ? "ad-status-bad" : "ad-status-ok"}`}
                    >
                      {adDetail.disabled
                        ? "Отключена"
                        : adDetail.locked
                          ? "Заблокирована"
                          : "Активна"}
                    </span>
                  </div>
                </div>
                <div className="modal-title small">
                  Группы ({adGroupsFiltered.length})
                </div>
                <div className="ad-table">
                  {adGroupsFiltered.map((group) => (
                    <div className="ad-table-row" key={group.name}>
                      <span className="ad-group-name">{group.name}</span>
                      <span className="ad-table-value ad-group-desc">
                        {group.description || "—"}
                      </span>
                    </div>
                  ))}
                  {!adGroupsFiltered.length && (
                    <div className="ad-table-row">
                      <span className="ad-table-value">Не найдено</span>
                    </div>
                  )}
                </div>
              </>
            ) : adSearching ? (
              <div className="ad-loading">
                <span className="ad-spinner" />
                Загружаем данные из AD…
              </div>
            ) : (
              <div className="past-empty">
                Не удалось получить данные из AD.
                <button className="quiet-action" onClick={() => setAdOpen(false)}>
                  Закрыть
                </button>
              </div>
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
                className="history-find"
                disabled={historyLoading}
                title="Скачать результаты поиска в Excel"
                onClick={() => void exportHistory().catch((cause: unknown) =>
                  setError(cause instanceof Error ? cause.message : "Не удалось выгрузить Excel"),
                )}
              >
                Excel
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
              {/* Owner (2026-11-19): full-width "Назад" row above the
                  history + details columns. */}
              <button
                type="button"
                className="history-back"
                onClick={() => setHistoryPageTicket(null)}
              >
                Назад
              </button>
              <div className="history-detail-columns">
              <div className="history-detail-chat">
                <div className="modal-title">
                  #{shortId(historyPageTicket.ticket_id)} ·{" "}
                  {statusName[historyPageTicket.status]}
                </div>
                <div className="history-messages">
                  <HistoryMessages
                    messages={historyPageTicket.messages ?? []}
                    onDownload={(attachment) => void downloadAttachment(attachment)}
                  />
                  {!(historyPageTicket.messages ?? []).length && (
                    <div className="past-empty">Сообщений нет.</div>
                  )}
                </div>
              </div>
              {/* Owner (2026-11-19): the aside mirrors the workspace
                  details-panel sections (data / moves / SLA / tags / status). */}
              <aside className="history-detail-info">
                <div className="details-header">
                  <h3>Детали обращения</h3>
                </div>
                <section className="detail-section">
                  <div className="detail-label">ОСНОВНЫЕ ДАННЫЕ</div>
                  {/* Owner (2026-11-19): compact fact blocks. */}
                  <div className="history-fact-block">
                    <div className="history-fact-title">Пользователь</div>
                    <div className="history-fact">
                      <span>ФИО</span>
                      <strong>
                        {historyPageTicket.user_ad?.full_name ||
                          historyPageTicket.user_name ||
                          shortId(historyPageTicket.user_id)}
                      </strong>
                    </div>
                    <div className="history-fact">
                      <span>Логин</span>
                      <strong>{historyPageTicket.user_ad?.login || "—"}</strong>
                    </div>
                    <div className="history-fact">
                      <span>Почта</span>
                      <strong>{historyPageTicket.user_ad?.email || "—"}</strong>
                    </div>
                    <div className="history-fact">
                      <span>Руководитель</span>
                      <strong>
                        {historyPageTicket.user_ad?.manager || "—"}
                      </strong>
                    </div>
                  </div>
                  <div className="history-fact-block">
                    <div className="history-fact-title">Оператор</div>
                    <div className="history-fact">
                      <span>ФИО</span>
                      <strong>
                        {historyPageTicket.assignee_name || "—"}
                      </strong>
                    </div>
                    <div className="history-fact">
                      <span>Логин</span>
                      <strong>
                        {historyPageTicket.assignee_email
                          ? historyPageTicket.assignee_email.split("@")[0]
                          : "—"}
                      </strong>
                    </div>
                    <div className="history-fact">
                      <span>Почта</span>
                      <strong>{historyPageTicket.assignee_email || "—"}</strong>
                    </div>
                  </div>
                  <div className="history-fact-block">
                    <div className="history-fact-title">Чат</div>
                    <div className="history-fact">
                      <span>Создан</span>
                      <strong>
                        {new Date(historyPageTicket.created_at).toLocaleString(
                          "ru-RU",
                        )}
                      </strong>
                    </div>
                    <div className="history-fact">
                      <span>Закрыт</span>
                      <strong>
                        {[
                          "RESOLVED",
                          "CLOSED",
                          "CANCELLED",
                        ].includes(historyPageTicket.status)
                          ? new Date(historyPageTicket.updated_at).toLocaleString(
                              "ru-RU",
                            )
                          : "—"}
                      </strong>
                    </div>
                    <div className="history-fact">
                      <span>Времени затрачено</span>
                      <strong>
                        {fmtDuration(
                          new Date(historyPageTicket.updated_at).getTime() -
                            new Date(historyPageTicket.created_at).getTime(),
                        )}
                      </strong>
                    </div>
                  </div>
                </section>
                <section className="detail-section">
              {current?.user_rating ? (
                <section className="detail-section">
                  <div className="detail-label">ОЦЕНКА ПОЛЬЗОВАТЕЛЯ</div>
                  <div className="user-rating-row">
                    <span className="user-rating-stars">
                      {"★".repeat(current.user_rating)}
                      {"☆".repeat(5 - current.user_rating)}
                    </span>
                    <span className="muted">{current.user_rating}/5</span>
                  </div>
                </section>
              ) : null}
              <div className="detail-label">ПЕРЕМЕЩЕНИЯ</div>
                  <div className="assignment-history">
                    <span className="history-line" />
                    {(historyMovesExpanded
                      ? historyMoves
                      : historyMoves.slice(0, 3)
                      ).map((event) => (
                      <div
                        className="history-event"
                        key={`${event.created_at}-${event.actor_id}`}
                      >
                        {moveText(event, (id) => shortId(id))}
                        <time>{ago(event.created_at)}</time>
                      </div>
                    ))}
                    {!historyMoves.length && (
                      <div className="history-event">Перемещений пока не было</div>
                    )}
                  </div>
                  {/* Owner (2026-11-19): always present, like in the workspace. */}
                  <button
                    className="quiet-action"
                    onClick={() =>
                      setHistoryMovesExpanded(!historyMovesExpanded)
                    }
                  >
                    {historyMovesExpanded
                      ? "Свернуть"
                      : "Посмотреть полностью"}
                  </button>
                </section>
                <section className="detail-section">
                  {/* Owner (2026-11-19): SLA works for any ticket now. */}
                  <div className="detail-label">SLA</div>
                  <button
                    type="button"
                    className="sla-card history-sla-card"
                    onClick={() => void openSlaHistory(historyPageTicket)}
                  >
                    <span className="sla-card-title">SLA</span>
                    <span className="sla-card-sub">
                      Посмотреть статусы и SLA
                    </span>
                  </button>
                </section>
                <section className="detail-section">
                  <div className="detail-label">ТЕГИ</div>
                  <div className="tag-list">
                    {historyPageTicket.tags.length ? (
                      historyPageTicket.tags.map((tag) => (
                        <span className="tag" key={tag}>
                          {tag}
                        </span>
                      ))
                    ) : (
                      <span className="muted">Без тегов</span>
                    )}
                  </div>
                </section>
                <section className="detail-section">
                  <div
                    className={`status-card ${historyPageTicket.status.toLowerCase()}`}
                  >
                    <span className="status-card-dot" />
                    <span className="status-card-name">
                      {statusName[historyPageTicket.status]}
                    </span>
                  </div>
                </section>
              </aside>
              </div>
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
                        <td>{ticket.user_login || shortId(ticket.user_id)}</td>
                        <td>
                          {ticket.assignee_name ||
                            (ticket.assignee_id
                              ? ticket.assignee_id === operatorId
                                ? "Я"
                                : shortId(ticket.assignee_id)
                              : "—")}
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
