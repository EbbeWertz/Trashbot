from TrashbotConfig import TrashbotConfig
from engine.hal.TrashbotHardware import TrashbotHardware


class TrashbotEngine:
    def __init__(self, config:TrashbotConfig):
        self.config = config
        self.hal = TrashbotHardware(config)
        self.manager = mp.Manager()
        
        self.shared_state = self.manager.dict({
            "mode": "manual",
            "battery": 100.0,
            "cpu": 0.0,
            "battery_history": self.manager.list()
        })
        
        self.runners = []

    def add_service(self, service: BaseService, hz: float, mode="thread"):
        if mode == "process":
            runner = ProcessRunner(service, self.hal, hz)
        else:
            runner = ThreadedRunner(service, self.hal, hz)
        self.runners.append(runner)

    def start(self):
        for runner in self.runners:
            runner.start()

    def set_mode(self, new_mode: str):
        self.shared_state["mode"] = new_mode