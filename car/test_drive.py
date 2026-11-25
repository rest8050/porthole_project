"""Runs without hardware: python car/test_drive.py"""
from drive import MCU_ADDRESS, Car, drive


class FakeBus:
    def __init__(self, stop_failures=0):
        self.log, self.stop_failures = [], stop_failures

    def write_i2c_block_data(self, address, register, data):
        self.log.append(("go", address, data))

    def write_byte_data(self, address, register, value):
        if self.stop_failures:
            self.stop_failures -= 1
            raise OSError("i2c")
        self.log.append(("stop", address))


def run(responses, stop_failures=0):
    bus = FakeBus(stop_failures)
    values = iter(responses)

    def fetch():
        value = next(values)
        if isinstance(value, BaseException):
            raise value
        return value

    try:
        result = drive(Car(bus, 60, 55), fetch, sleep=lambda _: None)
    except BaseException as error:
        result = error
    return result, [entry[0] for entry in bus.log], bus.log


# keep going while unchanged, stop on change
result, actions, log = run(["a", "a", "a", "b"])
assert isinstance(result, str) and actions == ["go", "stop"], (result, actions)
assert log[0] == ("go", MCU_ADDRESS, [1, 60, 1, 55])

# empty DB (None): stop on the first event
assert run([None, None, "a"])[1] == ["go", "stop"]

# first request fails: never start
result, actions, _ = run([OSError("down")])
assert isinstance(result, OSError) and actions == ["stop"]

# network error, bad response, Ctrl+C, exit signal while driving: all stop
for failure in (OSError("lost"), KeyError("x"), KeyboardInterrupt(), SystemExit(1)):
    result, actions, _ = run(["a", failure])
    assert result is failure and actions == ["go", "stop"], (failure, actions)

# stop command is retried after transient failures
assert run(["a", "b"], stop_failures=2)[1] == ["go", "stop"]

print("OK")
