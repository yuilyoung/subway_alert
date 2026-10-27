CREATE SCHEMA IF NOT EXISTS app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC;
CREATE TABLE app_private.lines (
 id varchar(20) PRIMARY KEY, name text NOT NULL, topis_name text NOT NULL,
 up_label text NOT NULL, down_label text NOT NULL, demo boolean NOT NULL DEFAULT false
);
CREATE TABLE app_private.subway_stations (
 id varchar(80) PRIMARY KEY, line_id varchar(20) NOT NULL REFERENCES app_private.lines(id),
 topis_id varchar(40) NOT NULL, name text NOT NULL,
 latitude double precision CHECK (latitude BETWEEN -90 AND 90),
 longitude double precision CHECK (longitude BETWEEN -180 AND 180),
 source text NOT NULL, source_url text, verified_at timestamptz NOT NULL,
 UNIQUE(line_id, topis_id), UNIQUE(line_id, id),
 CHECK ((latitude IS NULL) = (longitude IS NULL))
);
CREATE TABLE app_private.station_edges (
 line_id varchar(20) NOT NULL, direction char(1) NOT NULL CHECK(direction IN ('0','1')),
 from_id varchar(80) NOT NULL, to_id varchar(80) NOT NULL,
 PRIMARY KEY(line_id,direction,from_id,to_id), CHECK(from_id <> to_id),
 FOREIGN KEY(line_id,from_id) REFERENCES app_private.subway_stations(line_id,id),
 FOREIGN KEY(line_id,to_id) REFERENCES app_private.subway_stations(line_id,id)
);
CREATE TABLE app_private.station_facilities (
 id uuid PRIMARY KEY, station_id varchar(80) NOT NULL REFERENCES app_private.subway_stations(id),
 kind varchar(20) NOT NULL CHECK(kind IN ('TRANSFER','TOILET','AMENITY','GATE','EXIT')),
 title text NOT NULL, location text NOT NULL, gate_side text, direction text, transfer_line text, car_door text,
 source_url text NOT NULL, verified_at timestamptz NOT NULL
);
CREATE TABLE app_private.tracking_sessions (
 id uuid PRIMARY KEY, owner_uid varchar(128) NOT NULL, idempotency_key varchar(128) NOT NULL,
 request_hash varchar(64) NOT NULL, line_id varchar(20) NOT NULL REFERENCES app_private.lines(id),
 direction char(1) NOT NULL CHECK(direction IN ('0','1')), route jsonb NOT NULL,
 fcm_token varchar(4096) NOT NULL, train_no varchar(100),
 status varchar(30) NOT NULL CHECK(status IN ('WAITING_BOARDING','TRACKING','ALERT_PENDING','ALERTED','CANCELLED','EXPIRED','FAILED')),
 last_index integer NOT NULL DEFAULT 0 CHECK(last_index>=0), last_seen timestamptz, last_reason varchar(100),
 created_at timestamptz NOT NULL, boarded_at timestamptz, expires_at timestamptz NOT NULL, alerted_at timestamptz,
 UNIQUE(owner_uid,idempotency_key), CHECK(jsonb_typeof(route)='array' AND jsonb_array_length(route)>=2)
);
CREATE UNIQUE INDEX one_active_session_per_owner ON app_private.tracking_sessions(owner_uid)
 WHERE status IN ('WAITING_BOARDING','TRACKING','ALERT_PENDING');
CREATE INDEX active_lines ON app_private.tracking_sessions(line_id,status,expires_at);
CREATE TABLE app_private.alert_outbox (
 id uuid PRIMARY KEY, session_id uuid NOT NULL UNIQUE REFERENCES app_private.tracking_sessions(id) ON DELETE CASCADE,
 payload jsonb NOT NULL, state varchar(20) NOT NULL CHECK(state IN ('PENDING','SENDING','SENT','FAILED','CANCELLED','EXPIRED')),
 attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL, lease_until timestamptz,
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL, sent_at timestamptz, result_code varchar(100)
);
CREATE INDEX outbox_due ON app_private.alert_outbox(state,next_attempt_at);
-- Server-only data: never expose these tables to Supabase's client Data API.
ALTER TABLE app_private.lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.subway_stations ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.station_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.station_facilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.tracking_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.alert_outbox ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
 IF EXISTS(SELECT FROM pg_roles WHERE rolname='anon') THEN
  REVOKE ALL ON SCHEMA app_private FROM anon;
  REVOKE ALL ON ALL TABLES IN SCHEMA app_private FROM anon;
 END IF;
 IF EXISTS(SELECT FROM pg_roles WHERE rolname='authenticated') THEN
  REVOKE ALL ON SCHEMA app_private FROM authenticated;
  REVOKE ALL ON ALL TABLES IN SCHEMA app_private FROM authenticated;
 END IF;
END $$;
