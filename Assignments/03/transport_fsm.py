import time

from frame_unit import Frame


class StopWaitRDT:
    def __init__(self, link, timeout=1.0):
        self.link = link
        self.timeout = float(timeout)

        self.tx_state = "IDLE"
        self.tx_index = 0
        self.last_send_time = 0.0

        self.rx_expect = 0

        self.to_sender = []
        self.to_receiver = []
        self.sender_log = []
        self.receiver_log = []
        self.delivered = []

    def _send_data(self, text):
        frame = Frame(seq=self.tx_index, payload=text)
        self.link.push("sender_to_receiver", frame)
        self.last_send_time = time.monotonic()
        return frame

    def step(self, messages):
        self.link.pump(self.to_receiver, self.to_sender)

        if self.tx_state == "IDLE" and self.tx_index < len(messages):
            frame = self._send_data(messages[self.tx_index])
            self.tx_state = "WAIT_ACK"
            self.sender_log.append(f"FSM S: IDLE->WAIT_ACK send seq={frame.seq}")
        elif self.tx_state == "WAIT_ACK":
            if time.monotonic() - self.last_send_time >= self.timeout:
                frame = self._send_data(messages[self.tx_index])
                self.sender_log.append(f"FSM S: timeout resend seq={frame.seq}")

        while self.to_receiver:
            incoming = self.to_receiver.pop(0)
            if incoming.invalid():
                self.receiver_log.append("FSM R: corrupt DATA ignored")
                dup = Frame(seq=max(-1, self.rx_expect - 1), payload="ACK", ack=True)
                self.link.push("receiver_to_sender", dup)
                continue

            if incoming.seq != self.rx_expect:
                self.receiver_log.append(f"FSM R: duplicate seq={incoming.seq} -> ACK old")
                dup = Frame(seq=max(-1, self.rx_expect - 1), payload="ACK", ack=True)
                self.link.push("receiver_to_sender", dup)
                continue

            self.delivered.append(incoming.payload)
            self.receiver_log.append(f"FSM R: accept seq={incoming.seq} deliver+ACK")
            self.link.push("receiver_to_sender", Frame(seq=self.rx_expect, payload="ACK", ack=True))
            self.rx_expect += 1

        while self.to_sender:
            ack = self.to_sender.pop(0)
            if ack.invalid() or not ack.ack:
                self.sender_log.append("FSM S: invalid ACK ignored")
                continue

            if self.tx_state == "WAIT_ACK" and ack.ack_for == self.tx_index:
                self.sender_log.append(f"FSM S: ACK {ack.ack_for} accepted")
                self.tx_state = "IDLE"
                self.tx_index += 1
            else:
                self.sender_log.append(f"FSM S: ACK {ack.ack_for} not expected")

        return self.tx_index >= len(messages) and self.tx_state == "IDLE"


class GoBackNProtocol:
    def __init__(self, link, window_size=4, timeout=1.5):
        self.link = link
        self.window_size = int(window_size)
        self.timeout = float(timeout)

        self.base = 0
        self.next_to_send = 0
        self.expected = 0
        self.sent_at = {}

        self.frames = []
        self.to_sender = []
        self.to_receiver = []
        self.sender_log = []
        self.receiver_log = []
        self.delivered = []

    def _emit(self, seq):
        self.link.push("sender_to_receiver", self.frames[seq])
        self.sent_at[seq] = time.monotonic()

    def step(self, messages):
        if not self.frames:
            self.frames = [Frame(seq=i, payload=text) for i, text in enumerate(messages)]

        self.link.pump(self.to_receiver, self.to_sender)

        while self.next_to_send < len(messages) and self.next_to_send < self.base + self.window_size:
            self._emit(self.next_to_send)
            self.sender_log.append(f"FSM S: send seq={self.next_to_send}")
            self.next_to_send += 1

        if self.base < self.next_to_send:
            # Single timer for oldest unacknowledged packet (GBN behavior).
            oldest_age = time.monotonic() - self.sent_at.get(self.base, 0.0)
            if oldest_age >= self.timeout:
                self.sender_log.append(f"FSM S: timeout at base={self.base} resend window")
                for seq in range(self.base, self.next_to_send):
                    self._emit(seq)

        while self.to_receiver:
            frame = self.to_receiver.pop(0)
            if frame.invalid() or frame.seq != self.expected:
                self.receiver_log.append("FSM R: bad/out-of-order -> ACK last in-order")
                self.link.push("receiver_to_sender", Frame(seq=self.expected - 1, payload="ACK", ack=True))
                continue

            self.delivered.append(frame.payload)
            self.receiver_log.append(f"FSM R: accept seq={frame.seq}")
            self.link.push("receiver_to_sender", Frame(seq=frame.seq, payload="ACK", ack=True))
            self.expected += 1

        while self.to_sender:
            ack = self.to_sender.pop(0)
            if ack.invalid() or not ack.ack:
                continue
            if ack.ack_for >= self.base:
                self.base = min(len(messages), ack.ack_for + 1)
                self.sender_log.append(f"FSM S: cumulative ACK {ack.ack_for}, base={self.base}")

        return self.base >= len(messages)


