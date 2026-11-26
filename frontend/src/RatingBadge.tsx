// Owner (2026-11-26): the operator's average rating emblem, shared by the
// workspace and the admin panel. Above 4.7 — a golden capsule with a
// crown on top; below — the same capsule, plain color, no crown.
export function RatingBadge({ value }: { value?: number | null }) {
  if (value == null) return null;
  const gold = value > 4.7;
  if (!gold) {
    return (
      <span className="rating-badge" title="Средняя оценка">
        <span className="rating-capsule plain">
          <span className="rating-value">{value}</span>
        </span>
      </span>
    );
  }
  return (
    <span className="rating-badge" title="Средняя оценка">
      <span className="rating-crown-stack">
        <svg className="rating-crown" viewBox="2 2 20 12" aria-hidden="true">
          <path
            d="M2.5 5.5l5 4.2L12 2.5l4.5 7.2 5-4.2-1.8 8H4.3l-1.8-8Z"
            fill="#e8a10e"
          />
        </svg>
        <span className="rating-capsule">
          <span className="rating-value gold">{value}</span>
        </span>
      </span>
    </span>
  );
}
