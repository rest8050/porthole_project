from ultralytics import YOLO

# 사전학습된 nano 가중치로 시작 (전이학습)
model = YOLO("yolov8n.pt")

results = model.train(
    data="data.yaml",      # 데이터셋 설정 파일
    epochs=100,
    imgsz=640,
    batch=16,              # GPU 메모리 부족하면 8 또는 -1(자동)
    device=0,              # CPU만 있으면 "cpu"
    workers=4,
    patience=20,           # 20 epoch 동안 개선 없으면 조기 종료
    project="runs/train",
    name="yolov8n_custom",
    pretrained=True,
    optimizer="auto",
    lr0=0.01,
    cos_lr=True,
    amp=True,              # 혼합정밀도 학습
)

# 검증
metrics = model.val()
print("mAP50:", metrics.box.map50)
print("mAP50-95:", metrics.box.map)

# 추론 테스트
model.predict("test.jpg", save=True, conf=0.25)

# 내보내기 (필요 시)
model.export(format="onnx")   # 또는 "engine"(TensorRT), "tflite" 등