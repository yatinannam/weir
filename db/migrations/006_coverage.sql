-- D79: the answer coverage check's result, and why a small answer was escalated.
alter table weir.request_log
  add column coverage_passed boolean,
  add column coverage_reason text,
  add column escalated_for text;
