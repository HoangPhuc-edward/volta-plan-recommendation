#!/usr/bin/env python3
"""
Simplified cost calculation flow.

Input:
  - One user profile JSON
  - One plan/pricing JSON

Output:
  - Estimated monthly cost
  - Basic cost breakdown

Flow:
  profile → interval_input → build_interval_read_day_24 → 
  compact_interval → calculate_cost → output JSON
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional


# Device types to support in interval input
DEVICE_TYPES_ALL = [
    "lighting",
    "refrigerator",
    "wifi_router",
    "air_conditioning",
    "electric_heating",
    "pool_pump",
    "dishwasher",
    "dryer",
    "induction_cooktop",
    "ev_charging",
    "electric_hot_water_controlled_load",
]


def load_json(path: str) -> Dict[str, Any]:
    """Load a JSON file and return dict."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_function(py_file: Path, fn_name: str):
    """Load a function from a Python file by path."""
    if not py_file.exists():
        raise FileNotFoundError(
            f"Missing dependency file: {py_file}. "
            "Make sure interval_builder.py is available in this directory."
        )
    module_name = f"mod_{py_file.stem}_{fn_name}"
    spec = importlib.util.spec_from_file_location(module_name, str(py_file))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {py_file}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    fn = getattr(mod, fn_name, None)
    if fn is None:
        raise RuntimeError(f"Function '{fn_name}' not found in {py_file}")
    return fn


