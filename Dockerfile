# VİOP Algoritmik Ticaret Sistemi - 7/24 Bulut Dockerfile
FROM python:3.12-slim

# Sistem bağımlılıkları ve UTF-8 yerelleştirmesi
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# Paket yöneticisi güncellemeleri ve derleme araçları
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Bağımlılıkları kopyala ve yükle
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Proje kaynak kodlarını kopyala
COPY . /app/

# Streamlit portu (8501)
EXPOSE 8501

# Varsayılan çalıştırma komutu (Hem arka plan canlı motor hem de Dashboard çalıştırılabilir)
CMD ["streamlit", "run", "src/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
