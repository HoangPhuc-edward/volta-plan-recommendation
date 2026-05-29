import json
import logging
import os
import re
import warnings
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from google.cloud import aiplatform, storage

from vertex_query import query_vertex_with_fallback
from calculation_function.normalize_plan_schema import normalize_plan_for_calculation
from calculation_function.normalize_user_schema import normalize_user_for_calculation
from calculation_function.cost_flow import calculate_net_cost
from normalize_user.prepare_user_data import normalize_user_for_query
from config import load_config
from validation import validate_user_profile, format_validation_errors


# =========================
# Logging / warnings
# =========================

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("volta-plan-api")

warnings.filterwarnings("ignore", module="google.api_core._python_version_support")
warnings.filterwarnings("ignore", category=FutureWarning)


# =========================
# Config
# =========================

_config = load_config()

PROJECT_ID = _config["PROJECT_ID"]
REGION = _config["REGION"]
ENDPOINT_RESOURCE_NAME = _config["ENDPOINT_RESOURCE_NAME"]
DEPLOYED_INDEX_ID = _config["DEPLOYED_INDEX_ID"]
BUCKET_NAME = _config["BUCKET_NAME"]
MODEL_NAME = _config["MODEL_NAME"]
PLAN_SUMMARY_PREFIX = _config["PLAN_SUMMARY_PREFIX"]
DEFAULT_TARGET_K = int(_config["DEFAULT_TARGET_K"])
DEFAULT_PER_LEVEL_TOP_K = int(_config["DEFAULT_PER_LEVEL_TOP_K"])
DEFAULT_TOP_N = int(_config["DEFAULT_TOP_N"])

# Optional configs not necessarily present in config.py yet.
RETAILER_PLAN_PREFIX = os.getenv(
    "RETAILER_PLAN_PREFIX",
    "gte-modernbert-processed-plans/plan_by_retailer",
)
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
    if origin.strip()
]


# =========================
# Global resources
# =========================

model: Optional[SentenceTransformer] = None
endpoint = None
gcs_client: Optional[storage.Client] = None
gcs_bucket: Optional[storage.Bucket] = None


# =========================
# Request schema
# =========================

class RecommendRequest(BaseModel):
    user_profile: Dict[str, Any]
    current_plan_id: Optional[str] = None
    current_retailer_name: Optional[str] = None
    current_plan_display_name: Optional[str] = None
    target_k: int = Field(default=DEFAULT_TARGET_K, ge=1, le=200)
    per_level_top_k: int = Field(default=DEFAULT_PER_LEVEL_TOP_K, ge=1, le=500)
    top_n: int = Field(default=DEFAULT_TOP_N, ge=1, le=20)


