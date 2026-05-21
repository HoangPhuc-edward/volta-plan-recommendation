import json
import csv
import random
from copy import deepcopy
from pathlib import Path
from datetime import datetime

INPUT_PATH = "selected_profile_payload.json"
OUTPUT_PATH = "synthetic_user_profiles.csv"

random.seed(42)


LOCATIONS = [
    {
        "postcode": "2000",
        "state": "NSW",
        "city": "Sydney",
        "suburb": "Sydney",
        "distributor_region": "Ausgrid",
        "network_tariff_region": "NSW-RES"
    },
    {
        "postcode": "3000",
        "state": "VIC",
        "city": "Melbourne",
        "suburb": "Melbourne",
        "distributor_region": "Citipower",
        "network_tariff_region": "VIC-RES"
    },
    {
        "postcode": "4000",
        "state": "QLD",
        "city": "Brisbane",
        "suburb": "Brisbane",
        "distributor_region": "Energex",
        "network_tariff_region": "QLD-RES"
    },
    {
        "postcode": "5000",
        "state": "SA",
        "city": "Adelaide",
        "suburb": "Adelaide",
        "distributor_region": "SA Power Networks",
        "network_tariff_region": "SA-RES"
    },
    {
        "postcode": "2600",
        "state": "ACT",
        "city": "Canberra",
        "suburb": "Canberra",
        "distributor_region": "Evoenergy",
        "network_tariff_region": "ACT-RES"
    }
]

HOUSEHOLD_TYPES = ["apartment", "townhouse", "detached_house"]
OWNERSHIP_TYPES = ["renting", "owning"]
OCCUPANCY_PATTERNS = [
    "single worker",
    "daytime family",
    "evening family",
    "work from home",
    "retired couple",
    "student share house"
]

USAGE_PATTERNS = [
    {
        "time_of_day": "evening",
        "weekday_weekend_variation": "high_weekend",
        "hours_at_home": "6-10"
    },
    {
        "time_of_day": "daytime",
        "weekday_weekend_variation": "weekday_high",
        "hours_at_home": "8-18"
    },
    {
        "time_of_day": "overnight",
        "weekday_weekend_variation": "stable",
        "hours_at_home": "22-7"
    },
    {
        "time_of_day": "balanced",
        "weekday_weekend_variation": "stable",
        "hours_at_home": "mixed"
    },
    {
        "time_of_day": "night",
        "weekday_weekend_variation": "high_weekend",
        "hours_at_home": "18-24"
    }
]

PRIMARY_GOALS = [
    "reduce_bill",
    "max_savings",
    "go_green",
    "backup_power",
    "good_roi"
]

PAYMENT_PREFERENCES = ["monthly", "quarterly"]
COMPLEXITY_TOLERANCE = ["low", "medium", "high"]
BUDGET_SENSITIVITY = ["low", "medium", "high"]


