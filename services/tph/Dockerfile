FROM python:3.12-slim

ENV PYTHONPATH=$PYTHONPATH:/app

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . /app/
CMD ["python3", "main.py"]