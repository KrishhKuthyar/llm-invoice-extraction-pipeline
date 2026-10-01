import json
import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])

INVOICE_SCHEMA = {
    "order_id": "string",
    "restaurant": "string",
    "datetime": "ISO datetime string",
    "items": [{"name": "string", "quantity": 1, "unit_price": 0.0, "total_price": 0.0}],
    "subtotal": 0.0,
    "delivery_fee": 0.0,
    "service_fee": 0.0,
    "discount": 0.0,
    "tip": 0.0,
    "total": 0.0,
    "payment_method": "string",
    "delivery_address": "string",
}

SYSTEM_PROMPT = (
    "You are an invoice extraction assistant. Extract structured data from "
    "food delivery invoices and return valid JSON only. All monetary values "
    "must be numbers, not strings."
)

def build_user_prompt(invoice_text: str) -> str:
    return (
        f"Extract data from this invoice:\n\n{invoice_text}\n\n"
        f"Return JSON matching this shape:\n{json.dumps(INVOICE_SCHEMA)}"
    )

def extract_invoice_data(invoice_text: str) -> dict:
    response = client.chat.completions.create(
        model=os.environ["GROQ_MODEL"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(invoice_text)},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)

def coerce_types(invoice_data: dict) -> dict:
    numeric_fields = ["subtotal", "delivery_fee", "service_fee", "discount", "tip", "total"]
    for field in numeric_fields:
        if field in invoice_data:
            invoice_data[field] = float(invoice_data[field])

    for item in invoice_data.get("items", []):
        item["quantity"] = int(item.get("quantity", 1))
        item["unit_price"] = float(item.get("unit_price", 0))
        item["total_price"] = float(item.get("total_price", 0))

    return invoice_data

if __name__ == "__main__":
    from step1_extract_text import extract_text
    from step3_store_postgres import store_invoice
    from step4_minio_source import get_client, list_incoming_pdfs, download_pdf, move_to_processed

    BUCKET = os.environ["MINIO_BUCKET"]

    minio_client = get_client()
    pending_keys = list_incoming_pdfs(minio_client, BUCKET)
    print(f"Found {len(pending_keys)} pending invoice(s) in incoming/: {pending_keys}")

    key = pending_keys[0]
    pdf_stream = download_pdf(minio_client, BUCKET, key)

    invoice_text = extract_text(pdf_stream)
    raw_result = extract_invoice_data(invoice_text)
    result = coerce_types(raw_result)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    invoice_id = store_invoice(result)
    print(f"Stored as invoices.id = {invoice_id}")

    new_key = move_to_processed(minio_client, BUCKET, key)
    print(f"Moved {key} -> {new_key}")
