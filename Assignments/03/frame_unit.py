from dataclasses import dataclass
import hashlib


@dataclass
class Frame:
    seq: int
    payload: str
    ack: bool = False
    ack_for: int = -1
    digest: str = ""

    def __post_init__(self):
        if self.ack_for < 0:
            self.ack_for = self.seq
        if not self.digest:
            self.digest = self._make_digest()

    def _make_digest(self):
        raw = f"{self.seq}#{self.payload}#{int(self.ack)}#{self.ack_for}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def invalid(self):
        return self.digest != self._make_digest()

    def copy(self):
        return Frame(
            seq=self.seq,
            payload=self.payload,
            ack=self.ack,
            ack_for=self.ack_for,
            digest=self.digest,
        )

    def __repr__(self):
        kind = "ACK" if self.ack else "DATA"
        return f"Frame({kind}, seq={self.seq}, ack_for={self.ack_for})"
