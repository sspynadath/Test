# Coforge PE Intelligence Platform — V3

A Streamlit account-intelligence workspace for researching both **private-equity firms** and their **portfolio companies**.

## What V3 adds

V3 makes a portfolio company a first-class research account. Select a PE sponsor, switch **Research scope** to **Portfolio company**, choose a company, and the same workspace now runs against that operating company:

- Command Center
- Portfolio / ownership context
- Leadership
- Hiring & Skills
- Technology Signals
- Newsroom
- Opportunity Lab
- AI Analyst
- Data Hub

The PE-firm experience remains intact.

## Required files

```text
app.py
pe_core.py
portfolio_intel.py
requirements.txt
README.md
.streamlit/config.toml
data/
  coforge_capabilities.json
  _templates/
```

`data/<firm_key>/...` and `data/portfolio_companies/<account-slug>/...` are optional persistent override folders.

## How portfolio-company intelligence works

### 1. Official website resolution

The app uses, in order:

1. A company website field from the portfolio dataset, when present.
2. An external company URL exposed by the PE portfolio source, when present.
3. Public-web discovery for the likely official domain.
4. A manual **Official website override** in the sidebar for ambiguous names.

The app does not treat a guessed domain as certain. When a website cannot be resolved, news and Wikipedia fallback can still work, while leadership/jobs are clearly marked incomplete.

### 2. Account description

For both PE firms and portfolio companies, a usable official-site description is preferred. Wikipedia is a neutral fallback when the official description cannot be parsed.

### 3. News and technology signals

Portfolio-company intelligence combines:

- Google News RSS
- official company news / press / insights pages where discoverable
- uploaded or local curated research

The existing signal classifier, skill taxonomy, technology detector and Coforge opportunity mapper are then reused.

### 4. Hiring and skills

The operating-company layer discovers careers pages and attempts structured extraction from common ATS/job-board systems, including:

- Greenhouse
- Lever
- Ashby
- SmartRecruiters (best effort; some API surfaces require customer authentication)
- Workday CXS (best effort; tenants vary)
- first-party/server-rendered job pages

If a site is JavaScript-only, protected, rate-limited or otherwise not publicly machine-readable, the app exposes the careers source and the Data Hub remains the reliable override route.

### 5. Leadership

The app discovers likely leadership/team/management pages, reads schema.org `Person` records where available, and uses conservative card parsing as a fallback. The result is treated as captured public evidence, **not an exhaustive org chart**.

### 6. Portfolio-company scoring

Operating companies are not penalised for lacking a PE investment portfolio. Their priority/confidence model focuses on:

- company profile coverage
- leadership coverage
- relevant hiring
- news / growth triggers
- AI, data, cloud, automation and technology evidence

PE firms retain the original portfolio-scale component.

## Data precedence

### PE firms

1. Current Streamlit session upload
2. Local file under `data/<firm_key>/`
3. Public configured source

### Portfolio companies

1. Current Streamlit session upload
2. Local file under `data/portfolio_companies/<account-slug>/`
3. Public company website / ATS / public news discovery

News is merged rather than replaced.

## Local data formats

The app accepts CSV, XLSX and JSON.

### Portfolio

Recommended columns:

```text
Company, Sector, Region, Status, Fund, Source, Website
```

### Leadership

```text
Name, Role, Location, Bio, Profile URL, Source
```

### Jobs

```text
title, location, description, url, source
```

### News / insights

```text
title, summary, link, published, source, signal_type
```

Templates are included under `data/_templates/`.

## Run locally

Use Python 3.12 if possible so local development matches a standard Streamlit Community Cloud deployment.

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Deploy on Streamlit Community Cloud

Push this folder to GitHub and deploy `app.py` as the entrypoint. Keep `requirements.txt` in the repository root or alongside the entrypoint.

When creating the deployment, select Python 3.12 in Advanced settings if you want the environment to match the recommended local setup.

No API key is required for the core public-data application.

## AI Analyst / Ollama

The deterministic signal engine always works without an LLM.

If you run the app **locally**, you can optionally enable Ollama:

```bash
pip install ollama
ollama pull gemma3
ollama serve
```

Then uncomment the `ollama` dependency in `requirements.txt` if desired.

Important: an Ollama server running on your laptop is **not accessible to an app running on Streamlit Community Cloud**. A cloud deployment therefore falls back to the deterministic signal engine unless you separately add a cloud-accessible model provider.

## Public-data limitations

This platform is deliberately conservative:

- PE portfolio directories can represent current, historical or multi-strategy investments differently.
- Company names can be ambiguous; use the website override when needed.
- Search engines and websites can block automated requests.
- Careers systems can be JavaScript-heavy or authenticated.
- SmartRecruiters public/API behaviour can vary by customer setup.
- Workday tenant structures differ significantly.
- Leadership directories are not always exhaustive or server-rendered.
- A public signal is evidence of a mention/activity, not proof of enterprise-wide adoption or confirmed buying intent.

For an important target account, validate critical facts against the linked official source and use PitchBook/internal exports through Data Hub for completeness.
