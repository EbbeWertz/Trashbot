from abc import ABC, abstractmethod


class BaseService(ABC):
    """ Serice is bedoeld voor de logica van een onderdeel. """
    def __init__(self):
        self.state = {}

    @abstractmethod
    def update(self, hal, deltaTime:float):
        """ Gecalled door de ServiceRunner. """
        pass