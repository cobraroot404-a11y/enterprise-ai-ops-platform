"""Identity-table hardening: row-level security and least privilege for `users` and `tenants`.

Revision ID: 0004

Findings that motivated this migration (see docs/security/identity-tables.md):
  * The API role could SELECT every user (emails, password hashes) and tenant, and UPDATE any of them,
    including `is_platform_admin`, if an application bug or injection ever reached those tables.

Model after this migration (the API role is NOT a table owner, so RLS always applies to it):
  * users:   readable only for the caller's own row and for members of the current tenant context.
  * tenants: readable only for the current tenant, the caller's own tenants, or by a platform admin.
  * The API role has SELECT only on both tables. INSERT/UPDATE/DELETE are revoked; the only writes are
    through narrow SECURITY DEFINER functions that re-check the caller's authority inside the database:
      - auth_find_user(email)         exact-match credential lookup for sign-in (no enumeration by scan)
      - app_create_tenant(slug,name)  platform admins only
      - app_provision_user(...)       tenant admins of the current tenant or platform admins; can never
                                      create a platform admin
  * Platform-admin actions outside any tenant are audited in audit_events rows with a NULL tenant that only
    platform admins can write or read.
RLS is ENABLEd (not FORCEd) on these two tables so the SECURITY DEFINER functions, which run as the table
owner (the migration/admin role, never used by the API), can read them; `eaop_app` cannot bypass it.
"""
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION app_is_platform_admin() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path = public, pg_temp AS
    $$ SELECT coalesce((SELECT is_platform_admin FROM users WHERE id = app_current_user()), false) $$;

    CREATE FUNCTION auth_find_user(p_email text)
      RETURNS TABLE (id uuid, email text, full_name text, password_hash text, is_platform_admin boolean)
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
    $$ SELECT u.id, u.email, u.full_name, u.password_hash, u.is_platform_admin
       FROM users u WHERE u.email = lower(p_email) $$;

    CREATE FUNCTION app_create_tenant(p_slug text, p_name text) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
      SET search_path = public, pg_temp AS
    $$ DECLARE v_id uuid;
    BEGIN
      IF NOT app_is_platform_admin() THEN
        RAISE EXCEPTION 'platform administrator required' USING ERRCODE = '42501';
      END IF;
      INSERT INTO tenants (slug, name) VALUES (p_slug, p_name) RETURNING id INTO v_id;
      RETURN v_id;
    END $$;

    CREATE FUNCTION app_provision_user(p_email text, p_full_name text, p_password_hash text)
      RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
    $$ DECLARE v_actor uuid := app_current_user(); v_tenant uuid := app_current_tenant(); v_id uuid;
    BEGIN
      IF v_actor IS NULL OR v_tenant IS NULL THEN
        RAISE EXCEPTION 'tenant and user context required' USING ERRCODE = '42501';
      END IF;
      IF NOT (app_is_platform_admin() OR EXISTS (
              SELECT 1 FROM memberships WHERE tenant_id = v_tenant AND user_id = v_actor
                AND role = 'tenant_admin')) THEN
        RAISE EXCEPTION 'not allowed to provision users' USING ERRCODE = '42501';
      END IF;
      SELECT id INTO v_id FROM users WHERE email = lower(p_email);
      IF v_id IS NULL THEN
        INSERT INTO users (email, full_name, password_hash)
          VALUES (lower(p_email), p_full_name, p_password_hash) RETURNING id INTO v_id;
      END IF;
      RETURN v_id;
    END $$;

    REVOKE EXECUTE ON FUNCTION app_is_platform_admin(), auth_find_user(text), app_create_tenant(text, text),
      app_provision_user(text, text, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_is_platform_admin(), auth_find_user(text), app_create_tenant(text, text),
      app_provision_user(text, text, text) TO eaop_app;

    REVOKE INSERT, UPDATE, DELETE ON users, tenants FROM eaop_app;
    ALTER TABLE users ENABLE ROW LEVEL SECURITY;
    ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

    CREATE POLICY users_select ON users FOR SELECT TO eaop_app
      USING (id = app_current_user()
             OR id IN (SELECT user_id FROM memberships WHERE tenant_id = app_current_tenant()));
    CREATE POLICY tenants_select ON tenants FOR SELECT TO eaop_app
      USING (id = app_current_tenant() OR app_is_platform_admin()
             OR id IN (SELECT tenant_id FROM memberships WHERE user_id = app_current_user()));

    CREATE POLICY platform_audit_insert ON audit_events FOR INSERT TO eaop_app
      WITH CHECK (tenant_id IS NULL AND action LIKE 'platform.%' AND app_is_platform_admin());
    CREATE POLICY platform_audit_select ON audit_events FOR SELECT TO eaop_app
      USING (tenant_id IS NULL AND app_is_platform_admin());
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
