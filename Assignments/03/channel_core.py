import random
import time


class UnreliableLink:
    def __init__(self, loss=0.1, corrupt=0.1, delay=(0.01, 0.05), seed=None):
        self.loss = float(loss)
        self.corrupt = float(corrupt)
        self.delay_min = float(delay[0])
        self.delay_max = float(delay[1])
        self._rng = random.Random(seed)
        self._in_flight = []

    def push(self, direction, frame):
        # Drop before enqueue to simulate loss on send.
        if self._rng.random() < self.loss:
            return "DROP"

        tx = frame.copy()
        if self._rng.random() < self.corrupt:
            tx.digest = "damaged"
            mark = "CORRUPT"
        else:
            mark = "OK"

        ready_at = time.monotonic() + self._rng.uniform(self.delay_min, self.delay_max)
        self._in_flight.append((ready_at, direction, tx))
        self._in_flight.sort(key=lambda it: it[0])
        return mark

    def pump(self, receiver_inbox, sender_inbox):
        # Deliver only frames whose scheduled arrival time has passed.
        now = time.monotonic()
        delivered = 0
        pending = []

        for item in self._in_flight:
            ready_at, direction, frame = item
            if ready_at > now:
                pending.append(item)
                continue

            if direction == "sender_to_receiver":
                receiver_inbox.append(frame)
            else:
                sender_inbox.append(frame)
            delivered += 1

        self._in_flight = pending
        return delivered
