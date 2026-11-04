"""수동 테스트: 폴더의 이미지를 N장(기본 4)씩 한 화면에 격자로 보여줌.
python manual_test.py --source test_images --weights runs/train/yolov8n_custom/weights/best.pt
키: 아무 키/스페이스=다음, b=이전, s=현재 화면 저장, q/ESC=종료"""
import argparse, math
from pathlib import Path
import cv2, numpy as np
from ultralytics import YOLO

p = argparse.ArgumentParser()
p.add_argument("--source", required=True, help="이미지 폴더 또는 파일")
p.add_argument("--weights", default="runs/train/yolov8n_custom/weights/best.pt")
p.add_argument("--n", type=int, default=4, help="한 화면에 보여줄 장수")
p.add_argument("--conf", type=float, default=0.25)
p.add_argument("--cell", type=int, default=640, help="칸 하나의 최대 크기(px)")
a = p.parse_args()

src = Path(a.source)
exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
files = [src] if src.is_file() else sorted(f for f in src.rglob("*") if f.suffix.lower() in exts)
if not files:
    raise SystemExit(f"이미지 없음: {src}")

model = YOLO(a.weights)
cols = math.ceil(math.sqrt(a.n)); rows = math.ceil(a.n / cols)

def cell(f):
    img = model.predict(str(f), conf=a.conf, verbose=False)[0].plot()  # 박스+라벨 그려진 BGR
    h, w = img.shape[:2]; s = a.cell / max(h, w)
    img = cv2.resize(img, (int(w * s), int(h * s)))
    canvas = np.zeros((a.cell, a.cell, 3), np.uint8)       # 정사각 칸에 레터박스
    canvas[:img.shape[0], :img.shape[1]] = img
    cv2.putText(canvas, f.name, (8, a.cell - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    return canvas

page, pages = 0, math.ceil(len(files) / a.n)
while True:
    chunk = files[page * a.n:(page + 1) * a.n]
    cells = [cell(f) for f in chunk] + [np.zeros((a.cell, a.cell, 3), np.uint8)] * (a.n - len(chunk))
    grid = np.vstack([np.hstack(cells[r * cols:(r + 1) * cols]) for r in range(rows)])
    win = f"{page + 1}/{pages}  [space=next b=prev s=save q=quit]"
    cv2.imshow("manual_test", cv2.resize(grid, None, fx=0.5, fy=0.5) if grid.shape[1] > 1600 else grid)
    cv2.setWindowTitle("manual_test", win)
    k = cv2.waitKey(0) & 0xFF
    if k in (ord("q"), 27): break
    if k == ord("s"): cv2.imwrite(f"manual_{page + 1}.jpg", grid); print("저장: manual_%d.jpg" % (page + 1)); continue
    page = max(page - 1, 0) if k == ord("b") else (page + 1) % pages
cv2.destroyAllWindows()
