from calculation_function.normalize_plan_schema import normalize_plan_for_calculation
from calculation_function.normalize_user_schema import normalize_user_for_calculation
from calculation_function.cost_flow import calculate_net_cost
import pandas as pd
import json
from datasets import load_dataset

def load_test_users(csv_path: str):
    df = pd.read_csv(csv_path)

    users = []

    for _, row in df.iterrows():
        users.append({
            "test_id": row["test_id"],
            "seed_plan_id": row.get("seed_plan_id"),
            "query_text": row["query_text"],
            "hard_filter": json.loads(row["hard_filter"]),
            "user_profile_json": json.loads(row["user_profile_json"])
        })

    return users

INPUT_USER_CSV = "inputs/ready_test_users.csv"
users = load_test_users(INPUT_USER_CSV) 
user = users[0]
normalized_user = normalize_user_for_calculation(user["user_profile_json"])




with open("schemas/user_calculation_schema.json", "w") as f:
    json.dump(normalized_user, f, indent=2)



data = load_dataset("hoangphuc090104/DCR_Energy_Plan")["train"]

for item in data:
    if item["plan_id"] == user["seed_plan_id"]:
        plan = item
        break


with open("schemas/plan_calculation_schema.json", "w") as f:
    json.dump(normalize_plan_for_calculation(plan), f, indent=2)


if plan:
    normalized_plan = normalize_plan_for_calculation(plan)
    cost_output = calculate_net_cost(normalized_user, normalized_plan)
    print(f"Cost Output: {json.dumps(cost_output, indent=2)}")
else:
    print(f"Plan with ID {user['seed_plan_id']} not found in the dataset.")
