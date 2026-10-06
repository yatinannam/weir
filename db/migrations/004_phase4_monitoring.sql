-- Phase 4 addendum §2: a read-only login for Grafana. Roles are cluster-wide, so create it only once.
-- Local-only password, like weir/weir: Postgres is bound to 127.0.0.1.
do $$
begin
  if not exists (select from pg_roles where rolname = 'weir_reader') then
    create role weir_reader login password 'weir_reader';
  end if;
end
$$;
grant usage on schema weir to weir_reader;
grant select on weir.request_log, weir.cache_entries, weir.model_prices, weir.feedback to weir_reader;
