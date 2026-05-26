import json
import pandas as pd
from pathlib import Path
from datetime import datetime

from sentence_transformers import SentenceTransformer
from google.cloud import aiplatform

from vertex_query import query_vertex_with_fallback


PROJECT_ID = "project-ce1ff6dc-7e15-4f39-bb3"
REGION = "us-central1"

ENDPOINT_RESOURCE_NAME = "projects/933786093071/locations/us-central1/indexEndpoints/7108256911664873472"
DEPLOYED_INDEX_ID = "energy_plan_endpoint_1779756140590"

MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"

INPUT_CSV = "inputs/ready_test_users.csv"
OUTPUT_DIR = "outputs"

TARGET_K = 10
PER_LEVEL_TOP_K = 50


def load_test_users(csv_path: str):
    df = pd.read_csv(csv_path)

    users = []

    for _, row in df.iterrows():
        users.append({
            "test_id": row["test_id"],
            "seed_plan_id": row.get("seed_plan_id"),
            "query_text": row["query_text"],
            "hard_filter": json.loads(row["hard_filter"]),
            "user_profile_json": json.loads(row["user_profile_json"])
        })

    return users


def init_vertex_endpoint():
    aiplatform.init(
        project=PROJECT_ID,
        location=REGION
    )

    endpoint = aiplatform.MatchingEngineIndexEndpoint(
        index_endpoint_name=ENDPOINT_RESOURCE_NAME
    )

    return endpoint


def explain_result_item(item, hard_filter):
    explanations = []

    explanations.append(
        f"Selected by Vertex AI Vector Search using semantic similarity after applying hard filter fallback level {item['filter_match_level']}."
    )

    if item.get("dropped_filters"):
        explanations.append(
            f"The result was retrieved after relaxing these filters: {', '.join(item['dropped_filters'])}."
        )
    else:
        explanations.append(
            "The result matched all hard filter conditions."
        )

    explanations.append(
        "The plan_id is returned because Vertex AI Vector Search stores and returns only vector IDs, not the full plan content."
    )

    return explanations


def process_one_user(user, model, endpoint):
    query_vector = model.encode(
        [user["query_text"]],
        normalize_embeddings=True
    )[0]

    retrieved = query_vertex_with_fallback(
        endpoint=endpoint,
        deployed_index_id=DEPLOYED_INDEX_ID,
        query_vector=query_vector,
        hard_filter=user["hard_filter"],
        target_k=TARGET_K,
        per_level_top_k=PER_LEVEL_TOP_K
    )

    results = []

    for item in retrieved:
        result = {
            "plan_id": item["plan_id"],
            "distance": item["distance"],
            "similarity_note": "For COSINE_DISTANCE, lower distance means higher similarity.",
            "filter_match_level": item["filter_match_level"],
            "dropped_filters": item["dropped_filters"],
            "matched_against_hard_filter": user["hard_filter"],
            "why_selected": explain_result_item(item, user["hard_filter"])
        }

        results.append(result)

    return {
        "test_id": user["test_id"],
        "seed_plan_id": user.get("seed_plan_id"),
        "query_text": user["query_text"],
        "hard_filter": user["hard_filter"],
        "num_results": len(results),
        "results": results
    }


def main():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading test users")
    test_users = load_test_users(INPUT_CSV)
    print("Loaded users:", len(test_users))

    print("Loading embedding model")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    print("Connecting to Vertex endpoint")
    endpoint = init_vertex_endpoint()

    all_outputs = []

    for idx, user in enumerate(test_users, start=1):
        print(f"\nProcessing user {idx}/{len(test_users)}: {user['test_id']}")

        try:
            output = process_one_user(
                user=user,
                model=model,
                endpoint=endpoint
            )

            all_outputs.append(output)

            print("Returned plans:", output["num_results"])

        except Exception as e:
            print(f"Failed user {user['test_id']}: {e}")

            all_outputs.append({
                "test_id": user["test_id"],
                "seed_plan_id": user.get("seed_plan_id"),
                "error": str(e)
            })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"vertex_test_results_{timestamp}.json"

    final_output = {
        "created_at": timestamp,
        "input_csv": INPUT_CSV,
        "model_name": MODEL_NAME,
        "endpoint_resource_name": ENDPOINT_RESOURCE_NAME,
        "deployed_index_id": DEPLOYED_INDEX_ID,
        "target_k": TARGET_K,
        "per_level_top_k": PER_LEVEL_TOP_K,
        "ranking_note": "Results are retrieved by Vertex AI using hard-filter fallback and vector similarity. Lower cosine distance means more similar.",
        "users": all_outputs
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print("\nSaved results to:", output_path)


if __name__ == "__main__":
    main()