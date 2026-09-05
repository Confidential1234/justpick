import type { Constraints, RelaxationHint } from "../types";

interface Props {
  hints: RelaxationHint[];
  constraints: Constraints;
  onRelax: (relaxed: Constraints) => void;
  onStartOver: () => void;
}

/** Applies one hint to the constraints, so a dead end is one tap from a result. */
function relax(constraints: Constraints, hint: RelaxationHint): Constraints {
  switch (hint.field) {
    case "min_rating":
      return { ...constraints, min_rating: null };
    case "max_runtime":
      return { ...constraints, max_runtime: 240 };
    case "genre_ids":
      return { ...constraints, genre_ids: [] };
    default:
      return constraints;
  }
}

export function NoResults({ hints, constraints, onRelax, onStartOver }: Props) {
  // provider_ids hints are dropped: the app cannot add a subscription for someone.
  const usable = hints.filter((hint) => hint.field !== "provider_ids");

  return (
    <section className="empty">
      <h1>Nothing fits.</h1>
      <p>Those filters are a little too tight. Loosen one?</p>

      <div className="hints">
        {usable.map((hint) => (
          <button
            key={hint.field}
            type="button"
            className="hint-button"
            onClick={() => onRelax(relax(constraints, hint))}
          >
            <span className="hint-label">{hint.label}</span>
            <span className="hint-count">{hint.would_yield.toLocaleString()} movies</span>
          </button>
        ))}
      </div>

      <button type="button" className="secondary" onClick={onStartOver}>
        Change filters
      </button>
    </section>
  );
}
