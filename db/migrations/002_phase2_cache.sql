-- Phase 2 addendum §4. Feedback can arrive before its asynchronously written request_log row,
-- so the API checks existence itself instead of relying on a foreign key.
alter table weir.feedback drop constraint if exists feedback_request_id_fkey;
create index if not exists feedback_request_id_idx on weir.feedback (request_id);
create index if not exists cache_entries_expires_at_idx on weir.cache_entries (expires_at);
