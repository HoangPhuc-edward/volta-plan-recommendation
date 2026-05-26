import json
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


if __name__ == "__main__":

    bucket_name = "energy-plan-bucket-1"

    blob_name = (
        "gte-modernbert-processed-plans/"
        "plan_store/plan_lookup.json"
    )

    plan_id = "1ST1029828MRE1@EME"

    plan = get_plan_from_bucket_by_id(
        plan_id=plan_id,
        bucket_name=bucket_name,
        blob_name=blob_name
    )

    schema = normalize_plan_for_calculation(plan)


    if plan:
        print(json.dumps(schema, indent=2)[:100])
    else:
        print("Plan not found.")