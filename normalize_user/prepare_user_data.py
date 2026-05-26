import json
import random
import pandas as pd

INPUT_CSV = "inputs/synthetic_users_from_plans.csv"
OUTPUT_CSV = "inputs/ready_test_users.csv"

random.seed(42)


def build_query_text(profile):
    parts = []

    retailer_name = (
        profile["plan"]
        .get("retailer_name")
    )

    people_count = (
        profile["household"]
        .get("people_count")
    )

    occupancy = (
        profile["household"]
        .get("occupancy_pattern")
    )

    if retailer_name:
        parts.append(f"Plan from {retailer_name}")

    if people_count:
        parts.append(f"{people_count} people household")

    if occupancy:
        parts.append(str(occupancy))

    time_of_day = (
        profile["energy_usage"]
        .get("usage_pattern", {})
        .get("time_of_day")
    )

    if time_of_day:
        parts.append(f"{time_of_day} electricity usage")

    if profile["solar"].get("has_solar"):
        parts.append("has solar panels")

    if profile["battery"].get("has_battery"):
        parts.append("has battery")

    if profile["ev"].get("has_ev"):
        parts.append("electric vehicle charging")

    if (
        profile["household"]
        .get("controlled_load_present")
    ):
        parts.append("controlled load")

    primary_goal = (
        profile["preferences"]
        .get("primary_goal")
    )

    if primary_goal == "go_green":
        parts.append("prefers renewable green energy")

    elif primary_goal == "reduce_bill":
        parts.append("wants lower electricity bills")

    elif primary_goal == "max_savings":
        parts.append("wants maximum savings")

    elif primary_goal == "backup_power":
        parts.append("interested in backup power")

    elif primary_goal == "good_roi":
        parts.append("wants good return on investment")

    return ". ".join(parts)


def normalize_tariff_type(tariff_pref):
    if tariff_pref in [
        "time_of_use",
        "TIME_OF_USE",
        "TIME_OF_USE_CONT_LOAD"
    ]:
        return "TIME_OF_USE"

    if tariff_pref in [
        "flat",
        "single_rate",
        "SINGLE_RATE",
        "SINGLE_RATE_CONT_LOAD"
    ]:
        return "SINGLE_RATE"

    return None


def build_hard_filter(profile):
    distributor = (
        profile["location"]
        .get("context", {})
        .get("distributor_region")
    )

    postcode = (
        profile["location"]
        .get("postcode")
    )

    tariff_pref = (
        profile["plan"]
        .get("tariff_type_preference")
    )

    tariff_type = normalize_tariff_type(
        tariff_pref
    )

    has_controlled_load = (
        profile["household"]
        .get("controlled_load_present", False)
    )

    has_solar = (
        profile["solar"]
        .get("has_solar", False)
    )

    has_ev = (
        profile["ev"]
        .get("has_ev", False)
    )

    retailer_name = (
        profile["plan"]
        .get("retailer_name")
    )

    return {
        "retailer_name": retailer_name,
        "customer_type": "RESIDENTIAL",

        "distributors": [
            distributor
        ] if distributor else [],

        "included_postcodes": [
            str(postcode)
        ] if postcode else [],

        "tariff_type": [
            tariff_type
        ] if tariff_type else [],

        "has_controlled_load": has_controlled_load,

        "has_solar": has_solar,

        "has_ev": has_ev
    }


def process_user_for_testing(row):
    payload = json.loads(
        row["user_profile_json"]
    )

    profile = payload["selected_profile"]

    hard_filter = build_hard_filter(
        profile
    )

    query_text = build_query_text(
        profile
    )

    normalized_user = {
        "test_id": row["test_id"],

        "seed_plan_id": row["seed_plan_id"],

        "query_text": query_text,

        "hard_filter": hard_filter,

        "user_profile": payload
    }

    return normalized_user


def normalize_user_for_query(payload):
    
    profile = payload["selected_profile"]
    
    hard_filter = build_hard_filter(
        profile
    )

    query_text = build_query_text(
        profile
    )

    normalized_user = {
        "query_text": query_text,
        "hard_filter": hard_filter,
        "user_profile": payload
    }

    return normalized_user
    


def main():
    df = pd.read_csv(INPUT_CSV)

    rows = []

    for _, row in df.iterrows():
        normalized_user = process_user_for_testing(
            row
        )

        rows.append({
            "test_id": normalized_user["test_id"],

            "seed_plan_id": normalized_user["seed_plan_id"],

            "query_text": normalized_user["query_text"],

            "hard_filter": json.dumps(
                normalized_user["hard_filter"],
                ensure_ascii=False
            ),

            "user_profile_json": json.dumps(
                normalized_user["user_profile"],
                ensure_ascii=False
            )
        })

    output_df = pd.DataFrame(rows)

    output_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"Processed {len(output_df)} users")
    print(f"Saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()