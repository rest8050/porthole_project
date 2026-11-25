"""Send sample pothole observations to POST /api/events (test data only).

Usage: python tools/send_sample.py [--url http://localhost:8000] [--count 8]
Requires Pillow. Also checks that resending an event_id is not stored twice.
"""
import argparse
import io
import json
import random
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8000")
parser.add_argument("--count", type=int, default=6, help="number of potholes")
args = parser.parse_args()


def make_jpeg(box):
    image = Image.new("RGB", (640, 480), (105, 105, 105))
    draw = ImageDraw.Draw(image)
    draw.ellipse(box, fill=(35, 35, 35))
    draw.text((10, 10), "SAMPLE", fill=(255, 255, 0))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def send(fields, jpeg):
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="{name}"\r\n\r\n{value}\r\n').encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             'name="image"; filename="sample.jpg"\r\n'
             "Content-Type: image/jpeg\r\n\r\n").encode()
    body += jpeg + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{args.url}/api/events", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


total = 0
for index in range(args.count):
    pothole_id = f"sample-{uuid.uuid4()}"
    lat = round(37.5665 + random.uniform(-0.01, 0.01), 6)
    lon = round(126.9780 + random.uniform(-0.01, 0.01), 6)
    seen = datetime.now(timezone.utc) - timedelta(hours=7 * index)
    x, y = random.randint(40, 300), random.randint(80, 250)
    shots = 2 + index % 3  # several images per pothole
    for shot in range(shots):
        left, top = x + 25 * shot, y + 15 * shot
        box = [left, top, left + 100 + 20 * shot, top + 60 + 10 * shot]
        fields = {
            "pothole_id": pothole_id,
            "event_id": f"sample-{uuid.uuid4()}",
            "captured_at": (seen + timedelta(milliseconds=300 * shot)).isoformat(),
            "detections": json.dumps(
                [{"confidence": round(random.uniform(0.3, 0.98), 3), "box": box}]
            ),
        }
        if index % 4 != 3:  # leave some potholes without GPS
            fields["lat"], fields["lon"] = lat, lon
        jpeg = make_jpeg(box)
        first = send(fields, jpeg)
        again = send(fields, jpeg)
        assert not first["duplicate"] and again == {"id": first["id"], "duplicate": True}, (first, again)
        total += 1
    with urllib.request.urlopen(f"{args.url}/api/potholes/{pothole_id}", timeout=10) as response:
        stored = json.load(response)
    assert stored["observation_count"] == shots, stored
    assert stored["max_confidence"] == max(o["max_confidence"] for o in stored["observations"])

print(f"OK: {args.count} potholes, {total} observations, duplicates ignored")
