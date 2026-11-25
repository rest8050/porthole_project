"""Drive straight; stop when the server stores a new pothole event. (Raspberry Pi)

    python3 drive.py --server http://<SERVER_IP>:8000

Lift the wheels off the ground for the first test.
ponytail: after kill -9 or a Pi freeze the MCU keeps the motors running.
Use the power switch in that case.
"""
import argparse
import json
import signal
import sys
import time
import urllib.request

# WARNING: this motor protocol is assumed from Yahboom 4WD (YB_Pcb_Car) and is
# not verified on this car. If it differs, follow the vendor example.
MCU_ADDRESS = 0x16
REG_MOTOR = 0x01  # [left dir, left speed, right dir, right speed]
REG_STOP = 0x02
FORWARD = 1

BUZZER_PIN = 12  # BCM 12 = BOARD 32

INTERVAL = 0.2  # poll interval (s)
TIMEOUT = 0.5  # response timeout (s); stop if exceeded


class Car:
    def __init__(self, bus, left, right):
        self.bus, self.left, self.right = bus, left, right

    def forward(self):
        self.bus.write_i2c_block_data(
            MCU_ADDRESS, REG_MOTOR, [FORWARD, self.left, FORWARD, self.right]
        )

    def stop(self):
        for attempt in range(5):  # retry stop on I2C errors
            try:
                self.bus.write_byte_data(MCU_ADDRESS, REG_STOP, 0x00)
                return
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.02)


def last_received(server):
    # "since" is required but does not affect last_received_at
    url = f"{server.rstrip('/')}/api/potholes/summary?since=2000-01-01T00:00:00Z"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        value = json.load(response)["last_received_at"]  # error if key is missing
    if value is not None and not isinstance(value, str):
        raise ValueError(f"invalid last_received_at: {value!r}")
    return value


def drive(car, fetch, sleep=time.sleep):
    """Return the stop reason. Motors are stopped however this ends."""
    try:
        baseline = fetch()  # do not start if the first request fails
        car.forward()
        while True:
            sleep(INTERVAL)
            if fetch() != baseline:
                return "new event stored on server"
    finally:
        car.stop()


def beep(gpio):
    gpio.setmode(gpio.BCM)
    gpio.setup(BUZZER_PIN, gpio.OUT)
    try:
        tone = gpio.PWM(BUZZER_PIN, 440)
        tone.start(50)
        time.sleep(0.3)
        tone.stop()
    finally:
        gpio.cleanup(BUZZER_PIN)


def speed(text):
    value = int(text)
    if not 0 <= value <= 255:
        raise argparse.ArgumentTypeError("speed must be 0-255")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, help="e.g. http://192.168.0.10:8000")
    # tune left/right separately if the car drifts
    parser.add_argument("--left", type=speed, default=60)
    parser.add_argument("--right", type=speed, default=60)
    args = parser.parse_args()

    import smbus  # Raspberry Pi only modules
    import RPi.GPIO as GPIO

    car = Car(smbus.SMBus(1), args.left, args.right)

    # make SSH hangup (SIGHUP) and kill run the finally block so motors stop
    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda number, frame: sys.exit(1))

    try:
        reason = drive(car, lambda: last_received(args.server))
    except KeyboardInterrupt:
        print("stopped by user")
        return
    except Exception as error:
        sys.exit(f"stopped on error: {error}")
    print(f"stopped: {reason}")
    beep(GPIO)


if __name__ == "__main__":
    main()
