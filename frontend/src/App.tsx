import { useState } from "react";

import { ApiError, NoCandidatesError, api } from "./api/client";
import { NoResults } from "./components/NoResults";
import { Result } from "./components/Result";
import { Setup } from "./components/Setup";
import type { Constraints, Decision, Movie, RejectReason, RelaxationHint } from "./types";

type Screen =
  | { name: "setup" }
  | { name: "result"; decision: Decision }
  | { name: "empty"; hints: RelaxationHint[] }
  | { name: "accepted"; movie: Movie };

export default function App() {
  const [screen, setScreen] = useState<Screen>({ name: "setup" });
  const [constraints, setConstraints] = useState<Constraints | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Every call goes through here so busy/error handling is written once. */
  async function run(work: () => Promise<Screen>) {
    setBusy(true);
    setError(null);
    try {
      setScreen(await work());
    } catch (caught) {
      if (caught instanceof NoCandidatesError) {
        setScreen({ name: "empty", hints: caught.hints });
      } else if (caught instanceof ApiError) {
        setError(caught.message);
      } else {
        setError("Something went wrong.");
      }
    } finally {
      setBusy(false);
    }
  }

  function decide(next: Constraints) {
    setConstraints(next);
    return run(async () => ({ name: "result", decision: await api.decide(next) }));
  }

  function reject(reason: RejectReason) {
    if (screen.name !== "result") return;
    const { request_id, recommendation_id } = screen.decision;
    return run(async () => ({
      name: "result",
      decision: await api.reject(request_id, recommendation_id, reason),
    }));
  }

  function accept() {
    if (screen.name !== "result") return;
    const { request_id, recommendation_id } = screen.decision;
    return run(async () => {
      const { movie } = await api.accept(request_id, recommendation_id);
      return { name: "accepted", movie };
    });
  }

  return (
    <main className="app">
      <header>
        <h1 className="wordmark" onClick={() => setScreen({ name: "setup" })}>
          JustPick
        </h1>
        <p className="tagline">One movie. Not forty.</p>
      </header>

      {error && <p className="error">{error}</p>}

      {screen.name === "setup" && (
        <Setup onSubmit={decide} busy={busy} initial={constraints ?? undefined} />
      )}

      {screen.name === "result" && (
        <Result
          decision={screen.decision}
          busy={busy}
          onReject={reject}
          onAccept={accept}
          onStartOver={() => setScreen({ name: "setup" })}
        />
      )}

      {screen.name === "empty" && constraints && (
        <NoResults
          hints={screen.hints}
          constraints={constraints}
          onRelax={decide}
          onStartOver={() => setScreen({ name: "setup" })}
        />
      )}

      {screen.name === "accepted" && (
        <section className="accepted">
          <h1>Enjoy {screen.movie.title}.</h1>
          <p>
            {screen.movie.providers.map((p) => p.name).join(" or ") || "Go watch it"}
            {screen.movie.runtime_minutes ? ` · ${screen.movie.runtime_minutes} min` : ""}
          </p>
          <button type="button" className="secondary" onClick={() => setScreen({ name: "setup" })}>
            Pick another
          </button>
        </section>
      )}

      <footer>
        This product uses the TMDB API but is not endorsed or certified by TMDB.
        Availability data from JustWatch via TMDB.
      </footer>
    </main>
  );
}
