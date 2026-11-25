"""Send Pi camera frames to POST /api/detect and print the result. (Raspberry Pi)

    python3 camera_send.py --server http://<SERVER_IP>:8000

Run drive.py in another terminal; it stops when the server stores a pothole.
"""
import argparse
import io
import json
import time
import urllib.request
import uuid
from datetime import datetime, timezone

TIMEOUT = 10  # s; inference on the server can be slow


def send(server, jpeg, captured_at, event_id):
    return post_image(f"{server.rstrip('/')}/api/detect",
                      {"event_id": event_id, "captured_at": captured_at}, jpeg)


def post_image(url, fields, jpeg):
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="{name}"\r\n\r\n{value}\r\n').encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             'name="image"; filename="frame.jpg"\r\n'
             "Content-Type: image/jpeg\r\n\r\n").encode()
    body += jpeg + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, help="e.g. http://192.168.0.10:8000")
    parser.add_argument("--interval", type=float, default=0.5, help="pause between frames (s)")
    # avoid storing the same pothole over and over
    parser.add_argument("--cooldown", type=float, default=5, help="pause after a pothole (s)")
    parser.add_argument("--count", type=int, default=0, help="frames to send, 0 = forever")
    args = parser.parse_args()

    from picamera2 import Picamera2  # Raspberry Pi only module

    camera = Picamera2()
    camera.configure(camera.create_still_configuration(main={"size": (1280, 720)}))
    if "AfMode" in camera.camera_controls:  # Camera Module 3 autofocus
        camera.set_controls({"AfMode": 2})  # 2 = continuous
    camera.start()
    time.sleep(1)  # let exposure and focus settle

    sent = 0
    try:
        while not args.count or sent < args.count:
            buffer = io.BytesIO()
            captured_at = datetime.now(timezone.utc).isoformat()
            camera.capture_file(buffer, format="jpeg")
            pause = args.interval
            started = time.monotonic()
            try:
                result = send(args.server, buffer.getvalue(), captured_at, str(uuid.uuid4()))
                took = time.monotonic() - started
                if result["pothole"]:
                    best = max(d["confidence"] for d in result["detections"])
                    print(f"POTHOLE conf={best:.2f} id={result['id']} ({took:.2f}s)", flush=True)
                    pause = args.cooldown
                else:
                    print(f"clear ({took:.2f}s)", flush=True)
            except (OSError, ValueError, KeyError) as error:
                # drive.py does not know about this failure, so make it visible
                print(f"send failed: {error}", flush=True)
            sent += 1
            time.sleep(pause)
    except KeyboardInterrupt:
        pass
    finally:
        camera.stop()
        camera.close()


if __name__ == "__main__":
    main()
