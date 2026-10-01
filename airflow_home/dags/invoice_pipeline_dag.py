import sys
from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


@dag(
    dag_id="invoice_extraction_pipeline",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["invoices", "minio", "llm", "postgres"],
)
def invoice_extraction_pipeline():

    @task()
    def list_pending_invoices() -> list[str]:
        import os

        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")

        from step4_minio_source import get_client, list_incoming_pdfs

        client = get_client()
        return list_incoming_pdfs(client, os.environ["MINIO_BUCKET"])

    @task()
    def process_invoice(key: str) -> dict:
        import logging
        import os

        from dotenv import load_dotenv

        log = logging.getLogger("airflow.task")
        load_dotenv(PROJECT_ROOT / ".env")

        from step1_extract_text import extract_text
        from step2_llm_extract import coerce_types, extract_invoice_data
        from step3_store_postgres import store_invoice
        from step4_minio_source import download_pdf, get_client, move_to_processed

        client = get_client()
        bucket = os.environ["MINIO_BUCKET"]

        log.info("STEP: downloading %s", key)
        pdf_stream = download_pdf(client, bucket, key)

        log.info("STEP: extracting text")
        invoice_text = extract_text(pdf_stream)

        log.info("STEP: calling LLM")
        raw_result = extract_invoice_data(invoice_text)

        log.info("STEP: coercing types")
        result = coerce_types(raw_result)

        log.info("STEP: storing in postgres")
        invoice_id = store_invoice(result)

        log.info("STEP: moving to processed")
        new_key = move_to_processed(client, bucket, key)

        log.info("STEP: done")
        return {"invoice_id": invoice_id, "file_key": key, "moved_to": new_key}

    pending_keys = list_pending_invoices()
    process_invoice.expand(key=pending_keys)


invoice_extraction_pipeline()
