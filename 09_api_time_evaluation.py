import json
import time
import pandas as pd
import requests


API_URL = "https://volta-plan-api-933786093071.us-central1.run.app/recommend-plans"

INPUT_CSV = "inputs/synthetic_users_from_plans.csv"
OUTPUT_CSV = "outputs/api_benchmark_results.csv"


def benchmark_api():

    df = pd.read_csv(INPUT_CSV)

    results = []

    for idx, row in df.iterrows():

        test_id = row["test_id"]

        user_profile = json.loads(
            row["user_profile_json"]
        )

        payload = {
            "user_profile": user_profile
        }

        print(
            f"[{idx + 1}/{len(df)}] "
            f"Testing {test_id}..."
        )

        start_time = time.perf_counter()

        try:

            response = requests.post(
                API_URL,
                json=payload,
                timeout=300
            )

            elapsed = (
                time.perf_counter()
                - start_time
            )

            results.append({
                "test_id": test_id,
                "status_code": response.status_code,
                "success": response.status_code == 200,
                "response_time_sec": round(elapsed, 4)
            })

            print(
                f"  Status={response.status_code} "
                f"Time={elapsed:.2f}s"
            )

        except Exception as e:

            elapsed = (
                time.perf_counter()
                - start_time
            )

            results.append({
                "test_id": test_id,
                "status_code": None,
                "success": False,
                "response_time_sec": round(elapsed, 4),
                "error": str(e)
            })

            print(
                f"  ERROR: {e}"
            )

    result_df = pd.DataFrame(results)

    result_df.to_csv(
        OUTPUT_CSV,
        index=False
    )

    successful = result_df[
        result_df["success"] == True
    ]

    

    if len(successful) > 0:

        latency = successful["response_time_sec"].iloc[1:]

        print("\n========== SUMMARY ==========")

        print(
            f"Total Requests: {len(result_df)}"
        )

        print(
            f"Success Rate: "
            f"{100 * len(successful) / len(result_df):.2f}%"
        )

        print(
            f"Average Latency: "
            f"{latency.mean():.2f}s"
        )

        print(
            f"Median Latency: "
            f"{latency.median():.2f}s"
        )

        print(
            f"Min Latency: "
            f"{latency.min():.2f}s"
        )

        print(
            f"Max Latency: "
            f"{latency.max():.2f}s"
        )

        print(
            f"P95 Latency: "
            f"{latency.quantile(0.95):.2f}s"
        )

    print()
    print(
        f"Detailed results saved to: "
        f"{OUTPUT_CSV}"
    )


if __name__ == "__main__":
    benchmark_api()