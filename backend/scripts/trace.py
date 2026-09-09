"""Narrate one decision, stage by stage, using the real code paths.

A learning and debugging aid: it calls the same functions the API calls and prints what
happens between a request arriving and a movie coming back.

    python -m scripts.trace
    python -m scripts.trace --genres comedy,romance --max-runtime 120 --min-rating 7
"""

import argparse
import asyncio
import sys
from collections import Counter
from datetime import date

from app.config import get_settings
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.engine import DecisionRequest, decide
from app.engine.constraints import MIN_VOTE_COUNT, failures
from app.engine.decide import BAND_FRACTION, MIN_BAND, band_size, rank
from app.engine.scoring import WEIGHTS, adjusted_rating
from app.services import catalog
from app.tmdb.client import NETFLIX, PRIME_VIDEO, DiscoverFilters, TMDbClient

TODAY = date.today()
SEED = "trace-session:1"

PROVIDER_NAMES = {NETFLIX: "Netflix", PRIME_VIDEO: "Prime Video"}


def banner(number: int, title: str) -> None:
    print(f"\n{'─' * 78}\nSTEP {number}   {title}\n{'─' * 78}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Narrate one decision.")
    p.add_argument("--genres", default="action,science-fiction")
    p.add_argument("--max-runtime", type=int, default=120)
    p.add_argument("--min-rating", type=float, default=None)
    p.add_argument("--min-year", type=int, default=None)
    return p.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    if not settings.tmdb_api_token or get_engine() is None:
        sys.exit("TMDB_API_TOKEN and DATABASE_URL must both be set in backend/.env")

    async with TMDbClient(settings.tmdb_api_token, settings.tmdb_base_url) as client:
        genre_list = await client.genres()
        by_slug = {g.name.lower().replace(" ", "-"): g.id for g in genre_list}
        names = {g.id: g.name for g in genre_list}
        genre_ids = frozenset(
            by_slug[s.strip().lower()] for s in args.genres.split(",") if s.strip()
        )

        request = DecisionRequest(
            provider_ids=frozenset({NETFLIX, PRIME_VIDEO}),
            genre_ids=genre_ids,
            max_runtime=args.max_runtime,
            min_rating=args.min_rating,
            min_year=args.min_year,
        )

        # ---------------------------------------------------------------- 1
        banner(1, "What the user asked for  (api/ builds this from the JSON body)")
        services = ", ".join(PROVIDER_NAMES[p] for p in sorted(request.provider_ids))
        print(f"  services     {services}")
        print(f"  genres       {', '.join(names[g] for g in sorted(request.genre_ids)) or 'any'}")
        print(f"  max runtime  {request.max_runtime} min")
        print(f"  min rating   {request.min_rating or 'any'}")
        print(f"  min year     {request.min_year or 'any'}")
        print("\n  This is a DecisionRequest — engine/models.py. Plain data, no HTTP.")

        # ---------------------------------------------------------------- 2
        banner(2, "Ask TMDb for candidates  (services/catalog.py -> tmdb/client.py)")
        filters = DiscoverFilters(
            provider_ids=request.provider_ids,
            genre_ids=request.genre_ids,
            max_runtime=request.max_runtime,
            min_rating=request.min_rating,
            min_year=request.min_year,
        )
        print("  the query TMDb actually receives:")
        for key, value in sorted(filters.as_params().items()):
            print(f"    {key:<32}{value}")

        first = await client.discover(filters, page=1)
        print(f"\n  TMDb says {first.total_results:,} films match.")

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            candidates = await catalog.fetch_candidates(client, db, request)
            await db.commit()
        print(f"  We pulled {len(candidates)} of them (3 pages max) and cached them.")
        known = sum(1 for c in candidates if c.runtime_minutes is not None)
        print(f"  {known} of {len(candidates)} already have a known runtime from the cache.")

        # ---------------------------------------------------------------- 3
        banner(3, "Eliminate  (engine/constraints.py — the hard rules)")
        tally: Counter[str] = Counter()
        eligible = []
        for movie in candidates:
            failed = failures(movie, request, frozenset(), TODAY)
            if failed:
                for constraint in failed:
                    tally[constraint.value] += 1
            else:
                eligible.append(movie)
        print(f"  started with {len(candidates)}")
        for reason, count in tally.most_common():
            print(f"    -{count:>3}  failed {reason}")
        print(f"  {len(eligible)} eligible\n")
        print(f"  Note: vote_count < {MIN_VOTE_COUNT} is our own quality floor, not the user's.")
        print("  A movie can fail several rules at once, so these do not sum to the drop.")

        if not eligible:
            print("\n  Nothing eligible — the API would answer 409 with relaxation hints.")
            return 1

        # ---------------------------------------------------------------- 4
        banner(4, "Score and rank  (engine/scoring.py, then engine/decide.py)")
        print("  weights: " + ", ".join(f"{k} {v}" for k, v in WEIGHTS.items()))
        ranked = rank(candidates, request, frozenset(), TODAY)
        size = band_size(len(ranked))
        header = f"  {'#':>3}  {'total':>6}" + "".join(f"{k:>13}" for k in WEIGHTS) + "   title"
        print("\n" + header)
        print("  " + "-" * (len(header) - 2))
        for i, scored in enumerate(ranked[:10], start=1):
            marker = "*" if i <= size else " "
            row = f"  {i:>3}{marker} {scored.breakdown.total:>6.3f}"
            row += "".join(
                f"{WEIGHTS[k] * getattr(scored.breakdown, k):>13.3f}" for k in WEIGHTS
            )
            print(f"{row}   {scored.movie.title[:34]}")
        print(f"\n  * = the band: top {size} of {len(ranked)}")
        formula = f"min({len(ranked)}, max({MIN_BAND}, ceil({len(ranked)} x {BAND_FRACTION})))"
        print(f"    band = {formula} = {size}")

        # ---------------------------------------------------------------- 5
        banner(5, "Pick one from the band  (engine/decide.py)")
        decision = decide(candidates, request, frozenset(), SEED, TODAY)
        assert decision.movie is not None
        position = next(
            i for i, s in enumerate(ranked, start=1) if s.movie.tmdb_id == decision.movie.tmdb_id
        )
        print(f'  seed "{SEED}"  ->  rank #{position} of the band  ->  {decision.movie.title}')
        print("\n  Same seed always gives the same movie, which is why the engine's tests")
        print("  are plain equality checks. A different attempt number moves the pick.")
        for attempt in range(2, 5):
            other = decide(candidates, request, frozenset(), f"trace-session:{attempt}", TODAY)
            assert other.movie is not None
            print(f'    seed "trace-session:{attempt}"  ->  {other.movie.title}')

        # ---------------------------------------------------------------- 6
        banner(6, "Verify and fill in the details  (services/decision.py)")
        print("  Search results carry no runtime and do not say which service holds the film,")
        print("  so we fetch details for the winner only — one request, not sixty.")
        async with sessionmaker() as db:
            details = await catalog.hydrate(client, db, decision.movie.tmdb_id)
            await db.commit()
        runtime = details.runtime_minutes
        print(f"\n  real runtime  {runtime} min  (limit was {request.max_runtime})")
        if runtime and runtime > request.max_runtime:
            print("  OVER THE LIMIT — TMDb's filter leaked. decide() re-runs without it.")
        else:
            print("  within the limit, so this pick stands")
        yours = [p.name for p in details.flatrate_providers if p.id in request.provider_ids]
        print(f"  on your services: {', '.join(yours) or 'none'}")
        print(f"  rating {details.vote_average} raw from {details.vote_count:,} votes")
        print(f"         {adjusted_rating(decision.movie):.2f} after shrinking toward the mean")

        # ---------------------------------------------------------------- 7
        banner(7, "What gets written down  (repositories/)")
        print("  decision_requests   1 row — the filters above")
        print("  recommendations     1 row — this movie, its score, every component")
        print("  movies              upserted for every candidate we saw")
        print("  movie_providers     upserted for the winner")
        print("  feedback            nothing yet; written when the user accepts or rejects")
        print("\n  The score breakdown is stored so a bad pick can be explained later.")
        print(f"  breakdown: {decision.breakdown}")

    return 0


async def main() -> int:
    """Run the trace, then close the pool inside the same event loop.

    Disposing in a second asyncio.run() would try to close live connections on an
    already-closed loop, which fails noisily even though the work succeeded.
    """
    try:
        return await run()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
