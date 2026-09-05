import { useState } from "react";

import type { Decision, RejectReason } from "../types";
import { REJECT_REASONS } from "../types";

interface Props {
  decision: Decision;
  busy: boolean;
  onReject: (reason: RejectReason) => void;
  onAccept: () => void;
  onStartOver: () => void;
}

export function Result({ decision, busy, onReject, onAccept, onStartOver }: Props) {
  const [choosingReason, setChoosingReason] = useState(false);
  const { movie } = decision;

  const meta = [
    movie.release_year,
    movie.runtime_minutes ? `${movie.runtime_minutes} min` : null,
    `★ ${movie.vote_average.toFixed(1)}`,
  ].filter(Boolean);

  return (
    <article className="result">
      <div className="poster">
        {movie.poster_url ? (
          <img src={movie.poster_url} alt={`${movie.title} poster`} />
        ) : (
          <div className="poster-fallback">{movie.title}</div>
        )}
      </div>

      <div className="details">
        <h1>{movie.title}</h1>
        <p className="meta">{meta.join(" · ")}</p>

        {movie.providers.length > 0 && (
          <p className="providers">
            Watch on <strong>{movie.providers.map((p) => p.name).join(" or ")}</strong>
          </p>
        )}

        <ul className="why">
          {decision.why.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>

        <p className="overview">{movie.overview}</p>

        {choosingReason ? (
          <div className="reasons">
            <p className="hint">What's wrong with it?</p>
            <div className="chips">
              {REJECT_REASONS.map((reason) => (
                <button
                  key={reason.value}
                  type="button"
                  className="chip"
                  disabled={busy}
                  onClick={() => {
                    setChoosingReason(false);
                    onReject(reason.value);
                  }}
                >
                  {reason.label}
                </button>
              ))}
            </div>
            <button type="button" className="link" onClick={() => setChoosingReason(false)}>
              Never mind
            </button>
          </div>
        ) : (
          <div className="actions">
            <button type="button" className="primary" disabled={busy} onClick={onAccept}>
              Watch this
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => setChoosingReason(true)}
            >
              {busy ? "…" : "Something else"}
            </button>
          </div>
        )}

        <p className="footnote">
          <a href={movie.tmdb_url} target="_blank" rel="noreferrer">
            View on TMDB
          </a>
          {" · "}
          <button type="button" className="link" onClick={onStartOver}>
            Change filters
          </button>
        </p>
      </div>
    </article>
  );
}
