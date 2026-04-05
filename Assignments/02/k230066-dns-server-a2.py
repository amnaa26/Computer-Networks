import socket
import struct
import threading
import random
import time
from collections import OrderedDict
 
# Ports for each server
ROOT_SERVER   = ("127.0.0.1", 5001)
TLD_SERVER    = ("127.0.0.1", 5002)
AUTH_SERVER   = ("127.0.0.1", 5003)
 
DNS_RECORDS = {
    "google.com": {
        "A":  ["64.233.187.99", "72.14.207.99", "64.233.167.99"],
        "NS": ["ns4.google.com.", "ns1.google.com.", "ns2.google.com.", "ns3.google.com."],
        "MX": ["10 smtp4.google.com.", "10 smtp1.google.com.", "10 smtp2.google.com.", "10 smtp3.google.com."]
    },
    "microsoft.com": {
        "A":  ["20.112.52.29", "20.70.246.20"],
        "NS": ["ns1-39.azure-dns.com.", "ns2-39.azure-dns.net.", "ns3-39.azure-dns.org.", "ns4-39.azure-dns.info."],
        "MX": ["10 microsoft-com.mail.protection.outlook.com."]
    },
    "yahoo.com": {
        "A":  ["98.137.11.163", "98.137.11.164"],
        "NS": ["ns1.yahoo.com.", "ns2.yahoo.com.", "ns3.yahoo.com."],
        "MX": ["1 mta6.am0.yahoodns.net.", "5 mta7.am0.yahoodns.net."]
    },
    "github.com": {
        "A":  ["140.82.121.4", "140.82.121.3"],
        "NS": ["ns-1707.awsdns-21.co.uk.", "ns-421.awsdns-52.com.", "ns-520.awsdns-01.net."],
        "MX": ["1 aspmx.l.google.com.", "5 alt1.aspmx.l.google.com."]
    }
}
 
# DNS Packet functions
# using struct to pack 16-bit ID and 16-bit flags as mentioned in Figure 02 of the assignment
 
def make_packet(msg_id, flags, message):
    # pack 2 unsigned shorts (each 16 bits) in network byte order
    header = struct.pack("!HH", msg_id, flags)
    return header + message.encode()
 
def read_packet(data):
    # unpack the first 4 bytes as header
    id_val, flags = struct.unpack("!HH", data[:4])
    message = data[4:].decode()
    return id_val, flags, message
 

class RootServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(ROOT_SERVER)
        print(f"[Root Server] Started on port {ROOT_SERVER[1]}")
 
    def start(self):
        while True:
            data, addr = self.sock.recvfrom(1024)
            msg_id, flags, domain = read_packet(data)
            print(f"[Root Server] Got query for '{domain}' (ID: {hex(msg_id)})")
 
            tld = domain.split(".")[-1]
 
            # root server refers to TLD server
            if tld == "com" or tld == "org" or tld == "net":
                reply = f"127.0.0.1:{TLD_SERVER[1]}"
            else:
                reply = "ERROR:UNKNOWN_TLD"
 
            # set QR bit to 1 (this is a response now)
            resp_flags = flags | 0x8000
            self.sock.sendto(make_packet(msg_id, resp_flags, reply), addr)
 

# It refers to the authoritative server
class TLDServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(TLD_SERVER)
        print(f"[TLD Server] Started on port {TLD_SERVER[1]}")
 
    def start(self):
        while True:
            data, addr = self.sock.recvfrom(1024)
            msg_id, flags, domain = read_packet(data)
            print(f"[TLD Server] Got query for '{domain}' (ID: {hex(msg_id)})")
 
            # TLD server knows which authoritative server has the records
            if domain in DNS_RECORDS:
                reply = f"127.0.0.1:{AUTH_SERVER[1]}"
            else:
                reply = "ERROR:NOT_FOUND_IN_TLD"
 
            resp_flags = flags | 0x8000
            self.sock.sendto(make_packet(msg_id, resp_flags, reply), addr)


# Authoritative Server
class AuthServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(AUTH_SERVER)
        print(f"[Auth Server] Started on port {AUTH_SERVER[1]}")
 
    def start(self):
        while True:
            data, addr = self.sock.recvfrom(1024)
            msg_id, flags, domain = read_packet(data)
            print(f"[Auth Server] Got query for '{domain}' (ID: {hex(msg_id)})")
 
            if domain in DNS_RECORDS:
                rec = DNS_RECORDS[domain]
                # serialize the record into a string
                a_part  = ",".join(rec["A"])
                ns_part = ",".join(rec["NS"])
                mx_part = ",".join(rec["MX"])
                reply = f"A:{a_part}|NS:{ns_part}|MX:{mx_part}"
            else:
                reply = "ERROR:NXDOMAIN"
 
            # AA flag = 0x0400 means authoritative answer
            resp_flags = flags | 0x8000 | 0x0400
            self.sock.sendto(make_packet(msg_id, resp_flags, reply), addr)
 