class SelectiveRepeatProtocol:
    def __init__(self, link, window_size=4, timeout=1.5):
        self.link = link
        self.window_size = int(window_size)
        self.timeout = float(timeout)

        self.base = 0
        self.next_to_send = 0
        self.recv_base = 0

        self.frames = []
        self.acked = {}
        self.sent_at = {}
        self.recv_buffer = {}

        self.to_sender = []
        self.to_receiver = []
        self.sender_log = []
        self.receiver_log = []
        self.delivered = []

    def _emit(self, seq):
        self.link.push("sender_to_receiver", self.frames[seq])
        self.sent_at[seq] = time.monotonic()

    def step(self, messages):
        if not self.frames:
            self.frames = [Frame(seq=i, payload=text) for i, text in enumerate(messages)]
            self.acked = {i: False for i in range(len(messages))}

        self.link.pump(self.to_receiver, self.to_sender)

        while self.next_to_send < len(messages) and self.next_to_send < self.base + self.window_size:
            self._emit(self.next_to_send)
            self.sender_log.append(f"FSM S: send seq={self.next_to_send}")
            self.next_to_send += 1

        now = time.monotonic()
        # SR keeps independent timers and retransmits timed-out frames individually.
        for seq in range(self.base, self.next_to_send):
            if self.acked[seq]:
                continue
            if now - self.sent_at.get(seq, now) >= self.timeout:
                self._emit(seq)
                self.sender_log.append(f"FSM S: timeout seq={seq}, selective resend")

        while self.to_receiver:
            frame = self.to_receiver.pop(0)
            if frame.invalid():
                self.receiver_log.append("FSM R: corrupt frame dropped")
                continue

            in_window = self.recv_base <= frame.seq < self.recv_base + self.window_size
            if in_window:
                self.recv_buffer[frame.seq] = frame.payload
                self.receiver_log.append(f"FSM R: buffered seq={frame.seq}")
                self.link.push("receiver_to_sender", Frame(seq=frame.seq, payload="ACK", ack=True))
            elif frame.seq < self.recv_base:
                self.receiver_log.append(f"FSM R: old seq={frame.seq}, re-ACK")
                self.link.push("receiver_to_sender", Frame(seq=frame.seq, payload="ACK", ack=True))

            while self.recv_base in self.recv_buffer:
                # Deliver only contiguous buffered sequence to preserve order.
                self.delivered.append(self.recv_buffer.pop(self.recv_base))
                self.recv_base += 1

        while self.to_sender:
            ack = self.to_sender.pop(0)
            if ack.invalid() or not ack.ack:
                continue
            if ack.ack_for in self.acked:
                self.acked[ack.ack_for] = True
                self.sender_log.append(f"FSM S: ACK {ack.ack_for}")

            while self.base < len(messages) and self.acked.get(self.base, False):
                self.base += 1

        return self.base >= len(messages)
