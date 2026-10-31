FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx solders

COPY app.py .

EXPOSE 8080

CMD ["python", "app.py"]
