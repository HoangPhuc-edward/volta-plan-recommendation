import json
import random
import pandas as pd
from datetime import datetime


INPUT_CSV = "inputs/processed_plans.csv"
OUTPUT_CSV = "inputs/synthetic_users_from_plans.csv"

N_SAMPLES = 30
RANDOM_SEED = 42

random.seed(RANDOM_SEED)

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


def build_user_profile_from_plan(row, idx):
    hard = safe_json_loads(
        row["hard_attributes"]
    )

    soft = safe_json_loads(
        row["soft_text"]
    )

    tariff_type = hard.get(
        "tariff_type"
    )

    distributor = pick_first(
        hard.get("distributors", []),
        "unknown"
    )

    postcode = pick_first(
        hard.get("included_postcodes", []),
        "0000"
    )

    has_controlled_load = bool(
        hard.get("has_controlled_load", False)
    )

    has_solar = bool(
        hard.get("has_solar", False)
    )

    has_ev = bool(
        hard.get("has_ev", False)
    )

    usage_time = tariff_type_to_usage_pattern(
        tariff_type
    )

    has_battery = (
        has_solar and random.random() < 0.5
    )

    monthly_usage_kwh = random.choice([
        250,
        350,
        420,
        550,
        700,
        900
    ])

    if has_ev:
        monthly_usage_kwh += random.choice([
            120,
            180,
            250
        ])

    if has_controlled_load:
        monthly_usage_kwh += random.choice([
            80,
            120
        ])

    primary_goal = random.choice([
        "reduce_bill",
        "max_savings",
        "backup_power",
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

                "retailer_name": hard.get(
                    "retailer_name"
                ),

                "plan_name": soft.get(
                    "plan_name"
                )
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
                "type": random.choice([
                    "apartment",
                    "townhouse",
                    "detached_house"
                ]),

                "ownership": random.choice([
                    "renting",
                    "owning"
                ]),

                "people_count": random.randint(1, 5),

                "occupancy_pattern": random.choice([
                    "single worker",
                    "daytime family",
                    "evening family",
                    "work from home"
                ]),

                "work_from_home_days": random.randint(0, 5),

                "controlled_load_present": has_controlled_load
            },

            "energy_usage": {
                "billing_period_days": 31,

                "monthly_usage_kwh": monthly_usage_kwh,

                "daily_usage_kwh": round(
                    monthly_usage_kwh / 31,
                    2
                ),

                "usage_pattern": {
                    "time_of_day": usage_time,

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

            "device_inputs": {
                "lighting": {
                    "enabled": True,

                    "input": {
                        "daily_kwh": round(
                            random.uniform(0.8, 2.5),
                            2
                        ),

                        "quantity": random.randint(6, 16),

                        "time_of_day": usage_time,

                        "season": "autumn"
                    }
                },

                "refrigerator": {
                    "enabled": True,

                    "input": {
                        "daily_kwh": round(
                            random.uniform(0.8, 1.8),
                            2
                        ),

                        "quantity": 1,

                        "season": "autumn"
                    }
                },

                "wifi_router": {
                    "enabled": True,

                    "input": {
                        "daily_kwh": 0.24,

                        "season": "autumn"
                    }
                },

                "air_conditioning": {
                    "enabled": random.random() < 0.7,

                    "input": {
                        "daily_kwh": round(
                            random.uniform(2.0, 8.0),
                            2
                        ),

                        "time_of_day": usage_time,

                        "season": "summer"
                    }
                },

                "dishwasher": {
                    "enabled": random.random() < 0.6,

                    "input": {
                        "daily_kwh": round(
                            random.uniform(0.6, 1.4),
                            2
                        ),

                        "runs_per_week": random.choice([
                            2,
                            4,
                            6
                        ]),

                        "time_of_day": random.choice([
                            "evening",
                            "night"
                        ]),

                        "season": "autumn"
                    }
                },

                "ev_charging": {
                    "enabled": has_ev,

                    "input": {
                        "daily_kwh": (
                            round(
                                random.uniform(5.0, 14.0),
                                2
                            )
                            if has_ev
                            else 0.0
                        ),

                        "time_of_day": "overnight",

                        "season": "autumn"
                    }
                },

                "electric_hot_water_controlled_load": {
                    "enabled": has_controlled_load,

                    "input": {
                        "daily_kwh": (
                            round(
                                random.uniform(3.0, 6.5),
                                2
                            )
                            if has_controlled_load
                            else 0.0
                        ),

                        "time_of_day": "overnight",

                        "season": "autumn"
                    }
                }
            },

            "plan": {
                "tariff_type_preference": (
                    tariff_type_to_user_preference(
                        tariff_type
                    )
                ),

                "controlled_load": has_controlled_load,

                "solar_enabled": has_solar,

                "ev_enabled": has_ev
            },

            "solar": {
                "has_solar": has_solar,

                "system": {
                    "size_kw": (
                        random.choice([
                            3.3,
                            5.0,
                            6.6,
                            8.0,
                            10.0
                        ])
                        if has_solar
                        else 0.0
                    )
                }
            },

            "battery": {
                "has_battery": has_battery,

                "system": {
                    "usable_capacity_kwh": (
                        random.choice([
                            5.0,
                            9.5,
                            12.1,
                            13.5
                        ])
                        if has_battery
                        else 0.0
                    )
                }
            },

            "ev": {
                "has_ev": has_ev,

                "ev_count": (
                    1 if has_ev else 0
                ),

                "charging": {
                    "pattern": (
                        "overnight"
                        if has_ev
                        else None
                    ),

                    "flexible": has_ev
                }
            },

            "preferences": {
                "primary_goal": primary_goal,

                "budget_sensitivity": random.choice([
                    "low",
                    "medium",
                    "high"
                ]),

                "payment_preference": "monthly",

                "complexity_tolerance": random.choice([
                    "low",
                    "medium",
                    "high"
                ]),

                "switching_willingness": random.choice([
                    "low",
                    "medium",
                    "high"
                ])
            }
        }
    }

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