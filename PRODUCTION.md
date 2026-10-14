# Production plan (200 casinos, daily updates)

This is a proposal, not a priced quote. Rand figures are order-of-magnitude estimates at October 2026 exchange rates and will move with USD/ZAR, traffic, and model prices.

## Hosting

Run the Next.js snapshot on Vercel (or Cloudflare Pages) and the Python workers on a small always-on or scheduled VM, for example a single Hetzner CX22 or AWS t4g.small in `eu-west-1` / `af-south-1`. A VM is the right place for outbound scraping, retries, and secrets. The public site should stay static so visitors never hold an Anthropic key.

## Scraper workers

Keep one orchestrator and source-specific adapters (`playmichigan.py`, `operator_promotions.py`, …). Each adapter owns robots.txt checks, selectors, and rate limits. Fan out across a queue (Redis or SQS) with concurrency caps per domain. Persist raw HTML alongside structured rows so a parser change can be replayed without refetching.

## PostgreSQL

Use managed PostgreSQL (Neon, RDS, or Hetzner). Relational storage fits this shape: `sources`, `casinos`, `offers`, `offer_snapshots`, `scrape_runs`, `validation_errors`. You need uniqueness on `(casino_id, offer_type)`, JSONB for extra terms, and time-based snapshots for history. Postgres gives constraints, cheap backups, and SQL for “what changed since yesterday”.

Suggested core columns on `offers`: `casino_id`, `welcome_bonus_text`, `wagering_multiplier`, `wagering_applies_to`, `min_deposit_amount`, `min_deposit_currency`, `source_url`, `extracted_at`, `status`. `offer_snapshots` copies those fields on every successful run.

## Backups

Enable daily automated backups with at least 7-day PITR. Once a month restore into a throwaway instance and run `SELECT count(*) FROM offers` plus a known-casino checksum. A backup that has never been restored is not a backup.

## Domain, DNS, HTTPS

Register a `.co.za` or `.com` name (~R150–R400/year). Point an apex and `www` CNAME/ALIAS at the frontend host. Force HTTPS with the host’s certificate. Keep `api.` (if added later) on the same DNS zone.

## Daily scheduling

Use systemd timers, GitHub Actions (with secret protection), or CloudWatch/cron at a quiet UTC hour. Sequence: robots refresh → fetch → extract → validate → write snapshots → publish JSON/CDN invalidate. Skip publish if fewer than a threshold of rows validate.

## Retries, monitoring, alerts

Retry transient HTTP 429/5xx with backoff and honour `Crawl-delay` / `Retry-After`. Log run_id, source, status, duration, offer counts. Alert on: zero successful sources, validation failure rate, stale rows older than 36 hours, 5xx from the public site. A weekly Slack/email digest is enough at this scale; page a human only for complete scrape failure.

## Validation and staleness

Never overwrite a good row with an empty LLM result. Store `last_good_extracted_at`. If a casino is missing for two consecutive days, mark it `stale` in the UI rather than deleting it. Diff yesterday’s multipliers and amounts; large unexplained jumps go to a review queue.

## Security

Keep `ANTHROPIC_API_KEY` in the worker secret store (not the frontend). Rotate quarterly. Restrict SSH/SSM, no public Postgres, least-privilege IAM. Do not log request bodies that could contain keys. Continue to refuse CAPTCHA/login bypass.

## Indicative monthly cost (ZAR)

| Item | Low | High | Notes |
| --- | --- | --- | --- |
| Frontend hosting | R0 | R200 | Vercel/Cloudflare free tier, bandwidth overage possible |
| Worker VM | R150 | R450 | One small cloud instance |
| PostgreSQL | R0 | R350 | Neon free/launch or smallest RDS |
| Domain (amortised) | R15 | R40 | Annual fee spread monthly |
| LLM usage | R200 | R1 200 | 200 casinos × 30 days, one batched request per source, Haiku-class model; spikes if you send full HTML |
| **Total** | **~R365** | **~R2 240** | Excludes labour and paid proxy/CAPTCHA services, which this design does not use |

A realistic starting budget is about **R800–R1 500/month** if you stay on Haiku-class models, one comparison page family, and the free frontend tier. Treat every figure as an estimate.
