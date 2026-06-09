-- 012_app_settings.sql
-- Key/value store for runtime-editable application settings (source of truth,
-- overlaid onto the config singleton at startup and on every save).
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);
