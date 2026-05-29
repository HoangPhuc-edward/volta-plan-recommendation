from datasets import load_dataset
from collections import defaultdict

data = load_dataset("hoangphuc090104/DCR_Energy_Plan")["train"]
# Remove NULL columns
null_cols = [c for c in data.column_names if any(v is None for v in data[c])]
data = data.remove_columns(null_cols)

# Remove single-value columns
single_value_cols = [c for c in data.column_names if len(set(data[c])) == 1]
data = data.remove_columns(single_value_cols)

print("Done. All NULL and Singleton columns dropped")

import json
import re


def safe_json_loads(value, default=None):
    if default is None:
        default = {}

    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        return value

    if not isinstance(value, str):
        return default

    try:
        return json.loads(value)
    except Exception:
        return default


def has_non_empty_list(value):
    return isinstance(value, list) and len(value) > 0


def convert_numeric_strings_to_float(obj):
    if isinstance(obj, dict):
        return {k: convert_numeric_strings_to_float(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [convert_numeric_strings_to_float(elem) for elem in obj]

    if isinstance(obj, str):
        try:
            return float(obj)
        except ValueError:
            return obj

    return obj


def extract_tariff_type(pricing_model):
    if pricing_model in ["SINGLE_RATE", "SINGLE_RATE_CONT_LOAD"]:
        return "SINGLE_RATE"

    if pricing_model in ["TIME_OF_USE", "TIME_OF_USE_CONT_LOAD"]:
        return "TIME_OF_USE"

    return None


def should_skip_plan(pricing_model):
    return pricing_model in ["FLEXIBLE", "FLEXIBLE_CONT_LOAD"]


def tariff_type_to_text(tariff_type):
    mapping = {
        "SINGLE_RATE": "Single-rate electricity plan with general anytime usage.",
        "TIME_OF_USE": "Time-of-use electricity plan with peak, shoulder, and off-peak usage periods."
    }

    return mapping.get(tariff_type, "")


EV_PATTERNS = [
    r"\bev\b",
    r"electric vehicle",
    r"electric vehicles",
    r"electric car",
    r"ev charging",
    r"ev owner",
    r"ev owners",
    r"own an ev",
    r"homeev",
    r"ev registration"
]


def contains_ev_keyword(text):
    if not text:
        return False

    text = str(text).lower()

    for pattern in EV_PATTERNS:
        if re.search(pattern, text):
            return True

    return False


def extract_has_ev(contract, plan_name=""):
    if contains_ev_keyword(plan_name):
        return True

    fields_to_check = [
        contract.get("terms", ""),
        contract.get("onExpiryDescription", ""),
        contract.get("additionalFeeInformation", "")
    ]

    for text in fields_to_check:
        if contains_ev_keyword(text):
            return True

    for field in ["eligibility", "incentives"]:
        items = contract.get(field, [])

        if not isinstance(items, list):
            continue

        for item in items:
            item_text = json.dumps(item, ensure_ascii=False)
            if contains_ev_keyword(item_text):
                return True

    return False


def build_soft_text(plan, contract, tariff_type, has_controlled_load, has_solar, has_ev):
    parts = {}

    plan_name = plan.get("display_name") or ""
    retailer_name = plan.get("brand_name") or ""

    parts["plan_name"] = plan_name

    if retailer_name:
        parts["retailer_text"] = f"Energy plan from {retailer_name}."
    else:
        parts["retailer_text"] = ""

    parts["tariff_type_text"] = tariff_type_to_text(tariff_type)

    contract_parts = []

    term_type = contract.get("termType")
    benefit_period = contract.get("benefitPeriod")
    terms = contract.get("terms")
    variation = contract.get("variation")

    if term_type:
        contract_parts.append(f"Contract term type: {term_type}.")

    if benefit_period:
        contract_parts.append(f"Benefit period: {benefit_period}.")

    if terms:
        contract_parts.append(terms)

    if variation:
        contract_parts.append(variation)

    parts["contract_text"] = " ".join(contract_parts).strip()

    billing_parts = []

    bill_frequency = contract.get("billFrequency", [])
    payment_options = contract.get("paymentOption", [])

    if bill_frequency:
        billing_parts.append(f"Bill frequency options: {', '.join(bill_frequency)}.")

    if payment_options:
        billing_parts.append(f"Payment options: {', '.join(payment_options)}.")

    parts["billing_text"] = " ".join(billing_parts).strip()

    tariff_parts = [tariff_type_to_text(tariff_type)]

    tariff_periods = contract.get("tariffPeriod", [])

    for period in tariff_periods:
        single_rate = period.get("singleRate")

        if isinstance(single_rate, dict):
            display_name = single_rate.get("displayName")
            description = single_rate.get("description")

            if display_name:
                tariff_parts.append(f"Single-rate usage: {display_name}.")
            if description:
                tariff_parts.append(f"Usage description: {description}.")

        tou_rates = period.get("timeOfUseRates", [])

        if isinstance(tou_rates, list):
            tou_parts = []

            for item in tou_rates:
                rate_type = item.get("type")
                display_name = item.get("displayName")
                description = item.get("description")

                text = rate_type or display_name

                if description:
                    text = f"{text}: {description}"

                if text:
                    tou_parts.append(text)

            if tou_parts:
                tariff_parts.append(
                    "Time-of-use periods include " + "; ".join(tou_parts) + "."
                )

    parts["tariff_structure_text"] = " ".join(tariff_parts).strip()

    if has_controlled_load:
        controlled_load_parts = []

        controlled_load = contract.get("controlledLoad", [])

        if isinstance(controlled_load, list):
            for item in controlled_load:
                display_name = item.get("displayName")
                single_rate = item.get("singleRate", {})

                description = single_rate.get("description")
                rate_display_name = single_rate.get("displayName")

                text_parts = []

                if display_name:
                    text_parts.append(display_name)

                if rate_display_name and rate_display_name != display_name:
                    text_parts.append(rate_display_name)

                if description:
                    text_parts.append(description)

                if text_parts:
                    controlled_load_parts.append(
                        "Controlled load support: " + ". ".join(text_parts) + "."
                    )

        parts["controlled_load_text"] = " ".join(controlled_load_parts).strip()
    else:
        parts["controlled_load_text"] = ""

    if has_solar:
        solar_parts = []

        solar_tariffs = contract.get("solarFeedInTariff", [])

        if isinstance(solar_tariffs, list):
            for tariff in solar_tariffs:
                display_name = tariff.get("displayName")
                description = tariff.get("description")

                if description:
                    solar_parts.append(description)
                elif display_name:
                    solar_parts.append(display_name)

        if solar_parts:
            parts["solar_text"] = "Solar feed-in tariff support: " + " ".join(solar_parts)
        else:
            parts["solar_text"] = "Solar feed-in tariff support is available."
    else:
        parts["solar_text"] = ""

    if has_ev:
        parts["ev_text"] = "This plan includes EV-related eligibility, incentives, or plan features."
    else:
        parts["ev_text"] = ""

    parts["expiry_text"] = contract.get("onExpiryDescription") or ""
    parts["additional_info_text"] = contract.get("additionalFeeInformation") or ""

    return parts


def transform_plan(plan):
    geography = safe_json_loads(plan.get("geography"), default={})
    contract = safe_json_loads(plan.get("electricity_contract"), default={})

    pricing_model = contract.get("pricingModel")

    if should_skip_plan(pricing_model):
        return None

    tariff_type = extract_tariff_type(pricing_model)

    if tariff_type is None:
        return None

    has_controlled_load = has_non_empty_list(contract.get("controlledLoad"))
    has_solar = has_non_empty_list(contract.get("solarFeedInTariff"))
    has_ev = extract_has_ev(
        contract=contract,
        plan_name=plan.get("display_name", "")
    )

    hard_attributes = {
        "retailer_name": plan.get("brand_name"),
        "customer_type": plan.get("customer_type"),
        "distributors": geography.get("distributors", []),
        "included_postcodes": geography.get("includedPostcodes", []),
        "tariff_type": tariff_type,
        "has_controlled_load": has_controlled_load,
        "has_solar": has_solar,
        "has_ev": has_ev
    }

    soft_text = build_soft_text(
        plan=plan,
        contract=contract,
        tariff_type=tariff_type,
        has_controlled_load=has_controlled_load,
        has_solar=has_solar,
        has_ev=has_ev
    )

    full_text = " ".join(
        value.strip()
        for value in soft_text.values()
        if isinstance(value, str) and value.strip()
    )

    return {
        "plan_id": plan.get("plan_id"),
        "hard_attributes": hard_attributes,
        "soft_text": soft_text,
        "full_text": full_text
    }


def transform_row(row):
    processed_plan = transform_plan(row)

    if processed_plan is None:
        return {
            "processed_plan": None
        }

    return {
        "processed_plan": convert_numeric_strings_to_float(processed_plan)
    }


processed_data = data.map(
    transform_row,
)

processed_data = processed_data.filter(
    lambda row: row["processed_plan"] is not None
)



import pandas as pd
import json

rows = []

for row in processed_data:
    processed_plan = row["processed_plan"]

    rows.append({
        "plan_id": processed_plan.get("plan_id"),

        "retailer_name": row["brand_name"],

        "display_name": row["display_name"],

        "hard_attributes": json.dumps(
            processed_plan.get("hard_attributes", {}),
            ensure_ascii=False
        ),

        "cost_attributes": json.dumps(
            processed_plan.get("cost_attributes", {}),
            ensure_ascii=False
        ),

        "soft_text": json.dumps(
            processed_plan.get("soft_text", {}),
            ensure_ascii=False
        ),

        "full_text": processed_plan.get("full_text", "")
    })

df = pd.DataFrame(rows)

OUTPUT_CSV = "inputs/processed_plans.csv"

df.to_csv(
    OUTPUT_CSV,
    index=False,
    encoding="utf-8-sig"
)

print(f"Saved {len(df)} processed plans to {OUTPUT_CSV}")