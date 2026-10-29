# Unified Streaming Platform Backend — Foundation

FastAPI + SQLAlchemy 2 + PostgreSQL starter.

## Included
- Accounts, profiles, server-side session model
- Plans, platforms, plan entitlements, subscriptions
- Platform profiles, providers, companies, networks, configurable sliders
- Viewing sessions, idempotent viewing events, watch progress
- Profile signals and recommendations
- TMDB client and platform-home orchestration
- Dynamic catalogue queries; no bulk movie import

## Local setup
1. Copy `.env.example` to `.env` and configure PostgreSQL and TMDB.
2. `pip install -e .`
3. `python -m app.dev_init` (development only; use Alembic in real deployments)
4. `python -m app.seed_reference`
5. `uvicorn app.main:app --reload`

OpenAPI docs: `http://127.0.0.1:8000/docs`

## Important
The demo identity header in this starter is NOT production authentication. Replace it with real server-side session authentication before deployment. Billing-provider signature verification, payment lifecycle handling, profile creation endpoints, production migrations, kids-content certification filtering, and full view-more pagination are extension points, not completed production features.

Verify all TMDB provider/company/network IDs from current TMDB data. Studio association is not proof of regional streaming availability or playback rights. TMDB content is fetched dynamically; user-owned progress and platform configuration are persisted.
