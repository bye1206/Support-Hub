import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { HistoryMessages } from "./Timeline";
import { RatingBadge } from "./RatingBadge";
import type { Message, MessageAttachmentInfo } from "./workspace-model";
import "./AdminPanel.css";

type Role = "OPERATOR" | "SUPERVISOR" | "ADMIN";
type Auth = { token: string };
type Operator = {
  operator_id: string;
  email: string;
  display_name: string | null;
  role: Role;
  is_active: boolean;
  presence_status?: string;
  max_active_tickets: number;
  // Owner (2026-11-20): the golden-crown rating in the Сотрудники tab.
  avg_rating?: number | null;
  created_at: string;
};
type AuditEntry = {
  audit_id: string;
  actor_type: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  created_at: string;
};
type Overview = { tickets: number; active_operators: number };
// Owner (2026-11-20): the stats section — per-operator workload, ratings
// and reviews, SLA breaches, and the AI bot counters.
type StatRating = { score: number; review: string | null; created_at: string };
type OperatorStat = {
  operator_id: string;
  name: string;
  email: string;
  dialogs_total: number;
  dialogs_day: number;
  avg_rating: number | null;
  ratings_count: number;
  sla_breached: number;
  ratings: StatRating[];
};
type OperatorDetail = {
  chats: number;
  avg_rating: number | null;
  ratings_count: number;
  ratings: StatRating[];
  sla_breached: number;
  breach_events: string[];
};
type StatDialog = {
  ticket_id: string;
  status: string;
  user_login: string;
  created_at: string;
  updated_at: string;
  score: number | null;
  review: string | null;
};
type StatDialogTicket = {
  ticket_id: string;
  status: string;
  created_at: string;
  messages?: Message[];
};
type AiStat = {
  avg_rating: number | null;
  ratings_count: number;
  ratings: StatRating[];
  chats_closed: number;
  chats_no_handoff: number;
  handoffs: number;
};
type TotalStat = {
  chats_total: number;
  chats_open: number;
  chats_closed: number;
  avg_rating: number | null;
  ratings_count: number;
};
type Category = { category_id: string; name: string; parent_id: string | null; is_active: boolean };
type Tag = { tag_id: string; name: string; is_active: boolean };
type Ticket = {
  ticket_id: string;
  user_id: string;
  user_name?: string | null;
  status: string;
  priority: string;
  assignee_id: string | null;
  pending_assignee_id: string | null;
  created_at: string;
  messages?: Array<{
    message_id: string;
    author_type: string;
    author_name?: string | null;
    text: string;
    created_at: string;
  }>;
};
type Colleague = {
  operator_id: string;
  display_name: string | null;
  email: string;
  presence_status?: string;
  max_active_tickets?: number;
};

const presenceLabels: Record<string, string> = {
  ACTIVE: "Активен",
  LUNCH: "Обед",
  BREAK: "Перерыв",
  OFFLINE: "Офлайн",
};

async function opApi<T>(path: string, auth: Auth, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/operator${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${auth.token}`,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message || "Не удалось выполнить запрос");
  }
  return response.json() as Promise<T>;
}

async function adminApi<T>(path: string, auth: Auth, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/admin${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${auth.token}`,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message || "Не удалось выполнить запрос");
  }
  return response.json() as Promise<T>;
}

const roleLabels: Record<Role, string> = {
  OPERATOR: "Оператор",
  SUPERVISOR: "Супервайзер",
  ADMIN: "Администратор",
};

const ticketStatuses: Record<string, string> = {
  NEW: "Без назначения",
  OPEN: "В работе",
  AI_PROCESSING: "Обработка ИИ",
  PENDING_USER: "Ожидает пользователя",
  RESOLVED: "Решён",
  // Owner (2026-11-23): CLOSED = the session timeout closed it.
  CLOSED: "Таймаут",
};

// Owner (2026-11-20): seconds → "X ч Y мин" for the presence card.
function fmtSeconds(value: number | undefined): string {
  if (value == null) return "—";
  const minutes = Math.floor(value / 60);
  const hours = Math.floor(minutes / 60);
  if (hours > 0) return `${hours} ч ${minutes % 60} мин`;
  if (minutes > 0) return `${minutes} мин`;
  return "<1 мин";
}

const authorLabels: Record<string, string> = {
  USER: "Пользователь",
  OPERATOR: "Оператор",
  AI: "ИИ",
  SYSTEM: "Система",
};
const messageHeading = (authorType: string) =>
  authorLabels[authorType] || authorType;

const shortId = (id: string) => id.slice(0, 8);

const initials = (name: string) =>
  name
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "?";