def profile_to_interval_input(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert user profile to the format required by build_interval_read_day_24.
    
    If profile has device_inputs, use them. Otherwise, build from profile attributes.
    """
    household = profile.get("household") or {}
    appliances = household.get("appliances") or {}
    lifestyle = household.get("lifestyle_signals") or {}
    ev = profile.get("ev") or {}
    solar = profile.get("solar") or {}

    devices: List[Dict[str, Any]] = []
    device_inputs = profile.get("device_inputs")
    
    if isinstance(device_inputs, dict) and device_inputs:
        # Use explicit device_inputs from profile
        for device_type in DEVICE_TYPES_ALL:
            cfg = device_inputs.get(device_type, {"enabled": False})
            if isinstance(cfg, bool):
                cfg = {"enabled": cfg}
            if not isinstance(cfg, dict):
                cfg = {"enabled": False}
            
            entry: Dict[str, Any] = {
                "id": f"{device_type}_1",
                "type": device_type,
                "enabled": bool(cfg.get("enabled", False)),
            }
            if isinstance(cfg.get("input"), dict):
                entry["input"] = cfg.get("input")
            if isinstance(cfg.get("override"), dict):
                entry["override"] = cfg.get("override")
            devices.append(entry)
    else:
        # Fallback: build from profile attributes
        if bool(lifestyle.get("has_air_conditioning")):
            devices.append({"id": "ac_1", "type": "air_conditioning", "enabled": True})
        if bool(lifestyle.get("has_electric_heating")):
            devices.append({"id": "heat_1", "type": "electric_heating", "enabled": True})
        if bool(lifestyle.get("has_pool")) or bool(appliances.get("pool_pump")):
            devices.append({"id": "pool_1", "type": "pool_pump", "enabled": True})
        if bool(appliances.get("dishwasher")):
            devices.append({"id": "dw_1", "type": "dishwasher", "enabled": True})
        if bool(appliances.get("dryer")):
            devices.append({"id": "dryer_1", "type": "dryer", "enabled": True})
        if bool(appliances.get("induction_cooktop")):
            devices.append({"id": "cook_1", "type": "induction_cooktop", "enabled": True})
        if bool(ev.get("has_ev") or ev.get("planning_ev")):
            charging = ev.get("charging") if isinstance(ev.get("charging"), dict) else {}
            time_of_day = "overnight"
            pattern = str(charging.get("pattern") or "").lower()
            if "day" in pattern:
                time_of_day = "daytime"
            elif "evening" in pattern:
                time_of_day = "evening"
            devices.append(
                {"id": "ev_1", "type": "ev_charging", "enabled": True, "input": {"time_of_day": time_of_day}}
            )
        if bool(lifestyle.get("has_electric_hot_water")):
            devices.append({"id": "hw_1", "type": "electric_hot_water_controlled_load", "enabled": True})

    out = {
        "date": date.today().isoformat(),
        "location": {"postcode": (profile.get("location") or {}).get("postcode")},
        "household": {"controlled_load_present": bool(household.get("controlled_load_present"))},
        "devices": devices,
        "solar": {
            "has_solar": bool(solar.get("has_solar")),
            "system": {"size_kw": (((solar.get("system") or {}).get("size_kw")) if isinstance(solar.get("system"), dict) else None)},
            "performance": (solar.get("performance") if isinstance(solar.get("performance"), dict) else {}),
        },
    }
    return out


def compact_interval_result(interval_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compact interval result to keep only interval_reads and daily_kwh for each meter.
    
    Processes: E1, E2, B1, and solar_generation.
    """
    out: Dict[str, Any] = {}
    
    for meter in ["E1", "E2", "B1"]:
        meter_obj = interval_result.get(meter) if isinstance(interval_result.get(meter), dict) else {}
        reads = meter_obj.get("interval_reads") if isinstance(meter_obj.get("interval_reads"), list) else []
        reads_24 = [float(v) for v in reads[:24]] if reads else []
        out[meter] = {
            "interval_reads": reads_24,
            "daily_kwh": round(sum(reads_24), 4),
        }
    
    # Handle solar generation
    solar_gen_obj = interval_result.get("solar_generation") if isinstance(interval_result.get("solar_generation"), dict) else {}
    solar_reads = solar_gen_obj.get("interval_reads") if isinstance(solar_gen_obj.get("interval_reads"), list) else []
    if solar_reads:
        solar_24 = [float(v) for v in solar_reads[:24]]
        out["solar_generation"] = {
            "interval_reads": solar_24,
            "daily_kwh": round(sum(solar_24), 4),
        }
    
    return out

def build_net_e1_reads(compact_interval: Dict[str, Any]) -> List[float]:
    e1_reads = compact_interval.get("E1", {}).get("interval_reads", [])
    b1_reads = compact_interval.get("B1", {}).get("interval_reads", [])
    solar_reads = compact_interval.get("solar_generation", {}).get("interval_reads", [])

    max_len = max(len(e1_reads), len(b1_reads), len(solar_reads), 24)

    net_reads = []

    for i in range(min(max_len, 24)):
        e1 = float(e1_reads[i]) if i < len(e1_reads) else 0.0
        b1 = float(b1_reads[i]) if i < len(b1_reads) else 0.0
        solar = float(solar_reads[i]) if i < len(solar_reads) else 0.0

        solar_self_used = max(0.0, solar - b1)
        e1_import = max(0.0, e1 - solar_self_used)

        net_reads.append(e1_import)

    return net_reads

def calculate_cost(
    profile: Dict[str, Any],
    plan: Dict[str, Any],
    compact_interval: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Calculate estimated monthly cost based on profile, cost plan schema, and interval data.

    Expected plan schema:
        {
          "plan_id": "...",
          "cost_info": {
            "tariff_type": "SINGLE_RATE" | "TIME_OF_USE",
            "billing": {...},
            "supply_charge": {...},
            "usage": {...},
            "time_of_use": {...},
            "controlled_load": {...},
            "solar_fit": {...}
          }
        }

    Supports:
      - SINGLE_RATE flat/block for E1 net import
      - TIME_OF_USE hourly windows for E1 net import
      - controlled load flat/block for E2
      - solar FIT flat/block for B1 export
    """

    cost_info = plan.get("cost_info", plan)

    if not isinstance(cost_info, dict):
        cost_info = {}

    billing_cfg = cost_info.get("billing", {})

    if not isinstance(billing_cfg, dict):
        billing_cfg = {}

    monthly_days = _safe_float(
        billing_cfg.get("monthly_days_default"),
        30.0
    )

    tariff_type = str(
        cost_info.get("tariff_type", "SINGLE_RATE")
    ).upper()

    supply_charge_cfg = cost_info.get("supply_charge", {})

    if not isinstance(supply_charge_cfg, dict):
        supply_charge_cfg = {}

    daily_supply_charge = _safe_float(
        supply_charge_cfg.get("daily_supply_charge"),
        0.0
    )

    e2_daily = _safe_float(
        compact_interval.get("E2", {}).get("daily_kwh"),
        0.0
    )

    b1_daily = _safe_float(
        compact_interval.get("B1", {}).get("daily_kwh"),
        0.0
    )

    e1_net_reads = build_net_e1_reads(
        compact_interval
    )

    e1_net_daily = sum(e1_net_reads)

    # -------------------------
    # E1 general usage cost
    # -------------------------

    if tariff_type == "TIME_OF_USE":
        tou_config = cost_info.get("time_of_use", {})

        if not isinstance(tou_config, dict):
            tou_config = {}

        day = (
            profile.get("day")
            or profile.get("weekday")
            or profile.get("day_of_week")
            or None
        )

        e1_cost_daily = calculate_tou_cost(
            interval_reads=e1_net_reads,
            tou_config=tou_config,
            day=day
        )

        e1_pricing_used = {
            "type": "TIME_OF_USE",
            "structure": tou_config.get("structure"),
            "rates_count": len(tou_config.get("rates", []))
            if isinstance(tou_config.get("rates", []), list)
            else 0
        }

    elif tariff_type == "SINGLE_RATE":
        usage_config = cost_info.get("usage", {})

        if not isinstance(usage_config, dict):
            usage_config = {}

        e1_cost_daily = calculate_single_rate_cost(
            daily_kwh=e1_net_daily,
            usage_config=usage_config
        )

        e1_pricing_used = {
            "type": "SINGLE_RATE",
            "structure": usage_config.get("structure"),
            "rates": usage_config.get("rates", [])
        }

    else:
        e1_cost_daily = 0.0

        e1_pricing_used = {
            "type": tariff_type,
            "structure": "UNSUPPORTED",
            "rates": []
        }

    # -------------------------
    # E2 controlled load cost
    # -------------------------

    controlled_load_cfg = cost_info.get("controlled_load", {})

    if not isinstance(controlled_load_cfg, dict):
        controlled_load_cfg = {}

    controlled_load_enabled = bool(
        controlled_load_cfg.get("enabled", False)
    )

    if controlled_load_enabled:
        e2_cost_daily = calculate_controlled_load_cost(
            daily_kwh=e2_daily,
            controlled_load_config=controlled_load_cfg
        )
    else:
        e2_cost_daily = 0.0

    controlled_load_pricing_used = {
        "enabled": controlled_load_enabled,
        "structure": controlled_load_cfg.get("structure"),
        "daily_supply_charge": controlled_load_cfg.get("daily_supply_charge"),
        "loads_count": len(controlled_load_cfg.get("loads", []))
        if isinstance(controlled_load_cfg.get("loads", []), list)
        else 0
    }

    # -------------------------
    # B1 solar export credit
    # -------------------------

    solar_fit_cfg = cost_info.get("solar_fit", {})

    if not isinstance(solar_fit_cfg, dict):
        solar_fit_cfg = {}

    solar_fit_enabled = bool(
        solar_fit_cfg.get("enabled", False)
    )

    if solar_fit_enabled:
        solar_credit_daily = calculate_solar_fit_credit(
            export_kwh=b1_daily,
            solar_fit_config=solar_fit_cfg
        )
    else:
        solar_credit_daily = 0.0

    solar_fit_pricing_used = {
        "enabled": solar_fit_enabled,
        "structure": solar_fit_cfg.get("structure"),
        "apply_policy": solar_fit_cfg.get("apply_policy"),
        "rates": solar_fit_cfg.get("rates", [])
    }

    # -------------------------
    # Total
    # -------------------------

    daily_cost = (
        e1_cost_daily
        + e2_cost_daily
        + daily_supply_charge
        - solar_credit_daily
    )

    estimated_monthly_cost = round(
        max(0.0, daily_cost * monthly_days),
        2
    )

    return {
        "plan_id": plan.get("plan_id"),
        "estimated_monthly_cost": estimated_monthly_cost,
        "breakdown": {
            "e1_net_daily_kwh": round(e1_net_daily, 4),
            "e2_daily_kwh": round(e2_daily, 4),
            "b1_export_daily_kwh": round(b1_daily, 4),

            "e1_cost_daily": round(e1_cost_daily, 4),
            "e2_cost_daily": round(e2_cost_daily, 4),
            "solar_credit_daily": round(solar_credit_daily, 4),
            "supply_charge_daily": round(daily_supply_charge, 4),
            "daily_cost": round(daily_cost, 4),

            "e1_cost": round(e1_cost_daily * monthly_days, 2),
            "e2_cost": round(e2_cost_daily * monthly_days, 2),
            "solar_credit": round(solar_credit_daily * monthly_days, 2),
            "supply_charge": round(daily_supply_charge * monthly_days, 2),

            "monthly_days": monthly_days,
            "tariff_type": tariff_type,

            "e1_pricing_used": e1_pricing_used,
            "controlled_load_pricing_used": controlled_load_pricing_used,
            "solar_fit_pricing_used": solar_fit_pricing_used,

            "controlled_load_enabled": controlled_load_enabled,
            "solar_fit_enabled": solar_fit_enabled
        }
    }


from typing import Any, Dict, List


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_hour_from_time(value: Any, default: int = 0) -> int:
    """
    Convert:
        "15:00" -> 15
        "20:59" -> 21

    Note:
        end_time trong CDR thường là inclusive, ví dụ 20:59.
        Để tính theo hourly bucket, 20:59 nên map thành 21.
    """
    if value is None:
        return default

    text = str(value).strip()

    if not text:
        return default

    if ":" not in text:
        return _safe_int(text, default)

    try:
        hour_text, minute_text = text.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)

        if minute > 0:
            hour += 1

        return max(0, min(24, hour))
    except Exception:
        return default


def _get_hours_in_window(start: int, end: int) -> List[int]:
    """
    start/end là hour trong khoảng 0..24.

    Case thường:
        start=15, end=21 -> [15,16,17,18,19,20]

    Case qua nửa đêm:
        start=21, end=15 -> [21,22,23,0,1,...,14]
    """
    start = max(0, min(23, start))
    end = max(0, min(24, end))

    if start == end:
        return list(range(24))

    if start < end:
        return list(range(start, end))

    return list(range(start, 24)) + list(range(0, end))


def calculate_rate_blocks(
    kwh: float,
    rate_config: Dict[str, Any]
) -> float:
    """
    Tính cost cho FLAT hoặc BLOCK.

    Dùng được cho:
        cost_info["usage"]
        cost_info["controlled_load"]
        cost_info["solar_fit"] nếu truyền đúng rates

    Schema example:
        {
            "enabled": true,
            "structure": "BLOCK",
            "rates": [
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
        }

    Returns:
        daily cost hoặc daily credit tùy context.
    """
    if not isinstance(rate_config, dict):
        return 0.0

    if not rate_config.get("enabled", True):
        return 0.0

    rates = rate_config.get("rates", [])

    if not isinstance(rates, list) or not rates:
        return 0.0

    kwh = max(0.0, _safe_float(kwh, 0.0))

    if kwh <= 0:
        return 0.0

    structure = str(rate_config.get("structure", "FLAT")).upper()

    # FLAT: dùng rate đầu tiên
    if structure == "FLAT":
        unit_price = _safe_float(rates[0].get("unit_price"), 0.0)
        return kwh * unit_price

    # BLOCK: tính theo bậc
    remaining_kwh = kwh
    previous_limit = 0.0
    total_cost = 0.0

    for rate in rates:
        if not isinstance(rate, dict):
            continue

        unit_price = _safe_float(rate.get("unit_price"), 0.0)
        limit_kwh = rate.get("limit_kwh")

        # limit_kwh = null nghĩa là phần còn lại
        if limit_kwh is None:
            if remaining_kwh > 0:
                total_cost += remaining_kwh * unit_price
                remaining_kwh = 0.0
            break

        limit_kwh = _safe_float(limit_kwh, 0.0)

        # volume = 0 thường nghĩa là thereafter trong solar FIT
        if limit_kwh <= 0:
            if remaining_kwh > 0:
                total_cost += remaining_kwh * unit_price
                remaining_kwh = 0.0
            break

        block_size = max(0.0, limit_kwh - previous_limit)
        usage_in_block = min(remaining_kwh, block_size)

        total_cost += usage_in_block * unit_price
        remaining_kwh -= usage_in_block
        previous_limit = limit_kwh

        if remaining_kwh <= 0:
            break

    # Nếu vẫn còn kWh nhưng không có block null, dùng rate cuối như fallback
    if remaining_kwh > 0 and rates:
        last_rate = rates[-1]
        if isinstance(last_rate, dict):
            total_cost += remaining_kwh * _safe_float(
                last_rate.get("unit_price"),
                0.0
            )

    return total_cost


def calculate_single_rate_cost(
    daily_kwh: float,
    usage_config: Dict[str, Any]
) -> float:
    """
    Wrapper cho E1 general usage.

    Dùng với:
        cost_info["usage"]

    Hỗ trợ:
        FLAT
        BLOCK
    """
    if not isinstance(usage_config, dict):
        return 0.0

    if not usage_config.get("enabled", False):
        return 0.0

    return calculate_rate_blocks(
        kwh=daily_kwh,
        rate_config=usage_config
    )


def calculate_controlled_load_cost(
    daily_kwh: float,
    controlled_load_config: Dict[str, Any]
) -> float:
    """
    Tính E2 controlled load cost.

    Schema hiện tại controlled_load có dạng:
        {
            "enabled": true,
            "structure": "FLAT",
            "daily_supply_charge": 0.05,
            "loads": [
                {
                    "rates": [...]
                }
            ]
        }

    Nếu có nhiều loads, hiện tại chia cùng daily_kwh cho load đầu tiên là không đúng.
    Giai đoạn này: nếu chỉ có 1 load thì tính chính xác.
    """
    if not isinstance(controlled_load_config, dict):
        return 0.0

    if not controlled_load_config.get("enabled", False):
        return 0.0

    loads = controlled_load_config.get("loads", [])

    daily_supply_charge = _safe_float(
        controlled_load_config.get("daily_supply_charge"),
        0.0
    )

    if isinstance(loads, list) and loads:
        # Giai đoạn đầu assume E2 chỉ có 1 controlled load chính
        main_load = loads[0]

        usage_cost = calculate_rate_blocks(
            kwh=daily_kwh,
            rate_config={
                "enabled": True,
                "structure": main_load.get("structure", "FLAT"),
                "rates": main_load.get("rates", [])
            }
        )

        return usage_cost + daily_supply_charge

    # Fallback nếu schema controlled_load có rates trực tiếp
    usage_cost = calculate_rate_blocks(
        kwh=daily_kwh,
        rate_config=controlled_load_config
    )

    return usage_cost + daily_supply_charge


def calculate_solar_fit_credit(
    export_kwh: float,
    solar_fit_config: Dict[str, Any]
) -> float:
    """
    Tính credit cho B1/export.

    Dùng với:
        cost_info["solar_fit"]

    Hỗ trợ:
        FLAT
        BLOCK

    Với schema đã normalize, MULTI retailer FIT nên được gom thành BLOCK trước.
    """
    if not isinstance(solar_fit_config, dict):
        return 0.0

    if not solar_fit_config.get("enabled", False):
        return 0.0

    return calculate_rate_blocks(
        kwh=export_kwh,
        rate_config=solar_fit_config
    )


def calculate_tou_cost(
    interval_reads: List[float],
    tou_config: Dict[str, Any],
    day: Optional[str] = None
) -> float:
    """
    Tính TOU cost theo schema cost mới.

    interval_reads:
        list 24 hourly kWh values.

    tou_config:
        cost_info["time_of_use"]

    Schema example:
        {
          "enabled": true,
          "structure": "TOU",
          "period": "P1D",
          "rates": [
            {
              "name": "PEAK",
              "display_name": "Peak",
              "unit_price": 0.6,
              "unit": "KWH",
              "windows": [
                {
                  "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                  "start_time": "15:00",
                  "end_time": "20:59"
                }
              ]
            },
            {
              "name": "OFF_PEAK",
              "unit_price": 0.229,
              "windows": [
                {
                  "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                  "start_time": "21:00",
                  "end_time": "14:59"
                }
              ]
            }
          ]
        }

    day:
        Optional, ví dụ "MON", "TUE", "SAT".
        Nếu None thì bỏ qua filter theo ngày.
    """
    if not isinstance(tou_config, dict):
        return 0.0

    if not tou_config.get("enabled", False):
        return 0.0

    rates = tou_config.get("rates", [])

    if not isinstance(rates, list) or not rates:
        return 0.0

    default_rate = _infer_default_tou_rate(rates)
    hourly_rates = [default_rate] * 24

    day = str(day).upper() if day else None

    for rate_item in rates:
        if not isinstance(rate_item, dict):
            continue

        unit_price = _safe_float(
            rate_item.get("unit_price"),
            default_rate
        )

        windows = rate_item.get("windows", [])

        if not isinstance(windows, list):
            continue

        for window in windows:
            if not isinstance(window, dict):
                continue

            days = window.get("days", [])

            if day and isinstance(days, list) and days:
                normalized_days = [str(d).upper() for d in days]
                if day not in normalized_days:
                    continue

            start_hour = _parse_hour_from_time(
                window.get("start_time"),
                0
            )

            end_hour = _parse_hour_from_time(
                window.get("end_time"),
                0
            )

            hours = _get_hours_in_window(
                start=start_hour,
                end=end_hour
            )

            for hour in hours:
                hourly_rates[hour] = unit_price

    total_cost = 0.0

    for hour in range(24):
        usage = _safe_float(
            interval_reads[hour] if hour < len(interval_reads) else 0.0,
            0.0
        )

        total_cost += usage * hourly_rates[hour]

    return total_cost


def _infer_default_tou_rate(rates: List[Dict[str, Any]]) -> float:
    """
    Nếu không có default_rate trong schema mới,
    lấy OFF_PEAK nếu có, nếu không lấy rate đầu tiên.
    """
    if not rates:
        return 0.0

    for rate in rates:
        if not isinstance(rate, dict):
            continue

        name = str(rate.get("name", "")).upper()

        if name == "OFF_PEAK":
            return _safe_float(rate.get("unit_price"), 0.0)

    first = rates[0]

    if isinstance(first, dict):
        return _safe_float(first.get("unit_price"), 0.0)

    return 0.0


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Simplified cost calculation flow for energy profiles and plans."
    )
    parser.add_argument(
        "--profile",
        type=str,
        required=True,
        help="Path to user profile JSON file."
    )
    parser.add_argument(
        "--plan",
        type=str,
        required=True,
        help="Path to plan/pricing JSON file."
    )
    parser.add_argument(
        "--out",
        type=str,
        default="cost_output.json",
        help="Path to output JSON file (default: cost_output.json)."
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output."
    )
    return parser.parse_args()

def calculate_net_cost(
    user: Dict[str, Any],
    plan: Dict[str, Any],
    pretty: bool = False
) -> Dict[str, Any]:
    """
    Calculate net monthly cost from an already-loaded user profile and plan.

    Args:
        user: User profile dict. Can be raw selected_profile_payload or selected_profile directly.
        plan: Plan dict.
        pretty: Not required for calculation, kept only for compatibility.

    Returns:
        Dict containing estimated monthly cost, compact interval, and cost breakdown.
    """

    profile = user.get("selected_profile", user)

    # Load interval builder dynamically
    interval_builder_file = (
        Path(__file__).resolve().parent / "interval_builder.py"
    )

    build_interval_read_day_24 = _load_function(
        interval_builder_file,
        "build_interval_read_day_24"
    )

    interval_input = profile_to_interval_input(profile)
    interval_result = build_interval_read_day_24(interval_input)
    compact_interval = compact_interval_result(interval_result)

    cost_result = calculate_cost(
        profile=profile,
        plan=plan,
        compact_interval=compact_interval
    )

    output = {
        "profile_id": profile.get("profile_id", "unknown"),
        "plan_id": plan.get("plan_id", "unknown"),
        "tariff_type": plan.get("tariff_type", "SINGLE_RATE"),
        "estimated_monthly_cost": cost_result["estimated_monthly_cost"],
        "compact_interval": compact_interval,
        "cost_breakdown": cost_result["breakdown"]
    }

    return output


def main() -> None:
    """Main flow: load inputs, calculate cost, save output."""
    args = _parse_args()
    
    # Load inputs
    raw_profile = load_json(args.profile)
    profile = raw_profile.get("selected_profile", raw_profile)

    plan = load_json(args.plan)
    
    # Load interval builder
    interval_builder_file = Path(__file__).resolve().parent / "interval_builder.py"
    build_interval_read_day_24 = _load_function(interval_builder_file, "build_interval_read_day_24")
    
    # Convert profile to interval input
    interval_input = profile_to_interval_input(profile)
    
    # Build interval for a day
    interval_result = build_interval_read_day_24(interval_input)
    
    # Compact interval
    compact_interval = compact_interval_result(interval_result)
    
    # Calculate cost
    cost_result = calculate_cost(profile, plan, compact_interval)
    
    # Build output JSON
    output = {
        "profile_id": profile.get("profile_id", "unknown"),
        "plan_id": plan.get("plan_id", "unknown"),
        "tariff_type": plan.get("tariff_type", "SINGLE_RATE"),
        "estimated_monthly_cost": cost_result["estimated_monthly_cost"],
        "compact_interval": compact_interval,
        "cost_breakdown": cost_result["breakdown"]
    }
    
    # Save output
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2 if args.pretty else None
        )
    
    # Print summary
    print(f"Cost calculation complete. Output saved to: {args.out}")
    print(f"Estimated monthly cost: ${cost_result['estimated_monthly_cost']:.2f}")


if __name__ == "__main__":
    main()
