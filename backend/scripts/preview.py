"""Drive the real chain from the command line: TMDb -> mappers -> engine -> one movie.

Everything the API will do in M4, minus the database and the web layer. Useful for
sanity-checking the engine's taste against the live catalogue.

    python -m scripts.preview --genres action,science-fiction --max-runtime 120
    python -m scripts.preview --min-rating 8 --reject 3
"""

import argparse
import asyncio
import sys
from datetime import date

from app.config import get_settings
from app.engine import DecisionRequest, decide
from app.engine.constraints import counts_if_relaxed
from app.tmdb.client import NETFLIX, PRIME_VIDEO, DiscoverFilters, TMDbClient
from app.tmdb.errors import TMDbError
from app.tmdb.mappers import to_candidate

PROVIDERS = {"netflix": NETFLIX, "prime": PRIME_VIDEO}
PAGES = 3
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pick one movie.")
    p.add_argument("--providers", default="netflix,prime", help="netflix,prime")
    p.add_argument("--genres", default="", help="genre names, e.g. action,comedy")
    p.add_argument("--max-runtime", type=int, default=120)
    p.add_argument("--min-rating", type=float, default=None)
    p.add_argument("--session", default="preview-session")
    p.add_argument("--reject", type=int, default=0, help="simulate N rejections first")
    return p.parse_args()


def resolve_genres(names: str, lookup: dict[str, int]) -> frozenset[int]:
    if not names.strip():
        return frozenset()
    ids = set()
    for raw in names.split(","):
        key = raw.strip().lower().replace(" ", "-")
        if key not in lookup:
            sys.exit(f"Unknown genre {raw.strip()!r}. Options: {', '.join(sorted(lookup))}")
        ids.add(lookup[key])
    return frozenset(ids)


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    if not settings.tmdb_api_token:
        sys.exit("TMDB_API_TOKEN is not set (see backend/.env.example)")

    provider_ids = frozenset(PROVIDERS[p.strip().lower()] for p in args.providers.split(","))

    async with TMDbClient(settings.tmdb_api_token, settings.tmdb_base_url) as client:
        genre_list = await client.genres()
        by_slug = {g.name.lower().replace(" ", "-"): g.id for g in genre_list}
        names_by_id = {g.id: g.name for g in genre_list}
        genre_ids = resolve_genres(args.genres, by_slug)

        filters = DiscoverFilters(
            provider_ids=provider_ids,
            genre_ids=genre_ids,
            max_runtime=args.max_runtime,
            min_rating=args.min_rating,
        )

        first = await client.discover(filters, page=1)
        rest = await asyncio.gather(
            *(client.discover(filters, page=n) for n in range(2, min(PAGES, first.total_pages) + 1))
        )

        seen: dict[int, object] = {}
        for page in (first, *rest):
            for movie in page.movies:
                seen.setdefault(movie.tmdb_id, movie)
        candidates = [to_candidate(m, provider_ids) for m in seen.values()]  # type: ignore[arg-type]

        request = DecisionRequest(
            provider_ids=provider_ids,
            genre_ids=genre_ids,
            max_runtime=args.max_runtime,
            min_rating=args.min_rating,
        )

        print(f"TMDb matched {first.total_results:,}; pulled {len(candidates)} candidates\n")

        rejected: set[int] = set()
        for attempt in range(1, args.reject + 2):
            decision = decide(
                candidates, request, frozenset(rejected), f"{args.session}:{attempt}", date.today()
            )
            if not decision.found:
                print("No movie fits those constraints.")
                hints = counts_if_relaxed(candidates, request, frozenset(rejected), date.today())
                for constraint, count in sorted(hints.items(), key=lambda kv: -kv[1]):
                    if count:
                        print(f"  relaxing {constraint.value:<8} would unlock {count} more")
                return 1

            assert decision.movie is not None
            if attempt <= args.reject:
                print(f"  attempt {attempt}: rejected {decision.movie.title}")
                rejected.add(decision.movie.tmdb_id)
                continue

            details = await client.movie_details(decision.movie.tmdb_id)
            year = details.release_date.year if details.release_date else "?"
            runtime = f"{details.runtime_minutes} min" if details.runtime_minutes else "runtime ?"
            services = ", ".join(p.name for p in details.flatrate_providers) or "unknown"

            print(f"  {details.title} ({year})")
            print(f"  {runtime}  ·  {details.vote_average:.1f} from {details.vote_count:,} votes")
            print(f"  {', '.join(names_by_id.get(g, str(g)) for g in sorted(details.genre_ids))}")
            print(f"  on {services}")
            print(f"\n  {details.overview[:280]}")
            if details.poster_path:
                print(f"\n  {IMAGE_BASE}{details.poster_path}")
            print(
                f"\n  score {decision.breakdown.total:.3f}"  # type: ignore[union-attr]
                f"  ·  drawn from top {decision.band_size} of {decision.candidate_count}"
            )
            print("  driven by: " + ", ".join(
                f"{h.component} {h.contribution:.3f}" for h in decision.highlights
            ))
            return 0
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except TMDbError as exc:
        print(f"TMDb error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
