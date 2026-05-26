import json
from pathlib import Path
from typing import Any, Dict, List, Optional


INPUT_DIR = Path("plan_inputs")
OUTPUT_DIR = Path("plan_outputs")


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_json_loads(value: Any, default=None):
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


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_contract(plan_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Input sample format:
    {
      "sample_info": {...},
      "cost_relevant_contract": {...},
      "raw_electricity_contract": {...}
    }

    Theo yêu cầu: lấy raw_electricity_contract làm contract chính.
    """
    contract = plan_json.get("electricity_contract")

    if isinstance(contract, dict):
        return contract

    if isinstance(contract, str):
        return safe_json_loads(contract, {})

    return {}


def get_plan_id(plan_json: Dict[str, Any], file_path: Path) -> str:
    sample_info = plan_json.get("sample_info", {})

    if isinstance(sample_info, dict):
        plan_id = sample_info.get("plan_id")
        if plan_id:
            return str(plan_id)

    return file_path.stem


def normalize_pricing_model(pricing_model: str) -> str:
    pricing_model = str(pricing_model or "").upper()

    if pricing_model in ["SINGLE_RATE", "SINGLE_RATE_CONT_LOAD"]:
        return "SINGLE_RATE"

    if pricing_model in ["TIME_OF_USE", "TIME_OF_USE_CONT_LOAD"]:
        return "TIME_OF_USE"

    return "UNSUPPORTED"


def get_first_tariff_period(contract: Dict[str, Any]) -> Dict[str, Any]:
    tariff_periods = contract.get("tariffPeriod", [])

    if isinstance(tariff_periods, list) and tariff_periods:
        for period in tariff_periods:
            if isinstance(period, dict):
                return period

    return {}


def classify_block_rates(rates: List[Dict[str, Any]]) -> str:
    if not rates:
        return "NONE"

    has_volume = any(
        isinstance(rate, dict) and "volume" in rate
        for rate in rates
    )

    if len(rates) == 1 and not has_volume:
        return "FLAT"

    return "BLOCK"


def normalize_rate_blocks(
    rates: Any,
    period: Optional[str] = None,
    default_unit: str = "KWH"
) -> List[Dict[str, Any]]:
    """
    Normalize raw CDR rates thành dạng dễ tính cost.

    Raw flat:
    [{"unitPrice": "0.356"}]

    Raw block:
    [{"volume": 15, "unitPrice": "0.344"}, {"unitPrice": "0.399"}]

    Output:
    [
      {
        "block_index": 0,
        "unit_price": 0.344,
        "unit": "KWH",
        "limit_kwh": 15.0,
        "limit_period": "P1D"
      },
      {
        "block_index": 1,
        "unit_price": 0.399,
        "unit": "KWH",
        "limit_kwh": null,
        "limit_period": "P1D"
      }
    ]
    """
    if not isinstance(rates, list):
        return []

    normalized = []

    for idx, rate in enumerate(rates):
        if not isinstance(rate, dict):
            continue

        unit_price = safe_float(rate.get("unitPrice"))
        volume = safe_float(rate.get("volume"))

        normalized.append({
            "block_index": idx,
            "unit_price": unit_price,
            "unit": rate.get("measureUnit") or default_unit,
            "limit_kwh": volume,
            "limit_period": period
        })

    return normalized


def normalize_supply_charge(contract: Dict[str, Any]) -> Dict[str, Any]:
    tariff_period = get_first_tariff_period(contract)

    daily_supply_charge = safe_float(
        tariff_period.get("dailySupplyCharge"),
        0.0
    )

    return {
        "enabled": daily_supply_charge is not None,
        "structure": "FLAT",
        "period": "P1D",
        "daily_supply_charge": daily_supply_charge or 0.0,
        "daily_supply_charge_type": tariff_period.get("dailySupplyChargeType")
    }


def normalize_single_rate(contract: Dict[str, Any]) -> Dict[str, Any]:
    tariff_period = get_first_tariff_period(contract)
    single_rate = tariff_period.get("singleRate")

    if not isinstance(single_rate, dict):
        return {
            "enabled": False,
            "type": None,
            "structure": "NONE",
            "period": None,
            "rates": []
        }

    raw_rates = single_rate.get("rates", [])
    period = single_rate.get("period")

    return {
        "enabled": True,
        "type": "SINGLE_RATE",
        "structure": classify_block_rates(raw_rates),
        "period": period,
        "display_name": single_rate.get("displayName"),
        "description": single_rate.get("description"),
        "rates": normalize_rate_blocks(
            raw_rates,
            period=period,
            default_unit="KWH"
        )
    }


def normalize_time_of_use(contract: Dict[str, Any]) -> Dict[str, Any]:
    tariff_period = get_first_tariff_period(contract)
    tou_rates = tariff_period.get("timeOfUseRates")

    if not isinstance(tou_rates, list) or not tou_rates:
        return {
            "enabled": False,
            "structure": "NONE",
            "period": None,
            "rates": []
        }

    normalized_rates = []

    for idx, tou_item in enumerate(tou_rates):
        if not isinstance(tou_item, dict):
            continue

        raw_rates = tou_item.get("rates", [])
        normalized_blocks = normalize_rate_blocks(
            raw_rates,
            period=tou_item.get("period"),
            default_unit="KWH"
        )

        unit_price = None
        unit = "KWH"

        if normalized_blocks:
            unit_price = normalized_blocks[0].get("unit_price")
            unit = normalized_blocks[0].get("unit") or "KWH"

        windows = []

        raw_windows = tou_item.get("timeOfUse", [])

        if isinstance(raw_windows, list):
            for window in raw_windows:
                if not isinstance(window, dict):
                    continue

                windows.append({
                    "days": window.get("days", []),
                    "start_time": window.get("startTime"),
                    "end_time": window.get("endTime")
                })

        normalized_rates.append({
            "tou_index": idx,
            "name": tou_item.get("type"),
            "display_name": tou_item.get("displayName"),
            "description": tou_item.get("description"),
            "period": tou_item.get("period"),
            "unit_price": unit_price,
            "unit": unit,
            "windows": windows
        })

    return {
        "enabled": True,
        "structure": "TOU",
        "period": "P1D",
        "rates": normalized_rates
    }


def normalize_controlled_load(contract: Dict[str, Any]) -> Dict[str, Any]:
    controlled_load = contract.get("controlledLoad", [])

    if not isinstance(controlled_load, list) or not controlled_load:
        return {
            "enabled": False,
            "structure": "NONE",
            "period": None,
            "daily_supply_charge": 0.0,
            "loads": []
        }

    loads = []

    for load_index, item in enumerate(controlled_load):
        if not isinstance(item, dict):
            continue

        single_rate = item.get("singleRate", {})

        if not isinstance(single_rate, dict):
            single_rate = {}

        raw_rates = single_rate.get("rates", [])
        period = single_rate.get("period")

        loads.append({
            "load_index": load_index,
            "display_name": item.get("displayName") or single_rate.get("displayName"),
            "description": single_rate.get("description"),
            "rate_block_u_type": item.get("rateBlockUType"),
            "structure": classify_block_rates(raw_rates),
            "period": period,
            "daily_supply_charge": safe_float(
                single_rate.get("dailySupplyCharge"),
                0.0
            ) or 0.0,
            "rates": normalize_rate_blocks(
                raw_rates,
                period=period,
                default_unit="KWH"
            )
        })

    if any(load["structure"] == "BLOCK" for load in loads):
        structure = "BLOCK"
    elif any(load["structure"] == "FLAT" for load in loads):
        structure = "FLAT"
    else:
        structure = "UNKNOWN"

    total_daily_supply_charge = sum(
        load.get("daily_supply_charge", 0.0) or 0.0
        for load in loads
    )

    return {
        "enabled": True,
        "structure": structure,
        "period": "P1D",
        "daily_supply_charge": total_daily_supply_charge,
        "loads": loads
    }


def normalize_solar_fit(contract: Dict[str, Any]) -> Dict[str, Any]:
    solar_items = contract.get("solarFeedInTariff", [])

    if not isinstance(solar_items, list) or not solar_items:
        return {
            "enabled": False,
            "structure": "NONE",
            "apply_policy": "NONE",
            "period": None,
            "rates": []
        }

    retailer_items = [
        item for item in solar_items
        if isinstance(item, dict)
        and str(item.get("payerType", "")).upper() == "RETAILER"
    ]

    # Giai đoạn đầu nên ưu tiên RETAILER vì đây là phần thường dùng cho bill/recommendation.
    # Nếu không có RETAILER thì lấy toàn bộ item có sẵn.
    selected_items = retailer_items if retailer_items else solar_items

    normalized_rates = []

    for item in selected_items:
        if not isinstance(item, dict):
            continue

        single_tariff = item.get("singleTariff", {})

        if not isinstance(single_tariff, dict):
            single_tariff = {}

        raw_rates = single_tariff.get("rates", [])
        period = single_tariff.get("period")

        rate_blocks = normalize_rate_blocks(
            raw_rates,
            period=period,
            default_unit="KWH"
        )

        for block in rate_blocks:
            block["payer_type"] = item.get("payerType")
            block["scheme"] = item.get("scheme")
            block["description"] = item.get("description")
            block["display_name"] = item.get("displayName")
            normalized_rates.append(block)

    # Sort để block có volume > 0 đứng trước, block volume 0/null đứng sau.
    # Cách này hợp với case:
    # first 5 kWh/day => volume 5
    # thereafter => volume 0
    normalized_rates.sort(
        key=lambda x: (
            x.get("limit_kwh") is None,
            x.get("limit_kwh") == 0,
            x.get("block_index", 0)
        )
    )

    # Re-index block sau khi gom nhiều solarFeedInTariff item.
    for idx, rate in enumerate(normalized_rates):
        rate["block_index"] = idx

        # Trong raw solar sample, period là P1Y nhưng mô tả nói first 5 kWh/day.
        # Để cost_flow tính theo daily export, dùng limit_period P1D nếu có limit.
        if rate.get("limit_kwh") is not None:
            rate["limit_period"] = "P1D"

        # volume 0 thường biểu thị thereafter.
        if rate.get("limit_kwh") == 0:
            rate["limit_kwh"] = None
            rate["limit_period"] = "P1D"

    has_multiple_items = len(selected_items) > 1
    has_volume = any(rate.get("limit_kwh") is not None for rate in normalized_rates)

    if not normalized_rates:
        structure = "UNKNOWN"
    elif len(normalized_rates) == 1 and not has_volume and not has_multiple_items:
        structure = "FLAT"
    else:
        structure = "BLOCK"

    return {
        "enabled": True,
        "structure": structure,
        "apply_policy": "RETAILER_ONLY" if retailer_items else "ALL_AVAILABLE",
        "period": "P1D",
        "rates": normalized_rates
    }


def detect_support(schema: Dict[str, Any]) -> Dict[str, Any]:
    cost_info = schema["cost_info"]
    reasons = []

    pricing_model = cost_info.get("pricing_model")
    tariff_type = cost_info.get("tariff_type")

    if tariff_type == "UNSUPPORTED":
        reasons.append(f"Unsupported pricing model: {pricing_model}")

    usage = cost_info["usage"]
    tou = cost_info["time_of_use"]
    controlled_load = cost_info["controlled_load"]
    solar_fit = cost_info["solar_fit"]

    if usage.get("enabled") and usage.get("structure") == "BLOCK":
        reasons.append("Single rate uses block pricing.")

    if tou.get("enabled"):
        reasons.append("TOU pricing requires interval-level usage.")

        for rate in tou.get("rates", []):
            for window in rate.get("windows", []):
                start_time = window.get("start_time")
                end_time = window.get("end_time")

                if start_time and end_time and start_time > end_time:
                    reasons.append("TOU window crosses midnight.")
                    break

    if controlled_load.get("enabled") and controlled_load.get("structure") == "BLOCK":
        reasons.append("Controlled load uses block pricing.")

    if solar_fit.get("enabled") and solar_fit.get("structure") == "BLOCK":
        reasons.append("Solar FIT uses block pricing.")

    if tariff_type == "UNSUPPORTED":
        level = "UNSUPPORTED_COMPLEX"
    elif not reasons:
        level = "SUPPORTED_SIMPLE"
    else:
        level = "SUPPORTED_WITH_EXTENSIONS"

    return {
        "level": level,
        "reasons": sorted(set(reasons))
    }


def normalize_contract_to_cost_schema(
    contract: Dict[str, Any],
    plan_id: str
) -> Dict[str, Any]:
    pricing_model = str(contract.get("pricingModel", "")).upper()
    tariff_type = normalize_pricing_model(pricing_model)

    if tariff_type == "SINGLE_RATE":
        usage = normalize_single_rate(contract)
        time_of_use = {
            "enabled": False,
            "structure": "NONE",
            "period": None,
            "rates": []
        }

    elif tariff_type == "TIME_OF_USE":
        usage = {
            "enabled": False,
            "type": None,
            "structure": "NONE",
            "period": None,
            "rates": []
        }
        time_of_use = normalize_time_of_use(contract)

    else:
        usage = {
            "enabled": False,
            "type": None,
            "structure": "NONE",
            "period": None,
            "rates": []
        }
        time_of_use = {
            "enabled": False,
            "structure": "NONE",
            "period": None,
            "rates": []
        }

    schema = {
        "schema_version": "cost_plan_schema_v1",
        "plan_id": plan_id,
        "cost_info": {
            "pricing_model": pricing_model,
            "tariff_type": tariff_type,
            "billing": {
                "monthly_days_default": 30,
                "currency": "AUD"
            },
            "supply_charge": normalize_supply_charge(contract),
            "usage": usage,
            "time_of_use": time_of_use,
            "controlled_load": normalize_controlled_load(contract),
            "solar_fit": normalize_solar_fit(contract),
            "support": {
                "level": None,
                "reasons": []
            }
        }
    }

    schema["cost_info"]["support"] = detect_support(schema)

    return schema


def process_files(input_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*.json"))

    if not files:
        print(f"No JSON files found in: {input_dir}")
        return

    print(f"Input folder: {input_dir}")
    print(f"Output folder: {output_dir}")
    print(f"Total input files: {len(files)}")

    for idx, input_path in enumerate(files, start=1):
        plan_json = load_json(input_path)
        contract = get_contract(plan_json)

        if not contract:
            print(f"[SKIP] {input_path.name}: raw_electricity_contract not found")
            continue

        plan_id = get_plan_id(plan_json, input_path)

        schema = normalize_contract_to_cost_schema(
            contract=contract,
            plan_id=plan_id
        )

        output_path = output_dir / f"{input_path.stem}_schema.json"
        save_json(output_path, schema)

        print(f"[{idx}/{len(files)}] Saved: {output_path.name}")

    print("Done")



def normalize_plan_for_calculation(plan_json):
    contract = get_contract(plan_json)

    if not contract:
        raise ValueError("raw_electricity_contract not found in input JSON")

    plan_id = get_plan_id(plan_json, Path("input.json"))

    schema = normalize_contract_to_cost_schema(
        contract=contract,
        plan_id=plan_id
    )

    return schema


def main():
    process_files(INPUT_DIR, OUTPUT_DIR)


if __name__ == "__main__":
    main()