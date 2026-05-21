import json
import pandas as pd
from pathlib import Path
from datetime import datetime

from embedding_cosine import is_recommended_text_better_than_seed


ATTRIBUTE_FIELDS = [
    "customer_type",
    "distributors",
    "included_postcodes",
    "tariff_type",
    "has_controlled_load",
    "has_solar",
    "has_ev"
]


def safe_json_loads(value, default=None):
    if default is None:
        default = {}

    if pd.isna(value):
        return default

    if isinstance(value, dict):
        return value

    try:
        return json.loads(value)
    except Exception:
        return default


def normalize_value(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return str(value).lower()

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)

    if isinstance(value, int):
        return str(value)

    text = str(value).strip()

    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except Exception:
        pass

    return text.lower()


def as_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def match_attribute(seed_value, recommended_value):
    seed_values = [
        normalize_value(v)
        for v in as_list(seed_value)
        if v is not None
    ]

    recommended_values = [
        normalize_value(v)
        for v in as_list(recommended_value)
        if v is not None
    ]

    if not seed_values and not recommended_values:
        return True

    if not seed_values or not recommended_values:
        return False

    return any(v in recommended_values for v in seed_values)


def load_plan_lookup(processed_plans_csv):
    df = pd.read_csv(processed_plans_csv)

    lookup = {}

    for _, row in df.iterrows():
        plan_id = str(row["plan_id"])

        lookup[plan_id] = {
            "plan_id": plan_id,
            "hard_attributes": safe_json_loads(row["hard_attributes"]),
            "soft_text": safe_json_loads(row["soft_text"]),
            "full_text": row.get("full_text", "")
        }

    return lookup


def calculate_attribute_score(seed_plan, recommended_plan):
    seed_hard = seed_plan.get("hard_attributes", {})
    recommended_hard = recommended_plan.get("hard_attributes", {})

    details = {}
    score = 0

    for field in ATTRIBUTE_FIELDS:
        is_match = match_attribute(
            seed_hard.get(field),
            recommended_hard.get(field)
        )

        details[field] = {
            "seed": seed_hard.get(field),
            "recommended": recommended_hard.get(field),
            "match": is_match,
            "point": 1 if is_match else 0
        }

        if is_match:
            score += 1

    return {
        "attribute_score": score,
        "max_attribute_score": len(ATTRIBUTE_FIELDS),
        "attribute_details": details
    }


def calculate_embedding_score(
    user_text,
    seed_plan,
    recommended_plan,
    model_name,
    device
):
    seed_text = seed_plan.get("full_text", "")
    recommended_text = recommended_plan.get("full_text", "")

    result = is_recommended_text_better_than_seed(
        user_text=user_text,
        recommended_plan_text=recommended_text,
        seed_plan_text=seed_text,
        model_name=model_name,
        device=device
    )

    return {
        "embedding_score": 1 if result["is_better"] else 0,
        "max_embedding_score": 1,
        "embedding_details": result
    }


def calculate_plan_recommendation_score(
    user_text,
    seed_plan,
    recommended_plan,
    model_name,
    device
):
    attr_result = calculate_attribute_score(
        seed_plan=seed_plan,
        recommended_plan=recommended_plan
    )

    embedding_result = calculate_embedding_score(
        user_text=user_text,
        seed_plan=seed_plan,
        recommended_plan=recommended_plan,
        model_name=model_name,
        device=device
    )

    raw_score = (
        attr_result["attribute_score"]
        + embedding_result["embedding_score"]
    )

    max_score = (
        attr_result["max_attribute_score"]
        + embedding_result["max_embedding_score"]
    )

    score_10 = round((raw_score / max_score) * 10, 4) if max_score else 0.0

    return {
        "raw_score": raw_score,
        "max_score": max_score,
        "score_10": score_10,
        **attr_result,
        **embedding_result
    }


