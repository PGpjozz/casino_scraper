# Casino Bonus Scraper

Educational screening project that collects three public welcome-bonus listings from one comparison page, structures them with the Anthropic Claude API, stores JSON, and displays the snapshot in a static Next.js page.

## Architecture

1. `scraper/scrape.py` checks `robots.txt`, fetches one public HTML page, and logs HTTP failures without inventing data.
2. `scraper/extract.py` uses BeautifulSoup to pull casino names, bonus copy, terms, and allowed source URLs.
3. One Claude request converts those three snippets into structured fields.
4. `scraper/validate.py` rejects malformed LLM output and refuses to publish numbers that are not present in the source text.
5. Valid results are written to `public/data/casinos.json`.
6. The Next.js app reads that JSON at build time. The live site does not call Anthropic.

Current source: [AskGamblers welcome bonuses](https://www.askgamblers.com/casino-bonuses/welcome). `robots.txt` allows that path. The scraper does not follow `/visit/` affiliate links. PlayMichigan’s comparison page allows the path in `robots.txt`, but requests from this environment received an HTTP 403 challenge page, so it is not the live source.

## Prerequisites

- Python 3.11 or newer (developed with Python 3.14)
- Node.js 18 or newer
- An Anthropic API key for running the scraper (not required to view the frontend)

## Python installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
```

## Node.js installation

```bash
npm install
```

## Environment variables

Copy `.env.example` to `.env` and set your key:

```bash
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

Never commit `.env`. The scraper reads `ANTHROPIC_API_KEY` from the environment. You may set `ANTHROPIC_MODEL` to a model ID that your account actually lists.

## Run the scraper

```bash
python -m scraper
```

Equivalent: `python scraper/scrape.py` or `npm run scrape`.

If scraping, validation, or the API call fails, any previously valid `public/data/casinos.json` is left unchanged.

## Run tests

```bash
python -m pytest tests -q
```

API calls are mocked. Tests do not spend Anthropic credits.

## Run the frontend locally

```bash
npm run dev
```

Open http://localhost:3000

## Build and deploy on Vercel

The app uses `output: "export"` so it can be hosted as static files.

1. Run the scraper locally so `public/data/casinos.json` contains real data.
2. `npm run build` produces the `out/` directory.
3. Install Vercel CLI if needed: `npm i -g vercel`
4. From this folder: `vercel login` then `vercel`
5. Do not add `ANTHROPIC_API_KEY` to the Vercel project. The hosted page only serves the committed JSON.

If you prefer the Vercel dashboard, import the GitHub repository, leave environment variables empty, and use the default Next.js settings.

## Publish the repository on GitHub

```bash
git init
git add .
git status
git commit -m "Add casino bonus scraper, tests, and static frontend"
gh auth login
gh repo create casino-bonus-scraper --private --source=. --remote=origin --push
```

Confirm `.env` is not in `git status` before you push.

## Known limitations

- Only the first three welcome cards from one AskGamblers listing are collected.
- AskGamblers is an affiliate publisher. Figures are second-hand, can change, and are localized (this environment received ZAR and EUR amounts).
- Wagering shorthand such as `10xb` and `7x(d+b)` is preserved as bonus-only or deposit-plus-bonus. Mixed multipliers stay null.
- Claude may mark fields `uncertain` or `null`. That is intentional. The scraper does not publish a new file when the API key is missing or the model output fails validation.
- There is no scheduler, database, or account login.
- This is not gambling advice and does not claim operator-official terms.
