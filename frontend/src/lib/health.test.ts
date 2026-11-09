import { describe, expect, it } from "vitest";

import { parseHealth } from "./health";

describe("parseHealth", () => {
  it("accepts a valid health payload", () => {
    expect(parseHealth({ status: "ok", version: "0.1.0" })).toBe("ok");
  });

  it("rejects payloads without status ok", () => {
    expect(parseHealth({ status: "error" })).toBe("invalid");
  });

  it("rejects non-object payloads", () => {
    expect(parseHealth(null)).toBe("invalid");
    expect(parseHealth("ok")).toBe("invalid");
  });
});
