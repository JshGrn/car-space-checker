FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY car_space_checker /app/car_space_checker
COPY run.sh /app/run.sh
ENV PYTHONPATH=/app
CMD ["sh", "/app/run.sh"]
