"""In-memory persistence boundary for Morek module tests."""

from copy import deepcopy


class MemoryOutcomes:
    def __init__(self):
        self.value = None
        self.writes = []

    async def read(self):
        return deepcopy(self.value)

    async def write(self, value):
        self.value = deepcopy(value)
        self.writes.append(deepcopy(value))