export function AdminPanel({
  auth,
  selfId,
  role,
  onRoleChange,
}: {
  auth: Auth;
  selfId: string;
  role: Role;
  onRoleChange: (role: Role) => void;
}) {
  const [section, setSection] = useState<"overview" | "stats" | "distribution" | "operators" | "categories" | "tags" | "audit">("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [colleagues, setColleagues] = useState<Colleague[]>([]);
  const [distSelected, setDistSelected] = useState<string | null>(null);
  const [distTicket, setDistTicket] = useState<Ticket | null>(null);
  const [assignFor, setAssignFor] = useState<Ticket | null>(null);
  const [assignTo, setAssignTo] = useState<string | null>(null);
  const [assignPriority, setAssignPriority] = useState("NORMAL");
  const [staffModal, setStaffModal] = useState(false);
  const [unassignedModal, setUnassignedModal] = useState(false);
  const [deleteCategory, setDeleteCategory] = useState<Category | null>(null);
  const [toastMessage, setToastMessage] = useState("");
  const [themesOpen, setThemesOpen] = useState<Category | null>(null);
  const [themeName, setThemeName] = useState("");
  const [categorySearchOpen, setCategorySearchOpen] = useState(false);
  const [categoryQuery, setCategoryQuery] = useState("");
  const categorySearchRef = useRef<HTMLInputElement>(null);
  const [reassignTo, setReassignTo] = useState<Record<string, string>>({});
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  // Owner (2026-11-23, plan item 8): knowledge base reference.
  // Owner (2026-11-25): deleted articles restorable for 14 days.
  // Owner (2026-11-20): stats block, loaded lazily when the tab opens.
  const [statOps, setStatOps] = useState<OperatorStat[]>([]);
  const [statAi, setStatAi] = useState<AiStat | null>(null);
  const [statTotal, setStatTotal] = useState<TotalStat | null>(null);
  const [statDate] = useState("");
  // Owner (2026-11-20): the two-column stats — operator picker, per-card
  // periods (day / month / all), SLA breaches and the dialogs mini-table.
  const [statSearch, setStatSearch] = useState("");
  const [statSelected, setStatSelected] = useState<OperatorStat | null>(null);
  const [chatsPeriod, setChatsPeriod] = useState<{ mode: string; value: string }>({ mode: "all", value: "" });
  const [ratingsPeriod, setRatingsPeriod] = useState<{ mode: string; value: string }>({ mode: "all", value: "" });
  const [slaPeriod, setSlaPeriod] = useState<{ mode: string; value: string }>({ mode: "all", value: "" });
  const [chatsData, setChatsData] = useState<OperatorDetail | null>(null);
  const [ratingsData, setRatingsData] = useState<OperatorDetail | null>(null);
  const [slaData, setSlaData] = useState<OperatorDetail | null>(null);
  // Owner (2026-11-20): the ACTIVE/LUNCH/BREAK/OFFLINE durations card,
  // also with its own day / month / all switcher.
  const [presencePeriod, setPresencePeriod] = useState<{ mode: string; value: string }>({ mode: "all", value: "" });
  const [presenceData, setPresenceData] = useState<Record<string, number> | null>(null);
  const [statDialogs, setStatDialogs] = useState<StatDialog[]>([]);
  const [statDialogDay, setStatDialogDay] = useState("");
  const [statDialogScore, setStatDialogScore] = useState("");
  const [statTicket, setStatTicket] = useState<StatDialogTicket | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [categoryName, setCategoryName] = useState("");
  const [categoryParent, setCategoryParent] = useState("");
  const [tagName, setTagName] = useState("");
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    const requests: Promise<unknown>[] = [
      adminApi<Overview>("/overview", auth).then((data) => active && setOverview(data)),
    ];
    if (role === "ADMIN")
      requests.push(adminApi<{ operators: Operator[] }>("/operators", auth).then((data) => active && setOperators(data.operators)));
    requests.push(adminApi<{ entries: AuditEntry[] }>("/audit", auth).then((data) => active && setAudit(data.entries)));
    requests.push(adminApi<{ categories: Category[] }>("/categories", auth).then((data) => active && setCategories(data.categories)));
    requests.push(adminApi<{ tags: Tag[] }>("/tags", auth).then((data) => active && setTags(data.tags)));
    if (role !== "OPERATOR") {
      requests.push(opApi<{ tickets: Ticket[] }>("/tickets?limit=200", auth).then((data) => active && setTickets(data.tickets)));
      requests.push(opApi<{ colleagues: Colleague[] }>("/colleagues", auth).then((data) => active && setColleagues(data.colleagues)));
    }
    void Promise.all(requests)
      .catch((cause: unknown) => active && setError(cause instanceof Error ? cause.message : "Не удалось загрузить панель"))
      .finally(() => active && setBusy(false));
    return () => { active = false; };
  }, [auth, role]);

  // Owner (2026-11-20): the stats tab fetches on open and on date change.
  useEffect(() => {
    if (section !== "stats") return;
    let active = true;
    const query = statDate ? `?date=${encodeURIComponent(statDate)}` : "";
    void Promise.all([
      adminApi<{ operators: OperatorStat[] }>(`/stats/operators${query}`, auth),
      adminApi<AiStat>("/stats/ai", auth),
      adminApi<TotalStat>("/stats/total", auth),
    ])
      .then(([ops, ai, total]) => {
        if (!active) return;
        setStatOps(ops.operators);
        setStatAi(ai);
        setStatTotal(total);
      })
      .catch((cause: unknown) =>
        active && setError(cause instanceof Error ? cause.message : "Не удалось загрузить статистику"),
      );
    return () => { active = false; };
  }, [auth, section, statDate]);

  // Owner (2026-11-20): per-card counters for the selected operator.
  useEffect(() => {
    if (section !== "stats" || !statSelected) return;
    let active = true;
    const build = (period: { mode: string; value: string }) => {
      if (period.mode === "day") return `period=day&date=${encodeURIComponent(period.value)}`;
      if (period.mode === "month") return `period=month&month=${encodeURIComponent(period.value)}`;
      return "period=all";
    };
    const base = `/stats/operator/${statSelected.operator_id}`;
    void Promise.all([
      adminApi<OperatorDetail>(`${base}?${build(chatsPeriod)}`, auth),
      adminApi<OperatorDetail>(`${base}?${build(ratingsPeriod)}`, auth),
      adminApi<OperatorDetail>(`${base}?${build(slaPeriod)}`, auth),
      adminApi<Record<string, number>>(`${base}/presence?${build(presencePeriod)}`, auth),
    ])
      .then(([chats, ratings, sla, presence]) => {
        if (!active) return;
        setChatsData(chats);
        setRatingsData(ratings);
        setSlaData(sla);
        setPresenceData(presence);
      })
      .catch((cause: unknown) =>
        active && setError(cause instanceof Error ? cause.message : "Не удалось загрузить карточки"),
      );
    return () => { active = false; };
  }, [auth, section, statSelected, chatsPeriod, ratingsPeriod, slaPeriod, presencePeriod]);

  // Owner (2026-11-20): the dialogs mini-table for the selected operator.
  useEffect(() => {
    if (section !== "stats" || !statSelected) return;
    let active = true;
    const params = new URLSearchParams({ limit: "10" });
    if (statDialogDay) params.set("date", statDialogDay);
    if (statDialogScore) params.set("min_score", statDialogScore);
    void adminApi<{ dialogs: StatDialog[] }>(
      `/stats/operator/${statSelected.operator_id}/dialogs?${params.toString()}`,
      auth,
    )
      .then((data) => active && setStatDialogs(data.dialogs))
      .catch(() => active && setStatDialogs([]));
    return () => { active = false; };
  }, [auth, section, statSelected, statDialogDay, statDialogScore]);

  // Owner (2026-11-20): open a dialog's full history from the mini table.
  const openStatTicket = useCallback(
    async (ticketId: string) => {
      try {
        const card = await opApi<StatDialogTicket>(`/tickets/${ticketId}`, auth);
        setStatTicket(card);
      } catch {
        setError("Не удалось открыть обращение");
      }
    },
    [auth],
  );
  const downloadStatAttachment = useCallback(async (attachment: MessageAttachmentInfo) => {
    const response = await fetch(`/api/v1/operator/attachments/${attachment.id}/file`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    if (!response.ok) return;
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = attachment.file_name;
    link.click();
    URL.revokeObjectURL(url);
  }, [auth.token]);

  // Presence changes constantly; refresh staff statuses quietly.
  // Perf (2026-11-17): guard against overlapping polls (a slow answer used
  // to stack the next tick's requests) and skip when the tab is hidden.
  const refreshingRef = useRef(false);
  useEffect(() => {
    const refresh = () => {
      if (refreshingRef.current || document.hidden) return;
      refreshingRef.current = true;
      void (async () => {
        try {
          if (role === "ADMIN")
            await adminApi<{ operators: Operator[] }>("/operators", auth)
              .then((data) => setOperators(data.operators))
              .catch(() => {});
          if (role !== "OPERATOR") {
            await Promise.all([
              opApi<{ colleagues: Colleague[] }>("/colleagues", auth)
                .then((data) => setColleagues(data.colleagues))
                .catch(() => {}),
              // Owner request 2026-11-13: new chats must appear in the
              // distribution panel without reopening it.
              opApi<{ tickets: Ticket[] }>("/tickets?limit=200", auth)
                .then((data) => setTickets(data.tickets))
                .catch(() => {}),
            ]);
          }
        } finally {
          refreshingRef.current = false;
        }
      })();
    };
    // Owner request 2026-11-13: 3 s so new chats reach the distribution
    // panel almost instantly.
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [auth, role]);

  const changeRole = async (operator: Operator, nextRole: Role) => {
    try {
      const updated = await adminApi<Operator>(`/operators/${operator.operator_id}/role`, auth, {
        method: "PATCH",
        body: JSON.stringify({ role: nextRole }),
      });
      setOperators((items) => items.map((item) => item.operator_id === updated.operator_id ? updated : item));
      if (updated.operator_id === selfId)
        onRoleChange(updated.role);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Роль не обновлена");
    }
  };

  const changeLimit = async (operator: Operator, limit: number) => {
    if (!Number.isFinite(limit) || limit < 1 || limit > 100 || limit === operator.max_active_tickets)
      return;
    try {
      const updated = await adminApi<Operator>(`/operators/${operator.operator_id}/limit`, auth, {
        method: "PATCH",
        body: JSON.stringify({ max_active_tickets: limit }),
      });
      setOperators((items) => items.map((item) => item.operator_id === updated.operator_id ? updated : item));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Лимит не обновлён");
    }
  };

  const deactivate = async (operator: Operator) => {
    if (!window.confirm(`Отключить профиль ${operator.email}? Активные обращения будут переназначены выбранному сотруднику.`))
      return;
    try {
      const updated = await adminApi<Operator>(`/operators/${operator.operator_id}/deactivate`, auth, {
        method: "POST",
        body: JSON.stringify({ reassign_to: reassignTo[operator.operator_id] || null }),
      });
      setOperators((items) => items.map((item) => item.operator_id === updated.operator_id ? updated : item));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось отключить профиль");
    }
  };

  const saveCategory = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const category = await adminApi<Category>("/categories", auth, {
        method: "POST",
        body: JSON.stringify({ name: categoryName, parent_id: categoryParent || null }),
      });
      setCategories((items) => [...items.filter((item) => item.category_id !== category.category_id), category].sort((a, b) => a.name.localeCompare(b.name, "ru")));
      setCategoryName("");
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Категория не сохранена"); }
  };

  const addTheme = async (event: FormEvent) => {
    event.preventDefault();
    if (!themesOpen) return;
    try {
      const theme = await adminApi<Category>("/categories", auth, {
        method: "POST",
        body: JSON.stringify({ name: themeName, parent_id: themesOpen.category_id }),
      });
      setCategories((items) => [...items.filter((item) => item.category_id !== theme.category_id), theme].sort((a, b) => a.name.localeCompare(b.name, "ru")));
      setThemeName("");
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Тема не сохранена"); }
  };

  const saveTag = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const tag = await adminApi<Tag>("/tags", auth, { method: "POST", body: JSON.stringify({ name: tagName }) });
      setTags((items) => [...items.filter((item) => item.tag_id !== tag.tag_id), tag].sort((a, b) => a.name.localeCompare(b.name, "ru")));
      setTagName("");
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Тег не сохранён"); }
  };

  const updateCategory = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingCategory) return;
    try {
      const updated = await adminApi<Category>(`/categories/${editingCategory.category_id}`, auth, {
        method: "PUT",
        body: JSON.stringify({ name: editingCategory.name, parent_id: editingCategory.parent_id }),
      });
      setCategories((items) => items.map((item) => item.category_id === updated.category_id ? updated : item));
      setEditingCategory(null);
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Категория не обновлена"); }
  };

  const updateTag = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingTag) return;
    try {
      const updated = await adminApi<Tag>(`/tags/${editingTag.tag_id}`, auth, {
        method: "PUT",
        body: JSON.stringify({ name: editingTag.name }),
      });
      setTags((items) => items.map((item) => item.tag_id === updated.tag_id ? updated : item));
      setEditingTag(null);
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Тег не обновлён"); }
  };

  const setDirectoryActive = async (kind: "categories" | "tags", id: string, active: boolean) => {
    try {
      await adminApi(`/${kind}/${id}/${active ? "activate" : "deactivate"}`, auth, { method: "POST" });
      if (kind === "categories") setCategories((items) => items.map((item) => item.category_id === id ? { ...item, is_active: active } : item));
      else setTags((items) => items.map((item) => item.tag_id === id ? { ...item, is_active: active } : item));
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Изменение не сохранено"); }
  };

  // Owner (2026-11-23): hard delete for tags — a used tag needs a second,
  // explicit confirmation (its links to tickets are removed too).
  const deleteTag = async (tag: Tag) => {
    const run = (force: boolean) =>
      adminApi<{ deleted: boolean; links_removed: number }>(
        `/tags/${tag.tag_id}${force ? "?force=true" : ""}`,
        auth,
        { method: "DELETE" },
      );
    try {
      await run(false);
      setTags((items) => items.filter((item) => item.tag_id !== tag.tag_id));
      setToastMessage(`Тег «${tag.name}» удалён`);
      setError("");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "";
      if (!message.includes("принудительное")) {
        setError(message || "Тег не удалён");
        return;
      }
      if (!window.confirm(`Тег «${tag.name}» привязан к обращениям. Удалить его и снять с этих обращений?`)) return;
      try {
        const result = await run(true);
        setTags((items) => items.filter((item) => item.tag_id !== tag.tag_id));
        setToastMessage(`Тег «${tag.name}» удалён${result.links_removed ? `, снят с ${result.links_removed} обращен.` : ""}`);
        setError("");
      } catch (causeForce) {
        setError(causeForce instanceof Error ? causeForce.message : "Тег не удалён");
      }
    }
  };

  const confirmCategoryDelete = async (categoryId: string) => {
    try {
      const result = await adminApi<{ deleted: boolean; deactivated: boolean }>(
        `/categories/${categoryId}`,
        auth,
        { method: "DELETE" },
      );
      setDeleteCategory(null);
      if (result.deleted) {
        setCategories((items) => items.filter((item) => item.category_id !== categoryId));
        setToastMessage("Категория удалена");
      } else {
        setCategories((items) => items.map((item) => item.category_id === categoryId ? { ...item, is_active: false } : item));
        setToastMessage("Категория используется в обращениях — она отключена и скрыта из выбора");
      }
      window.setTimeout(() => setToastMessage(""), 4000);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось удалить категорию");
    }
  };

  const refreshTickets = async () => {
    const data = await opApi<{ tickets: Ticket[] }>("/tickets?limit=200", auth);
    setTickets(data.tickets);
  };

  // Perf (2026-11-17): derived lists were recomputed on every render —
  // with a 3 s poll and hundreds of tickets that is real work per keystroke.
  const activeTickets = useMemo(
    () => tickets.filter((ticket) => ticket.status !== "RESOLVED" && ticket.status !== "CLOSED"),
    [tickets],
  );
  const staff: Array<Operator | Colleague> = useMemo(
    () => role === "ADMIN"
      ? operators
      : colleagues.map((colleague) => ({ ...colleague, max_active_tickets: 5 })),
    [role, operators, colleagues],
  );
  // Distribution targets active operators only: an offline / on-break
  // colleague is shown grayed out and cannot receive chats.
  const isReachable = useCallback((member: Operator | Colleague) =>
    (member as Operator).is_active !== false &&
    (member.presence_status ?? "ACTIVE") === "ACTIVE", []);
  const distStaff = useMemo(() => staff.filter(isReachable), [staff, isReachable]);
  const activeByOperator = useMemo(() => {
    const counts = new Map<string, number>();
    for (const ticket of activeTickets)
      if (ticket.assignee_id)
        counts.set(ticket.assignee_id, (counts.get(ticket.assignee_id) ?? 0) + 1);
    return counts;
  }, [activeTickets]);
  const loadOf = useCallback(
    (operatorId: string) => activeByOperator.get(operatorId) ?? 0,
    [activeByOperator],
  );
  const nameOf = useCallback((operatorId: string | null) => {
    if (!operatorId) return null;
    const member = staff.find((item) => item.operator_id === operatorId);
    return member ? member.display_name || member.email : shortId(operatorId);
  }, [staff]);
  const operatorTickets = useMemo(
    () => distSelected
      ? activeTickets.filter((ticket) => ticket.assignee_id === distSelected)
      : [],
    [distSelected, activeTickets],
  );
  // Чаты у ИИ в распределении не нужны.
  const unassignedTickets = useMemo(
    () => activeTickets.filter(
      (ticket) => !ticket.assignee_id && ticket.status !== "AI_PROCESSING",
    ),
    [activeTickets],
  );

  const openAssign = (ticket: Ticket) => {
    setAssignFor(ticket);
    setAssignTo(null);
    setAssignPriority(ticket.priority || "NORMAL");
  };

  const confirmAssign = async () => {
    if (!assignFor || !assignTo) return;
    try {
      if (assignPriority !== assignFor.priority) {
        await opApi(`/tickets/${assignFor.ticket_id}/priority`, auth, {
          method: "PATCH",
          body: JSON.stringify({ priority: assignPriority }),
        });
      }
      await opApi(`/tickets/${assignFor.ticket_id}/assign`, auth, {
        method: "POST",
        body: JSON.stringify({ assignee_id: assignTo }),
      });
      await refreshTickets();
      setAssignFor(null);
      setAssignTo(null);
      setDistTicket(null);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось назначить обращение");
    }
  };

  const renderChatMessages = (ticket: Ticket | null) => (
    <div className="history-messages">
      {(ticket?.messages ?? []).map((message) => (
        <div
          key={message.message_id}
          className={`message ${message.author_type === "OPERATOR" ? "from-operator" : ""}`}
        >
          <div className="message-content">
            <div className="message-heading">
              <strong>
                {message.author_name || messageHeading(message.author_type)}
              </strong>
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
      {!(ticket?.messages ?? []).length && (
        <div className="past-empty">Сообщений пока нет.</div>
      )}
    </div>
  );

  const openDistTicket = async (ticket: Ticket) => {
    try {
      const card = await opApi<Ticket>(`/tickets/${ticket.ticket_id}`, auth);
      setDistTicket(card);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось открыть чат");
    }
  };

  const renderDistTicket = (ticket: Ticket) => (
    <div className="dist-ticket" key={ticket.ticket_id}>
      <div className="dist-row">
        <button
          className="dist-row-main"
          onClick={() => void openDistTicket(ticket)}
        >
          <strong>#{shortId(ticket.ticket_id)}</strong>
          <span className="muted">
            {ticket.user_name || `Пользователь ${shortId(ticket.user_id)}`} ·{" "}
            {ticketStatuses[ticket.status] || ticket.status}
          </span>
          {ticket.pending_assignee_id && (
            <span className="pending-badge" title={`Отложено для ${nameOf(ticket.pending_assignee_id) || "сотрудника"}`}>Отложено</span>
          )}
        </button>
        <button className="dist-assign" onClick={() => openAssign(ticket)}>
          Назначить
        </button>
      </div>
    </div>
  );

  return (
    <section className="admin-panel" aria-label="Административная панель">
      <header className="admin-header">
        <div><p className="eyebrow">SUPPORT HUB</p><h1>Панель управления</h1></div>
        <div className="admin-header-actions" />
      </header>
      <nav className="admin-nav" aria-label="Разделы панели">
        {([ ["overview", "Обзор"], ["stats", "Статистика"], ["distribution", "Распределение"], ["operators", "Сотрудники"], ["categories", "Категории"], ["tags", "Теги"], ["audit", "Аудит"] ] as const)
          .filter(([key]) => (key !== "operators" || role === "ADMIN") && (key !== "categories" && key !== "tags" || role !== "OPERATOR"))
          .map(([key, label]) => <button key={key} className={section === key ? "active" : ""} onClick={() => setSection(key)}>{label}</button>)}
      </nav>
      <div className="admin-content">
        {error && <div className="admin-error" role="alert">{error}</div>}
        {toastMessage && <div className="admin-toast" role="status">{toastMessage}</div>}
        {busy ? <p className="admin-muted">Загружаем данные…</p> : (
          <>
            {section === "overview" && <>
              <p className="admin-intro">Состояние рабочего пространства</p>
              <div className="admin-stats">
                <article><span>Обращений в системе</span><strong>{overview?.tickets ?? "—"}</strong></article>
                <article><span>Активных операторов</span><strong>{overview?.active_operators ?? "—"}</strong></article>
              </div>
              <div className="admin-note"><strong>Доступы</strong><span>Ваша роль: {roleLabels[role]}. Действия проверяются сервером.</span></div>
            </>}
            {section === "distribution" && <>
              <p className="admin-intro">Нажмите на сотрудника — откроется окно со всеми его чатами: история, информация и кнопка «Назначить». Справа — неназначенные чаты. Чаты в обработке ИИ здесь не отображаются.</p>
              <div className="dist-full">
                <div className="dist-layout">
                  <div className="dist-col">
                  <div className="dist-col-title">Сотрудники</div>
                  <div className="dist-grid">
                    {distStaff.slice(0, 10).map((member) => {
                      const load = loadOf(member.operator_id);
                      const max = member.max_active_tickets ?? 5;
                      const full = load >= max;
                      return (
                        <button
                          key={member.operator_id}
                          className={`dist-operator ${full ? "full" : ""}`}
                          onClick={() => {
                            setDistSelected(member.operator_id);
                            setDistTicket(null);
                          }}
                        >
                          <span className="dist-avatar">{initials(member.display_name || member.email)}</span>
                          <span className="dist-name">{member.display_name || member.email}<span>{member.email}</span></span>
                          <span className="dist-load">{load}/{max}{full ? " · полная" : ""}</span>
                        </button>
                      );
                    })}
                    {!distStaff.length && <p className="admin-muted">Нет активных сотрудников.</p>}
                  </div>
                  {distStaff.length > 10 && (
                    <button
                      className="dist-more"
                      onClick={() => setStaffModal(true)}
                    >
                      Показать больше · {distStaff.length}
                    </button>
                  )}
                </div>
                <div className="dist-col">
                  <div className="dist-dialogs">
                    <div className="dist-col-title">Неназначенные чаты</div>
                    {unassignedTickets.slice(0, 10).map((ticket) => renderDistTicket(ticket))}
                    {!unassignedTickets.length && (
                      <p className="admin-muted">Неназначенных чатов нет.</p>
                    )}
                    {unassignedTickets.length > 10 && (
                      <button
                        className="dist-more"
                        onClick={() => setUnassignedModal(true)}
                      >
                        Показать больше · {unassignedTickets.length}
                      </button>
                    )}
                  </div>
                </div>
                </div>
              </div>
            </>}
            {section === "operators" && role === "ADMIN" && <>
              <p className="admin-intro">Профили, роли и лимиты нагрузки. Лимит — сколько активных обращений авто-распределение может назначить сотруднику одновременно (прямая передача не ограничена).</p>
              <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Сотрудник</th><th>Роль</th><th>Ср. оценка</th><th>Лимит</th><th>Статус</th><th>Действие</th></tr></thead><tbody>
                {operators.map((operator) => <tr key={operator.operator_id}><td><strong>{operator.display_name || operator.email}</strong><span>{operator.email}</span></td><td><select value={operator.role} aria-label={`Роль ${operator.email}`} disabled={!operator.is_active} onChange={(event) => void changeRole(operator, event.target.value as Role)}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td><td>{operator.avg_rating != null ? <RatingBadge value={operator.avg_rating} /> : "—"}</td><td><input className="limit-input" type="number" min={1} max={100} defaultValue={operator.max_active_tickets} aria-label={`Лимит обращений ${operator.email}`} disabled={!operator.is_active} onBlur={(event) => void changeLimit(operator, Number(event.target.value))} onKeyDown={(event) => { if (event.key === "Enter") (event.target as HTMLInputElement).blur(); }} /></td><td><span className={`admin-state ${!operator.is_active ? "inactive" : operator.presence_status === "ACTIVE" || !operator.presence_status ? "active" : "away"}`}>{!operator.is_active ? "Отключён" : presenceLabels[operator.presence_status ?? "ACTIVE"]}</span></td><td>{operator.is_active && operator.operator_id !== selfId && <div className="operator-actions"><select aria-label={`Кому переназначить обращения ${operator.email}`} title="Куда передать активные обращения этого сотрудника при отключении" value={reassignTo[operator.operator_id] || ""} onChange={(event) => setReassignTo((values) => ({ ...values, [operator.operator_id]: event.target.value }))}><option value="">Без переназначения</option>{operators.filter((candidate) => candidate.is_active && candidate.operator_id !== operator.operator_id).map((candidate) => <option key={candidate.operator_id} value={candidate.operator_id}>{candidate.display_name || candidate.email}</option>)}</select><button title="Отключить профиль: сотрудник больше не сможет входить; активные обращения уйдут выбранному сотруднику или в общую очередь" onClick={() => void deactivate(operator)}>Отключить</button></div>}</td></tr>)}
              </tbody></table></div>
            </>}
            {section === "categories" && <>
              <p className="admin-intro">Два уровня: категория → тема (у темы подкатегорий нет). Нажмите на категорию, чтобы открыть её темы. Категории и темы используются в окне «Решить обращение» при закрытии чатов.</p>
              <div className="category-toolbar">
                <form className="directory-form" onSubmit={(event) => void saveCategory(event)}>
                  <input required maxLength={255} placeholder="Название категории" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} />
                  <select aria-label="Родительская категория" value={categoryParent} onChange={(event) => setCategoryParent(event.target.value)}><option value="">Верхний уровень (категория)</option>{categories.filter((item) => item.is_active && !item.parent_id).map((item) => <option key={item.category_id} value={item.category_id}>{item.name}</option>)}</select>
                  <button type="submit">Добавить</button>
                </form>
                <div className="category-search">
                  <div
                    className={`admin-inline-search ${categorySearchOpen ? "open" : ""}`}
                  >
                    <input
                      ref={categorySearchRef}
                      tabIndex={categorySearchOpen ? 0 : -1}
                      placeholder="Поиск по категориям и темам"
                      value={categoryQuery}
                      onChange={(event) => setCategoryQuery(event.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className={`icon-button ${categorySearchOpen ? "active-icon" : ""}`}
                    title="Поиск"
                    aria-label="Поиск по категориям"
                    onClick={() => {
                      const opening = !categorySearchOpen;
                      setCategorySearchOpen(opening);
                      if (!opening) setCategoryQuery("");
                      else
                        requestAnimationFrame(() =>
                          requestAnimationFrame(() => categorySearchRef.current?.focus()),
                        );
                    }}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <circle cx="11" cy="11" r="6.5" />
                      <path d="m16 16 4.5 4.5" />
                    </svg>
                    {categoryQuery.trim() && <i className="tool-dot" />}
                  </button>
                </div>
              </div>
              <div className="directory-list">{(() => {
                const query = categoryQuery.trim().toLowerCase();
                const topLevel = categories.filter((category) => !category.parent_id);
                const visible = query
                  ? topLevel.filter(
                      (category) =>
                        category.name.toLowerCase().includes(query) ||
                        categories.some(
                          (theme) =>
                            theme.parent_id === category.category_id &&
                            theme.name.toLowerCase().includes(query),
                        ),
                    )
                  : topLevel;
                return visible.length ? (
                  visible.map((category) => <div key={category.category_id} className={`directory-row ${!category.is_active ? "inactive" : ""}`}>
                    {editingCategory?.category_id === category.category_id ? <form className="directory-edit" onSubmit={(event) => void updateCategory(event)}><input required maxLength={255} value={editingCategory.name} onChange={(event) => setEditingCategory({ ...editingCategory, name: event.target.value })} /><button type="submit">Сохранить</button><button type="button" onClick={() => setEditingCategory(null)}>Отмена</button></form> : <>
                      <button className="directory-open" onClick={() => { setThemesOpen(category); setThemeName(""); }} title="Открыть темы категории">
                        {category.name}
                        <span className="muted">тем: {categories.filter((item) => item.parent_id === category.category_id).length}</span>
                      </button>
                      <span>{category.is_active ? "Активна" : "Отключена"}</span>
                      <div className="directory-actions">
                        {category.is_active && <button onClick={() => setEditingCategory(category)}>Изменить</button>}
                        <button onClick={() => void setDirectoryActive("categories", category.category_id, !category.is_active)}>{category.is_active ? "Отключить" : "Включить"}</button>
                        <button className="directory-delete" title="Удалить" aria-label={`Удалить ${category.name}`} onClick={() => setDeleteCategory(category)}>×</button>
                      </div>
                    </>}
                  </div>)
                ) : (
                  <div className="past-empty">Ничего не найдено.</div>
                );
              })()}</div>
            </>}
            {section === "tags" && <>
              <p className="admin-intro">Метки для группировки и поиска обращений.</p>
              <form className="directory-form" onSubmit={(event) => void saveTag(event)}><input required maxLength={100} placeholder="Название тега" value={tagName} onChange={(event) => setTagName(event.target.value)} /><button type="submit">Добавить</button></form>
              <div className="directory-list">{tags.map((tag) => <div key={tag.tag_id} className={`directory-row ${!tag.is_active ? "inactive" : ""}`}>
                {editingTag?.tag_id === tag.tag_id ? <form className="directory-edit" onSubmit={(event) => void updateTag(event)}><input required maxLength={100} value={editingTag.name} onChange={(event) => setEditingTag({ ...editingTag, name: event.target.value })} /><button type="submit">Сохранить</button><button type="button" onClick={() => setEditingTag(null)}>Отмена</button></form> : <><span>{tag.name}</span><span>{tag.is_active ? "Активен" : "Отключён"}</span><div className="directory-actions">{tag.is_active && <button onClick={() => setEditingTag(tag)}>Изменить</button>}<button onClick={() => void setDirectoryActive("tags", tag.tag_id, !tag.is_active)}>{tag.is_active ? "Отключить" : "Включить"}</button><button className="directory-delete" onClick={() => void deleteTag(tag)}>Удалить</button></div></>}
              </div>)}</div>
            </>}
            {section === "stats" && (
              <div className="stats-layout">
                {/* Left: employees. */}
                <div className="stats-people">
                  <p className="admin-intro">Сотрудники</p>
                  <input
                    className="stats-search"
                    placeholder="Поиск: ФИО, логин или почта"
                    value={statSearch}
                    onChange={(event) => setStatSearch(event.target.value)}
                  />
                  {statSelected ? (
                    <>
                      <button className="quiet-action" onClick={() => { setStatSelected(null); setChatsData(null); setRatingsData(null); setSlaData(null); }}>
                        ← К списку сотрудников
                      </button>
                      <div className="stats-cards">
                        <article className="stat-card">
                          <span className="stat-card-title">Чаты</span>
                          <strong className="stat-card-value">{chatsData?.chats ?? "—"}</strong>
                          <div className="stat-card-periods">
                            {([["day", "За день"], ["month", "За месяц"], ["all", "За всё время"]] as const).map(([mode, label]) => (
                              <button key={mode} className={chatsPeriod.mode === mode ? "active" : ""} onClick={() => setChatsPeriod({ mode, value: "" })}>{label}</button>
                            ))}
                          </div>
                          {chatsPeriod.mode === "day" && <input type="date" value={chatsPeriod.value} onChange={(event) => setChatsPeriod({ mode: "day", value: event.target.value })} />}
                          {chatsPeriod.mode === "month" && <input type="month" value={chatsPeriod.value} onChange={(event) => setChatsPeriod({ mode: "month", value: event.target.value })} />}
                        </article>
                        <article className="stat-card">
                          <span className="stat-card-title">Оценки</span>
                          <strong className="stat-card-value">{ratingsData?.avg_rating ?? "—"}</strong>
                          <span className="stat-card-sub">{ratingsData?.ratings_count ?? 0} оценок</span>
                          <div className="stat-card-periods">
                            {([["day", "За день"], ["month", "За месяц"], ["all", "За всё время"]] as const).map(([mode, label]) => (
                              <button key={mode} className={ratingsPeriod.mode === mode ? "active" : ""} onClick={() => setRatingsPeriod({ mode, value: "" })}>{label}</button>
                            ))}
                          </div>
                          {ratingsPeriod.mode === "day" && <input type="date" value={ratingsPeriod.value} onChange={(event) => setRatingsPeriod({ mode: "day", value: event.target.value })} />}
                          {ratingsPeriod.mode === "month" && <input type="month" value={ratingsPeriod.value} onChange={(event) => setRatingsPeriod({ mode: "month", value: event.target.value })} />}
                        </article>
                      </div>
                      <article className="stat-card sla-card-stat">
                        <span className="stat-card-title">SLA</span>
                        <strong className="stat-card-value">{slaData?.sla_breached ?? "—"}</strong>
                        <span className="stat-card-sub">просрочек</span>                        <div className="stat-card-periods">
                          {([["day", "За день"], ["month", "За месяц"], ["all", "За всё время"]] as const).map(([mode, label]) => (
                            <button key={mode} className={slaPeriod.mode === mode ? "active" : ""} onClick={() => setSlaPeriod({ mode, value: "" })}>{label}</button>
                          ))}
                        </div>
                        {slaPeriod.mode === "day" && <input type="date" value={slaPeriod.value} onChange={(event) => setSlaPeriod({ mode: "day", value: event.target.value })} />}
                        {slaPeriod.mode === "month" && <input type="month" value={slaPeriod.value} onChange={(event) => setSlaPeriod({ mode: "month", value: event.target.value })} />}
                        {slaData && slaData.breach_events.length > 0 && (
                          <div className="stats-reviews">
                            {slaData.breach_events.slice(0, 10).map((event) => (
                              <div className="stats-review" key={event}>
                                <span className="stats-score bad">!</span>
                                <p>SLA просрочен</p>
                                <time>{new Date(event).toLocaleString("ru-RU")}</time>
                              </div>
                            ))}
                          </div>
                        )}
                      </article>
                      {/* Owner (2026-11-20): how long the operator was
                          ACTIVE / on LUNCH / on BREAK / OFFLINE — day /
                          month / all time, like the other cards. */}
                      <article className="stat-card presence-card">
                        <span className="stat-card-title">Активность</span>
                        <div className="stat-card-periods">
                          {([["day", "За день"], ["month", "За месяц"], ["all", "За всё время"]] as const).map(([mode, label]) => (
                            <button key={mode} className={presencePeriod.mode === mode ? "active" : ""} onClick={() => setPresencePeriod({ mode, value: "" })}>{label}</button>
                          ))}
                        </div>
                        {presencePeriod.mode === "day" && <input type="date" value={presencePeriod.value} onChange={(event) => setPresencePeriod({ mode: "day", value: event.target.value })} />}
                        {presencePeriod.mode === "month" && <input type="month" value={presencePeriod.value} onChange={(event) => setPresencePeriod({ mode: "month", value: event.target.value })} />}
                        <div className="presence-rows">
                          <div className="presence-row"><span>Активен</span><strong>{fmtSeconds(presenceData?.ACTIVE)}</strong></div>
                          <div className="presence-row"><span>На обеде</span><strong>{fmtSeconds(presenceData?.LUNCH)}</strong></div>
                          <div className="presence-row"><span>На перерыве</span><strong>{fmtSeconds(presenceData?.BREAK)}</strong></div>
                          <div className="presence-row"><span>Офлайн</span><strong>{fmtSeconds(presenceData?.OFFLINE)}</strong></div>
                        </div>
                        {/* Owner (2026-11-20): sum per period + the average
                            per working day, so a month reads sensibly. */}
                        {presencePeriod.mode !== "day" && (presenceData?.days ?? 0) > 1 && (
                          <span className="stat-card-sub">≈ {fmtSeconds((presenceData?.ACTIVE ?? 0) / (presenceData?.days ?? 1))} активной работы в день</span>
                        )}
                      </article>
                      <p className="admin-intro">Последние чаты</p>
                      <div className="stats-dialog-filters">
                        <input type="date" value={statDialogDay} onChange={(event) => setStatDialogDay(event.target.value)} />
                        <select value={statDialogScore} onChange={(event) => setStatDialogScore(event.target.value)}>
                          <option value="">Все оценки</option>
                          {[5, 4, 3, 2, 1].map((score) => <option key={score} value={score}>{score}</option>)}
                        </select>
                      </div>
                      <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Чат</th><th>Пользователь</th><th>Статус</th><th>Обновлён</th><th>Оценка</th></tr></thead><tbody>
                        {statDialogs.map((dialog) => (
                          <tr key={dialog.ticket_id} className="stats-row" onClick={() => void openStatTicket(dialog.ticket_id)}>
                            <td><strong>{dialog.ticket_id.slice(0, 8)}</strong>{dialog.review ? <span className="stats-cell-review"> · {dialog.review.slice(0, 40)}</span> : ""}</td>
                            <td>{dialog.user_login || "—"}</td>
                            <td>{dialog.status}</td>
                            <td>{new Date(dialog.updated_at).toLocaleString("ru-RU")}</td>
                            <td>{dialog.score ?? "—"}</td>
                          </tr>
                        ))}
                        {!statDialogs.length && <tr><td colSpan={5}>Чатов не найдено</td></tr>}
                      </tbody></table></div>
                    </>
                  ) : (
                    <div className="stats-people-list">
                      {statOps
                        .filter((operator) => {
                          const needle = statSearch.trim().toLowerCase();
                          if (!needle) return true;
                          return (
                            operator.name.toLowerCase().includes(needle) ||
                            operator.email.toLowerCase().includes(needle)
                          );
                        })
                        .map((operator) => (
                          <button key={operator.operator_id} className="stats-person" onClick={() => setStatSelected(operator)}>
                            <strong>
                              {operator.name}
                              {/* Owner (2026-11-26): the rating next to the name. */}
                              <RatingBadge value={operator.avg_rating} />
                            </strong>
                            <span>{operator.email}</span>
                          </button>
                        ))}
                      {!statOps.length && <p className="admin-muted">Операторов пока нет</p>}
                    </div>
                  )}
                </div>
                {/* Right: the AI bot. */}
                <div className="stats-ai">
                  <p className="admin-intro">ИИ-бот</p>
                  <div className="admin-stats">
                    <article><span>Средняя оценка</span><strong>{statAi?.avg_rating ?? "—"}</strong></article>
                    <article><span>Чатов без перевода</span><strong>{statAi?.chats_no_handoff ?? "—"}</strong></article>
                    <article><span>Переводов на оператора</span><strong>{statAi?.handoffs ?? "—"}</strong></article>
                  </div>
                  {statAi && statAi.ratings.length > 0 && (
                    <div className="stats-reviews">
                      {statAi.ratings.map((rating, index) => (
                        <div className="stats-review" key={`ai-${index}`}>
                          <span className={`stats-score ${rating.score >= 4 ? "good" : rating.score === 3 ? "mid" : "bad"}`}>{rating.score}</span>
                          <p>{rating.review || "Без отзыва"}</p>
                          <time>{new Date(rating.created_at).toLocaleString("ru-RU")}</time>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {/* Owner (2026-11-23): whole-support totals, third column. */}
                <div className="stats-total">
                  <p className="admin-intro">Всего по поддержке</p>
                  <div className="admin-stats">
                    <article><span>Чатов всего</span><strong>{statTotal?.chats_total ?? "—"}</strong></article>
                    <article><span>Открыто сейчас</span><strong>{statTotal?.chats_open ?? "—"}</strong></article>
                    <article><span>Закрыто чатов</span><strong>{statTotal?.chats_closed ?? "—"}</strong></article>
                    <article><span>Средняя оценка</span><strong>{statTotal?.avg_rating ?? "—"}</strong></article>
                  </div>
                  {statTotal && statTotal.ratings_count > 0 && (
                    <p className="admin-muted">Оценок учтено: {statTotal.ratings_count}</p>
                  )}
                </div>
              </div>
            )}
            {section === "audit" && <>
              <p className="admin-intro">Последние действия · показаны только метаданные</p>
              <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Действие</th><th>Объект</th><th>Время</th></tr></thead><tbody>
                {audit.map((entry) => <tr key={entry.audit_id}><td><strong>{entry.action}</strong><span>{entry.actor_type}</span></td><td>{entry.entity_type}{entry.entity_id ? ` · ${entry.entity_id.slice(0, 8)}` : ""}</td><td>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(entry.created_at))}</td></tr>)}
                {!audit.length && <tr><td colSpan={3}>Записей пока нет</td></tr>}
              </tbody></table></div>
            </>}
          </>
        )}
      </div>
      {statTicket && (
        <div
          className="modal-backdrop"
          onClick={() => setStatTicket(null)}
          role="presentation"
        >
          <div
            className="modal dialog-modal"
            role="dialog"
            aria-label="История диалога"
            onClick={(event) => event.stopPropagation()}
          >
            <button className="modal-close" aria-label="Закрыть" onClick={() => setStatTicket(null)}>
              ×
            </button>
            <div className="modal-title">
              Диалог · #{statTicket.ticket_id.slice(0, 8)}
            </div>
            <div className="history-messages">
              <HistoryMessages
                messages={statTicket.messages ?? []}
                onDownload={(attachment) => void downloadStatAttachment(attachment)}
              />
              {!(statTicket.messages ?? []).length && (
                <p className="admin-muted">Сообщений нет</p>
              )}
            </div>
          </div>
        </div>
      )}
      {staffModal && !distSelected && (
        <div
          className="modal-backdrop"
          onClick={() => setStaffModal(false)}
          role="presentation"
        >
          <div
            className="modal wide"
            role="dialog"
            aria-label="Все сотрудники"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">Сотрудники · {distStaff.length}</div>
            <div className="dist-grid">
              {distStaff.map((member) => {
                const load = loadOf(member.operator_id);
                const max = member.max_active_tickets ?? 5;
                const full = load >= max;
                return (
                  <button
                    key={member.operator_id}
                    className={`dist-operator ${full ? "full" : ""}`}
                    onClick={() => {
                      setStaffModal(false);
                      setDistSelected(member.operator_id);
                      setDistTicket(null);
                    }}
                  >
                    <span className="dist-avatar">{initials(member.display_name || member.email)}</span>
                    <span className="dist-name">{member.display_name || member.email}<span>{member.email}</span></span>
                    <span className="dist-load">{load}/{max}{full ? " · полная" : ""}</span>
                  </button>
                );
              })}
            </div>
            <button className="quiet-action" onClick={() => setStaffModal(false)}>
              Закрыть
            </button>
          </div>
        </div>
      )}
      {distSelected && !assignFor && (
        <div
          className="modal-backdrop"
          onClick={() => {
            setDistSelected(null);
            setDistTicket(null);
          }}
          role="presentation"
        >
          <div
            className="modal wide"
            role="dialog"
            aria-label="Диалоги сотрудника"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              Чаты · {nameOf(distSelected) || shortId(distSelected)}
            </div>
            {operatorTickets.map((ticket) => renderDistTicket(ticket))}
            {!operatorTickets.length && (
              <div className="past-empty">Активных чатов нет.</div>
            )}
            <button
              className="quiet-action"
              onClick={() => {
                setDistSelected(null);
                setDistTicket(null);
              }}
            >
              Закрыть
            </button>
          </div>
        </div>
      )}
      {unassignedModal && (
        <div
          className="modal-backdrop"
          onClick={() => setUnassignedModal(false)}
          role="presentation"
        >
          <div
            className="modal wide"
            role="dialog"
            aria-label="Все неназначенные чаты"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              Неназначенные чаты · {unassignedTickets.length}
            </div>
            {unassignedTickets.map((ticket) => renderDistTicket(ticket))}
            {!unassignedTickets.length && (
              <div className="past-empty">Неназначенных чатов нет.</div>
            )}
            <button
              className="quiet-action"
              onClick={() => setUnassignedModal(false)}
            >
              Закрыть
            </button>
          </div>
        </div>
      )}
      {distTicket && (
        <div
          className="modal-backdrop"
          onClick={() => setDistTicket(null)}
          role="presentation"
        >
          <div
            className="modal wide"
            role="dialog"
            aria-label="Чат обращения"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              #{shortId(distTicket.ticket_id)} ·{" "}
              {ticketStatuses[distTicket.status] || distTicket.status}
            </div>
            <div className="muted history-meta">
              {distTicket.user_name || `Пользователь #${shortId(distTicket.user_id)}`}
              {" · приоритет: "}
              {distTicket.priority === "URGENT"
                ? "срочный"
                : distTicket.priority === "HIGH"
                  ? "высокий"
                  : "обычный"}
              {` · открыт ${new Date(distTicket.created_at).toLocaleString("ru-RU")}`}
            </div>
            {renderChatMessages(distTicket)}
            <button
              className="resolve-submit"
              onClick={() => openAssign(distTicket)}
            >
              Назначить сотруднику
            </button>
            <button className="quiet-action" onClick={() => setDistTicket(null)}>
              Закрыть
            </button>
          </div>
        </div>
      )}
      {assignFor && (
        <div
          className="modal-backdrop"
          onClick={() => setAssignFor(null)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-label="Назначить обращение"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              Назначить #{shortId(assignFor.ticket_id)}
            </div>
            <div className="assign-grid">
              {distStaff.map((member) => {
                const load = loadOf(member.operator_id);
                const max = member.max_active_tickets ?? 5;
                return (
                  <button
                    key={member.operator_id}
                    className={`assign-candidate ${assignTo === member.operator_id ? "selected" : ""}`}
                    onClick={() => setAssignTo(member.operator_id)}
                  >
                    <span className="dist-avatar">{initials(member.display_name || member.email)}</span>
                    <span className="dist-name">
                      {member.display_name || member.email}
                      <span>
                        Чатов: {load} из {max}
                        {load >= max ? " · полная загрузка (встанет в отложенные)" : ""}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
            <label className="resolve-label" htmlFor="assign-priority">
              Приоритет чата
              <select
                id="assign-priority"
                value={assignPriority}
                onChange={(event) => setAssignPriority(event.target.value)}
              >
                <option value="NORMAL">Обычный</option>
                <option value="HIGH">Высокий</option>
                <option value="URGENT">Срочный</option>
              </select>
            </label>
            <button
              className="resolve-submit"
              disabled={!assignTo}
              onClick={() => void confirmAssign()}
            >
              Назначить
            </button>
            <button className="quiet-action" onClick={() => setAssignFor(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
      {themesOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setThemesOpen(null)}
          role="presentation"
        >
          <div
            className="modal wide"
            role="dialog"
            aria-label="Темы категории"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">
              Категория «{themesOpen.name}» ·{" "}
              {categories.filter((item) => item.parent_id === themesOpen.category_id).length} тем
            </div>
            <div className="directory-list">
              {categories
                .filter((item) => item.parent_id === themesOpen.category_id)
                .map((theme) => (
                  <div
                    key={theme.category_id}
                    className={`directory-row ${!theme.is_active ? "inactive" : ""}`}
                  >
                    {editingCategory?.category_id === theme.category_id ? (
                      <form className="directory-edit" onSubmit={(event) => void updateCategory(event)}>
                        <input
                          required
                          maxLength={255}
                          value={editingCategory.name}
                          onChange={(event) =>
                            setEditingCategory({ ...editingCategory, name: event.target.value })
                          }
                        />
                        <button type="submit">Сохранить</button>
                        <button type="button" onClick={() => setEditingCategory(null)}>Отмена</button>
                      </form>
                    ) : (
                      <>
                        <span>{theme.name}</span>
                        <span>{theme.is_active ? "Активна" : "Отключена"}</span>
                        <div className="directory-actions">
                          {theme.is_active && (
                            <button onClick={() => setEditingCategory(theme)}>Изменить</button>
                          )}
                          <button
                            onClick={() =>
                              void setDirectoryActive("categories", theme.category_id, !theme.is_active)
                            }
                          >
                            {theme.is_active ? "Отключить" : "Включить"}
                          </button>
                          <button
                            className="directory-delete"
                            title="Удалить"
                            aria-label={`Удалить ${theme.name}`}
                            onClick={() => setDeleteCategory(theme)}
                          >
                            ×
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              {!categories.some((item) => item.parent_id === themesOpen.category_id) && (
                <div className="past-empty">Тем пока нет.</div>
              )}
            </div>
            <form className="directory-form" onSubmit={(event) => void addTheme(event)}>
              <input
                required
                maxLength={255}
                placeholder="Название темы"
                value={themeName}
                onChange={(event) => setThemeName(event.target.value)}
              />
              <button type="submit">Добавить тему</button>
            </form>
            <button className="quiet-action" onClick={() => setThemesOpen(null)}>
              Закрыть
            </button>
          </div>
        </div>
      )}
      {deleteCategory && (
        <div
          className="modal-backdrop"
          onClick={() => setDeleteCategory(null)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-label="Удаление категории"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-title">Удалить категорию?</div>
            <p className="admin-muted" style={{ margin: 0 }}>
              «{deleteCategory.name}»{deleteCategory.parent_id ? "" : " вместе с её темами"} будет
              удалена из справочника и пропадёт из окна «Решить обращение».
              Если она уже использовалась в обращениях, она будет только
              отключена, чтобы история осталась корректной.
            </p>
            <button
              className="resolve-submit"
              onClick={() => void confirmCategoryDelete(deleteCategory.category_id)}
            >
              Да, удалить
            </button>
            <button className="quiet-action" onClick={() => setDeleteCategory(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
