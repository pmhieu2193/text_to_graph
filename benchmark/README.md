# Per-document benchmark tools

This folder is isolated from the production pipeline. It reads existing SQLAlchemy records and exports evidence; it does not modify document, extraction, ER or Neo4j data.

## Export one document

Run from repository root in the same Python environment/container configuration as the API:

```bash
python -m benchmark.document_benchmark --document-id <DOCUMENT_UUID>
```

Optional manually curated labels:

```bash
python -m benchmark.document_benchmark --document-id <DOCUMENT_UUID> --ground-truth benchmark/ground_truth/<DOCUMENT_UUID>.json
```

Output is written to `benchmark/results/<document_id>/`:
- `summary.json`: current document status and aggregate processing, extraction, ER and graph-integrity metrics.
- `chunks.csv`: chunk status, attempts, provider/model, elapsed time and last error.
- `entities.csv`: raw entities, aliases, evidence and canonical mapping.
- `relations.csv`: raw relations with endpoint names.
- `candidates.csv`: ER candidate scores, method, classification and human decisions.
- `benchmark.md`: short report.

Generated results are ignored by Git. Run again after each workflow stage for a new snapshot. This is not an event-history system.

## Ground truth

Start from `ground_truth_template.json`. The optional evaluator compares normalized exact entity name + type, and normalized subject/relation/object triples. Optional `entity_clusters` is a list of groups containing `raw_entity_id` values (copy from `entities.csv`) that refer to the same real-world entity. If ER is finalized, the tool computes final clustering pairwise P/R/F1.

Exact-name matching does not infer aliases or semantic equivalence. Label the complete evaluation scope consistently and inspect exported CSVs. An incomplete label set must not be described as full-document accuracy.

## Interpretation

- Chunk status, retry count, duration, entity/relation counts and candidate counts are operational metrics.
- Extraction P/R/F1 and final ER pairwise P/R/F1 require manual ground truth.
- Entity reduction is not accuracy; over-merging can increase reduction while damaging the graph.
- Auto-merge precision and Human Review accuracy require separately labeled decisions; they are not inferred from graph size.
