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


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def has_non_empty_list(value):
    return isinstance(value, list) and len(value) > 0


def convert_numeric_strings_to_float(obj):
    if isinstance(obj, dict):
        return {k: convert_numeric_strings_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numeric_strings_to_float(elem) for elem in obj]
    elif isinstance(obj, str):
        try:
            return float(obj)
        except ValueError:
            return obj
    return obj


def extract_single_rate(contract):
    tariff_periods = contract.get("tariffPeriod", [])

    for period in tariff_periods:
        single_rate = period.get("singleRate")
        if not isinstance(single_rate, dict):
            continue

        rates = single_rate.get("rates", [])
        if not rates:
            continue

        return [
            {
                "unit_price": to_float(rate.get("unitPrice")),
                "volume": to_float(rate.get("volume"), default=0.0) # Convert volume to float
            }
            for rate in rates
        ]

    return []


def extract_tou_rates(contract):
    tariff_periods = contract.get("tariffPeriod", [])

    result = {
        "peak": None,
        "shoulder": None,
        "offpeak": None
    }

    for period in tariff_periods:
        tou_rates = period.get("timeOfUseRates", [])
        if not isinstance(tou_rates, list):
            continue

        for item in tou_rates:
            rate_type = str(item.get("type", "")).lower()
            rates = item.get("rates", [])

            if not rates:
                continue

            unit_price = to_float(rates[0].get("unitPrice"))

            if rate_type == "peak":
                result["peak"] = unit_price
            elif rate_type == "shoulder":
                result["shoulder"] = unit_price
            elif rate_type in ["off_peak", "offpeak"]:
                result["offpeak"] = unit_price

    return result


def extract_daily_supply_charge(contract):
    tariff_periods = contract.get("tariffPeriod", [])

    for period in tariff_periods:
        if "dailySupplyCharge" in period:
            return to_float(period.get("dailySupplyCharge"))

    return 0.0


def extract_controlled_load_rate(contract):
    controlled_load = contract.get("controlledLoad", [])

    if not isinstance(controlled_load, list) or not controlled_load:
        return None

    first = controlled_load[0]
    single_rate = first.get("singleRate", {})
    rates = single_rate.get("rates", [])

    if not rates:
        return None

    return to_float(rates[0].get("unitPrice"))


def extract_feed_in_tariff(contract):
    tariffs = contract.get("solarFeedInTariff", [])

    if not isinstance(tariffs, list):
        return None

    retailer_rates = []

    for tariff in tariffs:
        if tariff.get("payerType") != "RETAILER":
            continue

        single_tariff = tariff.get("singleTariff", {})
        rates = single_tariff.get("rates", [])

        for rate in rates:
            retailer_rates.append({
                "unit_price": to_float(rate.get("unitPrice")),
                "volume": to_float(rate.get("volume"), default=0.0), # Convert volume to float
                "description": tariff.get("description")
            })

    if not retailer_rates:
        return None

    return retailer_rates


def extract_discount(contract):
    discounts = contract.get("discounts", [])

    if not isinstance(discounts, list) or not discounts:
        return None

    result = []

    for discount in discounts:
        item = {
            "display_name": discount.get("displayName"),
            "description": discount.get("description")
        }

        percent_of_bill = discount.get("percentOfBill")
        if isinstance(percent_of_bill, dict):
            item["rate"] = to_float(percent_of_bill.get("rate"))

        result.append(item)

    return result


def extract_demand_charges(contract):
    tariff_periods = contract.get("tariffPeriod", [])
    demand_charges = []

    for period in tariff_periods:
        charges = period.get("demandCharges", [])

        if not isinstance(charges, list):
            continue

        for charge in charges:
            demand_charges.append({
                "amount": to_float(charge.get("amount")),
                "start_time": charge.get("startTime"),
                "end_time": charge.get("endTime"),
                "description": charge.get("description"),
                "display_name": charge.get("displayName")
            })

    return demand_charges

def extract_green_power(contract):
    green_power_charges = contract.get("greenPowerCharges", [])

    if not isinstance(green_power_charges, list) or not green_power_charges:
        return {
            "has_green_power": False,
            "green_power_options": []
        }

    options = []

    for charge in green_power_charges:
        charge_type = charge.get("type")
        tiers = charge.get("tiers", [])

        if not isinstance(tiers, list):
            continue

        for tier in tiers:
            options.append({
                "type": charge_type,
                "amount": to_float(tier.get("amount")),
                "percent_green": to_float(tier.get("percentGreen"))
            })

    return {
        "has_green_power": len(options) > 0,
        "green_power_options": options
    }


def build_green_power_text(contract):
    green_power = extract_green_power(contract)

    if not green_power["has_green_power"]:
        return ""

    percents = [
        int(option["percent_green"] * 100)
        for option in green_power["green_power_options"]
        if option.get("percent_green") is not None
    ]

    if not percents:
        return "This plan offers GreenPower renewable energy options."

    return f"This plan offers GreenPower renewable energy options up to {max(percents)}%."



def pricing_model_to_text(pricing_model):
    mapping = {
        "SINGLE_RATE": "Single-rate electricity plan with general anytime usage.",
        "SINGLE_RATE_CONT_LOAD": "Single-rate electricity plan with controlled load support.",
        "TIME_OF_USE": "Time-of-use electricity plan with peak, shoulder, and off-peak usage periods.",
        "TIME_OF_USE_CONT_LOAD": "Time-of-use electricity plan with controlled load support.",
        "FLEXIBLE": "Flexible electricity plan with variable tariff structure.",
        "FLEXIBLE_CONT_LOAD": "Flexible electricity plan with controlled load support."
    }

    return mapping.get(pricing_model, f"Electricity plan with pricing model {pricing_model}.")


