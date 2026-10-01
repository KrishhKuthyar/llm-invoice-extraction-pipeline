CREATE DATABASE invoice_db;

\c invoice_db

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) UNIQUE NOT NULL,
    restaurant VARCHAR(255),
    order_datetime TIMESTAMP,
    items JSONB,
    subtotal NUMERIC(10,2),
    delivery_fee NUMERIC(10,2),
    service_fee NUMERIC(10,2),
    discount NUMERIC(10,2),
    tip NUMERIC(10,2),
    total NUMERIC(10,2),
    payment_method VARCHAR(100),
    delivery_address TEXT,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
