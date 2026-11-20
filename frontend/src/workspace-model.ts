// Shared types and helpers extracted from App.tsx (decomposition round,
// 2026-11-17) so leaf components can import them without the App monolith.

export type Status =
  | "NEW"
  | "OPEN"
  | "AI_PROCESSING"
  | "PENDING_USER"
  | "RESOLVED"
  | "CLOSED";

export type Ticket = {
  ticket_id: string;
  conversation_id: string;
  user_id: string;
  user_name?: string | null;
  status: Status;
  priority: string;
  assignee_id: string | null;
  category_id: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
  // Owner (2026-11-18): user messages since the operator's last reply —
  // badge in the queue, resets when the operator answers.
  unread_from_user?: number;
  // Owner (2026-11-19): the history shows the operator's name, not a UUID.
  assignee_name?: string | null;
  // Owner (2026-11-19): operator email + user AD facts for the history aside.
  assignee_email?: string | null;
  user_ad?: {
    full_name?: string | null;
    login?: string | null;
    email?: string | null;
    manager?: string | null;
  } | null;
  messages?: Message[];
  session?: { started_at: string; expires_at: string } | null;
  // Owner (2026-11-19): the 15-minute operator reply SLA clock.
  sla?: { deadline: string | null; breached_at: string | null } | null;
};

export type SlaHistoryEvent = {
  kind: string;
  from_status: string | null;
  to_status: string | null;
  changed_at: string;
};

export type Message = {
  message_id: string;
  sequence_no: number;
  author_type: string;
  // Owner (2026-11-19): WHO wrote the message (operator/user real name).
  author_name?: string | null;
  text: string;
  created_at: string;
  // Owner (2026-11-19): files travel with the message in both directions.
  attachments?: MessageAttachmentInfo[];
};

export type MessageAttachmentInfo = {
  id: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
};

// AD group with its description (GetGroupBox layout, owner 2026-11-17).
export type AdGroup = { name: string; description?: string };

export const statusName: Record<Status, string> = {
  NEW: "Без назначения",
  OPEN: "В работе",
  AI_PROCESSING: "Обработка ИИ",
  PENDING_USER: "Ждём пользователя",
  RESOLVED: "Решён",
  CLOSED: "Закрыт",
};

export const shortId = (value: string) => value.slice(0, 8).toUpperCase();

export const ago = (value: string) => {
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

export const authorLabels: Record<string, string> = {
  USER: "Пользователь",
  OPERATOR: "Оператор",
  AI: "ИИ",
  SYSTEM: "Система",
};

export const messageHeading = (authorType: string) =>
  authorLabels[authorType] || authorType;

export const initials = (value: string) =>
  value
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((x) => x[0].toUpperCase())
    .join("") || "SH";

// Owner (2026-11-17): the queue shows "Фамилия И.О." instead of the full
// name. Source order differs: Tag profiles give "Имя Фамилия" (2 words),
// AD-style records are "Фамилия Имя Отчество" (3 words).
export const shortFio = (fullName: string) => {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return fullName;
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) {
    const [first, last] = parts;
    return `${last} ${first[0].toUpperCase()}.`;
  }
  const [last, first, middle] = parts;
  return `${last} ${first[0].toUpperCase()}.${middle[0].toUpperCase()}.`;
};