def build_tariff_structure_text(contract):
    pricing_model = contract.get("pricingModel")
    tariff_periods = contract.get("tariffPeriod", [])

    parts = [pricing_model_to_text(pricing_model)]

    for period in tariff_periods:
        single_rate = period.get("singleRate")
        if isinstance(single_rate, dict):
            display_name = single_rate.get("displayName")
            description = single_rate.get("description")

            if display_name:
                parts.append(f"Single-rate usage: {display_name}.")
            if description:
                parts.append(f"Usage description: {description}.")

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
                parts.append("Time-of-use periods include " + "; ".join(tou_parts) + ".")

    return " ".join(parts).strip()


def build_controlled_load_text(contract):
    controlled_load = contract.get("controlledLoad", [])

    if not isinstance(controlled_load, list) or not controlled_load:
        return ""

    parts = []

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
            parts.append("Controlled load support: " + ". ".join(text_parts) + ".")

    return " ".join(parts).strip()


def build_solar_text(contract):
    tariffs = contract.get("solarFeedInTariff", [])

    if not isinstance(tariffs, list) or not tariffs:
        return ""

    parts = []

    for tariff in tariffs:
        display_name = tariff.get("displayName")
        description = tariff.get("description")

        if description:
            parts.append(description)
        elif display_name:
            parts.append(display_name)

    if not parts:
        return "Solar feed-in tariff support is available."

    return "Solar feed-in tariff support: " + " ".join(parts)


def build_billing_text(contract):
    bill_frequency = contract.get("billFrequency", [])
    payment_options = contract.get("paymentOption", [])

    parts = []

    if bill_frequency:
        parts.append(f"Bill frequency options: {', '.join(bill_frequency)}.")

    if payment_options:
        parts.append(f"Payment options: {', '.join(payment_options)}.")

    return " ".join(parts).strip()


def build_contract_text(contract):
    parts = []

    term_type = contract.get("termType")
    benefit_period = contract.get("benefitPeriod")
    terms = contract.get("terms")
    variation = contract.get("variation")

    if term_type:
        parts.append(f"Contract term type: {term_type}.")

    if benefit_period:
        parts.append(f"Benefit period: {benefit_period}.")

    if terms:
        parts.append(terms)

    if variation:
        parts.append(variation)

    return " ".join(parts).strip()


def transform_plan(plan):
    geography = safe_json_loads(plan.get("geography"), default={})
    contract = safe_json_loads(plan.get("electricity_contract"), default={})
    reference_price = safe_json_loads(plan.get("reference_price"), default={})

    # Ensure numeric strings in reference_price are converted to floats
    reference_price = convert_numeric_strings_to_float(reference_price)

    pricing_model = contract.get("pricingModel")

    has_controlled_load = has_non_empty_list(contract.get("controlledLoad"))
    has_solar_fit = has_non_empty_list(contract.get("solarFeedInTariff"))
    has_demand_charges = any(
        has_non_empty_list(period.get("demandCharges"))
        for period in contract.get("tariffPeriod", [])
        if isinstance(period, dict)
    )

    hard_attributes = {
        "retailer_name": plan.get("brand_name"),
        "customer_type": plan.get("customer_type"),
        "distributors": geography.get("distributors", []),
        "included_postcodes": geography.get("includedPostcodes", []),
        "pricing_model": pricing_model,
        "has_controlled_load": has_controlled_load,
        "has_green_power": extract_green_power(contract)["has_green_power"],
        "has_solar_fit": has_solar_fit
        
    }

    cost_attributes = {
        "single_rate": extract_single_rate(contract),
        "tou_rates": extract_tou_rates(contract),
        "controlled_load_rate": extract_controlled_load_rate(contract),
        "daily_supply_charge": extract_daily_supply_charge(contract),
        "feed_in_tariff": extract_feed_in_tariff(contract),
        "discount": extract_discount(contract),
        "demand_charges": extract_demand_charges(contract),
        "reference_price": reference_price,
        "green_power": extract_green_power(contract)
    }

    soft_text = {
        "plan_name": plan.get("display_name") or "",
        "retailer_text": f"Energy plan from {plan.get('brand_name')}." if plan.get("brand_name") else "",
        "pricing_model_text": pricing_model_to_text(pricing_model),
        "contract_text": build_contract_text(contract),
        "billing_text": build_billing_text(contract),
        "solar_text": build_solar_text(contract),
        "green_power_text": build_green_power_text(contract),
        "controlled_load_text": build_controlled_load_text(contract),
        "tariff_structure_text": build_tariff_structure_text(contract),
        "expiry_text": contract.get("onExpiryDescription") or "",
        "additional_info_text": contract.get("additionalFeeInformation") or ""
    }

    full_text = " ".join(
        value.strip()
        for value in soft_text.values()
        if isinstance(value, str) and value.strip()
    )

    return {
        "plan_id": plan.get("plan_id"),
        "hard_attributes": hard_attributes,
        "cost_attributes": cost_attributes,
        "soft_text": soft_text,
        "full_text": full_text
    }


def transform_row(row):
    processed_plan = transform_plan(row)
    return {
        "processed_plan": convert_numeric_strings_to_float(processed_plan)
    }

processed_data = data.map(
    transform_row,
    remove_columns=data.column_names
)

import pandas as pd
import json

rows = []

for row in processed_data:
    processed_plan = row["processed_plan"]

    rows.append({
        "plan_id": processed_plan.get("plan_id"),

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

OUTPUT_CSV = "processed_plans_1.csv"

df.to_csv(
    OUTPUT_CSV,
    index=False,
    encoding="utf-8-sig"
)

print(f"Saved {len(df)} processed plans to {OUTPUT_CSV}")