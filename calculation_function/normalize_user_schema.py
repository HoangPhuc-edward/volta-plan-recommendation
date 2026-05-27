import json
from typing import Any, Dict


def _get_nested(data: Dict[str, Any], path: list[str], default=None):
    current = data

    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)

        if current is None:
            return default

    return current


def _normalize_device(device: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep only:
    {
      "enabled": bool,
      "input": {
        "daily_kwh": ...,
        "time_of_day": ...
      }
    }

    Other extra fields such as quantity, season, runs_per_week are removed
    to match sample_profile.json.
    """

    if not isinstance(device, dict):
        return {
            "enabled": False,
            "input": {}
        }

    input_data = device.get("input", {})

    if not isinstance(input_data, dict):
        input_data = {}

    normalized_input = {}

    if "daily_kwh" in input_data:
        normalized_input["daily_kwh"] = input_data.get("daily_kwh")

    if "time_of_day" in input_data:
        normalized_input["time_of_day"] = input_data.get("time_of_day")

    if "quantity" in input_data:
        normalized_input["quantity"] = input_data.get("quantity")

    if "start_hour" in input_data:
        normalized_input["start_hour"] = input_data.get("start_hour")

    if "end_hour" in input_data:
        normalized_input["end_hour"] = input_data.get("end_hour")


    return {
        "enabled": bool(device.get("enabled", False)),
        "input": normalized_input
    }


def normalize_user_for_calculation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert selected_profile_payload schema into sample_profile schema.

    Input:
        {
          "selected_profile": {...}
        }

    Output:
        {
          "profile_id": "...",
          "location": {
            "postcode": "..."
          },
          "household": {
            "controlled_load_present": true
          },
          "device_inputs": {...},
          "solar": {...}
        }
    """

    selected_profile = payload.get("selected_profile", payload)

    device_inputs = selected_profile.get("device_inputs", {})

    normalized = {
        "profile_id": selected_profile.get("profile_id"),
        "location": {
            "postcode": _get_nested(
                selected_profile,
                ["location", "postcode"]
            )
        },
        "household": {
            "controlled_load_present": bool(
                _get_nested(
                    selected_profile,
                    ["household", "controlled_load_present"],
                    False
                )
            )
        },
        "device_inputs": {},
        "solar": {
            "has_solar": bool(
                _get_nested(
                    selected_profile,
                    ["solar", "has_solar"],
                    False
                )
            ),
            "system": {
                "size_kw": _get_nested(
                    selected_profile,
                    ["solar", "system", "size_kw"]
                )
            },
            "performance": {
                "export_cap_kw": _get_nested(
                    selected_profile,
                    ["solar", "performance", "export_cap_kw"]
                )
            }
        }
    }


    for device_name in device_inputs:
        normalized["device_inputs"][device_name] = _normalize_device(
            device_inputs.get(device_name, {})
        )

    return normalized


if __name__ == "__main__":
    input_path = "selected_profile_payload(2).json"
    output_path = "normalized_profile.json"

    with open(input_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    normalized_profile = normalize_user_for_calculation(payload)

    print(json.dumps(normalized_profile, indent=2, ensure_ascii=False))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            normalized_profile,
            f,
            indent=2,
            ensure_ascii=False
        )