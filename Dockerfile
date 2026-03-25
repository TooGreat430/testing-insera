FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN apt-get update && apt-get install -y \
    ghostscript \
    libreoffice \
    libreoffice-calc \
    libreoffice-writer \
    default-jre \
    fonts-dejavu \
 && ln -sf /usr/bin/libreoffice /usr/bin/soffice || true \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080
CMD ["streamlit", "run", "main.py", "--server.port=8080", "--server.address=0.0.0.0"]