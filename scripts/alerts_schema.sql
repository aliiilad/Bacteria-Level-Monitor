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
