import time


DFL_TIMING_FUNC = time.perf_counter
DFL_DIV = 1

class Timer(object):
    def __init__(self, timing_func=DFL_TIMING_FUNC, div=DFL_DIV):
        self.timing_func = timing_func
        self.div = div

    def __enter__(self):
        self.start_time = self.timing_func()
        return self

    def __exit__(self, type, value, traceback):
        self.end_time = self.timing_func()
        self.duration = (self.end_time - self.start_time) / self.div
