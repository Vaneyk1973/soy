import json
import os
import sqlite3
from pathlib import Path

log_path = Path(os.environ["UVICORN_LOG"])
if not log_path.exists():
    raise SystemExit(f"log file not found: {log_path}")

required_fields = {"request_id", "method", "endpoint", "status_code", "duration_ms", "user_id", "timestamp"}
json_lines = []
with log_path.open("r", encoding="utf-8", errors="ignore") as file:
    for line in file:
        stripped = line.strip()
        if stripped.startswith("{") and "request_id" in stripped:
            try:
                json_lines.append(json.loads(stripped))
            except Exception:
                pass

if not json_lines:
    raise SystemExit("No JSON access logs found")

if not all(required_fields.issubset(set(item.keys())) for item in json_lines[:20]):
    raise SystemExit("Some JSON logs miss required fields")

masked = False
body_logged = False
for item in json_lines:
    body = item.get("request_body")
    if body is not None:
        body_logged = True
        if isinstance(body, dict) and body.get("password") == "***":
            masked = True

if not body_logged:
    raise SystemExit("No request_body logged for mutating request")
if not masked:
    raise SystemExit("Password masking not found in logs")

print("Log checks passed")

db_path = Path("scenario_all_main.db")
connection = sqlite3.connect(db_path)
cursor = connection.cursor()

queries = [
    ("users", "SELECT id,email,role,created_at FROM users ORDER BY created_at DESC LIMIT 5"),
    ("products", "SELECT id,name,status,stock,seller_id,created_at,updated_at FROM products ORDER BY created_at DESC LIMIT 10"),
    ("orders", "SELECT id,user_id,status,promo_code_id,total_amount,discount_amount FROM orders ORDER BY created_at DESC LIMIT 10"),
    ("order_items", "SELECT id,order_id,product_id,quantity,price_at_order FROM order_items ORDER BY rowid DESC LIMIT 10"),
    ("promo_codes", "SELECT id,code,current_uses,max_uses,active,valid_from,valid_until FROM promo_codes ORDER BY created_at DESC LIMIT 10"),
    ("user_operations", "SELECT id,user_id,operation_type,created_at FROM user_operations ORDER BY created_at DESC LIMIT 10"),
]

for name, query in queries:
    print(f"\n-- {name} --")
    rows = cursor.execute(query).fetchall()
    for row in rows:
        print(row)

connection.close()
print("DB proof printed")
