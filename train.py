"""학습: python train.py [--model yolov8n.pt] [--epochs 100] [--device 0]"""
import argparse
from ultralytics import YOLO

p = argparse.ArgumentParser()
p.add_argument("--data", default="data.yaml")
p.add_argument("--model", default="yolov8n.pt")  # 이어서 학습하려면 runs/.../last.pt + --resume
p.add_argument("--epochs", type=int, default=100)
p.add_argument("--imgsz", type=int, default=640)
p.add_argument("--batch", type=int, default=16)  # OOM이면 8, 자동은 -1
p.add_argument("--device", default="0")          # CPU면 "cpu"
p.add_argument("--workers", type=int, default=4)
p.add_argument("--name", default="yolov8n_custom")
p.add_argument("--resume", action="store_true")
if __name__ == '__main__':  # Windows 멀티프로세싱 필수
    a = p.parse_args()

    model = YOLO(a.model)
    if a.resume:
        model.train(resume=True)
    else:
        model.train(data=a.data, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch,
                    device=a.device, workers=a.workers, patience=20,
                    project="runs/train", name=a.name, cos_lr=True, amp=True)
    print("best:", model.trainer.best)
