import json
from pathlib import Path
from datetime import datetime
import time
import pandas as pd
from sentence_transformers import SentenceTransformer
from google.cloud import aiplatform, storage
from yaml import warnings
from vertex_query import query_vertex_with_fallback
from calculation_function.normalize_plan_schema import normalize_plan_for_calculation
from calculation_function.normalize_user_schema import normalize_user_for_calculation
from calculation_function.cost_flow import calculate_net_cost
from normalize_user.prepare_user_data import normalize_user_for_query


# Project information
PROJECT_ID = "project-ce1ff6dc-7e15-4f39-bb3"
REGION = "us-central1"

ENDPOINT_RESOURCE_NAME = "projects/933786093071/locations/us-central1/indexEndpoints/7108256911664873472"
DEPLOYED_INDEX_ID = "energy_plan_endpoint_1779775426827"

MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"

_gcs_client = None
_gcs_bucket = None

def get_plan_from_bucket_by_id(
    plan_id: str,
    client=None,
    bucket=None
):
    """
    Retrieve a single plan JSON directly from Google Cloud Storage.

    Structure:
    gs://energy-plan-bucket-1/
        gte-modernbert-processed-plans/
            plan_store/
                <plan_id>.json
    """
    global _gcs_client, _gcs_bucket
    
    bucket_name = "energy-plan-bucket-1"

    if client is None:
        if _gcs_client is None:
            _gcs_client = storage.Client()
        client = _gcs_client
    
    if bucket is None:
        if _gcs_bucket is None:
            _gcs_bucket = client.bucket(bucket_name)
        bucket = _gcs_bucket

    blob_name = (
        "gte-modernbert-processed-plans/"
        f"plan_summary/plan_{plan_id}.json"
    )

    # Access blob/file
    blob = bucket.blob(blob_name)

    # Check if file exists
    if not blob.exists():
        return None

    # Download JSON content
    content = blob.download_as_text(
        encoding="utf-8"
    )

    # Convert JSON string -> Python dict
    return json.loads(content)

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

    retailer_name = hard_filter.get("retailer_name")
    customer_type = hard_filter.get("customer_type")
    distributors = hard_filter.get("distributors", [])[0]
    tariff_type = hard_filter.get("tariff_type")[0]
    has_solar = hard_filter.get("has_solar")
    has_ev = hard_filter.get("has_ev")
    has_controlled_load = hard_filter.get("has_controlled_load")

    if retailer_name:
        explanations.append(
            f"This plan matches your preferred retailer: {retailer_name}."
        )

    if customer_type:
        explanations.append(
            f"This plan is available for {customer_type.lower()} customers."
        )


    if distributors:
        distributor_text = ", ".join(distributors)

        explanations.append(
            f"This plan supports your electricity distributor: {distributor_text}."
        )


    if hard_filter.get("included_postcodes"):
        explanations.append(
            "This plan is available in your area."
        )

    if tariff_type:
        explanations.append(
            f"This plan supports your tariff preference: {tariff_type.replace('_', ' ').title()}."
        )


    if has_solar is True:
        explanations.append(
            "This plan is compatible with households that use solar energy."
        )

    if has_ev is True:
        explanations.append(
            "This plan is suitable for electric vehicle charging usage."
        )

    if has_controlled_load is True:
        explanations.append(
            "This plan supports controlled load usage such as electric hot water systems."
        )  

    if item.get("dropped_filters"):

        dropped_text = ", ".join(
            item["dropped_filters"]
        )

        explanations.append(
            f"To widen the search results, the system relaxed these filters: {dropped_text}."
        )

    else:
        explanations.append(
            "This plan matched all of your hard filter conditions."
        )

    return explanations

