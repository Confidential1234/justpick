import type {
  Constraints,
  Decision,
  Genre,
  Movie,
  Provider,
  RejectReason,
  RelaxationHint,
} from "../types";

// Same-origin in dev (Vite proxies /api) and in production when the API is behind the
// same domain; VITE_API_URL covers the split-deployment case.
const BASE = `${import.meta.env.VITE_API_URL ?? ""}/api/v1`;

const SESSION_KEY = "justpick.session";

function sessionId(): string {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

/** Nothing matched. Carries what the user could loosen to get results. */
export class NoCandidatesError extends Error {
  constructor(readonly hints: RelaxationHint[]) {
    super("No movies match those constraints.");
    this.name = "NoCandidatesError";
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Session-Id": sessionId(),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection.");
  }

  // The server mints a session id when we did not send a usable one; adopt it so the
  // next request is recognised as the same browser.
  const echoed = response.headers.get("X-Session-Id");
  if (echoed) localStorage.setItem(SESSION_KEY, echoed);

  if (response.ok) return (await response.json()) as T;

  const body = await response.json().catch(() => null);
  if (response.status === 409 && body?.error === "no_candidates") {
    throw new NoCandidatesError(body.relaxation_hints ?? []);
  }
  throw new ApiError(response.status, body?.message ?? "Something went wrong.");
}

export const api = {
  providers: () => request<Provider[]>("/providers"),

  genres: () => request<Genre[]>("/genres"),

  decide: (constraints: Constraints) =>
    request<Decision>("/decisions", {
      method: "POST",
      body: JSON.stringify(constraints),
    }),

  reject: (requestId: string, recommendationId: string, reason: RejectReason) =>
    request<Decision>(`/decisions/${requestId}/reject`, {
      method: "POST",
      body: JSON.stringify({ recommendation_id: recommendationId, reason }),
    }),

  accept: (requestId: string, recommendationId: string) =>
    request<{ status: string; movie: Movie }>(`/decisions/${requestId}/accept`, {
      method: "POST",
      body: JSON.stringify({ recommendation_id: recommendationId }),
    }),
};
