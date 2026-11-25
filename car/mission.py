"""Pothole inspection mission. (Raspberry Pi; needs drive.py and camera_send.py)

    python3 mission.py --server http://<SERVER_IP>:8000 --no-motors   # dry run
    python3 mission.py --server http://<SERVER_IP>:8000 --once

CRUISE (short step, stop, look) -> CONFIRM -> AIM -> EXPLORE -> FINISH -> LEAVE.
The car only moves right after the server answered for a still frame.
Do not run drive.py or camera_send.py at the same time.

Lift the wheels off the ground for the first motor test.
ponytail: no encoders, so moves are timed and the car cannot return exactly.
ponytail: after kill -9 or a Pi freeze during a step the motors keep running.
"""
import argparse
import io
import json
import signal
import sys
import time
import urllib.request
import uuid
from collections import namedtuple
from datetime import datetime, timezone
from statistics import median

from camera_send import TIMEOUT, post_image
from drive import FORWARD, MCU_ADDRESS, REG_MOTOR, Car, beep, speed

REG_SERVO = 0x03  # [servo id, angle]; verified on this car
PAN_SERVO, TILT_SERVO = 3, 4
PAN_CENTER = 90  # smaller = right
PAN_RANGE = TILT_RANGE = (70, 110)  # only this range has been tested; tilt: larger = down
HFOV, VFOV = 44, 30  # degrees seen in one frame, measured roughly at 16:9
GAIN = 0.6  # damping for aiming
CENTERED = 0.1  # allowed offset from the frame center (fraction)
ANGLE_STEP = 8
BETTER = 0.02  # score gain that counts as an improvement
FRAMES = 3  # frames per pose; same as MIN_FRAMES on the server
BACKWARD = 0  # assumed; not verified on this car
SONAR_TRIG, SONAR_ECHO = 23, 24  # BCM

Pose = namedtuple("Pose", "score pan tilt move center bottom")


class Stop(Exception):
    """The mission cannot continue; a person has to check."""


def clamp(value, limits):
    return int(round(min(max(value, limits[0]), limits[1])))


def now():
    return datetime.now(timezone.utc).isoformat()


