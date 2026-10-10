-- M31 / D75: a request shed under CPU overload is logged with status 'shed' (a quick 503, no model call).
alter table weir.request_log drop constraint request_log_status_check;
alter table weir.request_log add constraint request_log_status_check
  check (status in ('ok', 'error', 'timeout', 'shed'));
