FROM python:3.12-slim

ENV PYTHONPATH=$PYTHONPATH:/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"] 