def load_base_profile(path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    return payload["selected_profile"]


def set_location(profile, location):
    profile["location"]["postcode"] = location["postcode"]
    profile["location"]["address"]["state"] = location["state"]
    profile["location"]["address"]["city"] = location["city"]
    profile["location"]["address"]["suburb"] = location["suburb"]
    profile["location"]["address"]["full_address"] = f"Demo address, {location['suburb']} {location['state']} {location['postcode']}"
    profile["location"]["context"]["distributor_region"] = location["distributor_region"]
    profile["location"]["context"]["network_tariff_region"] = location["network_tariff_region"]


def set_device(profile, device_name, enabled, daily_kwh=0.0, time_of_day=None, season="autumn", quantity=None, runs_per_week=None):
    if device_name not in profile["device_inputs"]:
        profile["device_inputs"][device_name] = {
            "enabled": enabled,
            "input": {}
        }

    profile["device_inputs"][device_name]["enabled"] = enabled

    device_input = profile["device_inputs"][device_name].setdefault("input", {})
    device_input["daily_kwh"] = round(float(daily_kwh), 2)

    if time_of_day is not None:
        device_input["time_of_day"] = time_of_day

    if season is not None:
        device_input["season"] = season

    if quantity is not None:
        device_input["quantity"] = quantity

    if runs_per_week is not None:
        device_input["runs_per_week"] = runs_per_week


def apply_usage_profile(profile, usage_pattern, monthly_usage_kwh):
    profile["energy_usage"]["monthly_usage_kwh"] = round(monthly_usage_kwh, 2)
    profile["energy_usage"]["daily_usage_kwh"] = round(monthly_usage_kwh / 31, 2)
    profile["energy_usage"]["monthly_bill"] = round(monthly_usage_kwh * random.uniform(0.28, 0.45), 2)
    profile["energy_usage"]["billing_period_days"] = 31
    profile["energy_usage"]["usage_pattern"] = deepcopy(usage_pattern)


def apply_solar(profile, has_solar):
    profile["solar"]["has_solar"] = has_solar

    if has_solar:
        size_kw = random.choice([3.3, 5.0, 6.6, 8.0, 10.0])
        export_ratio = random.choice([0.2, 0.35, 0.45, 0.6, 0.75])
        self_consumption_ratio = round(1.0 - export_ratio, 2)

        profile["solar"]["target_system_size_kw"] = size_kw
        profile["solar"]["system"]["size_kw"] = size_kw
        profile["solar"]["system"]["panel_capacity_kw"] = round(size_kw * random.uniform(1.1, 1.3), 1)
        profile["solar"]["performance"]["export_cap_kw"] = min(5.0, size_kw)
        profile["solar"]["performance"]["estimated_export_ratio"] = export_ratio
        profile["solar"]["performance"]["self_consumption_ratio"] = self_consumption_ratio
        profile["plan"]["solar_fit_enabled"] = True
    else:
        profile["solar"]["target_system_size_kw"] = 0.0
        profile["solar"]["system"]["size_kw"] = 0.0
        profile["solar"]["system"]["panel_capacity_kw"] = 0.0
        profile["solar"]["performance"]["export_cap_kw"] = 0.0
        profile["solar"]["performance"]["estimated_export_ratio"] = 0.0
        profile["solar"]["performance"]["self_consumption_ratio"] = 0.0
        profile["plan"]["solar_fit_enabled"] = False


def apply_battery(profile, has_battery, has_solar):
    profile["battery"]["has_battery"] = has_battery

    if has_battery:
        capacity = random.choice([5.0, 7.5, 10.0, 13.5, 15.0])
        profile["battery"]["target_capacity_kwh"] = capacity
        profile["battery"]["system"]["capacity_kwh"] = capacity
        profile["battery"]["system"]["usable_capacity_kwh"] = round(capacity * 0.9, 1)
        profile["battery"]["system"]["round_trip_efficiency"] = random.choice([0.85, 0.9, 0.92])
        profile["battery"]["features"]["backup_capability"] = random.choice([True, False])
        profile["battery"]["intent"]["wants_battery"] = True
    else:
        profile["battery"]["target_capacity_kwh"] = 0.0
        profile["battery"]["system"]["capacity_kwh"] = 0.0
        profile["battery"]["system"]["usable_capacity_kwh"] = 0.0
        profile["battery"]["features"]["backup_capability"] = False
        profile["battery"]["intent"]["wants_battery"] = has_solar and random.choice([True, False])


def apply_ev(profile, has_ev):
    profile["ev"]["has_ev"] = has_ev

    if has_ev:
        daily_km = random.choice([20, 34, 50, 70, 90])
        charging_pattern = random.choice(["overnight", "daytime", "evening"])

        profile["ev"]["ev_count"] = random.choice([1, 1, 1, 2])
        profile["ev"]["charging"]["pattern"] = charging_pattern
        profile["ev"]["charging"]["flexible"] = random.choice([True, False])
        profile["ev"]["charging"]["home_charging_share"] = random.choice([0.6, 0.75, 0.9, 1.0])
        profile["ev"]["usage"]["daily_km"] = daily_km
        profile["ev"]["usage"]["weekly_km"] = daily_km * 7
        profile["ev"]["usage"]["monthly_km"] = daily_km * 30
        profile["ev"]["usage"]["annual_km"] = daily_km * 365
        profile["ev"]["preferences"]["interested_in_ev_tariff"] = True

        ev_daily_kwh = round(daily_km * 0.18, 2)
        set_device(
            profile,
            "ev_charging",
            True,
            daily_kwh=ev_daily_kwh,
            time_of_day=charging_pattern,
            season="autumn",
            quantity=1,
            runs_per_week=random.choice([3, 5, 7])
        )
    else:
        profile["ev"]["ev_count"] = 0
        profile["ev"]["charging"]["pattern"] = None
        profile["ev"]["charging"]["flexible"] = False
        profile["ev"]["charging"]["home_charging_share"] = 0.0
        profile["ev"]["usage"]["daily_km"] = 0.0
        profile["ev"]["usage"]["weekly_km"] = 0.0
        profile["ev"]["usage"]["monthly_km"] = 0.0
        profile["ev"]["usage"]["annual_km"] = 0.0
        profile["ev"]["preferences"]["interested_in_ev_tariff"] = False

        set_device(profile, "ev_charging", False, daily_kwh=0.0, time_of_day="overnight")


def apply_controlled_load(profile, has_controlled_load):
    profile["household"]["controlled_load_present"] = has_controlled_load
    profile["plan"]["controlled_load"] = has_controlled_load

    if has_controlled_load:
        hot_water_kwh = random.choice([2.5, 3.5, 4.2, 5.5, 7.0])
        set_device(
            profile,
            "electric_hot_water_controlled_load",
            True,
            daily_kwh=hot_water_kwh,
            time_of_day="overnight",
            season="autumn",
            quantity=1
        )
        profile["household"]["lifestyle_signals"]["has_electric_hot_water"] = True
    else:
        set_device(
            profile,
            "electric_hot_water_controlled_load",
            False,
            daily_kwh=0.0,
            time_of_day="overnight",
            season="autumn"
        )
        profile["household"]["lifestyle_signals"]["has_electric_hot_water"] = False


def apply_appliances(profile, usage_time):
    people_count = profile["household"]["people_count"]

    lighting_kwh = random.uniform(0.6, 2.8)
    ac_kwh = random.uniform(0.0, 9.0)
    dishwasher_enabled = random.choice([True, False])
    dryer_enabled = random.choice([True, False])
    induction_enabled = random.choice([True, False])
    pool_enabled = profile["household"]["type"] == "detached_house" and random.choice([True, False])

    set_device(
        profile,
        "lighting",
        True,
        daily_kwh=lighting_kwh,
        time_of_day=usage_time,
        season=random.choice(["autumn", "summer", "winter"]),
        quantity=max(4, people_count * random.randint(3, 6))
    )

    set_device(
        profile,
        "refrigerator",
        True,
        daily_kwh=random.uniform(0.8, 1.8),
        time_of_day="balanced",
        season="autumn",
        quantity=random.choice([1, 1, 2])
    )

    set_device(
        profile,
        "wifi_router",
        True,
        daily_kwh=0.24,
        time_of_day="balanced",
        season="autumn",
        quantity=1
    )

    set_device(
        profile,
        "air_conditioning",
        ac_kwh > 1.0,
        daily_kwh=ac_kwh if ac_kwh > 1.0 else 0.0,
        time_of_day=usage_time,
        season=random.choice(["summer", "winter"])
    )

    set_device(
        profile,
        "dishwasher",
        dishwasher_enabled,
        daily_kwh=random.uniform(0.5, 1.5) if dishwasher_enabled else 0.0,
        time_of_day=random.choice(["night", "evening"]),
        season="autumn",
        runs_per_week=random.choice([2, 4, 6])
    )

    set_device(
        profile,
        "dryer",
        dryer_enabled,
        daily_kwh=random.uniform(1.0, 3.5) if dryer_enabled else 0.0,
        time_of_day=random.choice(["evening", "daytime"]),
        season=random.choice(["autumn", "winter"]),
        runs_per_week=random.choice([1, 2, 4])
    )

    set_device(
        profile,
        "induction_cooktop",
        induction_enabled,
        daily_kwh=random.uniform(0.8, 2.5) if induction_enabled else 0.0,
        time_of_day=random.choice(["evening", "daytime"]),
        season="autumn"
    )

    set_device(
        profile,
        "pool_pump",
        pool_enabled,
        daily_kwh=random.uniform(3.0, 8.0) if pool_enabled else 0.0,
        time_of_day="daytime",
        season="summer"
    )

    profile["household"]["appliances"]["dishwasher"] = dishwasher_enabled
    profile["household"]["appliances"]["dryer"] = dryer_enabled
    profile["household"]["appliances"]["induction_cooktop"] = induction_enabled
    profile["household"]["appliances"]["pool_pump"] = pool_enabled
    profile["household"]["lifestyle_signals"]["has_pool"] = pool_enabled
    profile["household"]["lifestyle_signals"]["has_air_conditioning"] = ac_kwh > 1.0


def apply_preferences(profile, primary_goal):
    profile["preferences"]["primary_goal"] = primary_goal
    profile["preferences"]["budget_sensitivity"] = random.choice(BUDGET_SENSITIVITY)
    profile["preferences"]["payment_preference"] = random.choice(PAYMENT_PREFERENCES)
    profile["preferences"]["complexity_tolerance"] = random.choice(COMPLEXITY_TOLERANCE)
    profile["preferences"]["switching_willingness"] = random.choice(["low", "medium", "high"])
    profile["preferences"]["install_willingness"] = random.choice(["low", "medium", "high"])

    profile["plan"]["green_charges"] = primary_goal == "go_green"

    if primary_goal == "go_green":
        profile["preferences"]["budget_sensitivity"] = random.choice(["low", "medium"])
        profile["preferences"]["complexity_tolerance"] = random.choice(["medium", "high"])
    elif primary_goal in ["reduce_bill", "max_savings"]:
        profile["preferences"]["budget_sensitivity"] = "high"
    elif primary_goal == "backup_power":
        profile["preferences"]["install_willingness"] = random.choice(["medium", "high"])
    elif primary_goal == "good_roi":
        profile["preferences"]["budget_sensitivity"] = random.choice(["medium", "high"])
        profile["preferences"]["maximum_upfront_budget"] = random.choice([5000, 10000, 15000, 20000])


def apply_plan_preference(profile, usage_pattern, has_controlled_load, has_ev):
    if usage_pattern in ["overnight", "night"] or has_ev:
        preferred = "time_of_use"
    elif usage_pattern == "balanced":
        preferred = random.choice(["flat", "time_of_use"])
    else:
        preferred = random.choice(["flat", "time_of_use"])

    profile["plan"]["tariff_type_preference"] = preferred
    profile["plan"]["tariff_type"] = preferred


def flatten_summary(profile):
    return {
        "profile_id": profile["profile_id"],
        "postcode": profile["location"]["postcode"],
        "state": profile["location"]["address"]["state"],
        "distributor_region": profile["location"]["context"]["distributor_region"],
        "household_type": profile["household"]["type"],
        "people_count": profile["household"]["people_count"],
        "controlled_load_present": profile["household"]["controlled_load_present"],
        "monthly_usage_kwh": profile["energy_usage"]["monthly_usage_kwh"],
        "daily_usage_kwh": profile["energy_usage"]["daily_usage_kwh"],
        "time_of_day": profile["energy_usage"]["usage_pattern"]["time_of_day"],
        "has_solar": profile["solar"]["has_solar"],
        "solar_size_kw": profile["solar"]["system"]["size_kw"],
        "solar_export_ratio": profile["solar"]["performance"]["estimated_export_ratio"],
        "has_battery": profile["battery"]["has_battery"],
        "battery_usable_capacity_kwh": profile["battery"]["system"]["usable_capacity_kwh"],
        "has_ev": profile["ev"]["has_ev"],
        "ev_charging_pattern": profile["ev"]["charging"]["pattern"],
        "primary_goal": profile["preferences"]["primary_goal"],
        "go_green": profile["preferences"]["primary_goal"] == "go_green",
        "tariff_type_preference": profile["plan"]["tariff_type_preference"],
        "user_profile_json": json.dumps(
            {"selected_profile": profile},
            ensure_ascii=False
        )
    }


def build_synthetic_profile(base_profile, index):
    profile = deepcopy(base_profile)

    location = LOCATIONS[index % len(LOCATIONS)]
    usage_pattern = USAGE_PATTERNS[index % len(USAGE_PATTERNS)]
    primary_goal = PRIMARY_GOALS[index % len(PRIMARY_GOALS)]

    has_controlled_load = index % 2 == 0
    has_solar = index % 3 != 0
    has_battery = has_solar and index % 4 == 0
    has_ev = index % 5 in [0, 1]

    profile["profile_id"] = f"synthetic-profile-{index + 1:03d}"
    profile["created_at"] = datetime.now().isoformat()
    profile["updated_at"] = datetime.now().isoformat()

    set_location(profile, location)

    profile["household"]["type"] = HOUSEHOLD_TYPES[index % len(HOUSEHOLD_TYPES)]
    profile["household"]["ownership"] = OWNERSHIP_TYPES[index % len(OWNERSHIP_TYPES)]
    profile["household"]["people_count"] = 1 + (index % 5)
    profile["household"]["occupancy_pattern"] = OCCUPANCY_PATTERNS[index % len(OCCUPANCY_PATTERNS)]
    profile["household"]["work_from_home_days"] = index % 6
    profile["household"]["has_children"] = profile["household"]["people_count"] >= 3

    base_usage = 180 + (index % 10) * 85
    if has_ev:
        base_usage += 180
    if has_controlled_load:
        base_usage += 90
    if profile["household"]["type"] == "detached_house":
        base_usage += 120

    apply_usage_profile(profile, usage_pattern, base_usage)
    apply_controlled_load(profile, has_controlled_load)
    apply_solar(profile, has_solar)
    apply_battery(profile, has_battery, has_solar)
    apply_ev(profile, has_ev)
    apply_appliances(profile, usage_pattern["time_of_day"])
    apply_preferences(profile, primary_goal)
    apply_plan_preference(profile, usage_pattern["time_of_day"], has_controlled_load, has_ev)

    return profile


def main():
    base_profile = load_base_profile(INPUT_PATH)

    rows = []

    for i in range(50):
        profile = build_synthetic_profile(base_profile, i)
        rows.append(flatten_summary(profile))

    fieldnames = list(rows[0].keys())

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Created {len(rows)} synthetic user profiles")
    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()