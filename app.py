import json
import warnings
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from google.cloud import aiplatform, storage

from vertex_query import query_vertex_with_fallback
from calculation_function.normalize_plan_schema import normalize_plan_for_calculation
from calculation_function.normalize_user_schema import normalize_user_for_calculation
from calculation_function.cost_flow import calculate_net_cost
from normalize_user.prepare_user_data import normalize_user_for_query

from fastapi.middleware.cors import CORSMiddleware
# =========================
# Suppress noisy warnings
# =========================

warnings.filterwarnings(
    "ignore",
    module="google.api_core._python_version_support"
)

warnings.filterwarnings(
    "ignore",
    category=FutureWarning
)


# =========================
# Config
# =========================

PROJECT_ID = "project-ce1ff6dc-7e15-4f39-bb3"
REGION = "us-central1"

ENDPOINT_RESOURCE_NAME = (
    "projects/933786093071/locations/us-central1/"
    "indexEndpoints/7108256911664873472"
)

DEPLOYED_INDEX_ID = "energy_plan_endpoint_1779852224601"

MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"

BUCKET_NAME = "energy-plan-bucket-1"

PLAN_SUMMARY_PREFIX = (
    "gte-modernbert-processed-plans/"
    "plan_summary"
)

DEFAULT_TARGET_K = 20
DEFAULT_PER_LEVEL_TOP_K = 50
DEFAULT_TOP_N = 5


# =========================
# Global resources
# =========================

model: Optional[SentenceTransformer] = None
endpoint = None
gcs_client: Optional[storage.Client] = None
gcs_bucket = None


# =========================
# Request schema
# =========================

class RecommendRequest(BaseModel):
    user_profile: Dict[str, Any]
    current_plan_id: Optional[str] = None
    target_k: int = DEFAULT_TARGET_K
    per_level_top_k: int = DEFAULT_PER_LEVEL_TOP_K
    top_n: int = DEFAULT_TOP_N


# =========================
# Lifespan startup
# =========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    global endpoint
    global gcs_client
    global gcs_bucket

    print("Loading embedding model...")
    model = SentenceTransformer(
        MODEL_NAME,
        trust_remote_code=True
    )

    print("Initializing Vertex AI endpoint...")
    aiplatform.init(
        project=PROJECT_ID,
        location=REGION
    )

    endpoint = aiplatform.MatchingEngineIndexEndpoint(
        index_endpoint_name=ENDPOINT_RESOURCE_NAME
    )

    print("Initializing Google Cloud Storage client...")
    gcs_client = storage.Client()
    gcs_bucket = gcs_client.bucket(BUCKET_NAME)

    print("API startup complete.")

    yield

    print("API shutdown complete.")


