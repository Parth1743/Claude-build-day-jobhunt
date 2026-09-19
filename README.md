# jobhunt

A local-first CLI for running a job search:

- **Ledger**: an append-only record of your experience, projects, education, certifications, achievements and skills. Every edit is snapshotted, so you can see how your profile evolved.
- **Jobs**: save postings, score fit against your ledger, get tailored resume bullets and a cover letter grounded only in ledger facts, and track each application through a pipeline.
- **Roles and roadmaps**: define target roles, see which required skills you have and which are gaps, and generate a prioritised skill-up plan. Finishing a roadmap item writes the new skill back into the ledger.

Everything is stored in a single SQLite file under `data/`. Only the AI features call the Claude API.

Two front ends share the same database and logic: a **web UI** (React, served by FastAPI) and a **CLI**.

## Install

```bash
cd jobhunt
pip install -e ".[dev]"
cp .env.example .env      # then put your key in it, or export ANTHROPIC_API_KEY
jobhunt init
```

On Windows PowerShell, set the key with `$env:ANTHROPIC_API_KEY = "sk-ant-..."` for the session.

The app also reads a `.env` file on startup from the current directory, the project root (`jobhunt/.env`) or the package directory. Use `KEY=VALUE` lines; a line containing only an `sk-ant-...` key is accepted as `ANTHROPIC_API_KEY`. Real environment variables always win over `.env`. Restart `jobhunt serve` after changing it.

## Discovering openings

The **Discover** page searches job boards for you, scores every posting against the skills in your ledger, and shows them with an Apply link. Save the interesting ones into the tracker with one click and run the fit analysis there.

| Source | Coverage | Key |
| --- | --- | --- |
| JSearch (RapidAPI) | Postings from LinkedIn, Indeed, Naukri, Glassdoor and company sites via Google Jobs | free tier key from RapidAPI |
| Adzuna | Thousands of boards, by country (India, US, UK and more) | free app id and key |
| Remotive | Curated remote jobs | none |
| RemoteOK | Remote tech jobs | none |
| Arbeitnow | Remote and European tech jobs | none |

LinkedIn and Naukri do not offer public job-search APIs and prohibit scraping, so the app never scrapes them. Their postings are reached through JSearch, and every search also shows pre-filled links that open the same query on LinkedIn, Naukri, Indeed, Glassdoor, Foundit, Wellfound and Google Jobs directly.

Matching is local and free: a posting scores on how many of your ledger skills it mentions, how closely its title matches your target roles, and how recent it is. Keys, default location, country and the remote-only preference live in the Sources panel on the Discover page.

```bash
jobhunt discover sources --set-key rapidapi_key=... --enable jsearch,remotive,remoteok --location "Bengaluru, India" --country in
jobhunt discover run "Platform Engineer"
jobhunt discover show 12
jobhunt discover save 12
jobhunt discover links "Platform Engineer" --location "Bengaluru, India"
```

## AI providers

The AI features work with any of these providers. Pick one on the **Settings** page (or with `jobhunt settings set`), paste a key, and press **Test connection**.

| Provider | Default model | Key variable | How it connects |
| --- | --- | --- | --- |
| Anthropic Claude | `claude-opus-5` | `ANTHROPIC_API_KEY` | Anthropic SDK, native structured outputs |
| OpenAI | `gpt-4.1` | `OPENAI_API_KEY` | Chat Completions with JSON schema |
| Google Gemini | `gemini-2.5-flash` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini's OpenAI-compatible endpoint |
| Groq | `llama-3.3-70b-versatile` | `GROQ_API_KEY` | OpenAI-compatible endpoint |
| OpenRouter | `anthropic/claude-sonnet-4` | `OPENROUTER_API_KEY` | OpenAI-compatible endpoint, any routed model |

Keys saved in Settings take precedence over environment variables. Every provider returns the same validated structures; for the OpenAI-compatible ones the app first asks for a JSON-schema response, falls back to JSON mode with the schema in the prompt if the model or gateway rejects that, and repairs the output once if it fails validation. Model IDs are editable, so you can use any model your provider offers. You can also point a provider at a custom base URL for a proxy or gateway.

```bash
jobhunt settings show
jobhunt settings set --provider groq --model llama-3.3-70b-versatile --key gsk_...
jobhunt settings test
```

## Concurrency

The web server is safe for several people using it at once. SQLite runs in write-ahead-log mode so readers never block on a writer, each request gets its own connection, and concurrent writers wait up to 30 seconds instead of failing. There are no user accounts: everyone who can reach the server shares one ledger, so keep it on localhost or behind your own authentication.

## Web UI

```bash
cd jobhunt/web/frontend && npm install && npm run build && cd ../../..
jobhunt serve                      # http://127.0.0.1:8000
```

Pages:

- **Dashboard**: stat tiles, pipeline funnel, per-role readiness, recent jobs and ledger activity. Shows a setup guide when everything is empty.
- **Ledger**: entries with kind filter and retired toggle, add/edit modal with per-entry history, skills view with evidence, full change history, Markdown export, and the resume import flow (upload, Claude extracts, you tick what to keep).
- **Target roles**: cards with coverage bars. Add a role and let Claude suggest its typical required skills.
- **Role detail**: have/gap chips for every required and nice-to-have skill, linked jobs, and the roadmap. Generate with hours per week and horizon, expand items for steps and resources, start, skip, or complete. Completing writes the skill into the ledger.
- **Jobs**: status tabs with counts, fit scores, inline status change, save-a-job modal with optional analyze-on-save.
- **Job detail**: fit meter, matched and missing skills, keywords, red flags, tailored bullets and cover letter with copy buttons, editable description, notes and status history.

