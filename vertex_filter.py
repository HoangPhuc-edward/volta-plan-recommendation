from typing import Any, Dict, List, Optional

from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import Namespace


DEFAULT_FALLBACK_LEVELS = [
    {
        "filter_match_level": 7,
        "drop_fields": []
    },
    {
        "filter_match_level": 6,
        "drop_fields": ["has_ev"]
    },
    {
        "filter_match_level": 5,
        "drop_fields": ["has_ev", "has_solar"]
    },
    {
        "filter_match_level": 4,
        "drop_fields": ["has_ev", "has_solar", "has_controlled_load"]
    },
    {
        "filter_match_level": 3,
        "drop_fields": ["has_ev", "has_solar", "has_controlled_load", "tariff_type"]
    },
    {
        "filter_match_level": 2,
        "drop_fields": ["has_ev", "has_solar", "has_controlled_load", "tariff_type", "included_postcodes"]
    },
]


def normalize_filter_value(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, bool):
        return str(value).lower()

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)

    if isinstance(value, int):
        return str(value)

    text = str(value).strip()

    if not text:
        return None

    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except Exception:
        pass

    return text


def normalize_filter_values(values: Any) -> List[str]:
    if values is None:
        return []

    if not isinstance(values, list):
        values = [values]

    result = []

    for value in values:
        normalized = normalize_filter_value(value)
        if normalized is not None:
            result.append(normalized)

    return sorted(set(result))


def build_postcode_tokens(postcodes: Any) -> List[str]:
    tokens = []

    for postcode in normalize_filter_values(postcodes):
        tokens.append(postcode)

        try:
            tokens.append(str(float(postcode)))
        except Exception:
            pass

    return sorted(set(tokens))


def build_bool_filter(
    filters: List[Namespace],
    hard_filter: Dict[str, Any],
    field_name: str,
    drop_fields: List[str],
):
    if field_name in drop_fields:
        return

    value = hard_filter.get(field_name)

    if value is True:
        filters.append(
            Namespace(field_name, ["true", "True"], [])
        )

    elif value is False:
        filters.append(
            Namespace(field_name, ["false", "False"], [])
        )


def build_vertex_hard_filter(
    hard_filter: Dict[str, Any],
    drop_fields: Optional[List[str]] = None,
) -> List[Namespace]:
    if drop_fields is None:
        drop_fields = []

    filters = []

    if "customer_type" not in drop_fields:
        values = normalize_filter_values(
            hard_filter.get("customer_type")
        )

        if values:
            filters.append(
                Namespace("customer_type", values, [])
            )

    if "distributors" not in drop_fields:
        values = normalize_filter_values(
            hard_filter.get("distributors", [])
        )

        if values:
            filters.append(
                Namespace("distributors", values, [])
            )

    if "included_postcodes" not in drop_fields:
        values = build_postcode_tokens(
            hard_filter.get("included_postcodes", [])
        )

        if values:
            filters.append(
                Namespace("included_postcodes", values, [])
            )

    if "tariff_type" not in drop_fields:
        values = normalize_filter_values(
            hard_filter.get("tariff_type", [])
        )

        if values:
            filters.append(
                Namespace("tariff_type", values, [])
            )

    build_bool_filter(
        filters=filters,
        hard_filter=hard_filter,
        field_name="has_controlled_load",
        drop_fields=drop_fields,
    )

    build_bool_filter(
        filters=filters,
        hard_filter=hard_filter,
        field_name="has_solar",
        drop_fields=drop_fields,
    )

    build_bool_filter(
        filters=filters,
        hard_filter=hard_filter,
        field_name="has_ev",
        drop_fields=drop_fields,
    )

    return filters


def build_fallback_filter_levels(
    hard_filter: Dict[str, Any],
    fallback_levels: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if fallback_levels is None:
        fallback_levels = DEFAULT_FALLBACK_LEVELS

    levels = []

    for level_config in fallback_levels:
        drop_fields = level_config.get("drop_fields", [])

        vertex_filter = build_vertex_hard_filter(
            hard_filter=hard_filter,
            drop_fields=drop_fields,
        )

        levels.append({
            "filter_match_level": level_config["filter_match_level"],
            "drop_fields": drop_fields,
            "vertex_filter": vertex_filter,
        })

    return levels