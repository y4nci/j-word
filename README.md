# jword

Finds jobs, screens them against your CV, writes tailored cover letters and fills in
application forms. A human is in the loop throughout: nothing goes out without your approval,
and the final submit click is always yours.

Same architecture as [autoreview](iosl-ws25-p4-autoreview/): staged services behind a
provider-agnostic `AsyncChatLLM`, source adapters, LLM screening with human override.

```text
onboarding/     Profile        CV + proto cover letter  -> CandidateProfile (experiences with ids)
                  |
onboarding/     Plan           prompt + filters         -> SearchPlan (titles, keywords, criteria, queries)
                  |
discovery/      Discover       source adapters -> dedupe -> hard filters -> full descriptions
                  |
screening/      Screen         LLM fit: include / exclude / unsure (+ human override)
                  |
drafting/       Draft          match requirements -> write letter -> fact-check letter
                  |
                [HUMAN]        edit / approve / reject     (approval is bound to the exact draft)
                  |
submission/     Prepare        package (PDF letter, CV, notes) + browser autofill, no submit
                  |
                [HUMAN]        submit in the browser, then mark as applied
```

| autoreview | jword |
|---|---|
| research question -> refined RQ + SearchPlan | prompt + CV + filters -> profile + SearchPlan |
| arXiv / IEEE / PubMed adapters | Arbeitnow / Bundesagentur / Adzuna / Greenhouse / Lever / Ashby adapters |
| metadata gate + title/abstract screening | hard filters + LLM fit screening |
| chunk -> VDB -> retrieve | LLM selects experiences by id (a profile is small; no VDB needed) |
| synthesis | cover letter + short pitch, then a fact check against the profile |

## Job sources

| Source | Key | Search | Notes |
|---|---|---|---|
| Arbeitnow | none | local keyword filter | Germany/EU, English-friendly, newest ~500 jobs |
| Bundesagentur für Arbeit | public client id | server-side, location + radius | Largest German database. Search: `/pc/v6/jobs`, details: `/pc/v4/jobdetails` (checked live 2026-10) |
| Adzuna | paid `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` (check current pricing) | server-side | Optional aggregator. Descriptions are snippets only. Enabled only when keys are set |
| Greenhouse / Lever / Ashby | none | local keyword filter | Company watchlist (`company_boards`). These are also the sites autofill supports |

LinkedIn and Indeed are not included. Neither has a public job API, and LinkedIn's terms
prohibit scraping and automated applying; accounts get restricted. If you add one later,
make it a separate optional adapter.

## Human-in-the-loop guarantees

Enforced in `applications/models.py`, not just in the UI:

- Only a `HUMAN` actor can move an application to `APPROVED` or `APPLIED`.
- Approval stores a hash of the draft. Editing or regenerating the draft drops it back to `DRAFTED`.
- `prepare` refuses anything that isn't approved or whose draft changed after approval.
- Browser autofill never clicks submit.
- Each draft carries a fact-check list (`unsupported_claims`) of statements the profile doesn't back up.
- Every status change is recorded in `history` with the actor.

## Setup

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # for autofill
cp ../.env.example .env              # add OPENAI_API_KEY
pytest
```

## Usage

### Web UI

```bash
# terminal 1: backend on :8000 (needs OPENAI_API_KEY in backend/.env)
cd backend && source .venv/bin/activate && uvicorn api.main:app --app-dir src --reload

# terminal 2: frontend on :5173 (proxies /api -> :8000)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173:

1. **Profiles**: upload your CV and paste your proto cover letter. Then check the extracted
   profile and fix anything wrong. Letters can only use facts from it.
2. **New search**: prompt, hard filters, and optionally company boards (Greenhouse / Lever / Ashby slugs).
3. **Search**: run Discover → Screen → Draft. Include or exclude any job by hand, and expand a row for details.
4. **Review** each draft: edit it, check the fact-check box, then *Approve this exact text*.
5. **Prepare** opens the form filled in (Greenhouse / Lever / Ashby) or gives you the package.
   You submit it yourself, then click *I submitted it*.

LLM steps run synchronously and can take a minute or two for many jobs; keep the tab open.

### Terminal (interactive)

```bash
cd backend
python scripts/run_pipeline.py \
  --cv ~/Documents/cv.pdf --letter ~/Documents/proto_letter.md \
  --name "Your Name" --email you@example.com --city Berlin --linkedin https://linkedin.com/in/you \
  --prompt "Working student or junior roles in ML engineering, ideally NLP/LLMs" \
  --part-time --working-student --remote --hybrid --location Berlin --lang en --lang de \
  --board greenhouse:n26 --board lever:eu:mistral --board ashby:ramp \
  --min-fit 0.6
```

It shows the extracted profile (check it: drafts can only use facts from it), the search plan,
the screening table, then asks about uncertain jobs. After that it walks through every draft:
approve / edit in `$EDITOR` / regenerate / reject / skip. For approved ones it builds the package
in `backend/outputs/applications/` and opens the filled-in form.

Reuse a profile in later runs with `--profile-id <uuid>`. Jobs already seen for that profile are skipped.

### API

```bash
cd backend && uvicorn api.main:app --app-dir src --reload    # docs at http://localhost:8000/docs
```

`POST /profiles` (multipart) -> `PUT /profiles/{id}` (fix extraction) -> `POST /searches` ->
`/searches/{id}/discover` -> `/screen` -> `/draft` -> `PATCH /applications/{id}/draft` ->
`/approve` -> `/prepare` -> `/mark-applied`.

## Known limits / next steps

- **The frontend is a local single-user tool.** There's no auth, and the autofill browser opens on the
  machine running the backend.
- **The CV is attached as-is.** Drafting tailors the letter, not the CV.
- **Autofill covers standard fields only.** Custom questions (visa, salary, "why us") are left for
  you. Selectors were checked on live GitLab / Palantir / Ashby forms; ATS markup can change.
- **Work mode / employment type come from heuristics** for sources that don't report them.
  Unknown values pass the hard filters and the LLM screener judges them.
- **The cover letter PDF uses a core font** (Latin-1). German umlauts work; other scripts
  need a bundled TTF font in `infra/documents.py`.
