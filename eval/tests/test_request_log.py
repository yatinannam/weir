from weir_eval.request_log import attach


def test_attach_maps_log_rows_to_question_ids_and_reports_missing():
    results = [{"id": "q-1", "status_code": 200, "meta": {"request_id": "r1"}},
               {"id": "q-2", "status_code": 200, "meta": {"request_id": "r2"}},
               {"id": "q-3", "status_code": 503}]
    log_rows = [{"request_id": "r1", "model": "s", "route_reason": "router_disabled", "grounding_passed": True,
                 "grounding_reason": None, "grounding_overlap": 0.9}]
    rows, missing = attach(results, log_rows)
    assert rows == [{"id": "q-1", **log_rows[0]}] and missing == ["q-2"]
