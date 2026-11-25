FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV YOLO_CONFIG_DIR=/tmp/ultralytics YOLO_AUTOINSTALL=false
WORKDIR /app
# OpenCV(ultralytics 의존성)에 필요한 시스템 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0
# CPU 전용 PyTorch를 먼저 설치해 GPU 패키지(수 GB)를 받지 않습니다.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -m -u 1000 appuser && mkdir data && chown appuser data
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