class Server:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def infer(self, jpeg):
        fields = {"event_id": uuid.uuid4().hex, "captured_at": now(), "save": "false"}
        return post_image(f"{self.url}/api/detect", fields, jpeg)["detections"]

    def view(self, inspection, fields, jpeg):
        url = f"{self.url}/api/inspections/{inspection}/views"
        return post_image(url, fields, jpeg)["target"]

    def finish(self, inspection, aborted):
        request = urllib.request.Request(
            f"{self.url}/api/inspections/{inspection}/finish",
            data=json.dumps({"aborted": aborted}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)


class Mission:
    """hw: look(pan, tilt), capture(), step(direction), blocked(), stop(), beep()."""

    def __init__(self, hw, server, cfg, sleep=time.sleep, clock=time.monotonic, log=print):
        self.hw, self.server, self.cfg = hw, server, cfg
        self.sleep, self.clock, self.log = sleep, clock, log
        self.driven = 0

    def run(self):
        try:
            while True:
                self.cruise()
                self.hw.stop()
                if self.confirm():
                    self.hw.beep()
                    result = self.inspect()
                    self.log("RESULT " + json.dumps(result))
                    if self.cfg.once:
                        return
                else:
                    self.log("not confirmed, moving on")
                self.leave()
        finally:
            self.hw.stop()

    # --- driving ---

    def sees_pothole(self):
        return bool(self.server.infer(self.hw.capture()))

    def advance(self):
        """One short forward step. Call only after looking at a fresh frame."""
        if self.hw.blocked():
            self.log("obstacle ahead or no sonar reading, waiting")
            self.sleep(1)
            return 0
        if self.cfg.max_steps and self.driven >= self.cfg.max_steps:
            raise Stop(f"reached --max-steps {self.cfg.max_steps}")
        self.hw.step(1)
        self.driven += 1
        return 1

    def cruise(self):
        self.log("CRUISE")
        self.hw.look(PAN_CENTER, self.cfg.drive_tilt)
        while not self.sees_pothole():
            self.advance()

    def confirm(self):
        self.log("CONFIRM")
        return sum(self.sees_pothole() for _ in range(FRAMES)) >= 2

    def leave(self):
        """Drive past the handled pothole, ignoring it until the view stays clear."""
        self.log("LEAVE")
        self.hw.look(PAN_CENTER, self.cfg.drive_tilt)
        steps = clear = 0
        while True:
            clear = 0 if self.sees_pothole() else clear + 1
            if steps >= self.cfg.leave_min and clear >= self.cfg.leave_clear:
                return
            if steps >= self.cfg.leave_max:
                raise Stop(f"pothole still visible after {steps} steps")
            steps += self.advance()

    # --- inspection ---

    def measure(self, pan, tilt):
        """Take FRAMES views at one pose. The score is the median confidence."""
        if self.hint:  # predict where the target moves when the camera turns
            self.hint = (self.hint[0] + (pan - self.pan) / HFOV,
                         self.hint[1] - (tilt - self.tilt) / VFOV)
        self.pan, self.tilt = pan, tilt
        self.hw.look(pan, tilt)
        self.poses += 1
        pose_id = f"p{self.poses}"
        scores, targets = [], []
        for frame in range(FRAMES):
            fields = {"view_id": f"{pose_id}-{frame}", "pose_id": pose_id,
                      "pan": pan, "tilt": tilt, "move": self.position,
                      "captured_at": now()}
            if self.hint:  # the server only accepts -1..2
                fields["hint_x"], fields["hint_y"] = (min(max(v, -1), 2) for v in self.hint)
            target = self.server.view(self.inspection, fields, self.hw.capture())
            scores.append(target["confidence"] if target else 0)
            if target:
                targets.append(target["label"])
                self.hint = (target["label"]["cx"], target["label"]["cy"])
        center = bottom = None
        if targets:
            center = (median(t["cx"] for t in targets), median(t["cy"] for t in targets))
            bottom = median(t["cy"] + t["h"] / 2 for t in targets)
        pose = Pose(median(scores), pan, tilt, self.position, center, bottom)
        self.log(f"  {pose_id} pan={pan} tilt={tilt} move={self.position} "
                 f"score={pose.score:.2f}")
        return pose

    def spent(self):
        return (self.poses >= self.cfg.max_poses
                or self.clock() - self.started >= self.cfg.budget)

    @staticmethod
    def off_center(pose):
        return pose.center is not None and max(abs(v - 0.5) for v in pose.center) > CENTERED

    @staticmethod
    def corrected(pose):
        return (clamp(pose.pan - (pose.center[0] - 0.5) * HFOV * GAIN, PAN_RANGE),
                clamp(pose.tilt + (pose.center[1] - 0.5) * VFOV * GAIN, TILT_RANGE))

    def aim(self):
        pose = best = self.measure(PAN_CENTER, self.cfg.drive_tilt)
        for _ in range(5):
            if self.spent() or not self.off_center(pose):
                break
            angles = self.corrected(pose)
            if angles == (pose.pan, pose.tilt):
                break  # servo limit
            pose = self.measure(*angles)
            best = max(best, pose, key=lambda p: p.score)
        return best

    def explore_angles(self, best):
        movable = self.cfg.max_forward or self.cfg.max_reverse
        limit = self.cfg.max_poses - (4 if movable else 0)  # keep poses for moving
        seen = {(best.pan, best.tilt)}
        improved = True
        while improved:
            improved = False
            for dp, dt in ((ANGLE_STEP, 0), (-ANGLE_STEP, 0), (0, ANGLE_STEP), (0, -ANGLE_STEP)):
                if self.spent() or self.poses >= limit:
                    return best
                angles = (clamp(best.pan + dp, PAN_RANGE), clamp(best.tilt + dt, TILT_RANGE))
                if angles in seen:
                    continue
                seen.add(angles)
                pose = self.measure(*angles)
                if pose.score > best.score + BETTER:
                    best, improved = pose, True
                    break
        return best

    def move(self, direction, view):
        """One step during inspection, within the safety limits. False if refused."""
        limit = self.cfg.max_forward if direction > 0 else self.cfg.max_reverse
        if self.used[direction] >= limit:
            return False
        if direction > 0:
            # never creep forward blind or once the target reaches the frame bottom
            if view.bottom is None or view.bottom >= 0.95 or self.hw.blocked():
                return False
        self.hw.step(direction)
        self.used[direction] += 1
        self.position += direction
        return True

    def explore_distance(self, best):
        origin = best.move
        for direction in (1, -1):
            view = best
            while not self.spent() and self.move(direction, view):
                view = self.measure(best.pan, best.tilt)
                if self.off_center(view) and not self.spent():
                    view = max(view, self.measure(*self.corrected(view)),
                               key=lambda p: p.score)
                if view.score <= best.score + BETTER:
                    break
                best = view
            while self.position != best.move:  # go back toward the best spot
                if not self.move(1 if best.move > self.position else -1, best):
                    break
                self.sees_pothole()  # every step needs a fresh server answer
            if best.move != origin:
                break  # this side was better; the other side was already passed
        return best

    def inspect(self):
        self.inspection = uuid.uuid4().hex
        self.log(f"INSPECT {self.inspection}")
        self.poses = self.position = 0
        self.used = {1: 0, -1: 0}
        self.hint = None
        self.pan, self.tilt = PAN_CENTER, self.cfg.drive_tilt
        self.started = self.clock()
        try:
            self.explore_distance(self.explore_angles(self.aim()))
        except BaseException:
            self.hw.stop()
            try:
                self.server.finish(self.inspection, True)
            except Exception as error:
                self.log(f"could not mark inspection aborted: {error}")
            raise
        self.hw.stop()
        return self.finish()

    def finish(self):
        """Safe to retry: the server returns the first result again."""
        for attempt in range(8):
            try:
                return self.server.finish(self.inspection, False)
            except (OSError, ValueError) as error:
                self.log(f"finish failed, retrying: {error}")
                self.sleep(min(2 ** attempt, 10))
        raise Stop(f"result of inspection {self.inspection} was not confirmed by the server")


class PiHardware:
    def __init__(self, cfg):
        import smbus  # Raspberry Pi only modules
        import RPi.GPIO as GPIO
        from picamera2 import Picamera2

        self.cfg, self.gpio = cfg, GPIO
        self.bus = smbus.SMBus(1)
        self.car = Car(self.bus, cfg.left, cfg.right)
        self.angles = {}
        if cfg.min_distance:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(SONAR_TRIG, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(SONAR_ECHO, GPIO.IN)
        self.camera = Picamera2()
        # queue=False: every capture is a frame taken after the request
        self.camera.configure(self.camera.create_still_configuration(
            main={"size": (1280, 720)}, queue=False))
        if "AfMode" in self.camera.camera_controls:
            self.camera.set_controls({"AfMode": 2})  # continuous autofocus
        self.camera.start()
        time.sleep(1)

    def look(self, pan, tilt):
        moved = False
        for servo, target in ((PAN_SERVO, pan), (TILT_SERVO, tilt)):
            start = self.angles.get(servo, target)
            direction = 2 if target >= start else -2
            if self.angles.get(servo) == target:
                continue
            for angle in [*range(start, target, direction), target]:
                self.bus.write_i2c_block_data(MCU_ADDRESS, REG_SERVO, [servo, angle])
                time.sleep(0.03)
            self.angles[servo] = target
            moved = True
        if moved:
            time.sleep(self.cfg.settle)

    def capture(self):
        buffer = io.BytesIO()
        self.camera.capture_file(buffer, format="jpeg")
        return buffer.getvalue()

    def step(self, direction):
        if self.cfg.no_motors:
            print(f"  (no motors) step {'forward' if direction > 0 else 'backward'}")
        else:
            try:
                way = FORWARD if direction > 0 else BACKWARD
                self.bus.write_i2c_block_data(
                    MCU_ADDRESS, REG_MOTOR, [way, self.car.left, way, self.car.right])
                time.sleep(self.cfg.pulse)
            finally:
                self.car.stop()
        time.sleep(self.cfg.settle)

    def stop(self):
        self.car.stop()

    def distance(self):
        """Ultrasonic distance in cm, or None if the sensor does not answer."""
        gpio = self.gpio
        gpio.output(SONAR_TRIG, True)
        time.sleep(0.00001)
        gpio.output(SONAR_TRIG, False)
        edges = []
        for waiting_level in (0, 1):
            deadline = time.monotonic() + 0.05
            while gpio.input(SONAR_ECHO) == waiting_level:
                if time.monotonic() > deadline:
                    return None
            edges.append(time.monotonic())
        return (edges[1] - edges[0]) * 17150

    def blocked(self):
        if not self.cfg.min_distance:
            return False
        readings = []
        for _ in range(3):
            value = self.distance()
            if value is not None:
                readings.append(value)
            time.sleep(0.03)
        return len(readings) < 2 or median(readings) < self.cfg.min_distance

    def beep(self):
        try:
            beep(self.gpio)
            if self.cfg.min_distance:
                self.gpio.setmode(self.gpio.BCM)
        except RuntimeError as error:
            print(f"buzzer failed: {error}")

    def close(self):
        self.camera.stop()
        self.camera.close()
        if self.cfg.min_distance:
            self.gpio.cleanup((SONAR_TRIG, SONAR_ECHO))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", required=True, help="e.g. http://192.168.0.10:8000")
    parser.add_argument("--no-motors", action="store_true",
                        help="move camera servos only, never the wheels")
    parser.add_argument("--once", action="store_true", help="exit after one inspection")
    # calibrate these on the real car
    parser.add_argument("--left", type=speed, default=60)
    parser.add_argument("--right", type=speed, default=60)
    parser.add_argument("--pulse", type=float, default=0.15, help="motor time per step (s)")
    parser.add_argument("--settle", type=float, default=0.4, help="wait after moving (s)")
    parser.add_argument("--drive-tilt", type=int, default=100, help="camera tilt while driving")
    parser.add_argument("--min-distance", type=float, default=20,
                        help="sonar stop distance (cm), 0 = sonar off")
    parser.add_argument("--max-steps", type=int, default=0,
                        help="stop after this many cruise steps, 0 = no limit")
    parser.add_argument("--max-forward", type=int, default=3, help="inspection steps forward")
    parser.add_argument("--max-reverse", type=int, default=3,
                        help="inspection steps backward, 0 = never reverse")
    parser.add_argument("--max-poses", type=int, default=12)
    parser.add_argument("--budget", type=float, default=45, help="inspection time limit (s)")
    parser.add_argument("--leave-min", type=int, default=5)
    parser.add_argument("--leave-clear", type=int, default=5)
    parser.add_argument("--leave-max", type=int, default=40)
    args = parser.parse_args(argv)
    if not TILT_RANGE[0] <= args.drive_tilt <= TILT_RANGE[1]:
        parser.error(f"--drive-tilt must be {TILT_RANGE[0]}-{TILT_RANGE[1]}")
    if not 0 < args.pulse <= 1:
        parser.error("--pulse must be in (0, 1]")
    return args


def main():
    args = parse_args()
    # make SSH hangup (SIGHUP) and kill run the finally blocks so motors stop
    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda number, frame: sys.exit(1))
    hardware = PiHardware(args)
    try:
        Mission(hardware, Server(args.server), args,
                log=lambda text: print(text, flush=True)).run()
    except KeyboardInterrupt:
        print("stopped by user")
    except Stop as reason:
        sys.exit(f"stopped: {reason}")
    except Exception as error:
        sys.exit(f"stopped on error: {error}")
    finally:
        try:
            hardware.stop()
        finally:
            hardware.close()


if __name__ == "__main__":
    main()
