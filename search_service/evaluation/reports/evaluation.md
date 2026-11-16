# Search quality evaluation

Queries: 61. Top-k: 5.

Precision uses the number of answer rows actually returned, up to k. Queries with an empty relevant set are omitted from precision, recall, hit rate, MRR, and nDCG, and are scored by empty-result correctness. Context rows are not answers. Partially supported measurement queries are omitted from relevance so production rows are not treated as the requested measure. The figures below describe this labeled set and are not a statistical ranking of the two systems.

## dictionary

| Metric | Value |
| --- | --- |
| Ranked queries | 40 |
| Empty ground-truth queries | 10 |
| Precision@k | 0.895 |
| Recall@k | 0.4294 |
| Hit rate@k | 1.0 |
| MRR | 0.9417 |
| nDCG@k | 0.8868 |
| Empty-result correctness | 1.0 |
| Availability accuracy | 1.0 |
| Filter correctness | 1.0 |
| Measure marking | 1.0 |

Phase 6 subset (original 45 queries):

| Metric | Value |
| --- | --- |
| Ranked queries | 28 |
| Empty ground-truth queries | 8 |
| Precision@k | 1.0 |
| Recall@k | 0.5446 |
| Hit rate@k | 1.0 |
| MRR | 1.0 |
| nDCG@k | 1.0 |
| Empty-result correctness | 1.0 |
| Availability accuracy | 1.0 |
| Filter correctness | 1.0 |
| Measure marking | 1.0 |

### By category

- exact_crop: ranked 4, empty 0, P 1.0, R 0.2817, hit 1.0, availability 1.0
- thai_alias: ranked 2, empty 0, P 1.0, R 0.4762, hit 1.0, availability 1.0
- english_alias: ranked 5, empty 0, P 1.0, R 0.2619, hit 1.0, availability 1.0
- calendar_year: ranked 4, empty 0, P 1.0, R 0.6429, hit 1.0, availability 1.0
- region: ranked 2, empty 0, P 1.0, R 1.0, hit 1.0, availability 1.0
- northeast_versus_north: ranked 3, empty 0, P 1.0, R 0.8889, hit 1.0, availability 1.0
- country_versus_region: ranked 2, empty 0, P 1.0, R 0.3472, hit 1.0, availability 1.0
- rice_season: ranked 4, empty 0, P 1.0, R 0.2679, hit 1.0, availability 1.0
- multiple_crop: ranked 4, empty 0, P 1.0, R 0.1302, hit 1.0, availability 1.0
- ambiguous: ranked 0, empty 0, P None, R None, hit None, availability 1.0
- missing_combination: ranked 2, empty 3, P 1.0, R 0.6667, hit 1.0, availability 1.0
- unsupported_measure: ranked 0, empty 7, P None, R None, hit None, availability 1.0
- unfiltered_query: ranked 0, empty 0, P None, R None, hit None, availability 1.0
- paraphrase: ranked 2, empty 0, P 1.0, R 1.0, hit 1.0, availability 1.0
- numeric_condition: ranked 6, empty 0, P 0.3, R 0.1551, hit 1.0, availability 1.0

## semantic

| Metric | Value |
| --- | --- |
| Ranked queries | 40 |
| Empty ground-truth queries | 6 |
| Precision@k | 0.8838 |
| Recall@k | 0.4402 |
| Hit rate@k | 0.975 |
| MRR | 0.9238 |
| nDCG@k | 0.8898 |
| Empty-result correctness | 0.8333 |
| Availability accuracy | 1.0 |
| Filter correctness | 1.0 |
| Measure marking | 1.0 |

Phase 6 subset (original 45 queries):

| Metric | Value |
| --- | --- |
| Ranked queries | 28 |
| Empty ground-truth queries | 5 |
| Precision@k | 1.0 |
| Recall@k | 0.5446 |
| Hit rate@k | 1.0 |
| MRR | 1.0 |
| nDCG@k | 1.0 |
| Empty-result correctness | 1.0 |
| Availability accuracy | 1.0 |
| Filter correctness | 1.0 |
| Measure marking | 1.0 |

### By category

- exact_crop: ranked 4, empty 0, P 1.0, R 0.2817, hit 1.0, availability 1.0
- thai_alias: ranked 2, empty 0, P 1.0, R 0.4762, hit 1.0, availability 1.0
- english_alias: ranked 5, empty 0, P 1.0, R 0.2619, hit 1.0, availability 1.0
- calendar_year: ranked 4, empty 0, P 1.0, R 0.6429, hit 1.0, availability 1.0
- region: ranked 2, empty 0, P 1.0, R 1.0, hit 1.0, availability 1.0
- northeast_versus_north: ranked 3, empty 0, P 1.0, R 0.8889, hit 1.0, availability 1.0
- country_versus_region: ranked 2, empty 0, P 1.0, R 0.3472, hit 1.0, availability 1.0
- rice_season: ranked 4, empty 0, P 1.0, R 0.2679, hit 1.0, availability 1.0
- multiple_crop: ranked 4, empty 0, P 1.0, R 0.1302, hit 1.0, availability 1.0
- ambiguous: ranked 0, empty 0, P None, R None, hit None, availability 1.0
- missing_combination: ranked 2, empty 3, P 0.875, R 1.0, hit 1.0, availability 1.0
- unsupported_measure: ranked 0, empty 3, P None, R None, hit None, availability 1.0
- unfiltered_query: ranked 0, empty 0, P None, R None, hit None, availability 1.0
- paraphrase: ranked 2, empty 0, P 1.0, R 1.0, hit 1.0, availability 1.0
- numeric_condition: ranked 6, empty 0, P 0.2667, R 0.1157, hit 0.8333, availability 1.0

## hybrid

