from typing import Any, Dict, List, Optional

from vertex_filter import build_fallback_filter_levels


def query_vertex_once(
    endpoint: Any,
    deployed_index_id: str,
    query_vector: Any,
    vertex_filter: List[Any],
    top_k: int = 20,
    return_full_datapoint: bool = False,
) -> List[Dict[str, Any]]:
    response = endpoint.find_neighbors(
        deployed_index_id=deployed_index_id,
        queries=[query_vector],
        num_neighbors=top_k,
        filter=vertex_filter,
        return_full_datapoint=return_full_datapoint,
    )

    neighbors = response[0] if response else []

    results = []

    for neighbor in neighbors:
        results.append({
            "plan_id": str(neighbor.id),
            "distance": float(neighbor.distance),
        })

    return results


def query_vertex_with_fallback(
    endpoint: Any,
    deployed_index_id: str,
    query_vector: Any,
    hard_filter: Dict[str, Any],
    target_k: int = 20,
    per_level_top_k: int = 50,
    fallback_levels: Optional[List[Dict[str, Any]]] = None,
    return_full_datapoint: bool = False,
) -> List[Dict[str, Any]]:
    levels = build_fallback_filter_levels(
        hard_filter=hard_filter,
        fallback_levels=fallback_levels,
    )

    results_by_id = {}

    for level in levels:
        filter_match_level = level["filter_match_level"]
        drop_fields = level["drop_fields"]
        vertex_filter = level["vertex_filter"]

        print(
            f"Querying level {filter_match_level} | "
            f"drop_fields={drop_fields}"
        )

        try:
            level_results = query_vertex_once(
                endpoint=endpoint,
                deployed_index_id=deployed_index_id,
                query_vector=query_vector,
                vertex_filter=vertex_filter,
                top_k=per_level_top_k,
                return_full_datapoint=return_full_datapoint,
            )
        except Exception as e:
            print(f"Vertex query failed at level {filter_match_level}: {e}")
            continue

        print(f"Returned {len(level_results)} plans")

        for item in level_results:
            plan_id = item["plan_id"]

            if plan_id in results_by_id:
                continue

            results_by_id[plan_id] = {
                "plan_id": plan_id,
                "distance": item["distance"],
                "filter_match_level": filter_match_level,
                "dropped_filters": drop_fields,
            }

        if len(results_by_id) >= target_k:
            break

    results = list(results_by_id.values())

    results = sorted(
        results,
        key=lambda x: (
            -x["filter_match_level"],
            x["distance"],
        )
    )

    return results[:target_k]