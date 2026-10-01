import json

import psycopg2


def store_invoice(invoice_data: dict) -> int:
    conn = psycopg2.connect(dbname="invoice_db")

    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO invoices (
                    order_id, restaurant, order_datetime, items,
                    subtotal, delivery_fee, service_fee, discount, tip, total,
                    payment_method, delivery_address, raw_data
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (order_id) DO UPDATE SET
                    raw_data = EXCLUDED.raw_data
                RETURNING id
                """,
                (
                    invoice_data["order_id"],
                    invoice_data["restaurant"],
                    invoice_data["datetime"],
                    json.dumps(invoice_data["items"]),
                    invoice_data["subtotal"],
                    invoice_data["delivery_fee"],
                    invoice_data["service_fee"],
                    invoice_data["discount"],
                    invoice_data["tip"],
                    invoice_data["total"],
                    invoice_data["payment_method"],
                    invoice_data["delivery_address"],
                    json.dumps(invoice_data),
                ),
            )
            invoice_id = cursor.fetchone()[0]

    conn.close()
    return invoice_id
