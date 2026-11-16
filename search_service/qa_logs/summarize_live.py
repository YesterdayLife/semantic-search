import json
from pathlib import Path

r = json.loads(Path("qa_logs/live_check.json").read_text(encoding="utf-8"))
print("query_only", r["sqlite_query_only"])
ready = r["ready"]["payload"]
print("ready", {k: ready.get(k) for k in ["status", "collection", "vector_dimension", "distance", "points", "embedding_model", "model_revision", "process_count", "embedding_runtime", "search_engine"]})
cat = r["catalog"]["payload"]
print("catalog", cat.get("process_count"), [c["crop_id"] for c in cat.get("crops", [])], "years", cat.get("years"))
print("catalog_leaks", r["catalog"]["leaks"], "eval_leaks", r["evaluation"]["leaks"])
match = r["evaluation_match"]
print("eval", match["query_count"], match["top_k"], match["has_safety"], match["has_queries"], match["precision_note"])
print("model_ms", match["benchmark_model_ms"], match["saved_model_ms"])
for name in ("dictionary", "semantic", "hybrid"):
    public = match["metrics"][name]
    saved = match["saved_metrics"][name]
    print(name, "equal", public == saved)
    print(" ", {k: public.get(k) for k in public})
print("contracts")
for key in ["unknown_route", "search_unknown_field", "search_empty", "hybrid_conflict", "hybrid_bad_unit", "get_search"]:
    item = r[key]
    err = item["payload"].get("error") or {}
    print(key, item["status"], err.get("code"), err.get("message"), "tb", item["traceback"], "leaks", len(item["leaks"]))
for item in r["hybrids"]:
    s = item["summary"]
    print("Q", item["query"])
    print(" ", item["status"], item["ms"], s["availability"], s["count"], s["eligible_count"], s["embedding_skipped"], len(s["mismatches"]))
    print(" ", s["filters"])
    print(" ", s["numeric"], s["warnings"])
    print(" ", s["timing_ms"])
    for row in s["rows"]:
        print("  row", row["process_id"], row["crop_id"], row["year_ce"], row["region_code"], row["season"], row["spatial_level"], row["quantity"], row["unit"], row["answers"], [i["metric_code"] for i in row["indicators"]])
for name, block in r["warm"].items():
    clients = [x["client_ms"] for x in block["samples"]]
    print("warm", name, sorted({x["status"] for x in block["samples"]}), round(sum(clients) / len(clients), 3), min(clients), max(clients))
    print(" ", block["samples"][-1]["server"])
print("dict", r["dictionary_ignores_explicit_filter"])
print("compare", r["compare"])
print("cold", r["cold_process"])