def evaluate_user_result(
    user_result,
    plan_lookup,
    model_name,
    device
):
    test_id = user_result.get("test_id")
    seed_plan_id = str(user_result.get("seed_plan_id"))
    user_text = user_result.get("query_text", "")
    recommended_results = user_result.get("results", [])

    seed_plan = plan_lookup.get(seed_plan_id)

    if seed_plan is None:
        return {
            "test_id": test_id,
            "seed_plan_id": seed_plan_id,
            "error": "seed_plan_id not found in plan_lookup",
            "user_average_score_10": 0.0,
            "plan_evaluations": []
        }

    plan_evaluations = []

    for rank, item in enumerate(recommended_results, start=1):
        recommended_plan_id = str(item.get("plan_id"))
        recommended_plan = plan_lookup.get(recommended_plan_id)

        if recommended_plan is None:
            plan_evaluations.append({
                "rank": rank,
                "plan_id": recommended_plan_id,
                "error": "recommended plan_id not found in plan_lookup"
            })
            continue

        score_result = calculate_plan_recommendation_score(
            user_text=user_text,
            seed_plan=seed_plan,
            recommended_plan=recommended_plan,
            model_name=model_name,
            device=device
        )

        plan_evaluations.append({
            "rank": rank,
            "plan_id": recommended_plan_id,
            "distance": item.get("distance"),
            "filter_match_level": item.get("filter_match_level"),
            "dropped_filters": item.get("dropped_filters"),
            **score_result
        })

    valid_scores = [
        p["score_10"]
        for p in plan_evaluations
        if "score_10" in p
    ]

    user_average_score = (
        sum(valid_scores) / len(valid_scores)
        if valid_scores
        else 0.0
    )

    return {
        "test_id": test_id,
        "seed_plan_id": seed_plan_id,
        "num_recommended_plans": len(recommended_results),
        "num_valid_evaluated_plans": len(valid_scores),
        "user_average_score_10": round(user_average_score, 4),
        "plan_evaluations": plan_evaluations
    }


def evaluate_recommendation_file(
    result_json_path,
    processed_plans_csv="inputs/processed_plans.csv",
    output_dir="outputs",
    model_name="Alibaba-NLP/gte-modernbert-base",
    device="cpu"
):
    with open(result_json_path, "r", encoding="utf-8") as f:
        result_data = json.load(f)

    plan_lookup = load_plan_lookup(processed_plans_csv)

    users = result_data.get("users", [])

    user_evaluations = []

    for idx, user_result in enumerate(users, start=1):
        print(f"Evaluating user {idx}/{len(users)}: {user_result.get('test_id')}")

        user_eval = evaluate_user_result(
            user_result=user_result,
            plan_lookup=plan_lookup,
            model_name=model_name,
            device=device
        )

        user_evaluations.append(user_eval)

    valid_user_scores = [
        u["user_average_score_10"]
        for u in user_evaluations
        if "user_average_score_10" in u
    ]

    model_average_score = (
        sum(valid_user_scores) / len(valid_user_scores)
        if valid_user_scores
        else 0.0
    )

    final_report = {
        "source_result_json": result_json_path,
        "processed_plans_csv": processed_plans_csv,
        "model_name": model_name,
        "score_definition": {
            "attribute_match": f"+1 for each matching hard attribute: {ATTRIBUTE_FIELDS}",
            "embedding_match": "+1 if recommended plan text is more similar to user query text than the seed plan text",
            "scale": "Final plan score is converted to a 0-10 scale",
            "note": "Tariff fit is not included in this evaluation version."
        },
        "num_users": len(user_evaluations),
        "model_average_score_10": round(model_average_score, 4),
        "user_evaluations": user_evaluations
    }

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir) / f"recommendation_evaluation_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)

    print("Evaluation saved to:", output_path)
    print("Model average score:", round(model_average_score, 4))

    return final_report


if __name__ == "__main__":
    evaluate_recommendation_file(
        result_json_path="outputs/vertex_test_results_20260521_104709.json",
        processed_plans_csv="inputs/processed_plans.csv",
        output_dir="outputs",
        model_name="Alibaba-NLP/gte-modernbert-base",
        device="cpu"
    )