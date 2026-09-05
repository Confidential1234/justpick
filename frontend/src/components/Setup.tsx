import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Constraints, Genre, Provider } from "../types";

const RUNTIME_MIN = 60;
const RUNTIME_MAX = 240;
const RATINGS = [
  { value: null, label: "Any" },
  { value: 6, label: "6+" },
  { value: 7, label: "7+" },
  { value: 8, label: "8+" },
];

function formatRuntime(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

interface Props {
  onSubmit: (constraints: Constraints) => void;
  busy: boolean;
  initial?: Constraints;
}

export function Setup({ onSubmit, busy, initial }: Props) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [chosenProviders, setChosenProviders] = useState<number[]>(
    initial?.provider_ids ?? [],
  );
  const [chosenGenres, setChosenGenres] = useState<number[]>(initial?.genre_ids ?? []);
  const [maxRuntime, setMaxRuntime] = useState(initial?.max_runtime ?? 120);
  const [minRating, setMinRating] = useState<number | null>(initial?.min_rating ?? null);

  useEffect(() => {
    Promise.all([api.providers(), api.genres()])
      .then(([p, g]) => {
        setProviders(p);
        setGenres(g);
        // Default to everything they could watch on, so the common case is one tap.
        setChosenProviders((current) => (current.length ? current : p.map((x) => x.id)));
      })
      .catch((error: Error) => setLoadError(error.message));
  }, []);

  function toggle(list: number[], id: number): number[] {
    return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
  }

  if (loadError) {
    return <p className="error">{loadError}</p>;
  }

  return (
    <form
      className="setup"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          provider_ids: chosenProviders,
          genre_ids: chosenGenres,
          max_runtime: maxRuntime,
          min_rating: minRating,
        });
      }}
    >
      <fieldset>
        <legend>Where can you watch?</legend>
        <div className="chips">
          {providers.map((provider) => (
            <button
              key={provider.id}
              type="button"
              className={`chip ${chosenProviders.includes(provider.id) ? "on" : ""}`}
              aria-pressed={chosenProviders.includes(provider.id)}
              onClick={() => setChosenProviders((c) => toggle(c, provider.id))}
            >
              {provider.logo_url && <img src={provider.logo_url} alt="" />}
              {provider.name}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>
          In the mood for <span className="hint">optional</span>
        </legend>
        <div className="chips">
          {genres.map((genre) => (
            <button
              key={genre.id}
              type="button"
              className={`chip ${chosenGenres.includes(genre.id) ? "on" : ""}`}
              aria-pressed={chosenGenres.includes(genre.id)}
              onClick={() => setChosenGenres((c) => toggle(c, genre.id))}
            >
              {genre.name}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>
          How much time? <strong className="value">{formatRuntime(maxRuntime)}</strong>
        </legend>
        <input
          type="range"
          min={RUNTIME_MIN}
          max={RUNTIME_MAX}
          step={15}
          value={maxRuntime}
          aria-label="Maximum runtime in minutes"
          onChange={(event) => setMaxRuntime(Number(event.target.value))}
        />
      </fieldset>

      <fieldset>
        <legend>Minimum rating</legend>
        <div className="chips">
          {RATINGS.map((rating) => (
            <button
              key={rating.label}
              type="button"
              className={`chip ${minRating === rating.value ? "on" : ""}`}
              aria-pressed={minRating === rating.value}
              onClick={() => setMinRating(rating.value)}
            >
              {rating.label}
            </button>
          ))}
        </div>
      </fieldset>

      <button
        type="submit"
        className="primary"
        disabled={busy || chosenProviders.length === 0}
      >
        {busy ? "Finding it…" : "Find my movie"}
      </button>
      {chosenProviders.length === 0 && (
        <p className="hint centered">Pick at least one service.</p>
      )}
    </form>
  );
}
