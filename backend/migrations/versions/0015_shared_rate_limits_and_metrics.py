"""Shared (multi-process) rate limits and durable operational metrics.

Revision ID: 0015

Additive; uses only the existing PostgreSQL.

* `rate_limit_state` holds token buckets (connector and webhook limits, per-tenant request limits) and fixed-window failure counters (sign-in throttling). It is reached ONLY through
  SECURITY DEFINER functions, so no application role can read or write the table directly and a caller can only touch the key it names. Atomicity: each call locks the one bucket row
  (`SELECT ... FOR UPDATE`) and computes refill from the DATABASE clock, so any number of API and worker processes share one limit and clock skew between processes is irrelevant.
  Tenant isolation is by key construction (the application prefixes every key with the tenant id); the table holds no tenant data, only counters.
* `metric_series` holds durable additive counter series (counters, histogram buckets, sums, counts) flushed by the API and worker processes, so metrics survive restarts and span
  processes. Written through `metric_add` (monotonic: negative deltas are refused), read through `metric_read`, which returns one tenant's series plus platform-level series, or every
  series when the caller (a platform administrator, decided by the API) asks for all. No tenant data beyond a tenant id label; no direct table grants.
Downgrade drops the (ephemeral) rate-limit state but refuses while `metric_series` holds rows, so durable metrics are never lost silently.
"""
from alembic import op

revision = "0015"
down_revision = "0014"

