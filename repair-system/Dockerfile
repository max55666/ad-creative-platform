# Reuses the user's existing Render Docker service and persistent disk.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Taipei
WORKDIR /app
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py line_support.py cloud_support.py dispatch_cards.py dispatch_workflow.py production.py cloud_start.py cloud_bootstrap.py database_tools.py ./
COPY test_case_cleanup.py ./
COPY production_payments.py production_payment_sender.py production_payment_sheet.py service_desk.py service_desk_reconciliation.py payment_sheet_sync.py payment_sheet_transport.py shopline_orders.py shopline_readonly.py order_matching.py line_test_sender.py ./
COPY index.html line-client.js settings.json ./
COPY payments.html ./
COPY assets/return-items.png ./assets/return-items.png
EXPOSE 10000
CMD ["python", "cloud_start.py"]
