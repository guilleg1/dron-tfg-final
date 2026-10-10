-- Esquema Postgres para Supabase. La aplicación crea estas tablas sola al
-- arrancar (SQLAlchemy create_all); este fichero queda como referencia y para
-- crearlas a mano desde el editor SQL de Supabase si se prefiere.

CREATE TABLE IF NOT EXISTS clients (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    address     VARCHAR(512) NOT NULL,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id                        SERIAL PRIMARY KEY,
    client_id                 INTEGER NOT NULL REFERENCES clients(id),
    weight_kg                 DOUBLE PRECISION NOT NULL,
    status                    VARCHAR(32) NOT NULL DEFAULT 'pendiente',
    assigned_profile_name     VARCHAR(255),
    assigned_route_name       VARCHAR(255),
    assigned_destination_name VARCHAR(255),
    assigned_destination_lat  DOUBLE PRECISION,
    assigned_destination_lon  DOUBLE PRECISION,
    assigned_distance_km      DOUBLE PRECISION,
    operational_state         VARCHAR(64),
    created_at                TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_client_id ON orders(client_id);