FUNCTIONS = [
    "rate_limit_take(text, double precision, integer, double precision)",
    "rate_limit_pause(text, double precision)",
    "rate_limit_window_wait(text, integer, integer)",
    "rate_limit_window_add(text, integer)",
    "rate_limit_window_clear(text)",
    "rate_limit_sweep(integer)",
    "metric_add(text, text, jsonb, text, double precision)",
    "metric_read(text, boolean)",
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE rate_limit_state (
          bucket_key text PRIMARY KEY CHECK (length(bucket_key) BETWEEN 1 AND 300),
          tokens double precision NOT NULL DEFAULT 1,
          rate double precision NOT NULL DEFAULT 1,
          capacity double precision NOT NULL DEFAULT 1,
          refilled_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          paused_until timestamptz,
          window_started timestamptz,
          window_count integer NOT NULL DEFAULT 0,
          updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )""")
    op.execute("CREATE INDEX rate_limit_state_idle_idx ON rate_limit_state (updated_at)")
    op.execute("""
        CREATE FUNCTION rate_limit_take(p_key text, p_rate double precision, p_burst integer, p_cost double precision DEFAULT 1)
          RETURNS double precision LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE r rate_limit_state%ROWTYPE; t timestamptz; v_tokens double precision; v_wait double precision;
        BEGIN
          IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 300 OR p_rate IS NULL OR p_rate <= 0 OR p_rate > 1000
             OR p_burst IS NULL OR p_burst < 1 OR p_burst > 1000 OR p_cost IS NULL OR p_cost <= 0 OR p_cost > p_burst THEN
            RAISE EXCEPTION 'invalid rate limit arguments' USING ERRCODE = '22023';
          END IF;
          t := clock_timestamp();
          INSERT INTO rate_limit_state (bucket_key, tokens, rate, capacity, refilled_at, updated_at) VALUES (p_key, p_burst, p_rate, p_burst, t, t) ON CONFLICT (bucket_key) DO NOTHING;
          SELECT * INTO r FROM rate_limit_state WHERE bucket_key = p_key FOR UPDATE;
          t := clock_timestamp();
          v_tokens := LEAST(p_burst, r.tokens + GREATEST(0, extract(epoch FROM t - r.refilled_at)) * p_rate);
          IF r.paused_until IS NOT NULL AND r.paused_until > t THEN
            v_wait := extract(epoch FROM r.paused_until - t);
          ELSIF v_tokens >= p_cost THEN
            v_tokens := v_tokens - p_cost; v_wait := 0;
          ELSE
            v_wait := (p_cost - v_tokens) / p_rate;
          END IF;
          UPDATE rate_limit_state SET tokens = v_tokens, rate = p_rate, capacity = p_burst, refilled_at = t, updated_at = t WHERE bucket_key = p_key;
          RETURN v_wait;
        END $$""")
    op.execute("""
        CREATE FUNCTION rate_limit_pause(p_key text, p_seconds double precision)
          RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE t timestamptz := clock_timestamp(); until timestamptz;
        BEGIN
          IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 300 OR p_seconds IS NULL THEN
            RAISE EXCEPTION 'invalid rate limit arguments' USING ERRCODE = '22023';
          END IF;
          until := t + make_interval(secs => LEAST(GREATEST(p_seconds, 0), 30));
          INSERT INTO rate_limit_state (bucket_key, paused_until, refilled_at, updated_at) VALUES (p_key, until, t, t)
            ON CONFLICT (bucket_key) DO UPDATE SET paused_until = GREATEST(COALESCE(rate_limit_state.paused_until, until), until), updated_at = t;
        END $$""")
    op.execute("""
        CREATE FUNCTION rate_limit_window_wait(p_key text, p_window integer, p_max integer)
          RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE r rate_limit_state%ROWTYPE; t timestamptz := clock_timestamp();
        BEGIN
          IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 300 OR p_window NOT BETWEEN 1 AND 86400 OR p_max NOT BETWEEN 1 AND 100000 THEN
            RAISE EXCEPTION 'invalid rate limit arguments' USING ERRCODE = '22023';
          END IF;
          SELECT * INTO r FROM rate_limit_state WHERE bucket_key = p_key;
          IF NOT FOUND OR r.window_started IS NULL OR r.window_started + make_interval(secs => p_window) <= t OR r.window_count < p_max THEN
            RETURN 0;
          END IF;
          RETURN CEIL(extract(epoch FROM r.window_started + make_interval(secs => p_window) - t))::integer;
        END $$""")
    op.execute("""
        CREATE FUNCTION rate_limit_window_add(p_key text, p_window integer)
          RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE t timestamptz := clock_timestamp(); n integer;
        BEGIN
          IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 300 OR p_window NOT BETWEEN 1 AND 86400 THEN
            RAISE EXCEPTION 'invalid rate limit arguments' USING ERRCODE = '22023';
          END IF;
          INSERT INTO rate_limit_state (bucket_key, window_started, window_count, refilled_at, updated_at) VALUES (p_key, t, 1, t, t)
            ON CONFLICT (bucket_key) DO UPDATE SET
              window_count = CASE WHEN rate_limit_state.window_started IS NULL OR rate_limit_state.window_started + make_interval(secs => p_window) <= t THEN 1 ELSE rate_limit_state.window_count + 1 END,
              window_started = CASE WHEN rate_limit_state.window_started IS NULL OR rate_limit_state.window_started + make_interval(secs => p_window) <= t THEN t ELSE rate_limit_state.window_started END,
              updated_at = t
            RETURNING window_count INTO n;
          RETURN n;
        END $$""")
    op.execute("""
        CREATE FUNCTION rate_limit_window_clear(p_key text) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS
        $$ DELETE FROM rate_limit_state WHERE bucket_key = p_key $$""")
    op.execute("""
        CREATE FUNCTION rate_limit_sweep(p_idle_seconds integer DEFAULT 3600) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE n integer;
        BEGIN
          IF p_idle_seconds IS NULL OR p_idle_seconds < 60 THEN RAISE EXCEPTION 'idle period must be at least 60 seconds' USING ERRCODE = '22023'; END IF;
          WITH doomed AS (SELECT bucket_key FROM rate_limit_state WHERE updated_at < clock_timestamp() - make_interval(secs => p_idle_seconds)
                          AND (paused_until IS NULL OR paused_until < clock_timestamp()) ORDER BY updated_at LIMIT 1000 FOR UPDATE SKIP LOCKED)
          DELETE FROM rate_limit_state s USING doomed d WHERE s.bucket_key = d.bucket_key;
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END $$""")
    op.execute("""
        CREATE TABLE metric_series (
          series_key text PRIMARY KEY CHECK (series_key ~ '^[0-9a-f]{64}$'),
          name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{0,99}$'),
          labels jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (pg_column_size(labels) < 2000),
          scope_tenant text,
          value double precision NOT NULL DEFAULT 0 CHECK (value >= 0),
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX metric_series_scope_idx ON metric_series (scope_tenant, name)")
    op.execute("""
        CREATE FUNCTION metric_add(p_key text, p_name text, p_labels jsonb, p_scope text, p_delta double precision)
          RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          IF p_delta IS NULL OR p_delta < 0 THEN RAISE EXCEPTION 'metric deltas must be non-negative' USING ERRCODE = '22023'; END IF;
          INSERT INTO metric_series (series_key, name, labels, scope_tenant, value) VALUES (p_key, p_name, COALESCE(p_labels, '{}'::jsonb), p_scope, p_delta)
            ON CONFLICT (series_key) DO UPDATE SET value = metric_series.value + EXCLUDED.value, updated_at = now();
        END $$""")
    op.execute("""
        CREATE FUNCTION metric_read(p_scope text, p_all boolean DEFAULT false)
          RETURNS TABLE (name text, labels jsonb, scope_tenant text, value double precision, updated_at timestamptz)
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
        $$ SELECT m.name, m.labels, m.scope_tenant, m.value, m.updated_at FROM metric_series m
           WHERE p_all OR m.scope_tenant IS NULL OR m.scope_tenant = p_scope ORDER BY m.name, m.series_key $$""")
    for fn in FUNCTIONS:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {fn} FROM PUBLIC")
    for fn in FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO eaop_app, eaop_worker")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT count(*) FROM metric_series").scalar():
        raise RuntimeError("refusing to downgrade 0015: metric_series holds durable metrics (export or delete them deliberately first)")
    for fn in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.execute("DROP TABLE IF EXISTS metric_series")
    op.execute("DROP TABLE IF EXISTS rate_limit_state")