AI actions run as background tasks and the UI polls, so nothing blocks while Claude works. If the server has no API key, AI buttons return a clear message and everything else still works.

The interactive API reference is at `/api/docs`.

### Frontend development

```bash
jobhunt serve --reload             # API on :8000
cd jobhunt/web/frontend && npm run dev   # Vite dev server on :5173, proxies /api
```

## API

All routes live under `/api` and return JSON.

| Area | Routes |
| --- | --- |
| meta | `GET /config`, `GET /status`, `GET /tasks/{id}` |
| settings | `GET /settings`, `PUT /settings`, `POST /settings/test` (task) |
| discover | `GET /discover`, `PUT /discover/settings`, `POST /discover/run` (task), `GET /discover/links`, `GET /discover/jobs`, `GET /discover/jobs/{id}`, `POST /discover/jobs/{id}/save`, `POST /discover/jobs/{id}/dismiss`, `POST /discover/jobs/{id}/restore` |
| ledger | `GET/POST /ledger`, `GET/PATCH/DELETE /ledger/{id}`, `GET /ledger/{id}/history`, `GET /ledger/history`, `GET /ledger/skills`, `GET /ledger/export`, `POST /ledger/import` (multipart, returns a task), `POST /ledger/import/commit` |
| roles | `GET/POST /roles`, `GET/PATCH /roles/{id}`, `POST /roles/suggest` (task), `GET /roles/{id}/roadmap`, `POST /roles/{id}/roadmap/generate` (task) |
| roadmap | `GET /roadmap/{item_id}`, `POST /roadmap/{item_id}/status` |
| jobs | `GET/POST /jobs`, `GET /jobs/funnel`, `GET/PATCH /jobs/{id}`, `POST /jobs/{id}/status`, `POST /jobs/{id}/notes`, `POST /jobs/{id}/analyze` (task) |

Task-returning routes respond `202` with `{id, status}`. Poll `GET /api/tasks/{id}` until `status` is `done` (read `result`) or `error` (read `error`).

## Quick start

```bash
# 1. Seed the ledger from your resume (PDF, Markdown or text). You confirm before anything is saved.
jobhunt ledger import resume.pdf
jobhunt ledger list
jobhunt ledger edit 3 --add-skills "Terraform,Helm"

# 2. Define what you are aiming for. --ai fills typical required skills.
jobhunt role add "Platform Engineer" --ai
jobhunt role show "Platform Engineer"        # have / gap per skill

# 3. Save a posting and analyze it.
jobhunt job add "Globex" "Senior Platform Engineer" --role "Platform Engineer" --jd posting.txt --analyze
jobhunt job status 1 applied --note "via referral"

# 4. Build the roadmap from your gaps and the postings you saved.
jobhunt roadmap generate "Platform Engineer" --hours 10 --weeks 12
jobhunt roadmap item 2
jobhunt roadmap start 2
jobhunt roadmap done 2 --level intermediate --proof https://github.com/you/k8s-lab

jobhunt status
```

`job analyze` writes `analysis.md`, `bullets.md` and `cover_letter.md` to `data/out/<id>-<company>-<title>/` so you can paste from them.

## CLI commands

| Group | Commands |
| --- | --- |
| top level | `init`, `status`, `serve` |
| `settings` | `show`, `set`, `clear-key`, `test` |
| `discover` | `run`, `list`, `show`, `save`, `dismiss`, `links`, `sources` |
| `ledger` | `add`, `list`, `show`, `edit`, `retire`, `history`, `skills`, `export`, `import` (AI) |
| `role` | `add` (`--ai` optional), `list`, `show`, `set-skills` |
| `job` | `add`, `jd`, `list`, `show`, `analyze` (AI), `materials`, `status`, `note`, `funnel` |
| `roadmap` | `generate` (AI), `show`, `item`, `start`, `done`, `skip` |

Run any command with `--help` for options.

Ledger kinds: `experience`, `education`, `skill`, `certification`, `project`, `achievement`.
Skill levels: `beginner`, `intermediate`, `advanced`, `expert`.
Job statuses: `saved`, `applied`, `screening`, `interview`, `offer`, `rejected`, `withdrawn`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | unset | Provider keys; the Settings page can store them instead |
| `JOBHUNT_PROVIDER` | `anthropic` | Provider when none is chosen in Settings |
| `JOBHUNT_MODEL` | provider default | Model when none is chosen in Settings |
| `JOBHUNT_HOME` | `./data` | Where the database and generated files live |
| `JOBHUNT_FALLBACKS` | `1` | Set to `0` to disable Anthropic server-side refusal fallbacks |

## Design notes

- The ledger is the single source of truth. Every AI prompt receives the rendered profile and is instructed to never invent facts. Tailored bullets cite which ledger entry they came from.
- Ledger changes are never destructive. `retire` hides an entry; `ledger_events` keeps a full snapshot of every create, update and retire.
- Regenerating a roadmap replaces open items but keeps completed ones.
- Nothing here submits applications for you. Automated submission violates most job boards' terms and is deliberately out of scope. The tool prepares materials and tracks what you submitted.

## Tests

```bash
pytest
```

Tests run fully offline; they use a temporary `JOBHUNT_HOME`. The API tests use FastAPI's test client, so the frontend build is not required for them.

## Layout

```
jobhunt/
  jobhunt/            Python package
    cli.py            Typer CLI (thin layer over services)
    services.py       Use cases shared by CLI and API
    ledger.py jobs.py roles.py db.py   SQLite storage
    ai.py             Claude calls with structured outputs
    web/api.py        FastAPI app, serves /api and the built SPA
    web/tasks.py      Background task registry for AI calls
    web/frontend/     React + TypeScript + Vite source (builds into web/static)
  tests/
```
