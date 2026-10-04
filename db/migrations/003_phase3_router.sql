-- Phase 3 router (addendum §4). grounding_passed, escalated and model_calls already exist from 001.
alter table weir.request_log add column route_reason text;
alter table weir.request_log add column grounding_reason text;
alter table weir.request_log add column grounding_overlap real;
