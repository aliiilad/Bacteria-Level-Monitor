-- Email-alert subscribers. Run once in Supabase: SQL Editor -> New query -> paste -> Run.
-- Stores only what alerts need: an email, a beach, a level, and a random token used for the
-- confirm and unsubscribe links. No names or anything else.
create table if not exists public.subscribers (
  id         bigint generated always as identity primary key,
  email      text    not null,
  site_id    text    not null,                      -- beach, same ids as data/processed/beaches.csv
  level      numeric(3,2) not null check (level in (0.30, 0.60)),  -- email at 30%+ or 60%+
  token      text    not null unique,               -- confirm + unsubscribe links
  confirmed  boolean not null default false,        -- no alerts until the email link is clicked
  alerted    boolean not null default false,        -- true while the beach is over the level
  created_at timestamptz not null default now(),
  unique (email, site_id)
);

-- Row-level security on with no policies: the public (anon) key can't read or write the table.
-- Only the service key, kept in Streamlit and GitHub secrets, can.
alter table public.subscribers enable row level security;

-- Table access for the Data API. Only the server-side service key may use the table; the public
-- (anon) and signed-in (authenticated) roles get nothing, even if new tables are auto-exposed.
revoke all on public.subscribers from anon, authenticated;
grant select, insert, update, delete on public.subscribers to service_role;
grant usage, select on sequence public.subscribers_id_seq to service_role;
