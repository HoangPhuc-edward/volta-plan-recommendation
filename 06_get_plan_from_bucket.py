import json
import re
from google.cloud import storage
from calculation_function.normalize_plan_schema import normalize_plan_for_calculation

def get_plan_from_bucket_by_id(
    plan_id: str,
    bucket_name: str,
    blob_name: str
):
    """
    Retrieve a plan from plan_lookup.json stored in Google Cloud Storage.

    Args:
        plan_id (str): The plan ID to search for.
        bucket_name (str): GCS bucket name.
        blob_name (str): Path to plan_lookup.json inside bucket.

    Returns:
        dict | None: Plan data if found, else None.
    """

    # Create authenticated GCS client
    client = storage.Client()

    # Access bucket
    bucket = client.bucket(bucket_name)

    # Access file/object
    blob = bucket.blob(blob_name)

    # Download JSON content
    content = blob.download_as_text(encoding="utf-8")

    # Convert JSON string -> Python dict
    plan_lookup = json.loads(content)

    # Return matching plan
    return plan_lookup.get(plan_id)


def normalize_text(text: str) -> str:
    """
    Normalize text for matching.

    Example:
        "1st Energy" -> "1st_energy"
        "Value Saver Plus" -> "value_saver_plus"
    """

    text = str(text or "").strip().lower()

    text = re.sub(r"[^a-z0-9]+", "_", text)

    text = re.sub(r"_+", "_", text).strip("_")

    return text


def get_plan_id_from_bucket(
    retailer_name: str,
    display_name: str,
    bucket_name: str,
    gcs_prefix: str
):

    retailer_key = normalize_text(retailer_name)

    blob_name = (
        f"{gcs_prefix}/"
        f"plan_{retailer_key}.json"
    )

    client = storage.Client()

    bucket = client.bucket(bucket_name)

    blob = bucket.blob(blob_name)

    if not blob.exists():
        print(f"Retailer file not found: {blob_name}")
        return None

    content = blob.download_as_text(
        encoding="utf-8"
    )

    plan_lookup = json.loads(content)
  

    target_display_name = normalize_text(display_name)

    for plan_id, plan_display_name in plan_lookup.items():

        if (
            normalize_text(plan_display_name)
            == target_display_name
        ):
            return plan_id

    return None


if __name__ == "__main__":

    bucket_name = "energy-plan-bucket-1"

    blob_name = (
        "gte-modernbert-processed-plans/"
        "plan_store/plan_lookup.json"
    )

    # plan_id = "1ST1029828MRE1@EME"

    # plan = get_plan_from_bucket_by_id(
    #     plan_id=plan_id,
    #     bucket_name=bucket_name,
    #     blob_name=blob_name
    # )

    # schema = normalize_plan_for_calculation(plan)


    # if plan:
    #     print(json.dumps(schema, indent=2)[:100])
    # else:
    #     print("Plan not found.")

    plan_id = get_plan_id_from_bucket(
        retailer_name="1st Energy",
        display_name="1st Orange - Time of Use",
        bucket_name=bucket_name,
        gcs_prefix="gte-modernbert-processed-plans/plan_by_retailer"
    )

    if plan_id:
        print(f"Found plan_id: {plan_id}")
    else:
        print("Plan ID not found.")
