FROM python:3.11-slim

WORKDIR /app

COPY services/training_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services /app/services

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "services.training_agent.main:app", "--host", "0.0.0.0", "--port", "9000"]
