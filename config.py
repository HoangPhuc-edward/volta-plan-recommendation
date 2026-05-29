"""
Configuration management for Volta Plan Recommendation API.
"""

import os
from dotenv import load_dotenv


load_dotenv()


def load_config():
    config = {
        "PROJECT_ID": os.getenv("PROJECT_ID", "project-ce1ff6dc-7e15-4f39-bb3"),
        "REGION": os.getenv("REGION", "us-central1"),
        "ENDPOINT_RESOURCE_NAME": os.getenv(
            "ENDPOINT_RESOURCE_NAME",
            "projects/933786093071/locations/us-central1/indexEndpoints/7108256911664873472"
        ),
        "DEPLOYED_INDEX_ID": os.getenv(
            "DEPLOYED_INDEX_ID",
            "energy_plan_endpoint_1779948482642"
        ),
        "BUCKET_NAME": os.getenv("BUCKET_NAME", "energy-plan-bucket-1"),
        "MODEL_NAME": os.getenv("MODEL_NAME", "Alibaba-NLP/gte-modernbert-base"),
        "PLAN_SUMMARY_PREFIX": os.getenv(
            "PLAN_SUMMARY_PREFIX",
            "gte-modernbert-processed-plans/plan_summary"
        ),
        "DEFAULT_TARGET_K": int(os.getenv("DEFAULT_TARGET_K", "20")),
        "DEFAULT_PER_LEVEL_TOP_K": int(os.getenv("DEFAULT_PER_LEVEL_TOP_K", "50")),
        "DEFAULT_TOP_N": int(os.getenv("DEFAULT_TOP_N", "5")),
    }

    return config