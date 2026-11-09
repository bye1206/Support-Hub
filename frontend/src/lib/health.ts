export interface HealthPayload {
  status: "ok";
  version?: string;
}

export type HealthPhase = "ok" | "invalid";

/**
 * Validates a /healthz response payload. Kept pure so it is testable
 * without a DOM environment.
 */
export function parseHealth(payload: unknown): HealthPhase {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "status" in payload &&
    (payload as HealthPayload).status === "ok"
  ) {
    return "ok";
  }
  return "invalid";
}
