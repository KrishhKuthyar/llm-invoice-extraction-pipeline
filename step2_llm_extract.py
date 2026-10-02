import json
import os
import subprocess
import sys

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

def log_to_langfuse(name: str, model: str, prompt: str, output: str, usage_details: dict) -> None:
    payload = json.dumps({
        "name": name,
        "model": model,
        "input": prompt,
        "output": output,
        "usage_details": usage_details,
    })
    subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "log_to_langfuse.py")],
        input=payload,
        text=True,
        timeout=15,
    )

def build_batch_user_prompt(invoice_texts: list) -> str:
    invoices_block = "\n\n".join(
        f"=== Invoice {i + 1} ===\n{text}" for i, text in enumerate(invoice_texts)
    )
    return (
        f"Extract data from these {len(invoice_texts)} invoices:\n\n{invoices_block}\n\n"
        f'Return a JSON object: {{"invoices": [...]}} where the array has exactly '
        f"{len(invoice_texts)} objects, one per invoice in the same order, each matching: "
        f"{json.dumps(INVOICE_SCHEMA)}"
    )

def extract_invoice_batch_data(invoice_texts: list) -> list:
    model = os.environ["GROQ_MODEL"]
    user_prompt = build_batch_user_prompt(invoice_texts)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=1200 * len(invoice_texts),
        response_format={"type": "json_object"},
    )
    output_text = response.choices[0].message.content
    log_to_langfuse(
        name="extract_invoice_batch_data",
        model=model,
        prompt=user_prompt,
        output=output_text,
        usage_details={
            "input": response.usage.prompt_tokens,
            "output": response.usage.completion_tokens,
        },
    )
    results = json.loads(output_text)["invoices"]
    if len(results) != len(invoice_texts):
        raise ValueError(f"Expected {len(invoice_texts)} results, got {len(results)}")
    return results

def extract_invoice_data(invoice_text: str) -> dict:
    model = os.environ["GROQ_MODEL"]
    user_prompt = build_user_prompt(invoice_text)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    output_text = response.choices[0].message.content
    log_to_langfuse(
        name="extract_invoice_data",
        model=model,
        prompt=user_prompt,
        output=output_text,
        usage_details={
            "input": response.usage.prompt_tokens,
            "output": response.usage.completion_tokens,
        },
    )
    return json.loads(output_text)

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

    invoice_texts = [
        extract_text(download_pdf(minio_client, BUCKET, key)) for key in pending_keys
    ]

    raw_results = extract_invoice_batch_data(invoice_texts)
    print(f"Got {len(raw_results)} results back from 1 LLM call")

    for key, raw_result in zip(pending_keys, raw_results):
        result = coerce_types(raw_result)
        invoice_id = store_invoice(result)
        new_key = move_to_processed(minio_client, BUCKET, key)
        print(f"  {key}: stored as id={invoice_id}, moved -> {new_key}")
