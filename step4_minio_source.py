import os
from io import BytesIO
from typing import List

from dotenv import load_dotenv
from minio import Minio
from minio.commonconfig import CopySource

load_dotenv()


def get_client() -> Minio:
    return Minio(
        endpoint=os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )


def list_incoming_pdfs(client: Minio, bucket: str, prefix: str = "incoming/") -> List[str]:
    objects = client.list_objects(bucket, prefix=prefix, recursive=True)
    return [obj.object_name for obj in objects if obj.object_name.endswith(".pdf")]


def download_pdf(client: Minio, bucket: str, key: str) -> BytesIO:
    response = client.get_object(bucket, key)
    data = response.read()
    response.close()
    response.release_conn()
    return BytesIO(data)


def move_to_processed(client: Minio, bucket: str, key: str) -> str:
    new_key = key.replace("incoming/", "processed/", 1)
    client.copy_object(bucket, new_key, CopySource(bucket, key))
    client.remove_object(bucket, key)
    return new_key
