# Railway -> Hetzner + Neon + Fly migration runbook

## Safety invariants

1. Keep all four trading classes at `DRY_RUN=True` during the migration.
2. Never run Telegram polling on Railway and the new active host at the same time.
3. Never commit BullionVault, Telegram, Anthropic, Neon, Fly, or Hetzner secrets.
4. Treat BullionVault as the source of truth for actual holdings/orders.
5. Keep Railway available for rollback until the Hetzner runtime is verified.

## Target layout

- **Hetzner**: primary long-running Guardian trading runtime.
- **Neon**: durable PostgreSQL database for bot/trade logs.
- **Fly.io**: warm/cold standby or shadow deployment with Telegram commands disabled.
- **Railway**: temporary rollback target only until cutover verification completes.

## Phase 1 — shadow deployment

Create `.env.production` from `.env.production.example`.

Required:
- `BV_USERNAME`
- `BV_PASSWORD`
- Telegram secrets
- `DATABASE_URL` from the Neon database `guardian_trading`

For shadow validation:
- `ENABLE_TELEGRAM_COMMANDS=0`
- keep the code-level `DRY_RUN=True`

Start on Hetzner:

```bash
docker compose -f docker-compose.hetzner.yml up -d --build
docker compose -f docker-compose.hetzner.yml logs -f --tail=200
```

Verify:
- BullionVault login succeeds.
- selected bot process remains stable.
- Neon receives rows in `bot_status` / `trade_logs`.
- no Telegram polling conflict appears.
- no real order is submitted.

## Phase 2 — cutover

Order matters:

1. Stop the Railway service first.
2. Confirm Railway process is no longer running.
3. On Hetzner set `ENABLE_TELEGRAM_COMMANDS=1`.
4. Restart the Hetzner container.
5. Send a read-only Telegram command and confirm one response only.
6. Keep `DRY_RUN=True` until a separate trading-go-live decision.

Rollback:
- disable Telegram on Hetzner;
- stop Hetzner container;
- redeploy/restart the previous successful Railway deployment.

## Phase 3 — Fly standby

Fly must use the same image/config but:
- `ENABLE_TELEGRAM_COMMANDS=0`
- `DRY_RUN=True`
- its own persistent volume mounted at `/data`

Do not make Fly and Hetzner simultaneously active Telegram pollers.

## Data notes

Railway currently has no attached volume for this service, so its local SQLite/state files are not a reliable durable migration source. Actual holdings/orders must be reconciled from BullionVault before any later live-trading re-enable.