# Local Host (Client)
# runs on the user's machine, it checks cache first, then queries servers
class LocalHost:
    def __init__(self, cache_size=3):
        self.cache = OrderedDict()
        self.cache_size = cache_size
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(3)
 
    def send_query(self, server_addr, domain):
        # generate a random 16-bit transaction ID
        msg_id = random.randint(0, 65535)
        # flags = 0x0100 means RD (recursion desired) is set, QR=0 (query)
        packet = make_packet(msg_id, 0x0100, domain)
        self.sock.sendto(packet, server_addr)
 
        try:
            resp, _ = self.sock.recvfrom(1024)
            r_id, r_flags, r_data = read_packet(resp)
 
            # check that reply ID matches our query ID
            if r_id != msg_id:
                print("  [Warning] ID mismatch! Possible spoofing.")
                return None
 
            # show flags info
            qr = (r_flags >> 15) & 1
            aa = (r_flags >> 10) & 1
            print(f"  [Flags] ID={hex(msg_id)}  QR={qr}  AA={aa}  Flags=0x{r_flags:04X}")
 
            return r_data
        except socket.timeout:
            print("  [Error] Request timed out.")
            return None
 
    def auto_flush(self):
        # remove oldest entry if cache is full
        if len(self.cache) >= self.cache_size:
            oldest = next(iter(self.cache))
            print(f"  [Cache] Cache full! Removing oldest entry: '{oldest}'")
            del self.cache[oldest]
 
    def resolve(self, domain):
        print(f"\n{'='*50}")
        print(f"  Resolving: {domain}")
        print(f"{'='*50}")
 
        # Step 1: check local cache
        if domain in self.cache:
            print("  [Cache] HIT! Returning cached result.")
            self.show_result(domain, self.cache[domain])
            return
 
        print("  [Cache] MISS. Starting DNS lookup...\n")
 
        # Step 2: ask Root Server
        print(f"  [Step 1] Contacting Root Server ({ROOT_SERVER[1]})...")
        root_reply = self.send_query(ROOT_SERVER, domain)
        if root_reply is None or "ERROR" in root_reply:
            print(f"  [Error] Root Server failed: {root_reply}")
            return
 
        # root reply is like "127.0.0.1:5002"
        tld_ip, tld_port = root_reply.split(":")
        print(f"  [Step 1] Root referred us to TLD at {root_reply}")
 
        # Step 3: ask TLD Server
        print(f"\n  [Step 2] Contacting TLD Server ({tld_port})...")
        tld_reply = self.send_query((tld_ip, int(tld_port)), domain)
        if tld_reply is None or "ERROR" in tld_reply:
            print(f"  [Error] TLD Server failed: {tld_reply}")
            return
 
        auth_ip, auth_port = tld_reply.split(":")
        print(f"  [Step 2] TLD referred us to Auth at {tld_reply}")
 
        # Step 4: ask Authoritative Server
        print(f"\n  [Step 3] Contacting Authoritative Server ({auth_port})...")
        auth_reply = self.send_query((auth_ip, int(auth_port)), domain)
        if auth_reply is None or "ERROR" in auth_reply:
            print(f"  [Error] Auth Server failed: {auth_reply}")
            return
 
        # parse the record string
        record = self.parse_record(auth_reply)
 
        # save to cache
        self.auto_flush()
        self.cache[domain] = record
        print(f"  [Cache] Saved '{domain}' to cache.")
 
        self.show_result(domain, record)
 
    def parse_record(self, raw):
        result = {}
        for part in raw.split("|"):
            key, val = part.split(":", 1)
            result[key] = val.split(",")
        return result
 
    def show_result(self, domain, record):
        first_ip = record["A"][0]
        print(f"\n  {domain}/{first_ip}")
        print("  -- DNS INFORMATION --")
        print(f"  A:  {', '.join(record['A'])}")
        print(f"  NS: {', '.join(record['NS'])}")
        print(f"  MX: {', '.join(record['MX'])}")

 
def start_servers():
    root = RootServer()
    tld  = TLDServer()
    auth = AuthServer()
 
    threading.Thread(target=root.start, daemon=True).start()
    threading.Thread(target=tld.start,  daemon=True).start()
    threading.Thread(target=auth.start, daemon=True).start()
 
 
if __name__ == "__main__":
    print("Starting DNS Servers...\n")
    start_servers()
    time.sleep(1)  # wait for servers to bind
 
    pc = LocalHost(cache_size=3)
 
    print("\nAvailable domains: google.com, microsoft.com, yahoo.com, github.com")
    print("Commands: type a domain to resolve, 'cache' to see cache, 'exit' to quit\n")
 
    while True:
        try:
            user = input("dns> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
 
        if user == "exit":
            break
        elif user == "cache":
            if pc.cache:
                print("\n  Cached entries:")
                for k in pc.cache:
                    print(f"    - {k} -> {pc.cache[k]['A'][0]}")
            else:
                print("  Cache is empty.")
        elif user:
            pc.resolve(user)
 