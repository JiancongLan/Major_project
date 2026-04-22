FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV HOUSEHOLD_ID=MAC000022
ENV PARAMS_FILE=household_params.csv

CMD ["python", "main.py"]