from abc import ABC, abstractmethod
import multiprocessing as mp
import threading
import time

class ServiceRunner(ABC):
    """ Runt BaseService instances in een process of thread """
    def __init__(self, service: BaseService, hal, realtime: bool = false hz: float = 1.0):
        self.service = service
        self.hal = hal
        self.realtime = realtime
        self.interval = 1.0 / hz
        self.running = False

    @abstractmethod
    def start(self): pass

    @abstractmethod
    def stop(self): pass

    def _loop(self):
        self.running = True
        prev_time = time.perf_counter()
        elapsed = 0.0
        while self.running:
            self.service.update(self.hal, elapsed)
            elapsed = time.perf_counter() - start_time
            if not realtime:
                time.sleep(max(0, self.interval - elapsed))

class ThreadedServiceRunner(ServiceRunner):
    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

class ProcessServiceRunner(ServiceRunner):
    def start(self):
        self.process = mp.Process(target=self._loop, daemon=True)
        self.process.start()