# LLM Invoice Extraction Pipeline

This is Module 1 of the [AI Data Engineer Bootcamp](https://github.com/owshq-academy/ai-data-engineer-bootcamp) rebuilt from scratch, one piece at a time, to actually understand what each part does instead of just running someone else's `docker-compose up`.

The job: pull UberEats PDF invoices out of object storage, hand the text to an LLM, get structured data back, store it in Postgres. Simple on paper. The interesting part is everything around that one sentence — orchestration, observability, batching, and about a dozen real bugs along the way, several of which turned out to be in the *original* repo, not just in this rebuild.

## How this was built

Instead of starting from the full stack, we started from nothing and added one real piece of infrastructure at a time, in this order:

1. **Core logic** — `pypdf` pulls raw text out of a PDF, Groq (OpenAI-compatible API) turns that into structured JSON, `temperature=0` and JSON mode keep it deterministic and syntactically valid.
2. **Postgres** — the structured result gets upserted into an `invoices` table (`ON CONFLICT (order_id) DO UPDATE`), so reprocessing the same invoice updates it instead of duplicating it.
3. **MinIO** — S3-compatible object storage replaces a hardcoded local file. Invoices land in `incoming/`, get moved to `processed/` after a successful run. There's no "move" operation in S3-style storage, so this is actually copy-then-delete under the hood.
4. **Airflow** — the three steps above get wrapped in a DAG (`list_pending_invoices` → `process_invoice`, dynamically mapped per file).
5. **Docker** — Postgres, MinIO, and two Airflow containers (scheduler + webserver), all reachable by service name on Docker's internal network instead of `localhost`.
6. **Langfuse** — every LLM call gets logged (prompt, output, token usage) for cost/latency visibility.
7. **Real batching** — multiple invoices packed into a single prompt, one API call returns a JSON array of results instead of one call per invoice.
8. **PydanticAI** — the hand-written Groq client call gets replaced with a declarative `Agent(model, output_type=InvoiceData, system_prompt=...)`, where the schema is just a Pydantic class instead of a JSON string embedded in the prompt.

Each stage is its own commit, so the git history itself is a decent way to read how this grew.

## What actually went wrong (the useful part)

A lot, and almost none of it was "the AI model got it wrong." In rough order of how much time they cost:

**The original repo's v2 batching doesn't batch.** The README claims "4 batched requests, 80% cost reduction" for 20 invoices in batches of 5. The actual code still calls the LLM once per invoice inside a loop — it only reduces the number of *Airflow tasks*, not API calls. We implemented what the README actually describes: one prompt containing N invoices, one API call, a JSON array back.

**Rosetta was breaking everything, intermittently.** The original `.venv` was built from an x86_64 Python (Anaconda) running translated under Rosetta 2 on Apple Silicon. Rosetta's translation cache for `libpq` (bundled in `psycopg2`) started failing — sometimes a hang, sometimes a crash with `rosetta error: Attachment of code signature supplement failed`. This was almost certainly also behind several earlier Airflow hangs that looked unrelated at the time. Fix: rebuild the venv on native ARM64 Python. Don't run data infrastructure through an instruction-set translator.

**Langfuse's SDK breaks Groq's HTTP client if you just import it.** Not call it — import it. Something in Langfuse's global state collides with Groq's underlying `httpx` client, and the next Groq API call hangs forever. The fix was architectural, not a version bump: logging runs in a completely separate subprocess (`log_to_langfuse.py`), so whatever Langfuse mutates globally never touches the process actually talking to Groq.

**`airflow-ai-sdk` is built against an old PydanticAI and has no upper version bound.** `pip install` grabbed the latest PydanticAI, which renamed `Agent`'s `result_type` parameter to `output_type` — so the SDK's internal call broke with `TypeError: unexpected keyword argument 'result_type'`. Chasing a compatible old PydanticAI version cascaded into *more* broken dependencies (a missing `opentelemetry` submodule). Fix: skip the wrapper, call `pydantic_ai.Agent` directly. Same library, no stale middleman.

**`LocalExecutor` can't pickle a `GroqModel`.** PydanticAI's model object holds an `httpx` client, which holds a thread lock, which can't survive being pickled across Airflow's fork-based task execution. Building the model object inside the task function (at run time) instead of at DAG parse time sidesteps this — nothing needs to be pickled if it's constructed fresh in the forked process.

**`.expand()` with two arguments is a cross product, not a zip.** `task.expand(key=keys, invoice_data=results)` pairs *every* key with *every* result — 3 invoices became 9 mismatched task instances. `keys.zip(results)` pairs them by position instead, same idea as Python's built-in `zip()`.

**Telling an LLM "extract the date as shown" gets you exactly that.** One invoice's date field came back as `"15 de março de 2024 às 20:35"` — correct, and useless, because Postgres can't parse it as a timestamp. The fix is always the same lesson: tell the model the actual target format (`ISO 8601`), don't assume it'll infer what you meant.

**MinIO's official Docker image got pulled from Docker Hub.** `minio/minio` now 404s; Quay.io's mirror requires auth for anonymous pulls. Used the `elestio/minio` community mirror instead.

**`setproctitle` SIGSEGVs on this macOS version.** Gunicorn uses it purely to make `ps` output look nicer (`gunicorn: worker [airflow-webserver]` instead of a raw PID). Its native code crashes deep in CoreFoundation on this OS build. Uninstalling it is a complete fix with zero functional loss — it's cosmetic.

## Project layout

```
step1_extract_text.py       PDF -> raw text (pypdf)
step2_llm_extract.py        text -> structured JSON (Groq), + batching, + Langfuse logging
step3_store_postgres.py     JSON -> Postgres upsert
step4_minio_source.py       MinIO list/download/move
log_to_langfuse.py          Langfuse logging, run as a subprocess (see "what went wrong")

airflow_home/dags/
  invoice_pipeline_dag.py       v1: one invoice per task, hand-written LLM call
  invoice_pipeline_v3_dag.py    v3: same pipeline, PydanticAI Agent instead of raw API calls

Dockerfile, docker-compose.yml, docker/init-dbs.sql    the containerized stack
requirements.txt             main app dependencies
requirements-airflow.txt     bare-metal Airflow venv (separate venv, see file header)
requirements-docker.txt      what gets installed into the Airflow container image
```

## Running it

**Core pipeline only** (no Airflow, no Docker):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY, MinIO/Langfuse config
python3 step2_llm_extract.py
```
Needs MinIO and Postgres running locally first (`brew install minio postgresql@14`, see commit history for exact setup).

**Full stack in Docker:**
```bash
docker compose up -d
```
Airflow's at `localhost:8081` (`admin` / `admin123`), MinIO's console at `localhost:9003` (`admin` / `password123`). Upload a PDF into the `invoices` bucket's `incoming/` prefix, trigger the DAG, watch it land in Postgres and move to `processed/`.

**Bare-metal Airflow** (its own venv, native ARM64 Python — see `requirements-airflow.txt` for why):
```bash
python3.11 -m venv .venv-airflow && source .venv-airflow/bin/activate
pip install apache-airflow==2.9.3 --constraint <see requirements-airflow.txt>
pip install -r requirements-airflow.txt
export AIRFLOW_HOME=$(pwd)/airflow_home
airflow db migrate && airflow users create ...
airflow scheduler & airflow webserver -p 8080 &
```
