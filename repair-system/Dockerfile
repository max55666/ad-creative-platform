# Reuses the user's existing Render Docker service and persistent disk.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Taipei
WORKDIR /app
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py line_support.py cloud_support.py production.py cloud_start.py cloud_bootstrap.py database_tools.py ./
COPY index.html line-client.js settings.json ./
COPY assets/return-items.png ./assets/return-items.png
EXPOSE 10000
CMD ["python", "cloud_start.py"]
