"""Runs without hardware or server: python car/test_mission.py"""
import sys

sys.dont_write_bytecode = True

from mission import PAN_RANGE, TILT_RANGE, Mission, Stop, parse_args


class World:
    """Fake car, camera and server. A pothole is seen while start <= x < end."""

    def __init__(self, start=3, end=10, best_x=5, fail_view=None, finish_failures=0):
        self.x, self.start, self.end, self.best_x = 0, start, end, best_x
        self.pan, self.tilt = 90, 100
        self.steps, self.finishes, self.views = [], [], []
        self.fail_view, self.finish_failures = fail_view, finish_failures
        self.fresh = False  # a still frame was judged since the last step
        self.obstacle = False

    # hardware
    def look(self, pan, tilt):
        assert PAN_RANGE[0] <= pan <= PAN_RANGE[1], pan
        assert TILT_RANGE[0] <= tilt <= TILT_RANGE[1], tilt
        self.pan, self.tilt = pan, tilt

    def capture(self):
        return b"jpeg"

    def step(self, direction):
        assert self.fresh, "moved without looking at a new server answer"
        self.fresh = False
        self.steps.append(direction)
        self.x += direction

    def blocked(self):
        return self.obstacle

    def stop(self):
        pass

    def beep(self):
        pass

    # server
    def visible(self):
        return self.start <= self.x < self.end

    def infer(self, jpeg):
        self.fresh = True
        return [{}] if self.visible() else []

    def view(self, inspection, fields, jpeg):
        if len(self.views) == self.fail_view:
            raise OSError("network lost")
        self.views.append(fields)
        self.fresh = True
        if not self.visible():
            return None
        # best when the camera is turned to pan 82 and the car is at best_x
        score = 0.9 - abs(self.pan - 82) * 0.01 - abs(self.x - self.best_x) * 0.1
        cx = 0.7 + (self.pan - 90) / 44  # turning right moves the target left
        cy = 0.6 - (self.tilt - 100) / 30
        return {"confidence": score, "label": {"cx": cx, "cy": cy, "w": 0.2, "h": 0.1}}

    def finish(self, inspection, aborted):
        if self.finish_failures:
            self.finish_failures -= 1
            raise OSError("timeout")
        self.finishes.append(aborted)
        return {"verdict": "inconclusive" if aborted else "confirmed"}


def run(world, *extra):
    cfg = parse_args(["--server", "x", "--once", *extra])
    mission = Mission(world, world, cfg, sleep=lambda _: None, clock=lambda: 0,
                      log=lambda _: None)
    try:
        mission.run()
        return mission, None
    except BaseException as error:
        return mission, error


def poses(world):
    return list(dict.fromkeys(v["pose_id"] for v in world.views))


# full flow: drive, stop at the pothole, inspect from several poses, finish once
world = World()
mission, error = run(world)
assert error is None and world.finishes == [False], error
assert world.steps[:3] == [1, 1, 1]
assert 5 <= len(poses(world)) <= 12 and len(world.views) == 3 * len(poses(world))
assert any(v["pan"] != 90 for v in world.views)      # turned the camera
assert any(v["move"] != 0 for v in world.views)      # moved the car
assert world.steps[3:].count(1) <= 3 and world.steps.count(-1) <= 3
assert world.x == world.best_x, world.x              # went to the best spot and back to it

# reverse disabled
world = World()
run(world, "--max-reverse", "0")
assert -1 not in world.steps

# network failure during inspection: abort and do not drive again
world = World(fail_view=7)
_, error = run(world)
assert isinstance(error, OSError) and world.finishes == [True], error
assert world.steps == [1, 1, 1]

# finish retries; if the server never answers the car stays stopped
world = World(finish_failures=3)
assert run(world)[1] is None and world.finishes == [False]
world = World(finish_failures=99)
assert isinstance(run(world)[1], Stop)

# leaving: ignore the same pothole until it is gone, then cruise again
world = World(start=0, end=8)
cfg = parse_args(["--server", "x"])
mission = Mission(world, world, cfg, sleep=lambda _: None, log=lambda _: None)
mission.leave()
assert world.x == 8 + cfg.leave_clear - 1 and not world.views, world.x

# a pothole that never leaves the view stops the car
world = World(start=0, end=999)
mission = Mission(world, world, cfg, sleep=lambda _: None, log=lambda _: None)
try:
    mission.leave()
    raise AssertionError("kept driving")
except Stop:
    assert len(world.steps) == cfg.leave_max

# obstacle: never step
world = World()
world.obstacle = True
mission = Mission(world, world, cfg, sleep=lambda _: None, log=lambda _: None)
assert mission.advance() == 0 and not world.steps

# --max-steps limits cruising
_, error = run(World(start=999), "--max-steps", "4")
assert isinstance(error, Stop), error

print("OK")
