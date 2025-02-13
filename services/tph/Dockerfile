FROM python:3.6-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY main.py /app/
CMD ["python3", "main.py"]