app = FastAPI(
    title="Volta Plan Recommendation API",
    version="1.0.0",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Helper functions
# =========================

def get_plan_from_bucket_by_id(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single plan JSON from GCS.

    GCS path:
    gs://energy-plan-bucket-1/
      gte-modernbert-processed-plans/
        plan_summary/
          plan_{plan_id}.json
    """

    if gcs_bucket is None:
        raise RuntimeError("GCS bucket is not initialized.")

    blob_name = (
        f"{PLAN_SUMMARY_PREFIX}/"
        f"plan_{plan_id}.json"
    )

    blob = gcs_bucket.blob(blob_name)

    if not blob.exists():
        return None

    content = blob.download_as_text(
        encoding="utf-8"
    )

    return json.loads(content)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def explain_result_item(
    item: Dict[str, Any],
    hard_filter: Dict[str, Any]
) -> List[str]:
    explanations = []

    retailer_name = hard_filter.get("retailer_name")
    customer_type = hard_filter.get("customer_type")
    distributors = _as_list(hard_filter.get("distributors"))
    tariff_types = _as_list(hard_filter.get("tariff_type"))

    has_solar = hard_filter.get("has_solar")
    has_ev = hard_filter.get("has_ev")
    has_controlled_load = hard_filter.get("has_controlled_load")

    if retailer_name:
        explanations.append(
            f"This plan matches your preferred retailer: {retailer_name}."
        )

    if customer_type:
        explanations.append(
            f"This plan is available for {str(customer_type).lower()} customers."
        )

    if distributors:
        explanations.append(
            "This plan supports your electricity distributor: "
            f"{', '.join(map(str, distributors))}."
        )

    if hard_filter.get("included_postcodes"):
        explanations.append(
            "This plan is available in your area."
        )

    if tariff_types:
        tariff_text = ", ".join(
            str(t).replace("_", " ").title()
            for t in tariff_types
        )

        explanations.append(
            f"This plan supports your tariff preference: {tariff_text}."
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

    dropped_filters = item.get("dropped_filters") or []

    if dropped_filters:
        explanations.append(
            "To widen the search results, the system relaxed these filters: "
            f"{', '.join(dropped_filters)}."
        )
    else:
        explanations.append(
            "This plan matched all of your hard filter conditions."
        )

    return explanations


def safe_percentage_diff(
    new_val: float,
    current_val: float
) -> Optional[float]:
    if current_val == 0:
        return None

    return ((new_val - current_val) / current_val) * 100


def build_compare_output(
    cost_output: Dict[str, Any],
    current_plan_cost_output: Dict[str, Any]
) -> Dict[str, Any]:
    current_cost = current_plan_cost_output["estimated_monthly_cost"]
    new_cost = cost_output["estimated_monthly_cost"]

    current_breakdown = current_plan_cost_output["cost_breakdown"]
    new_breakdown = cost_output["cost_breakdown"]

    return {
        "current_plan_cost": current_cost,
        "current_plan_cost_breakdown": current_breakdown,   
        "monthly_cost_difference": new_cost - current_cost,
        "monthly_cost_percentage_difference": safe_percentage_diff(
            new_cost,
            current_cost
        ),
        "e1_cost_difference": (
            new_breakdown.get("e1_cost", 0)
            - current_breakdown.get("e1_cost", 0)
        ),
        "e1_cost_percentage_difference": safe_percentage_diff(
            new_breakdown.get("e1_cost", 0),
            current_breakdown.get("e1_cost", 0)
        ),
        "e2_cost_difference": (
            new_breakdown.get("e2_cost", 0)
            - current_breakdown.get("e2_cost", 0)
        ),
        "e2_cost_percentage_difference": safe_percentage_diff(
            new_breakdown.get("e2_cost", 0),
            current_breakdown.get("e2_cost", 0)
        ),
        "supply_charge_difference": (
            new_breakdown.get("supply_charge", 0)
            - current_breakdown.get("supply_charge", 0)
        ),
        "supply_charge_percentage_difference": safe_percentage_diff(
            new_breakdown.get("supply_charge", 0),
            current_breakdown.get("supply_charge", 0)
        )
    }


def get_plan_from_user(
    user: Dict[str, Any],
    target_k: int = DEFAULT_TARGET_K,
    per_level_top_k: int = DEFAULT_PER_LEVEL_TOP_K,
    top_n: int = DEFAULT_TOP_N,
    current_plan_id: Optional[str] = None
) -> Dict[str, Any]:

    if model is None:
        raise RuntimeError("Embedding model is not initialized.")

    if endpoint is None:
        raise RuntimeError("Vertex endpoint is not initialized.")

    user_query = normalize_user_for_query(user)

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

    normalized_user = normalize_user_for_calculation(user)

    current_plan_cost_output = None

    if current_plan_id:
        current_plan_data = get_plan_from_bucket_by_id(current_plan_id)

        if current_plan_data:
            normalized_current_plan = normalize_plan_for_calculation(
                current_plan_data
            )

            current_plan_cost_output = calculate_net_cost(
                normalized_user,
                normalized_current_plan
            )

    results = []

    for item in retrieved:
        plan_id = item["plan_id"]

        plan_data = get_plan_from_bucket_by_id(plan_id)

        if plan_data is None:
            continue

        normalized_plan = normalize_plan_for_calculation(plan_data)

        cost_output = calculate_net_cost(
            normalized_user,
            normalized_plan
        )

        compare_output = None

        if current_plan_cost_output is not None:
            compare_output = build_compare_output(
                cost_output,
                current_plan_cost_output
            )

        result = {
            "plan_id": plan_id,
            "plan_data": plan_data,
            "net_monthly_cost": cost_output["estimated_monthly_cost"],
            "cost_breakdown": cost_output["cost_breakdown"],
            "distance": item["distance"],
            "similarity_note": (
                "For COSINE_DISTANCE, lower distance means higher similarity."
            ),
            "filter_match_level": item["filter_match_level"],
            "dropped_filters": item["dropped_filters"],
            "matched_against_hard_filter": user_query["hard_filter"],
            "why_selected": explain_result_item(
                item,
                user_query["hard_filter"]
            ),
            "compare_with_current_plan": compare_output
        }

        results.append(result)

    results = sorted(
        results,
        key=lambda x: x.get("net_monthly_cost", float("inf"))
    )

    results = results[:top_n]

    return {
        "num_results": len(results),
        "results": results
    }


# =========================
# API routes
# =========================

@app.get("/")
def root():
    return {
        "message": "Volta Plan Recommendation API is running."
    }


@app.post("/recommend-plans")
def recommend_plans(request: RecommendRequest):
    try:
        return get_plan_from_user(
            user=request.user_profile,
            target_k=request.target_k,
            per_level_top_k=request.per_level_top_k,
            top_n=request.top_n,
            current_plan_id=request.current_plan_id
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )