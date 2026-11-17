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

export type Message = {
  message_id: string;
  sequence_no: number;
  author_type: string;
  text: string;
  created_at: string;
};

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