| Metric | Value |
| --- | --- |
| Ranked queries | 40 |
| Empty ground-truth queries | 6 |
| Precision@k | 1.0 |
| Recall@k | 0.5044 |
| Hit rate@k | 1.0 |
| MRR | 1.0 |
| nDCG@k | 1.0 |
| Empty-result correctness | 1.0 |
| Availability accuracy | 1.0 |
| Filter correctness | 1.0 |
| Measure marking | 1.0 |

Phase 6 subset (original 45 queries):

| Metric | Value |
| --- | --- |
| Ranked queries | 28 |
| Empty ground-truth queries | 5 |
| Precision@k | 1.0 |
| Recall@k | 0.5446 |
| Hit rate@k | 1.0 |
| MRR | 1.0 |
| nDCG@k | 1.0 |
| Empty-result correctness | 1.0 |
| Availability accuracy | 1.0 |
| Filter correctness | 1.0 |
| Measure marking | 1.0 |

### By category

- exact_crop: ranked 4, empty 0, P 1.0, R 0.2817, hit 1.0, availability 1.0
- thai_alias: ranked 2, empty 0, P 1.0, R 0.4762, hit 1.0, availability 1.0
- english_alias: ranked 5, empty 0, P 1.0, R 0.2619, hit 1.0, availability 1.0
- calendar_year: ranked 4, empty 0, P 1.0, R 0.6429, hit 1.0, availability 1.0
- region: ranked 2, empty 0, P 1.0, R 1.0, hit 1.0, availability 1.0
- northeast_versus_north: ranked 3, empty 0, P 1.0, R 0.8889, hit 1.0, availability 1.0
- country_versus_region: ranked 2, empty 0, P 1.0, R 0.3472, hit 1.0, availability 1.0
- rice_season: ranked 4, empty 0, P 1.0, R 0.2679, hit 1.0, availability 1.0
- multiple_crop: ranked 4, empty 0, P 1.0, R 0.1302, hit 1.0, availability 1.0
- ambiguous: ranked 0, empty 0, P None, R None, hit None, availability 1.0
- missing_combination: ranked 2, empty 3, P 1.0, R 1.0, hit 1.0, availability 1.0
- unsupported_measure: ranked 0, empty 3, P None, R None, hit None, availability 1.0
- unfiltered_query: ranked 0, empty 0, P None, R None, hit None, availability 1.0
- paraphrase: ranked 2, empty 0, P 1.0, R 1.0, hit 1.0, availability 1.0
- numeric_condition: ranked 6, empty 0, P 1.0, R 0.544, hit 1.0, availability 1.0

## Comparison

Ranked nonempty queries: 40. Both hit: 39. Dictionary only: 1. Semantic only: 0. Neither: 0. Different top-k sets: 33. Mean Jaccard: 0.3815.

Hit counts use each backend's own ranking. Cosine scores are not compared with dictionary match reasons. Equal hit rates can still hide different top-k process ids.

## Latency

Environment: Windows-11-10.0.26200-SP0; Python 3.14.7; AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD.

Warm-up queries: 1. Repetitions per benchmark query: 3.
Model initialization: 2310.392 ms.
Dictionary first query: 3.293 ms. Warm: mean 0.608 ms, median 0.683 ms, p95 1.088 ms, n 9.
Semantic first query after initialization: 170.369 ms. Warm: mean 48.407 ms, median 34.575 ms, p95 81.072 ms, n 9.
Warm semantic components: embed mean 22.571 ms, median 23.731 ms, p95 24.704 ms, n 9; Qdrant mean 22.75 ms, median 6.593 ms, p95 57.261 ms, n 9; SQLite mean 1.316 ms, median 1.29 ms, p95 1.551 ms, n 9.
Warm compare: mean 42.784 ms, median 31.775 ms, p95 68.515 ms, n 9.
Benchmark errors: 0.

## Hybrid search recommendation

Hybrid search ranks only the SQLite-eligible process ids with local BGE-M3. Dictionary match reasons are not added to cosine similarity.

Reciprocal Rank Fusion is not part of this ranker. It remains a later experiment and cannot decide availability or numeric eligibility.

Among ranked queries with a nonempty relevant set, both backends hit 39, dictionary only 1, semantic only 0, and neither 0. Their top-k sets differed for 33 of those queries (mean Jaccard 0.3815). Dictionary search hits relevant rows that semantic search misses on this set, so a semantic-only candidate list would drop those rows.

Recommended architecture: use the structured crop, year, region, season, and spatial constraints as the eligibility filter, then rank that eligible set with local BGE-M3. Keep dictionary search as the exact audit path when its parser accepts the question. Call the embedding model after the cheap structured constraints are known, or in parallel when the latency budget allows it. Model initialization measured 2310.392 ms and is kept separate from warm queries. Warm median latency was 0.683 ms for dictionary search and 34.575 ms for semantic search.

Reciprocal Rank Fusion is a later experiment, not the first hybrid. It would fuse ranks rather than raw scores, and it is useful when the miss sets are complementary. It does not decide availability, and it cannot turn an unavailable fertilizer, energy, water, or carbon measurement into a production answer.

Dictionary-first retrieval is the fastest exact path, and it is the wrong sole retriever for ambiguous multi-crop questions and for wording its parser does not accept. Semantic-first retrieval is already filtered inside the BGE-M3 service. A hybrid should not compare that filtered list with a dictionary list that ignored a separate filter.

This recommendation describes the measured labeled set. It is not a claim of statistical superiority.

## Safety snapshot

SQLite unchanged during the run: True.
SQLite SHA-256: 700df10769c76624572c9761e8636daf82a6bd4c63b1d7ee0f3383f766834807.
Qdrant after the run: {'reachable': True, 'points_count': 180, 'vector_size': 1024, 'distance': 'Cosine'}.
