````md
# Volta Plan Recommendation

This is the repository for the Volta Energy Plan Recommendation project.

The system uses:

- Hard filter
- Semantic search
- Vector search (Vertex AI Vector Search)
- Embedding models
- Evaluation pipeline

to recommend suitable electricity plans for users.

---

# 1) Pipeline

```text
Raw Plan Dataset
        ↓
01_read_plan.py
        ↓
Processed Plans
(hard attributes + soft text)
        ↓
Embedding + Upload to Vertex AI
(PlanEmbeddingAndStore_Colab.ipynb)
        ↓
Generate Synthetic Users
(02_generate_profile_from_plan.py)
        ↓
Prepare User Query Data
(03_prepare_user_data.py)
        ↓
Query Vertex AI Vector Search
(04_query.py)
        ↓
Recommended Plans
        ↓
Evaluate Recommendation Quality
(05_evaluation.py)
````

---

# 2) File Structure

```text
volta-plan-recommendation/
│
├── benchmark_embedding_model/
│   └── HoangPhuc_SentenceTransformers_Benchmark.ipynb
│
├── plan_embedding_and_store/
│   └── PlanEmbeddingAndStore_Colab.ipynb
│
├── inputs/
│
├── outputs/
│
├── 01_read_plan.py
├── 02_generate_profile_from_plan.py
├── 03_prepare_user_data.py
├── 04_query.py
├── 05_evaluation.py
│
├── embedding_cosine.py
├── profile_generation.py
├── vertex_filter.py
├── vertex_query.py
│
└── README.md
```

---

# 3) Main Components

## 01_read_plan.py

Read and preprocess the energy plan dataset.

Features:

* Remove NULL columns
* Remove singleton columns
* Extract hard attributes
* Build soft text
* Generate full text for embedding

Output:

```text
processed_plans.csv
```

---

## 02_generate_profile_from_plan.py

Generate synthetic user profiles from plans.

The generated users inherit some characteristics from the original plan:

* tariff type
* solar
* EV
* controlled load
* distributor
* postcode

Output:

```text
synthetic_users_from_plans.csv
```

---

## 03_prepare_user_data.py

Convert user profiles into query-ready format.

Features:

* Build hard filter
* Build query text
* Normalize user data

Output:

```text
ready_test_users.csv
```

---

## 04_query.py

Query the recommendation system.

Pipeline:

```text
Hard Filter
    ↓
Vertex AI Vector Search
    ↓
Semantic Similarity
    ↓
Top Recommended Plans
```

Output:

```text
outputs/vertex_test_results_xxx.json
```

---

## 05_evaluation.py

Evaluate recommendation quality.

Current evaluation includes:

* Hard attribute matching
* Embedding similarity

Output:

```text
outputs/recommendation_evaluation_xxx.json
```

---

## embedding_cosine.py

Compute cosine similarity between:

* user query text
* recommended plan text
* seed/original plan text

Used for evaluation.

---

## vertex_filter.py

Build Vertex AI hard filters.

Features:

* customer_type
* distributors
* postcode
* tariff_type
* solar
* EV
* controlled load

Also supports fallback filtering levels.

---

## vertex_query.py

Query helper for Vertex AI Vector Search.

Features:

* embedding query
* hard filter query
* fallback filtering
* nearest neighbor retrieval

---

# 4) Benchmark Embedding Models

Notebook:

```text
benchmark_embedding_model/
```

Used to compare embedding models.

Current tested models include:

* BGE-M3
* GTE-ModernBERT
* E5-large-v2

Metrics:

* semantic similarity
* retrieval quality
* embedding speed
* vector dimension

---

# 5) Embedding and Store

Notebook:

```text
plan_embedding_and_store/
```

Used for:

* embedding plans
* uploading vectors to Google Cloud Storage
* creating Vertex AI index
* deploying Vertex AI endpoint

Better to run on Google Colab because embedding large datasets requires more RAM and GPU resources.

---

# 6) How to Use

## Step 1 — Preprocess plans

```bash
python 01_read_plan.py
```

Output:

```text
processed_plans.csv
```

---

## Step 2 — Generate synthetic users

```bash
python 02_generate_profile_from_plan.py
```

Output:

```text
synthetic_users_from_plans.csv
```

---

## Step 3 — Prepare query-ready user data

```bash
python 03_prepare_user_data.py
```

Output:

```text
ready_test_users.csv
```

---

## Step 4 — Query recommendation system

```bash
python 04_query.py
```

Output:

```text
outputs/vertex_test_results_xxx.json
```

---

## Step 5 — Evaluate recommendation quality

```bash
python 05_evaluation.py
```

Output:

```text
outputs/recommendation_evaluation_xxx.json
```

---

# 7) Requirements

Main libraries:

```text
pandas
datasets
sentence-transformers
google-cloud-aiplatform
numpy
torch
scikit-learn
```

Install example:

```bash
pip install pandas datasets sentence-transformers google-cloud-aiplatform numpy torch scikit-learn
```

---

# 8) Notes

* Embedding and Vertex AI upload are better on Google Colab.

* Local machine is mainly used for:

  * preprocessing
  * querying
  * evaluation
  * debugging

* Vertex AI Vector Search is used for:

  * semantic retrieval
  * hard filtering
  * nearest neighbor search

* Current project focuses on:

  * semantic recommendation
  * hard filter matching
  * recommendation evaluation

```
```
