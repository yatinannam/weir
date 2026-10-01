create extension if not exists vector;
create schema if not exists rag;
create schema if not exists weir;

-- hospital-rag ------------------------------------------------------------
create table rag.documents (
  id text primary key,
  namespace text not null,
  title text not null,
  path text not null,
  kb_version text not null,
  content_hash text not null,
  ingested_at timestamptz not null default now()
);

create table rag.chunks (
  id text primary key,
  doc_id text not null references rag.documents(id) on delete cascade,
  namespace text not null,
  kb_version text not null,
  chunk_index int not null,
  text text not null,
  token_count int not null,
  embedding vector(384) not null
);
create index on rag.chunks using hnsw (embedding vector_cosine_ops);
create index on rag.chunks (namespace, kb_version);

create table rag.kb_versions (
  namespace text primary key,
  kb_version text not null,
  updated_at timestamptz not null default now()
);

-- weir --------------------------------------------------------------------
create table weir.cache_entries (
  id uuid primary key,
  namespace text not null,
  kb_version text not null,
  prompt_version text not null,
  query_text text not null,
  embedding vector(384) not null,
  answer text not null,
  sources jsonb not null,
  source_ids text[] not null,
  model text not null,
  tokens_in int not null,
  tokens_out int not null,
  hit_count int not null default 0,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index on weir.cache_entries using hnsw (embedding vector_cosine_ops);
create index on weir.cache_entries (namespace, kb_version, prompt_version);
create index on weir.cache_entries using gin (source_ids);

create table weir.model_prices (
  model text not null,
  usd_per_m_input numeric not null,
  usd_per_m_output numeric not null default 0,
  effective_from date not null,
  primary key (model, effective_from)
);

create table weir.request_log (
  request_id uuid primary key,
  ts timestamptz not null,
  namespace text not null,
  cache_status text not null check (cache_status in ('hit','miss','bypass')),
  bypass_reason text,
  similarity real,
  cache_entry_id uuid,
  route text not null check (route in ('none','small','large')),
  escalated boolean not null default false,
  model_calls smallint not null default 0,
  model text,
  tokens_in int,
  tokens_out int,
  embed_tokens int,
  retrieval_top_score real,
  grounding_passed boolean,
  latency_embed_ms int,
  latency_cache_ms int,
  latency_retrieval_ms int,
  latency_llm_ms int,
  latency_total_ms int not null,
  cost_usd numeric not null default 0,
  counterfactual_cost_usd numeric not null default 0,
  status text not null check (status in ('ok','error','timeout')),
  error_detail text,
  query_hash text not null,
  query_text text,
  answer_len int,
  config_label text
);
create index on weir.request_log (ts);
create index on weir.request_log (namespace, ts);

create table weir.feedback (
  request_id uuid not null references weir.request_log(request_id),
  rating smallint not null,
  comment text,
  ts timestamptz not null default now()
);
