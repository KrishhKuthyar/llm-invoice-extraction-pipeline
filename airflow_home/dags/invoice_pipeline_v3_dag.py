import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from airflow.decorators import dag, task
from airflow_ai_sdk.models.base import BaseModel
from dotenv import load_dotenv
from pydantic_ai.models.groq import GroqModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")


class InvoiceItem(BaseModel):
    name: str
    quantity: int
    unit_price: float
    total_price: float


class InvoiceData(BaseModel):
    order_id: str
    restaurant: str
    datetime: str
    items: List[InvoiceItem]
    subtotal: float
    delivery_fee: float
    service_fee: float
    discount: float
    tip: float
    total: float
    payment_method: str
    delivery_address: str


@dag(
    dag_id="invoice_extraction_pipeline_v3",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["invoices", "minio", "llm", "postgres", "ai-sdk"],
)
def invoice_extraction_pipeline_v3():

    @task()
    def list_pending_invoices() -> List[str]:
        from step4_minio_source import get_client, list_incoming_pdfs

        client = get_client()
        return list_incoming_pdfs(client, os.environ["MINIO_BUCKET"])

    @task()
    def download_and_extract_text(key: str) -> str:
        from step1_extract_text import extract_text
        from step4_minio_source import download_pdf, get_client

        client = get_client()
        pdf_stream = download_pdf(client, os.environ["MINIO_BUCKET"], key)
        return extract_text(pdf_stream)

    @task.llm(
        model=GroqModel(os.environ["GROQ_MODEL"]),
        system_prompt=(
            "You are an expert at extracting structured data from UberEats "
            "invoices. Extract all information matching the InvoiceData schema. "
            "Be precise with monetary values and dates; all amounts must be "
            "numbers, not strings.\n\n"
            "Field guidance:\n"
            '- order_id: the order number shown near the top (e.g. "Pedido #1234" '
            "-> \"1234\"). Do NOT use any UUID, tracking ID, or transaction ID "
            "found elsewhere in the invoice.\n"
            "- restaurant: the restaurant's name.\n"
            "- datetime: the order date/time as shown on the invoice.\n"
            "- items: every ordered item, with its name, quantity, unit price, "
            "and total price.\n"
            "- subtotal, delivery_fee, service_fee, discount, tip, total: the "
            "matching monetary line items from the payment summary.\n"
            "- payment_method: how the order was paid (card type/last digits, "
            "PIX, etc).\n"
            "- delivery_address: the customer's delivery address, not the "
            "restaurant's address."
        ),
        result_type=InvoiceData,
    )
    def extract_invoice_with_ai_sdk(invoice_text: str) -> str:
        return invoice_text

    @task()
    def store_and_move(key: str, invoice_data: dict) -> dict:
        from step3_store_postgres import store_invoice
        from step4_minio_source import get_client, move_to_processed

        invoice_id = store_invoice(invoice_data)
        client = get_client()
        new_key = move_to_processed(client, os.environ["MINIO_BUCKET"], key)
        return {"invoice_id": invoice_id, "file_key": key, "moved_to": new_key}

    pending_keys = list_pending_invoices()
    texts = download_and_extract_text.expand(key=pending_keys)
    extracted = extract_invoice_with_ai_sdk.expand(invoice_text=texts)
    store_and_move.expand(key=pending_keys, invoice_data=extracted)


invoice_extraction_pipeline_v3()