def get_plan_from_user(user, model, endpoint, target_k=20, per_level_top_k=50, current_plan_id=None):

    user_query = normalize_user_for_query(user)

    print(f"User query for vertex: {user_query}")

    query_vector = model.encode(
        [user_query["query_text"]],
        normalize_embeddings=True
    )[0]

    retrieved = query_vertex_with_fallback(
        endpoint=endpoint,
        deployed_index_id=DEPLOYED_INDEX_ID,
        query_vector=query_vector,
        hard_filter=user_query["hard_filter"],
        target_k=target_k,
        per_level_top_k=per_level_top_k
    )

    results = []
    
    # Normalize user once outside the loop
    normalized_user = normalize_user_for_calculation(user)
    print(f"Normalized user for calculation: {normalized_user}")
    
    # Prepare current plan data if comparison is needed
    current_plan_data = None
    normalized_current_plan = None
    current_plan_cost_output = None
    
    if current_plan_id:
        current_plan_data = get_plan_from_bucket_by_id(plan_id=current_plan_id)
        if current_plan_data:
            print(f"Current plan {current_plan_data}")
            normalized_current_plan = normalize_plan_for_calculation(current_plan_data)
            current_plan_cost_output = calculate_net_cost(normalized_user, normalized_current_plan)
            print(f"CURRENT PLAN COST OUTPUT: {current_plan_cost_output}")       

    for item in retrieved:

        plan_data = get_plan_from_bucket_by_id(
            plan_id=item["plan_id"],
        )
        
        normalized_plan = normalize_plan_for_calculation(plan_data)

        cost_output = calculate_net_cost(normalized_user, normalized_plan)

       
        compare_output = None

        if current_plan_cost_output is not None:
            current_cost = current_plan_cost_output["estimated_monthly_cost"]
            new_cost = cost_output["estimated_monthly_cost"]
            
            # Helper function to safely calculate percentage difference
            def safe_percentage_diff(new_val, current_val):
                return ((new_val - current_val) / current_val * 100) if current_val != 0 else None
            
            compare_output = {
                "current_plan_cost": current_cost,
                "monthly_cost_difference": new_cost - current_cost,
                "monthly_cost_percentage_difference": safe_percentage_diff(new_cost, current_cost),
                "e1_cost_difference": cost_output["cost_breakdown"]["e1_cost"] - current_plan_cost_output["cost_breakdown"]["e1_cost"],
                "e1_cost_percentage_difference": safe_percentage_diff(
                    cost_output["cost_breakdown"]["e1_cost"],
                    current_plan_cost_output["cost_breakdown"]["e1_cost"]
                ),
                "e2_cost_difference": cost_output["cost_breakdown"]["e2_cost"] - current_plan_cost_output["cost_breakdown"]["e2_cost"],
                "e2_cost_percentage_difference": safe_percentage_diff(
                    cost_output["cost_breakdown"]["e2_cost"],
                    current_plan_cost_output["cost_breakdown"]["e2_cost"]
                ),
                "supply_charge_difference": cost_output["cost_breakdown"]["supply_charge"] - current_plan_cost_output["cost_breakdown"]["supply_charge"],
                "supply_charge_percentage_difference": safe_percentage_diff(
                    cost_output["cost_breakdown"]["supply_charge"],
                    current_plan_cost_output["cost_breakdown"]["supply_charge"]
                )
            }


        result = {
            "plan_id": item["plan_id"],
            "plan_data": plan_data,
            "net_monthly_cost": cost_output["estimated_monthly_cost"],
            "cost_breakdown": cost_output["cost_breakdown"],
            "distance": item["distance"],
            "similarity_note": "For COSINE_DISTANCE, lower distance means higher similarity.",
            "filter_match_level": item["filter_match_level"],
            "dropped_filters": item["dropped_filters"],
            "matched_against_hard_filter": user_query["hard_filter"],
            "why_selected": explain_result_item(item, user_query["hard_filter"]),
            "compare_with_current_plan": compare_output
        }

        results.append(result)

    results = sorted(
        results,
        key=lambda x: x["net_monthly_cost"]
    )

    # Keep only top 5 cheapest plans
    results = results[:5]


    return {
        "num_results": len(results),
        "results": results
    }

import warnings
warnings.simplefilter("ignore", FutureWarning)

import time


def main(): 

    start_time = time.time()

    endpoint = init_vertex_endpoint()

    model = SentenceTransformer(MODEL_NAME)

    # with open("inputs/selected_profile_payload.json", "r") as f:
    #     user = json.load(f)

    user_df = pd.read_csv(
        "inputs/synthetic_users_from_plans.csv"
    )

    user = json.loads(
        user_df.iloc[0]["user_profile_json"]
    )

    plan_recommendations = get_plan_from_user(
        user=user,
        model=model,
        endpoint=endpoint,
        target_k=20,
        per_level_top_k=50,
        current_plan_id="1ST937721MRE1@EME"
    )

    with open(
        "outputs/plan_recommendations.json",
        "w"
    ) as f:
        json.dump(
            plan_recommendations,
            f,
            indent=2
        )

    end_time = time.time()

    elapsed_time = end_time - start_time

    print(
        "Plan recommendations saved to "
        "outputs/plan_recommendations.json"
    )

    print(
        f"Execution time: "
        f"{elapsed_time:.2f} seconds"
    )


if __name__ == "__main__":
    main()


