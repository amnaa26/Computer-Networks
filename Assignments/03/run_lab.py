import argparse
import random
import string
import time

from channel_core import UnreliableLink
from transport_fsm import GoBackNProtocol, SelectiveRepeatProtocol, StopWaitRDT


def make_workload(count, payload_size, seed):
    rng = random.Random(seed)
    letters = string.ascii_lowercase + string.digits
    items = []
    for idx in range(count):
        token = "".join(rng.choice(letters) for _ in range(payload_size))
        items.append(f"pkt{idx:03d}:{token}")
    return items


def _print_tail(title, lines, n=10):
    print(f"\n{title}")
    if not lines:
        print("(empty)")
        return
    for row in lines[-n:]:
        print(row)


def choose_protocol(name, link, timeout, window):
    if name == "rdt3":
        return StopWaitRDT(link, timeout=timeout)
    if name == "gbn":
        return GoBackNProtocol(link, window_size=window, timeout=timeout)
    return SelectiveRepeatProtocol(link, window_size=window, timeout=timeout)


def execute(opts):
    link = UnreliableLink(
        loss=opts.loss,
        corrupt=opts.corrupt,
        delay=(opts.delay_min, opts.delay_max),
        seed=opts.seed + 123,
    )
    protocol = choose_protocol(opts.protocol, link, opts.timeout, opts.window)
    messages = make_workload(opts.count, opts.packet_size, opts.seed)

    print(f"protocol={opts.protocol}")
    print(f"messages={len(messages)}, payload_size={opts.packet_size}")
    print(f"loss={opts.loss}, corrupt={opts.corrupt}, delay=[{opts.delay_min}, {opts.delay_max}]")

    ticks = 0
    done = False
    while ticks < opts.max_ticks:
        done = protocol.step(messages)
        ticks += 1
        if done:
            break
        if opts.step_sleep > 0:
            time.sleep(opts.step_sleep)

    _print_tail("Sender transitions (tail)", protocol.sender_log)
    _print_tail("Receiver transitions (tail)", protocol.receiver_log)

    success = protocol.delivered == messages
    print("\nSummary")
    print(f"ticks={ticks}")
    print(f"delivered={len(protocol.delivered)}/{len(messages)}")
    print(f"in_order_complete={success}")
    return 0 if success else 2


def get_args():
    parser = argparse.ArgumentParser(description="RDT/GBN/SR simulator")
    parser.add_argument("--protocol", choices=["rdt3", "gbn", "sr"], default="rdt3")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--packet-size", type=int, default=8)
    parser.add_argument("--window", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=0.25)
    parser.add_argument("--loss", type=float, default=0.1)
    parser.add_argument("--corrupt", type=float, default=0.1)
    parser.add_argument("--delay-min", type=float, default=0.01)
    parser.add_argument("--delay-max", type=float, default=0.05)
    parser.add_argument("--step-sleep", type=float, default=0.001)
    parser.add_argument("--max-ticks", type=int, default=30000)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(execute(get_args()))
