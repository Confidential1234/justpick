/** Mirrors backend/app/api/schemas.py. Kept by hand for now. */

export interface Genre {
  id: number;
  name: string;
}

export interface Provider {
  id: number;
  name: string;
  logo_url: string | null;
}

export interface Movie {
  tmdb_id: number;
  title: string;
  overview: string;
  release_year: number | null;
  runtime_minutes: number | null;
  vote_average: number;
  vote_count: number;
  poster_url: string | null;
  genres: Genre[];
  providers: Provider[];
  tmdb_url: string;
}

export interface Highlight {
  component: string;
  contribution: number;
}

export interface Decision {
  request_id: string;
  recommendation_id: string;
  attempt: number;
  movie: Movie;
  why: string[];
  highlights: Highlight[];
  candidates_remaining: number;
}

export interface RelaxationHint {
  field: "min_rating" | "max_runtime" | "genre_ids" | "provider_ids" | "min_year";
  action: string;
  label: string;
  would_yield: number;
}

export interface Constraints {
  provider_ids: number[];
  genre_ids: number[];
  max_runtime: number;
  min_rating: number | null;
  min_year: number | null;
}

export type RejectReason =
  | "already_seen"
  | "not_in_the_mood"
  | "too_long"
  | "wrong_genre"
  | "looks_bad"
  | "other";

export const REJECT_REASONS: { value: RejectReason; label: string }[] = [
  { value: "already_seen", label: "Seen it" },
  { value: "not_in_the_mood", label: "Not in the mood" },
  { value: "too_long", label: "Too long" },
  { value: "wrong_genre", label: "Wrong vibe" },
  { value: "looks_bad", label: "Looks bad" },
  { value: "other", label: "Something else" },
];
