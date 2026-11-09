"""CosIng EU corporate-search query semantics smoke test (6 requests, not bulk collection).

Only tests supported-by-observation syntax and plausible exact-term alternatives.
Unverified filters may return HTTP 400 or zero results; that is evidence, not success.
EU search internal interface is not a documented public bulk API: check use terms.
"""
import argparse
import csv
import json
import os
import time

ENDPOINT = "https://webgate.ec.europa.eu/es/search-api/rest/search"


def query_for(name, variant):
    base = {"terms": {"itemType": ["ingredient"]}}
    if variant == "current_text_field":
        clause = {"text": {"query": name, "fields": ["inciName.exact"], "defaultOperator": "AND"}}
    elif variant == "terms_inci_exact":
        clause = {"terms": {"inciName.exact": [name]}}
    elif variant == "terms_inci":
        clause = {"terms": {"inciName": [name]}}
    else:
        raise ValueError(variant)
    return {"bool": {"must": [clause, base]}}


def norm(s):
    return " ".join(s.upper().split())


def main():
    ap = argparse.ArgumentParser(description="Compare EC Search API exact-INCI query variants")
    ap.add_argument("--names", nargs="+", default=["GLYCERIN", "DIMETHICONE"])
    ap.add_argument("--output", default="cosing_query_comparison.csv")
    ap.add_argument("--delay", type=float, default=2.0)
    args = ap.parse_args()
    key = os.getenv("COSING_SEARCH_API_KEY", "").strip()
    if not key:
        ap.error("Set COSING_SEARCH_API_KEY environment variable (do not hardcode credentials).")
    try:
        import requests
    except ImportError:
        ap.error("Install requests: python -m pip install requests")

    variants = ("current_text_field", "terms_inci_exact", "terms_inci")
    rows = []
    sess = requests.Session()
    for name in args.names:
        for variant in variants:
            item = {"input_inci": name, "query_variant": variant, "http_status": "", "total_candidates": "", "first_page_count": "", "first_page_exact_matches": "", "exact_substance_ids_first_page": "", "error": ""}
            try:
                # Never print response.url: the search key is included in query params.
                response = sess.post(
                    ENDPOINT,
                    params={"apiKey": key, "text": "*", "pageSize": 10, "pageNumber": 1},
                    files={"query": ("blob", json.dumps(query_for(name, variant)), "application/json")},
                    headers={"Accept": "application/json"},
                    timeout=25,
                )
                item["http_status"] = response.status_code
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    item["total_candidates"] = data.get("totalResults", "")
                    item["first_page_count"] = len(results)
                    exact_ids = set()
                    n_exact = 0
                    for hit in results:
                        md = hit.get("metadata", {})
                        if "GROWTH_COSING" not in md.get("esST_DATASOURCE", []):
                            continue
                        if any(norm(n) == norm(name) for n in md.get("inciName", [])):
                            n_exact += 1
                            exact_ids.update(str(x) for x in md.get("substanceId", []))
                    item["first_page_exact_matches"] = n_exact
                    item["exact_substance_ids_first_page"] = "|".join(sorted(exact_ids))
                else:
                    item["error"] = f"HTTP_{response.status_code}"
            except (ValueError, KeyError):
                item["error"] = "malformed_json_or_response"
            except Exception as err:
                # Exception messages may contain a URL with credentials, never print them.
                item["error"] = type(err).__name__
            rows.append(item)
            print(f"{name} / {variant}: HTTP {item['http_status']}, total={item['total_candidates']}, exact_first_page={item['first_page_exact_matches']}, error={item['error']}")
            if str(item["http_status"]) in {"401", "403", "429"}:
                print("Access denied/rate limit. Stopping; no automated retries.")
                break
            time.sleep(max(0, args.delay))
        else:
            continue
        break

    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("Saved:", args.output)


if __name__ == "__main__":
    main()
