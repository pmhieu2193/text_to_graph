# Vietnamese Knowledge Graph API

FastAPI application for turning Vietnamese PDF documents into a Knowledge Graph.

## Setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env
```

## Database migrations (Alembic)

The application no longer runs SQLAlchemy `create_all()` at startup. Schema changes must be managed with Alembic.

For a new database:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

For an existing database created by an earlier version of this project, back up `data/app.db` first, then run:

```bash
alembic upgrade head
```

The first revision is a non-destructive baseline: it creates missing legacy tables but does not drop or recreate existing tables. The next revision adds the ER tables and any missing document columns. It is designed to adopt the existing SQLite schema without deleting its rows.

Create a migration after changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe schema change"
```

Review the generated migration before applying it:

```bash
alembic upgrade head
alembic current
alembic history
```

Do not edit an already-applied migration. Add a new revision instead. Always back up the database before applying migrations to a database containing data.

## API

Swagger: `http://127.0.0.1:8000/docs`

### Entity Resolution workflow

1. Generate a persisted candidate run and XLSX report:

   `POST /api/v1/documents/{document_id}/entity-resolution/preview`

   The response contains `run_id`, candidate `pair_id`, both raw entity IDs, both evidence lists, match scores and classification. The XLSX Candidates sheet contains the same pair ID and evidence.

2. Retrieve all candidates and their latest decisions:

   `GET /api/v1/documents/{document_id}/entity-resolution/runs/{run_id}/candidates`

3. Decide one pair:

   `POST /api/v1/documents/{document_id}/entity-resolution/candidates/{pair_id}/decision`

   Body examples: `{"decision":"MERGE"}`, `{"decision":"KEEP_SEPARATE"}`, or `{"decision":"SKIP"}`.

4. Merge every pending AUTO_MERGE candidate:

   `POST /api/v1/documents/{document_id}/entity-resolution/runs/{run_id}/auto-merge`

   Candidates are processed sequentially and each pair resolves its current canonical cluster at execution time. Thus A-B followed by B-C merges all three into one cluster without relying on a deleted/obsolete raw entity.

5. Finalize the run and export the final result:

   `POST /api/v1/documents/{document_id}/entity-resolution/runs/{run_id}/finalize`

   Finalization applies AUTO_MERGE candidates that are still PENDING, preserves every decision already made by the reviewer, and changes unresolved PENDING pairs to SKIP (not KEEP_SEPARATE). It then rebuilds canonical aliases, maps raw relations to canonical endpoints, removes duplicate canonical edges and self-loops from the final graph view, and exports an XLSX workbook with Summary, Candidates, Canonical_Entities and Canonical_Relations sheets. A finalized run is immutable; calling finalize again returns a conflict.

6. Inspect canonical entities and relations:

   - `GET /api/v1/documents/{document_id}/entity-resolution/canonical-entities`
   - `GET /api/v1/documents/{document_id}/entity-resolution/canonical-relations`

### Data integrity

- `raw_entities` and `raw_relations` are retained as extraction provenance.
- `entity_candidates` stores a stable UUID pair ID, run/document IDs, scores, evidence snapshots and decision status.
- `canonical_entities` stores the current canonical representatives and the unique aliases aggregated from their raw members.
- `canonical_entity_members` maps each raw entity to exactly one current canonical cluster.
- Merging reassigns cluster membership and marks the losing canonical record with `merged_into_id`; raw entities and raw relations are not deleted.
- Canonical relation queries join each raw relation's subject and object through the membership table. The final view groups duplicate directed edges by canonical subject, canonical object and normalized relation type, retaining all contributing raw relation IDs and evidence. Self-loops created when both endpoints collapse into one entity are excluded from the final graph view, while raw relations remain intact.
- A previous KEEP_SEPARATE decision blocks a later merge that would combine those two clusters.

## Notes

The BGE-M3/FAISS embedding stage remains optional at runtime only if configured/injected accordingly; current default ER preview constructs the configured embedding matcher. The project is still an MVP and should be tested locally with a backed-up database before using it on valuable data.
