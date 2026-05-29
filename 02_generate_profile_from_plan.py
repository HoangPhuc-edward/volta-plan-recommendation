import json
import random
import pandas as pd
from datetime import datetime, date
from copy import deepcopy
from typing import Any, Dict, List, Optional


INPUT_CSV = "inputs/processed_plans.csv"
OUTPUT_CSV = "inputs/synthetic_users_from_plans.csv"

N_SAMPLES = 30
RANDOM_SEED = 42

random.seed(RANDOM_SEED)

# Device baseline specs for realistic consumption
DEVICE_QUANTITY_BASELINES: Dict[str, Dict[str, float]] = {
    "lighting": {"default_daily_kwh": 1.8, "default_quantity": 10.0},
    "refrigerator": {"default_daily_kwh": 1.2, "default_quantity": 1.0},
    "wifi_router": {"default_daily_kwh": 0.24, "default_quantity": 1.0},
    "air_conditioning": {"default_daily_kwh": 6.0, "default_quantity": 1.0},
    "electric_heating": {"default_daily_kwh": 5.0, "default_quantity": 1.0},
    "pool_pump": {"default_daily_kwh": 4.0, "default_quantity": 1.0},
    "dishwasher": {"default_daily_kwh": 1.2, "default_quantity": 1.0},
    "dryer": {"default_daily_kwh": 2.5, "default_quantity": 1.0},
    "induction_cooktop": {"default_daily_kwh": 1.6, "default_quantity": 1.0},
    "ev_charging": {"default_daily_kwh": 6.0, "default_quantity": 1.0},
    "electric_hot_water_controlled_load": {"default_daily_kwh": 6.0, "default_quantity": 1.0},
}

