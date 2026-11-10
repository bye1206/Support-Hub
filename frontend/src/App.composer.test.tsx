// @vitest-environment jsdom
// Stage-8 security requirement (docs/06 §8): the composer MUST separate the
// public reply from the internal note - two different endpoints, never mixed.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import App from "./App";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const TICKET_ID = "11111111-2222-3333-4444-555555555555";
const CONVERSATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

const ticket = {
  ticket_id: TICKET_ID,
  conversation_id: CONVERSATION_ID,
  user_id: "99999999-8888-7777-6666-555555555555",
  status: "OPEN",
  priority: "NORMAL",
  assignee_id: null,
  category_id: null,
  tags: [] as string[],
  created_at: "2026-11-10T10:00:00Z",
  updated_at: "2026-11-10T10:00:00Z",
};

type Call = { url: string; init?: RequestInit };

class FakeWebSocket {
  static last: FakeWebSocket | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.last = this;
  }
  // No-op: the reconnect timer must never fire inside a test.
  close(): void {}
  send(): void {}
}

function jsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
  };
}

function stubNetwork() {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    // Route order matters: specific subpaths first, then queue, then the card.
    if (url.includes("/me")) {
      return jsonResponse({
        operator_id: "op-1",
        email: "op@corp.test",
        display_name: "op@corp.test",
        role: "OPERATOR",
      });
    }
    if (url.includes("/categories")) return jsonResponse({ categories: [] });
    if (url.includes("/notes")) return jsonResponse({ notes: [] });
    if (url.includes("/assignment-history")) return jsonResponse({ events: [] });
    if (url.includes("/tag-details")) return jsonResponse({ tags: [] });
    if (url.includes("/users/")) return jsonResponse({ tickets: [] });
    if (url.includes("/tickets?")) {
      return jsonResponse({ tickets: [ticket], limit: 50, offset: 0 });
    }
    if (url.includes(`/tickets/${TICKET_ID}`)) {
      return jsonResponse({ ...ticket, messages: [] });
    }
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("WebSocket", FakeWebSocket);
  return calls;
}

async function openTicket(calls: Call[]) {
  render(<App />);
  // The queue row shows the short ticket id.
  const row = await screen.findByText("#11111111");
  fireEvent.click(row);
  // The composer appears once the ticket card is loaded.
  await screen.findByLabelText("Публичный ответ");
  return calls;
}

describe("operator composer mode separation (docs/06 §8)", () => {
  beforeEach(() => {
    sessionStorage.setItem(
      "support-hub-operator",
      JSON.stringify({ token: "dev-token", email: "op@corp.test", name: "Оператор" }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("reply mode posts the text to the public replies endpoint", async () => {
    const calls = await openTicket(stubNetwork());

    fireEvent.change(screen.getByLabelText("Публичный ответ"), {
      target: { value: "Передаём специалисту" },
    });
    fireEvent.click(screen.getByText("Отправить ответ ↗"));

    await waitFor(() => {
      expect(
        calls.some(
          (c) =>
            c.url.includes(`/tickets/${TICKET_ID}/replies`) &&
            c.init?.method === "POST" &&
            JSON.parse(String(c.init.body)).text === "Передаём специалисту",
        ),
      ).toBe(true);
    });
  });

  it("note mode posts the text to the internal notes endpoint", async () => {
    const calls = await openTicket(stubNetwork());

    fireEvent.click(screen.getByRole("tab", { name: /Внутренняя заметка/ }));
    fireEvent.change(screen.getByLabelText("Внутренняя заметка"), {
      target: { value: "Секретная служебная заметка" },
    });
    fireEvent.click(screen.getByText("Добавить заметку ↗"));

    await waitFor(() => {
      expect(
        calls.some(
          (c) =>
            c.url.includes(
              `/conversations/${CONVERSATION_ID}/notes`,
            ) &&
            c.init?.method === "POST" &&
            JSON.parse(String(c.init.body)).body ===
              "Секретная служебная заметка",
        ),
      ).toBe(true);
    });
  });

  it("note mode never calls the public replies endpoint", async () => {
    const calls = await openTicket(stubNetwork());

    fireEvent.click(screen.getByRole("tab", { name: /Внутренняя заметка/ }));
    fireEvent.change(screen.getByLabelText("Внутренняя заметка"), {
      target: { value: "Только для сотрудников" },
    });
    fireEvent.click(screen.getByText("Добавить заметку ↗"));

    await waitFor(() => {
      expect(
        calls.some(
          (c) => c.url.includes(`/conversations/${CONVERSATION_ID}/notes`),
        ),
      ).toBe(true);
    });
    expect(calls.some((c) => c.url.includes("/replies"))).toBe(false);
  });

  it("reply mode never calls the internal notes endpoint", async () => {
    const calls = await openTicket(stubNetwork());

    fireEvent.change(screen.getByLabelText("Публичный ответ"), {
      target: { value: "Ответ пользователю" },
    });
    fireEvent.click(screen.getByText("Отправить ответ ↗"));

    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("/replies"))).toBe(true);
    });
    // GET /conversations/{id}/notes loads the note list; a POST there from
    // reply mode would leak the reply as an internal note.
    expect(
      calls.some((c) => c.url.includes("/notes") && c.init?.method === "POST"),
    ).toBe(false);
  });
});

describe("websocket connection", () => {
  beforeEach(() => {
    sessionStorage.setItem(
      "support-hub-operator",
      JSON.stringify({ token: "dev-token", email: "op@corp.test", name: "Оператор" }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("connects to /ws with the dev token in the query string", async () => {
    const calls = stubNetwork();
    render(<App />);
    await screen.findByText("#11111111");

    expect(FakeWebSocket.last).not.toBeNull();
    expect(FakeWebSocket.last?.url).toContain("/ws?token=dev-token");
    // The socket auth must reuse the same token the REST client sends.
    expect(calls.every((c) => String(c.url).startsWith("/api/v1/operator"))).toBe(
      true,
    );
  });
});
