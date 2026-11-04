"""성능 테스트: python evaluate.py --weights runs/train/yolov8n_custom/weights/best.pt [--split test]
mAP/Precision/Recall, 클래스별 AP, 추론 속도(FPS) 출력."""
import argparse, time, glob
from pathlib import Path
from ultralytics import YOLO

p = argparse.ArgumentParser()
p.add_argument("--weights", default="runs/train/yolov8n_custom/weights/best.pt")
p.add_argument("--data", default="data.yaml")
p.add_argument("--split", default="val")  # val | test
p.add_argument("--imgsz", type=int, default=640)
p.add_argument("--device", default="0")
p.add_argument("--conf", type=float, default=0.001)  # mAP 측정은 낮은 conf가 표준
a = p.parse_args()

if __name__ == '__main__':  # Windows 멀티프로세싱 필수
    model = YOLO(a.weights)
    m = model.val(data=a.data, split=a.split, imgsz=a.imgsz, device=a.device, conf=a.conf, plots=True)

    print(f"\n=== {a.split} 결과 ===")
    print(f"Precision {m.box.mp:.3f} | Recall {m.box.mr:.3f} | mAP50 {m.box.map50:.3f} | mAP50-95 {m.box.map:.3f}")
    for i, ap in zip(m.box.ap_class_index, m.box.ap):
        print(f"  {m.names[i]:<20} AP50-95 {ap:.3f}")
    sp = m.speed  # ms/이미지
    print(f"속도(ms/img): 전처리 {sp['preprocess']:.1f} | 추론 {sp['inference']:.1f} | 후처리 {sp['postprocess']:.1f}"
          f" → 약 {1000 / sum(sp.values()):.0f} FPS")
    print("그래프(PR곡선, 혼동행렬)는", m.save_dir, "에 저장됨")