def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge patch dict into base dict"""
    out = deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _season_from_month(month: int) -> str:
    """Return season for Southern Hemisphere (Australia)"""
    if month in (12, 1, 2):
        return "summer"
    if month in (3, 4, 5):
        return "autumn"
    if month in (6, 7, 8):
        return "winter"
    return "spring"


def _people_count_to_band(people_count: Any) -> str:
    """Convert people count to band: '1', '2_3', or '4_plus'"""
    if isinstance(people_count, str):
        s = people_count.strip().lower()
        if s in {"4+", "4_plus", "4plus"}:
            return "4_plus"
        try:
            n = int(s)
        except Exception:
            n = None
    elif isinstance(people_count, (int, float)):
        n = int(people_count)
    else:
        n = None
    
    if n is None:
        return "2_3"
    if n <= 1:
        return "1"
    if n <= 3:
        return "2_3"
    return "4_plus"


def _occupancy_slug(occupancy_pattern: Any) -> str:
    """Classify occupancy pattern into meaningful labels"""
    if not isinstance(occupancy_pattern, list):
        occupancy_pattern = []
    
    occ = {str(x).strip().lower() for x in occupancy_pattern if x is not None}
    
    # Priority: school_term_pattern > weekday_daytime_home > weekday_evening_only
    if "school_term_pattern" in occ or "family" in occ:
        return "family"
    if "weekday_daytime_home" in occ or "daytime" in occ:
        return "daytime"
    if "weekday_evening_only" in occ or "evening" in occ:
        return "evening"
    return "mixed"


def _usage_band_slug(monthly_usage_kwh: Any) -> str:
    """Classify usage into low/medium/high bands"""
    try:
        kwh = float(monthly_usage_kwh)
    except Exception:
        return "unknown"
    
    if kwh < 450:
        return "low"
    if kwh <= 650:
        return "medium"
    return "high"


def _build_profile_label(profile: Dict[str, Any]) -> str:
    """Generate human-readable semantic label for profile"""
    household = profile.get("household") if isinstance(profile.get("household"), dict) else {}
    energy = profile.get("energy_usage") if isinstance(profile.get("energy_usage"), dict) else {}
    solar = profile.get("solar") if isinstance(profile.get("solar"), dict) else {}
    
    dwelling = str(household.get("type") or "unknown").strip().lower().replace(" ", "-")
    people = _people_count_to_band(household.get("people_count"))
    people_slug = f"{people.replace('_plus', 'p+').replace('_', '')}"
    
    occupancy = _occupancy_slug(household.get("occupancy_pattern"))
    usage = _usage_band_slug(energy.get("monthly_usage_kwh"))
    
    suffixes: List[str] = []
    if bool(solar.get("has_solar")):
        suffixes.append("solar")
    
    parts = [dwelling, people_slug, occupancy, usage]
    parts.extend(suffixes)
    return "-".join([p for p in parts if p])


def _set_profile_identity(profile: Dict[str, Any], idx: int) -> None:
    """Set profile_id, template_id, and profile_label"""
    profile["profile_id"] = f"prof_{idx:03d}"
    profile["template_id"] = profile.get("profile_id")
    profile["profile_label"] = _build_profile_label(profile)

def safe_json_loads(value, default=None):
    if default is None:
        default = {}

    if pd.isna(value):
        return default

    if isinstance(value, dict):
        return value

    try:
        return json.loads(value)
    except Exception:
        return default


def pick_first(value, default=None):
    if isinstance(value, list) and value:
        return value[0]

    return default


def tariff_type_to_user_preference(tariff_type):
    if tariff_type == "TIME_OF_USE":
        return "time_of_use"

    if tariff_type == "SINGLE_RATE":
        return "flat"

    return "unknown"


def tariff_type_to_usage_pattern(tariff_type):
    if tariff_type == "TIME_OF_USE":
        return random.choice([
            "evening",
            "overnight",
            "daytime"
        ])

    return random.choice([
        "balanced",
        "evening"
    ])


def _build_device_inputs(
    profile: Dict[str, Any],
    people_band: str,
    season: str,
    wfh_days: int,
    has_controlled_load: bool
) -> Dict[str, Any]:
    """
    Generate more realistic device inputs based on household size.

    Main changes:
    - If household >= 2 people, enable more devices more often.
    - Lighting quantity increases with household size.
    - Dishwasher, dryer, induction cooktop rates increase for larger households.
    - Refrigerator can be 2 units for 4+ households.
    """

    device_inputs = {}

    # =========================
    # Household-size baseline
    # =========================

    if people_band == "1":
        base_lighting_kwh = 1.2
        lighting_quantity_range = (6, 12)

        base_fridge_kwh = 1.0
        fridge_quantity = 1

        base_wifi_kwh = 0.20
        ac_base = 4.2
        heating_base = 3.8
        

        rates = {
            "ac": 0.85,
            "heating": 0.65,
            "pool": 0.1,
            "dishwasher": 0.65,
            "dryer": 0.35,
            "induction": 0.45,
        }

    elif people_band == "2_3":
        base_lighting_kwh = 1.9
        lighting_quantity_range = (12, 24)

        base_fridge_kwh = 1.25
        fridge_quantity = 1

        base_wifi_kwh = 0.28
        ac_base = 6.8
        heating_base = 5.8

        rates = {
            "ac": 0.82,
            "heating": 0.62,
            "pool": 0.12,
            "dishwasher": 0.75,
            "dryer": 0.75,
            "induction": 0.85,
        }

    else:  # 4_plus
        base_lighting_kwh = 2.8
        lighting_quantity_range = (18, 36)

        base_fridge_kwh = 1.55
        fridge_quantity = random.choice([1, 2])

        base_wifi_kwh = 0.35
        ac_base = 9.5
        heating_base = 7.8

        rates = {
            "ac": 0.90,
            "heating": 0.9,
            "pool": 0.4,
            "dishwasher": 0.88,
            "dryer": 0.88,
            "induction": 0.88,
        }

    # =========================
    # Season multipliers
    # =========================

    season_lighting_mult = {
        "summer": 0.90,
        "autumn": 1.00,
        "winter": 1.12,
        "spring": 0.96,
    }[season]

    ac_heat_multipliers = {
        "summer": {"ac": 1.35, "heat": 0.45},
        "autumn": {"ac": 0.85, "heat": 0.85},
        "winter": {"ac": 0.35, "heat": 1.45},
        "spring": {"ac": 0.75, "heat": 0.65},
    }[season]

    wfh_factor = max(0.0, min(1.0, float(wfh_days) / 5.0))

    # =========================
    # Always-on / core devices
    # =========================

    lighting_kwh = round(
        base_lighting_kwh
        * season_lighting_mult
        * (1.0 + 0.18 * wfh_factor),
        3
    )

    device_inputs["lighting"] = {
        "enabled": True,
        "input": {
            "daily_kwh": lighting_kwh,
            "quantity": random.randint(*lighting_quantity_range),
            "time_of_day": "evening",
            "season": season,
            "start_hour": 18,
            "end_hour": 23,
        }
    }

    fridge_kwh = round(
        base_fridge_kwh
        * fridge_quantity
        * (1.0 + 0.04 * wfh_factor),
        3
    )

    device_inputs["refrigerator"] = {
        "enabled": True,
        "input": {
            "daily_kwh": fridge_kwh,
            "quantity": fridge_quantity,
            "season": season,
            "start_hour": 0,
            "end_hour": 24,
        }
    }

    wifi_kwh = round(
        base_wifi_kwh
        * (1.0 + 0.20 * wfh_factor),
        3
    )

    device_inputs["wifi_router"] = {
        "enabled": True,
        "input": {
            "daily_kwh": wifi_kwh,
            "quantity": 1,
            "season": season,
            "start_hour": 0,
            "end_hour": 24,
        }
    }

    # General appliances should exist for most households.
    # This represents TV, laptop/PC, microwave, kettle, washing machine, chargers, standby loads, etc.
    

    # =========================
    # Heating / cooling
    # =========================

    has_ac = random.random() < rates["ac"]

    if has_ac:
        ac_kwh = round(
            ac_base
            * (1.0 + 0.22 * wfh_factor)
            * ac_heat_multipliers["ac"],
            3
        )

        ac_time = random.choice(["daytime", "evening", "balanced"])

        device_inputs["air_conditioning"] = {
            "enabled": True,
            "input": {
                "daily_kwh": ac_kwh,
                "quantity": 1,
                "time_of_day": ac_time,
                "season": season,
                "start_hour": 12 if ac_time == "daytime" else 17,
                "end_hour": 18 if ac_time == "daytime" else 23,
            }
        }
    else:
        device_inputs["air_conditioning"] = {
            "enabled": False,
            "input": {}
        }

    has_heating = random.random() < rates["heating"]

    if has_heating:
        heating_kwh = round(
            heating_base
            * (1.0 + 0.16 * wfh_factor)
            * ac_heat_multipliers["heat"],
            3
        )

        heat_time = random.choice(["morning", "evening", "balanced"])

        device_inputs["electric_heating"] = {
            "enabled": True,
            "input": {
                "daily_kwh": heating_kwh,
                "quantity": 1,
                "time_of_day": heat_time,
                "season": season,
                "start_hour": 6 if heat_time == "morning" else 17,
                "end_hour": 9 if heat_time == "morning" else 22,
            }
        }
    else:
        device_inputs["electric_heating"] = {
            "enabled": False,
            "input": {}
        }

    # =========================
    # Optional but more common for >= 2 people
    # =========================

    has_pool = random.random() < rates["pool"]

    if has_pool:
        device_inputs["pool_pump"] = {
            "enabled": True,
            "input": {
                "daily_kwh": round(random.uniform(3.0, 5.5), 2),
                "quantity": 1,
                "time_of_day": "daytime",
                "season": season,
                "start_hour": 10,
                "end_hour": 16,
            }
        }
    else:
        device_inputs["pool_pump"] = {
            "enabled": False,
            "input": {}
        }

    has_dishwasher = random.random() < rates["dishwasher"]

    if has_dishwasher:
        if people_band == "1":
            dish_runs = random.choice([2, 3, 4])
        elif people_band == "2_3":
            dish_runs = random.choice([3, 4, 5, 6])
        else:
            dish_runs = random.choice([5, 6, 7])

        if wfh_days >= 4:
            dish_runs = min(dish_runs + 1, 7)

        device_inputs["dishwasher"] = {
            "enabled": True,
            "input": {
                "daily_kwh": round(random.uniform(0.8, 1.6), 2),
                "quantity": 1,
                "runs_per_week": dish_runs,
                "time_of_day": random.choice(["evening", "night"]),
                "season": season,
            }
        }
    else:
        device_inputs["dishwasher"] = {
            "enabled": False,
            "input": {}
        }

    has_dryer = random.random() < rates["dryer"]

    if has_dryer:
        if people_band == "1":
            dryer_runs = random.choice([1, 2])
        elif people_band == "2_3":
            dryer_runs = random.choice([2, 3, 4])
        else:
            dryer_runs = random.choice([3, 4, 5])

        device_inputs["dryer"] = {
            "enabled": True,
            "input": {
                "daily_kwh": round(random.uniform(1.8, 3.5), 2),
                "quantity": 1,
                "runs_per_week": dryer_runs,
                "time_of_day": "evening",
                "season": season,
            }
        }
    else:
        device_inputs["dryer"] = {
            "enabled": False,
            "input": {}
        }

    # Important: use one random draw only.
    has_induction = random.random() < rates["induction"]

    if has_induction:
        if people_band == "1":
            cooktop_kwh = random.uniform(0.8, 1.8)
        elif people_band == "2_3":
            cooktop_kwh = random.uniform(1.4, 3.0)
        else:
            cooktop_kwh = random.uniform(2.2, 4.2)

        device_inputs["induction_cooktop"] = {
            "enabled": True,
            "input": {
                "daily_kwh": round(cooktop_kwh, 2),
                "quantity": 1,
                "time_of_day": "evening",
                "season": season,
            }
        }
    else:
        device_inputs["induction_cooktop"] = {
            "enabled": False,
            "input": {}
        }

    # =========================
    # EV / Controlled load placeholders
    # =========================

    device_inputs["ev_charging"] = {
        "enabled": False,
        "input": {}
    }

    if has_controlled_load:
        if people_band == "1":
            hot_water_kwh = random.uniform(3.0, 5.0)
        elif people_band == "2_3":
            hot_water_kwh = random.uniform(4.5, 7.5)
        else:
            hot_water_kwh = random.uniform(6.5, 10.0)

        device_inputs["electric_hot_water_controlled_load"] = {
            "enabled": True,
            "input": {
                "daily_kwh": round(hot_water_kwh, 2),
                "quantity": 1,
                "time_of_day": "overnight",
                "season": season,
                "start_hour": 0,
                "end_hour": 6,
            }
        }
    else:
        device_inputs["electric_hot_water_controlled_load"] = {
            "enabled": False,
            "input": {}
        }

    return device_inputs


def build_user_profile_from_plan(row, idx):
    hard = safe_json_loads(row["hard_attributes"])
    soft = safe_json_loads(row["soft_text"])

    tariff_type = hard.get("tariff_type")
    distributor = pick_first(hard.get("distributors", []), "unknown")
    postcode = pick_first(hard.get("included_postcodes", []), "0000")
    
    has_controlled_load = bool(hard.get("has_controlled_load", False))
    has_solar = bool(hard.get("has_solar", False))
    has_ev = bool(hard.get("has_ev", False))
    
    # Ensure battery only if solar exists
    has_battery = has_solar and random.random() < 0.5
    
    # More realistic usage distribution
    people_count = random.randint(1, 5)
    people_band = _people_count_to_band(people_count)
    
    # Base usage varies by household size
    base_usage = {
        "1": random.choice([180, 220, 280, 320]),
        "2_3": random.choice([350, 420, 480, 550, 620]),
        "4_plus": random.choice([550, 650, 750, 850, 950]),
    }[people_band]
    
    monthly_usage_kwh = base_usage
    
    if has_ev:
        monthly_usage_kwh += random.choice([120, 180, 250])
    
    if has_controlled_load:
        monthly_usage_kwh += random.choice([80, 120])
    
    if has_solar:
        # Solar reduces net usage
        monthly_usage_kwh = int(monthly_usage_kwh * random.uniform(0.6, 0.85))
    
    # Current month for seasonality
    current_month = date.today().month
    season = _season_from_month(current_month)
    
    wfh_days = random.randint(0, 5)
    occupancy_pattern = {
        0: ["weekday_evening_only"],
        1: ["weekday_daytime_home"],
        2: ["school_term_pattern"],
    }.get(random.randint(0, 2), ["mixed"])
    
    household_type = random.choice([
        "apartment",
        "townhouse",
        "detached_house"
    ])
    
    # Build device inputs with improved logic
    device_inputs = _build_device_inputs(
        {},
        people_band,
        season,
        wfh_days,
        has_controlled_load
    )
    
    # Add EV charging if applicable
    if has_ev:
        device_inputs["ev_charging"]["enabled"] = True
        device_inputs["ev_charging"]["input"] = {
            "daily_kwh": round(random.uniform(5.0, 14.0), 2),
            "quantity": 1,
            "time_of_day": "overnight",
            "season": season,
            "start_hour": 0,
            "end_hour": 6,
        }
    
    primary_goal = random.choice([
        "reduce_bill",
        "max_savings",
        "backup_power" if has_battery else "reduce_bill",
        "good_roi",
        "go_green"
    ])
    
    user_profile = {
        "selected_profile": {
            "profile_id": f"synthetic-from-plan-{idx:03d}",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            
            "source_seed_plan": {
                "plan_id": row.get("plan_id"),
                "tariff_type": tariff_type,
                "retailer_name": hard.get("retailer_name"),
                "plan_name": soft.get("plan_name")
            },
            
            "location": {
                "postcode": (
                    str(int(float(postcode)))
                    if str(postcode).replace(".", "", 1).isdigit()
                    else str(postcode)
                ),
                "address": {
                    "state": "UNKNOWN",
                    "city": "UNKNOWN",
                    "suburb": "UNKNOWN"
                },
                "context": {
                    "distributor_region": distributor,
                    "network_tariff_region": "UNKNOWN"
                }
            },
            
            "household": {
                "type": household_type,
                "ownership": random.choice(["renting", "owning"]),
                "people_count": people_count,
                "occupancy_pattern": occupancy_pattern,
                "work_from_home_days": wfh_days,
                "controlled_load_present": has_controlled_load,
                "lifestyle_signals": {
                    "has_air_conditioning": device_inputs["air_conditioning"]["enabled"],
                    "has_electric_heating": device_inputs["electric_heating"]["enabled"],
                    "has_pool": device_inputs["pool_pump"]["enabled"],
                    "has_electric_hot_water": has_controlled_load,
                }
            },
            
            "energy_usage": {
                "billing_period_days": 31,
                "monthly_usage_kwh": monthly_usage_kwh,
                "daily_usage_kwh": round(monthly_usage_kwh / 31, 2),
                "month_of_bill": date.today().strftime("%Y-%m"),
                "usage_pattern": {
                    "time_of_day": tariff_type_to_usage_pattern(tariff_type),
                    "weekday_weekend_variation": random.choice([
                        "stable",
                        "high_weekend",
                        "weekday_high"
                    ]),
                    "hours_at_home": random.choice([
                        "6-10",
                        "8-18",
                        "18-24",
                        "mixed"
                    ])
                }
            },
            
            "device_inputs": device_inputs,
            
            "plan": {
                "retailer_name": hard.get("retailer_name"),
                "current_plan_name": row["display_name"],
                "tariff_type_preference": tariff_type_to_user_preference(tariff_type),
                "tariff_type": tariff_type,
                "controlled_load": has_controlled_load,
                "solar_enabled": has_solar,
                "ev_enabled": has_ev
            },
            
            "solar": {
                "has_solar": has_solar,
                "system": {
                    "size_kw": random.choice([3.3, 5.0, 6.6]) if has_solar else 0.0
                } if has_solar else {}
            },
            
            "battery": {
                "has_battery": has_battery,
                "system": {
                    "usable_capacity_kwh": random.choice([5.0, 9.5, 12.1, 13.5]) if has_battery else 0.0
                } if has_battery else {}
            },
            
            "ev": {
                "has_ev": has_ev,
                "ev_count": 1 if has_ev else 0,
                "charging": {
                    "pattern": "overnight" if has_ev else None,
                    "flexible": has_ev
                }
            },
            
            "preferences": {
                "primary_goal": primary_goal,
                "budget_sensitivity": random.choice(["low", "medium", "high"]),
                "payment_preference": "monthly",
                "complexity_tolerance": random.choice(["low", "medium", "high"]),
                "switching_willingness": random.choice(["low", "medium", "high"])
            }
        }
    }
    
    # Set semantic identity (label, profile_id)
    profile = user_profile["selected_profile"]
    _set_profile_identity(profile, idx)
    
    return user_profile



def generate_users_from_processed_plans(
    input_csv=INPUT_CSV,
    output_csv=OUTPUT_CSV,
    n_samples=N_SAMPLES,
    random_seed=RANDOM_SEED
):
    random.seed(random_seed)

    df = pd.read_csv(input_csv)

    sampled_df = df.sample(
        n=min(n_samples, len(df)),
        random_state=random_seed
    ).reset_index(drop=True)

    rows = []

    for idx, row in sampled_df.iterrows():
        user_profile = build_user_profile_from_plan(
            row,
            idx + 1
        )

        profile = user_profile["selected_profile"]

        rows.append({
            "test_id": f"synthetic-test-{idx + 1:03d}",

            "seed_plan_id": row.get("plan_id"),

            "customer_type": (
                safe_json_loads(
                    row["hard_attributes"]
                ).get("customer_type")
            ),

            "distributor": (
                profile["location"]["context"]["distributor_region"]
            ),

            "postcode": (
                profile["location"]["postcode"]
            ),

            "tariff_type": (
                safe_json_loads(
                    row["hard_attributes"]
                ).get("tariff_type")
            ),

            "has_controlled_load": (
                profile["household"]["controlled_load_present"]
            ),

            "has_solar": (
                profile["solar"]["has_solar"]
            ),

            "has_battery": (
                profile["battery"]["has_battery"]
            ),

            "has_ev": (
                profile["ev"]["has_ev"]
            ),

            "usage_time_of_day": (
                profile["energy_usage"]["usage_pattern"]["time_of_day"]
            ),

            "monthly_usage_kwh": (
                profile["energy_usage"]["monthly_usage_kwh"]
            ),

            "primary_goal": (
                profile["preferences"]["primary_goal"]
            ),

            "user_profile_json": json.dumps(
                user_profile,
                ensure_ascii=False
            )
        })

    output_df = pd.DataFrame(rows)

    output_df.to_csv(
        output_csv,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"Generated {len(output_df)} synthetic users")
    print(f"Saved to: {output_csv}")

    return output_df


synthetic_users_df = (
    generate_users_from_processed_plans()
)