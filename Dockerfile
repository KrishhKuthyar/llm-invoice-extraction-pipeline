FROM apache/airflow:2.9.3-python3.9

COPY requirements-docker.txt /requirements-docker.txt
RUN pip install --no-cache-dir -r /requirements-docker.txt