# =========================
# Lifespan startup
# =========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, endpoint, gcs_client, gcs_bucket

    logger.info("Loading embedding model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)

    logger.info("Initializing Vertex AI endpoint")
    aiplatform.init(project=PROJECT_ID, location=REGION)
    endpoint = aiplatform.MatchingEngineIndexEndpoint(
        index_endpoint_name=ENDPOINT_RESOURCE_NAME
    )

    logger.info("Initializing Google Cloud Storage client")
    gcs_client = storage.Client()
    gcs_bucket = gcs_client.bucket(BUCKET_NAME)

    logger.info("API startup complete")
    yield
    logger.info("API shutdown complete")


app = FastAPI(
    title="Volta Plan Recommendation API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Helper functions
# =========================

def normalize_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def get_gcs_bucket() -> storage.Bucket:
    if gcs_bucket is None:
        raise RuntimeError("GCS bucket is not initialized.")
    return gcs_bucket


@lru_cache(maxsize=4096)
def get_plan_from_bucket_by_id(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single plan JSON from GCS.

    GCS path:
        gs://<bucket>/<PLAN_SUMMARY_PREFIX>/plan_<plan_id>.json
    """
    if not plan_id:
        return None

    bucket = get_gcs_bucket()
    blob_name = f"{PLAN_SUMMARY_PREFIX}/plan_{plan_id}.json"
    blob = bucket.blob(blob_name)

    if not blob.exists():
        logger.warning("Plan file not found: %s", blob_name)
        return None

    content = blob.download_as_text(encoding="utf-8")
    return json.loads(content)


@lru_cache(maxsize=256)
def get_retailer_plan_lookup(retailer_name: str) -> Optional[Dict[str, str]]:
    """
    Load one retailer lookup file from GCS and cache it in memory.

    Expected file:
        gs://<bucket>/<RETAILER_PLAN_PREFIX>/plan_<retailer_key>.json

    Expected content:
        {
            "PLAN_ID": "Display Name"
        }
    """
    retailer_key = normalize_text(retailer_name)
    if not retailer_key:
        return None

    bucket = get_gcs_bucket()
    blob_name = f"{RETAILER_PLAN_PREFIX}/plan_{retailer_key}.json"
    blob = bucket.blob(blob_name)

    if not blob.exists():
        logger.warning("Retailer file not found: %s", blob_name)
        return None

    content = blob.download_as_text(encoding="utf-8")
    return json.loads(content)


def get_plan_id_from_bucket(
    retailer_name: str,
    display_name: str,
) -> Optional[str]:
    plan_lookup = get_retailer_plan_lookup(retailer_name)
    if not plan_lookup:
        return None

    target_display_name = normalize_text(display_name)
    for plan_id, plan_display_name in plan_lookup.items():
        if normalize_text(plan_display_name) == target_display_name:
            return plan_id

    return None


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _get_selected_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(user, dict):
        return {}
    selected = user.get("selected_profile", user)
    return selected if isinstance(selected, dict) else {}


def _safe_get_plan_info(user: Dict[str, Any]) -> Dict[str, Any]:
    selected_profile = _get_selected_profile(user)
    plan = selected_profile.get("plan")
    return plan if isinstance(plan, dict) else {}


def explain_result_item(item: Dict[str, Any], hard_filter: Dict[str, Any]) -> List[str]:
    explanations = []

    retailer_name = hard_filter.get("retailer_name")
    customer_type = hard_filter.get("customer_type")
    distributors = _as_list(hard_filter.get("distributors"))
    tariff_types = _as_list(hard_filter.get("tariff_type"))

    has_solar = hard_filter.get("has_solar")
    has_ev = hard_filter.get("has_ev")
    has_controlled_load = hard_filter.get("has_controlled_load")

    if retailer_name:
        explanations.append(f"This plan matches your preferred retailer: {retailer_name}.")

    if customer_type:
        explanations.append(f"This plan is available for {str(customer_type).lower()} customers.")

    if distributors:
        explanations.append(
            "This plan supports your electricity distributor: "
            f"{', '.join(map(str, distributors))}."
        )

    if hard_filter.get("included_postcodes"):
        explanations.append("This plan is available in your area.")

    if tariff_types:
        tariff_text = ", ".join(str(t).replace("_", " ").title() for t in tariff_types)
        explanations.append(f"This plan supports your tariff preference: {tariff_text}.")

    if has_solar is True:
        explanations.append("This plan is compatible with households that use solar energy.")

    if has_ev is True:
        explanations.append("This plan is suitable for electric vehicle charging usage.")

    if has_controlled_load is True:
        explanations.append(
            "This plan supports controlled load usage such as electric hot water systems."
        )

    dropped_filters = item.get("dropped_filters") or []
    if dropped_filters:
        explanations.append(
            "To widen the search results, the system relaxed these filters: "
            f"{', '.join(map(str, dropped_filters))}."
        )
    else:
        explanations.append("This plan matched all of your hard filter conditions.")

    return explanations


def safe_percentage_diff(new_val: float, current_val: float) -> Optional[float]:
    if current_val == 0:
        return None
    return ((new_val - current_val) / current_val) * 100


def build_compare_output(
    cost_output: Dict[str, Any],
    current_plan_cost_output: Dict[str, Any],
) -> Dict[str, Any]:
    current_cost = current_plan_cost_output.get("estimated_monthly_cost", 0)
    new_cost = cost_output.get("estimated_monthly_cost", 0)

    current_breakdown = current_plan_cost_output.get("cost_breakdown", {})
    new_breakdown = cost_output.get("cost_breakdown", {})

    return {
        "current_plan_cost": current_cost,
        "current_plan_cost_breakdown": current_breakdown,
        "monthly_cost_difference": new_cost - current_cost,
        "monthly_cost_percentage_difference": safe_percentage_diff(new_cost, current_cost),
        "e1_cost_difference": new_breakdown.get("e1_cost", 0) - current_breakdown.get("e1_cost", 0),
        "e1_cost_percentage_difference": safe_percentage_diff(
            new_breakdown.get("e1_cost", 0), current_breakdown.get("e1_cost", 0)
        ),
        "e2_cost_difference": new_breakdown.get("e2_cost", 0) - current_breakdown.get("e2_cost", 0),
        "e2_cost_percentage_difference": safe_percentage_diff(
            new_breakdown.get("e2_cost", 0), current_breakdown.get("e2_cost", 0)
        ),
        "supply_charge_difference": new_breakdown.get("supply_charge", 0) - current_breakdown.get("supply_charge", 0),
        "supply_charge_percentage_difference": safe_percentage_diff(
            new_breakdown.get("supply_charge", 0), current_breakdown.get("supply_charge", 0)
        ),
    }


def resolve_current_plan_id(
    *,
    user: Dict[str, Any],
    current_plan_id: Optional[str] = None,
    current_retailer_name: Optional[str] = None,
    current_plan_display_name: Optional[str] = None,
) -> Optional[str]:
    if current_plan_id:
        return current_plan_id

    plan_info = _safe_get_plan_info(user)
    retailer_name = current_retailer_name or plan_info.get("retailer_name")
    display_name = (
        current_plan_display_name
        or plan_info.get("current_plan_name")
        or plan_info.get("display_name")
        or plan_info.get("plan_name")
    )

    if not retailer_name or not display_name:
        logger.info("Current plan retailer/display name not provided. Skipping current plan comparison.")
        return None

    logger.info(
        "Resolving current plan ID from retailer='%s', display_name='%s'",
        retailer_name,
        display_name,
    )
    return get_plan_id_from_bucket(retailer_name=retailer_name, display_name=display_name)


def build_current_plan_cost_output(
    *,
    user: Dict[str, Any],
    normalized_user: Dict[str, Any],
    current_plan_id: Optional[str],
    current_retailer_name: Optional[str] = None,
    current_plan_display_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    resolved_plan_id = resolve_current_plan_id(
        user=user,
        current_plan_id=current_plan_id,
        current_retailer_name=current_retailer_name,
        current_plan_display_name=current_plan_display_name,
    )

    if not resolved_plan_id:
        return None

    current_plan_data = get_plan_from_bucket_by_id(resolved_plan_id)
    if not current_plan_data:
        logger.warning("Current plan data not found for plan_id=%s", resolved_plan_id)
        return None

    normalized_current_plan = normalize_plan_for_calculation(current_plan_data)
    return calculate_net_cost(normalized_user, normalized_current_plan)


def get_plan_from_user(
    user: Dict[str, Any],
    target_k: int = DEFAULT_TARGET_K,
    per_level_top_k: int = DEFAULT_PER_LEVEL_TOP_K,
    top_n: int = DEFAULT_TOP_N,
    current_plan_id: Optional[str] = None,
    current_retailer_name: Optional[str] = None,
    current_plan_display_name: Optional[str] = None,
) -> Dict[str, Any]:
    if model is None:
        raise RuntimeError("Embedding model is not initialized.")
    if endpoint is None:
        raise RuntimeError("Vertex endpoint is not initialized.")

    selected_profile = _get_selected_profile(user)
    profile_id = selected_profile.get("profile_id", "unknown")
    logger.info("Processing recommendation request for profile_id=%s", profile_id)

    user_query = normalize_user_for_query(user)
    query_text = user_query["query_text"]
    hard_filter = user_query["hard_filter"]

    query_vector = model.encode([query_text], normalize_embeddings=True)[0]
    if hasattr(query_vector, "tolist"):
        query_vector = query_vector.tolist()

    retrieved = query_vertex_with_fallback(
        endpoint=endpoint,
        deployed_index_id=DEPLOYED_INDEX_ID,
        query_vector=query_vector,
        hard_filter=hard_filter,
        target_k=target_k,
        per_level_top_k=per_level_top_k,
    )

    normalized_user = normalize_user_for_calculation(user)
    current_plan_cost_output = build_current_plan_cost_output(
        user=user,
        normalized_user=normalized_user,
        current_plan_id=current_plan_id,
        current_retailer_name=current_retailer_name,
        current_plan_display_name=current_plan_display_name,
    )

    results = []
    skipped_plan_ids = []

    for item in retrieved:
        plan_id = item.get("plan_id")
        if not plan_id:
            continue

        plan_data = get_plan_from_bucket_by_id(plan_id)
        if plan_data is None:
            skipped_plan_ids.append(plan_id)
            continue

        normalized_plan = normalize_plan_for_calculation(plan_data)
        cost_output = calculate_net_cost(normalized_user, normalized_plan)

        compare_output = None
        if current_plan_cost_output is not None:
            compare_output = build_compare_output(cost_output, current_plan_cost_output)

        results.append({
            "plan_id": plan_id,
            "plan_data": plan_data,
            "net_monthly_cost": cost_output.get("estimated_monthly_cost"),
            "cost_breakdown": cost_output.get("cost_breakdown", {}),
            "distance": item.get("distance"),
            "similarity_note": "For COSINE_DISTANCE, lower distance means higher similarity.",
            "filter_match_level": item.get("filter_match_level"),
            "dropped_filters": item.get("dropped_filters", []),
            "matched_against_hard_filter": hard_filter,
            "why_selected": explain_result_item(item, hard_filter),
            "compare_with_current_plan": compare_output,
        })

    results = sorted(
        results,
        key=lambda x: x.get("net_monthly_cost") if x.get("net_monthly_cost") is not None else float("inf"),
    )[:top_n]

    logger.info(
        "Finished request profile_id=%s retrieved=%s returned=%s skipped=%s",
        profile_id,
        len(retrieved),
        len(results),
        len(skipped_plan_ids),
    )

    return {
        "profile_id": profile_id,
        "num_retrieved": len(retrieved),
        "num_results": len(results),
        "skipped_plan_ids": skipped_plan_ids,
        "results": results,
    }


# =========================
# API routes
# =========================

@app.get("/")
def root():
    return {"message": "Volta Plan Recommendation API is running."}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "vertex_endpoint_ready": endpoint is not None,
        "gcs_ready": gcs_bucket is not None,
        "project_id": PROJECT_ID,
        "region": REGION,
        "bucket_name": BUCKET_NAME,
    }


@app.post("/recommend-plans")
def recommend_plans(request: RecommendRequest):
    try:
        # Validate user profile
        is_valid, errors = validate_user_profile(request.user_profile)
        if not is_valid:
            error_message = format_validation_errors(errors)
            logger.warning(f"User profile validation failed: {error_message}")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Invalid user profile",
                    "message": error_message,
                    "errors": errors,
                }
            )

        return get_plan_from_user(
            user=request.user_profile,
            target_k=request.target_k,
            per_level_top_k=request.per_level_top_k,
            top_n=request.top_n,
            current_plan_id=request.current_plan_id,
            current_retailer_name=request.current_retailer_name,
            current_plan_display_name=request.current_plan_display_name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Recommendation request failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
