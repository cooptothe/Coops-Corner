-- Personal recordkeeping only. Does not create or submit sportsbook wagers.
BEGIN;
CREATE SCHEMA corner_app;
REVOKE ALL ON SCHEMA corner_app FROM PUBLIC;
CREATE TABLE corner_app.users (
 id uuid PRIMARY KEY,
 username text NOT NULL UNIQUE CHECK(username ~ '^[a-z0-9_]{3,40}$'),
 password_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE corner_app.sessions (
 token_hash text PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES corner_app.users(id),
 csrf_token text NOT NULL,
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ON corner_app.sessions(user_id);
CREATE TABLE corner_app.auth_limits (
 bucket text PRIMARY KEY,
 window_start timestamptz NOT NULL,
 attempts integer NOT NULL CHECK(attempts>0)
);
CREATE TABLE corner_app.cash_entries (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES corner_app.users(id),
 request_key uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('deposit','withdrawal')),
 amount numeric(16,2) NOT NULL CHECK(amount>0 AND amount<=100000000),
 note text NOT NULL CHECK(length(note)<=300),
 occurred_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(user_id,request_key)
);
CREATE TABLE corner_app.settled_records (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES corner_app.users(id),
 request_key uuid NOT NULL,
 description text NOT NULL CHECK(length(btrim(description)) BETWEEN 1 AND 300),
 sportsbook text NOT NULL CHECK(length(btrim(sportsbook)) BETWEEN 1 AND 100),
 stake numeric(16,2) NOT NULL CHECK(stake>0 AND stake<=100000000),
 returned numeric(16,2) NOT NULL CHECK(returned>=0 AND returned<=100000000),
 decimal_odds numeric(18,8) NOT NULL CHECK(decimal_odds>1 AND decimal_odds<=1000000),
 placed_at timestamptz NOT NULL,
 settled_at timestamptz NOT NULL CHECK(settled_at>=placed_at),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(user_id,request_key)
);
CREATE INDEX ON corner_app.settled_records(user_id,settled_at DESC,id);
CREATE INDEX ON corner_app.cash_entries(user_id,occurred_at DESC,id);
REVOKE ALL ON ALL TABLES IN SCHEMA corner_app FROM PUBLIC;
COMMIT;
