#!/usr/bin/env python3
"""ETAP Kilit - Pardus ETAP istemcisi (PyQt5).
Bağımlılıklar: python3-pyqt5 python3-aiohttp python3-qrcode  (paket kurulumunda otomatik gelir)
"""
import asyncio, base64, datetime, fcntl, json, os, random, socket, subprocess, sys, time
import aiohttp, qrcode
from aiohttp import WSMsgType
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal

APP_DIR = "/opt/etap-kilit"
CFG_PATH = os.environ.get("ETAP_CFG", f"{APP_DIR}/config.json")
STATE_PATH = os.path.expanduser("~/.cache/etap-kilit/state.json")

# Renk paleti
C = dict(bg1="#0B1020", bg2="#16213A", card="#18223D", key="#1F2C4D", border="#2A3A66",
         text="#E8ECF8", muted="#8FA0C4", accent="#4F8CFF", amber="#F5B301", ok="#34D399", bad="#F87171")

FALLBACK_QUOTES = [
    "Hayatta en hakiki mürşit ilimdir, fendir. — Mustafa Kemal Atatürk",
    "Önemli olan, soru sormayı bırakmamaktır. — Albert Einstein",
    "Damlaya damlaya göl olur. — Atasözü",
]
SETTINGS0 = {"school": "", "quotes": FALLBACK_QUOTES, "quote_interval": 20, "announcement": "",
             "idle_shutdown_min": 25, "durations": [20, 40, 45, 80], "usb_block": True,
             "pardus_logo_b64": "", "school_logo_b64": "", "wallpaper_b64": "", "extend_min": 10}
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

K = 1.0   # ekran ölçek katsayısı (1080p = 1.0)


def S(n):
    return max(1, int(n * K))


def load_cfg():
    cfg = {"board_id": "", "server": "", "port": 8080, "psk": "", "discovery_port": 45454}
    try:
        cfg.update(json.load(open(CFG_PATH)))
    except Exception as e:
        print("config okunamadı:", e)
    cfg["board_id"] = cfg["board_id"] or socket.gethostname()
    return cfg


def load_settings(cfg):
    st = dict(SETTINGS0)
    for k in ("idle_shutdown_min", "durations", "usb_block"):
        if k in cfg:
            st[k] = cfg[k]
    try:
        st.update(json.load(open(STATE_PATH)))      # sunucudan son alınan ayarlar (çevrimdışı açılış için)
    except Exception:
        pass
    return st


def save_settings(st):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        json.dump(st, open(STATE_PATH, "w"), ensure_ascii=False)
    except Exception:
        pass


def get_mac():
    base = "/sys/class/net"
    for n in sorted(os.listdir(base)):
        if n != "lo" and os.path.exists(f"{base}/{n}/device"):
            try:
                return open(f"{base}/{n}/address").read().strip()
            except OSError:
                pass
    return ""


def desktop_dir():
    try:
        p = subprocess.check_output(["xdg-user-dir", "DESKTOP"], text=True).strip()
        if p:
            return p
    except Exception:
        pass
    return os.path.expanduser("~/Masaüstü" if os.path.isdir(os.path.expanduser("~/Masaüstü")) else "~/Desktop")


# ===================================================================== LOGOLAR
def pixmap_from_b64(b64):
    if not b64:
        return None
    pm = QtGui.QPixmap()
    return pm if pm.loadFromData(base64.b64decode(b64)) else None


def pardus_logo(st):
    """Sıra: ana programdan gelen logo -> pakete gömülü dosya -> sistem simge teması."""
    pm = pixmap_from_b64(st.get("pardus_logo_b64"))
    if pm:
        return pm
    for p in (f"{APP_DIR}/assets/pardus-logo.png", "/usr/share/pixmaps/pardus-logo.png",
              "/usr/share/pixmaps/pardus.png"):
        if os.path.exists(p):
            pm = QtGui.QPixmap(p)
            if not pm.isNull():
                return pm
    for name in ("distributor-logo-pardus", "pardus-logo", "pardus", "distributor-logo"):
        ic = QtGui.QIcon.fromTheme(name)
        if not ic.isNull():
            return ic.pixmap(256, 256)
    return None


def school_logo(st):
    pm = pixmap_from_b64(st.get("school_logo_b64"))
    if pm:
        return pm
    p = f"{APP_DIR}/assets/school-logo.png"
    if os.path.exists(p):
        pm = QtGui.QPixmap(p)
        return None if pm.isNull() else pm
    return None


def qr_pixmap(text, size):
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    m = qr.get_matrix()
    cell = max(1, size // len(m))
    pm = QtGui.QPixmap(cell * len(m), cell * len(m))
    pm.fill(Qt.white)
    p = QtGui.QPainter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#0B1020"))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * cell, y * cell, cell, cell)
    p.end()
    return pm


# ===================================================================== AĞ KATMANI
class Net(QtCore.QThread):
    sig_status = pyqtSignal(bool)
    sig_qr = pyqtSignal(str)
    sig_pin = pyqtSignal(bool, str, str)
    sig_cmd = pyqtSignal(dict)
    sig_settings = pyqtSignal(dict)
    sig_frame = pyqtSignal(bytes)

    def __init__(self, cfg):
        super().__init__()
        self.cfg, self.loop, self.ws, self.session = cfg, None, None, None

    def send(self, obj):
        if self.loop and self.ws is not None and not self.ws.closed:
            asyncio.run_coroutine_threadsafe(self.ws.send_str(json.dumps(obj)), self.loop)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main())

    async def discover(self):
        port = self.cfg["discovery_port"]

        def blocking():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                s.settimeout(12)
                data, _ = s.recvfrom(256)
                p = data.decode().split("|")
                return (p[1], int(p[2])) if p[0] == "ETAPLOCK" else None
            except Exception:
                return None
            finally:
                s.close()
        return await asyncio.get_running_loop().run_in_executor(None, blocking)

    async def main(self):
        while True:
            host, port = (self.cfg["server"], self.cfg["port"]) if self.cfg["server"] else (None, None)
            if not host:
                found = await self.discover()
                if not found:
                    self.sig_status.emit(False)
                    continue
                host, port = found
            try:
                async with aiohttp.ClientSession() as self.session:
                    async with self.session.ws_connect(f"http://{host}:{port}/ws", heartbeat=20,
                                                       max_msg_size=2 ** 24) as ws:
                        self.ws = ws
                        await ws.send_str(json.dumps({"type": "hello", "id": self.cfg["board_id"],
                                                      "mac": get_mac(), "psk": self.cfg["psk"]}))
                        self.sig_status.emit(True)
                        await self.reader(ws)
            except Exception as e:
                print("bağlantı hatası:", e)
            self.ws = None
            self.sig_status.emit(False)
            await asyncio.sleep(5)

    async def reader(self, ws):
        async for m in ws:
            if m.type == WSMsgType.BINARY:
                self.sig_frame.emit(bytes(m.data))
            elif m.type == WSMsgType.TEXT:
                d = json.loads(m.data)
                t = d.get("type")
                if t == "exec":
                    asyncio.create_task(self.do_exec(d))
                elif t == "file":
                    asyncio.create_task(self.do_file(d))
                elif t == "qr":
                    self.sig_qr.emit(d["url"])
                elif t == "pin_result":
                    self.sig_pin.emit(d["ok"], d.get("msg", ""), d.get("teacher", ""))
                elif t == "settings":
                    self.sig_settings.emit(d)
                else:
                    self.sig_cmd.emit(d)

    async def do_exec(self, d):
        try:
            p = await asyncio.create_subprocess_shell(d["cmd"], stdout=asyncio.subprocess.PIPE,
                                                      stderr=asyncio.subprocess.STDOUT)
            try:
                out, _ = await asyncio.wait_for(p.communicate(), 60)
            except asyncio.TimeoutError:
                p.kill()
                out = b"[zaman asimi]"
            res = {"rc": p.returncode, "out": out.decode(errors="replace")[-65536:]}
        except Exception as e:
            res = {"rc": -1, "out": str(e)}
        self.send({"type": "exec_result", "rid": d["rid"], **res})

    async def do_file(self, d):
        name = os.path.basename(d["name"])
        dest = os.path.join(desktop_dir(), name)
        try:
            async with self.session.get(d["url"], headers={"X-PSK": self.cfg["psk"]}) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in r.content.iter_chunked(1 << 16):
                        f.write(chunk)
            self.sig_cmd.emit({"type": "msg", "text": f"Dosya masaüstüne alındı: {name}", "secs": 8})
        except Exception as e:
            print("dosya hatası:", e)


# ===================================================================== KİLİT EKRANI
def lock_css():
    return f"""
    QLabel {{ background: transparent; color: {C['text']}; font-family: 'Noto Sans','Ubuntu','DejaVu Sans',sans-serif; }}
    QLabel#school {{ font-size: {S(30)}px; font-weight: 600; }}
    QLabel#clock {{ font-size: {S(190)}px; font-weight: 300; }}
    QLabel#date {{ font-size: {S(36)}px; color: {C['muted']}; }}
    QLabel#conn {{ font-size: {S(18)}px; }}
    QFrame#card {{ background: rgba(24,34,61,235); border: 1px solid {C['border']}; border-radius: {S(28)}px; }}
    QFrame#ann {{ background: rgba(245,179,1,30); border: 1px solid {C['amber']}; border-radius: {S(18)}px; }}
    QLabel#annT {{ font-size: {S(18)}px; font-weight: 700; color: {C['amber']}; letter-spacing: 2px; }}
    QLabel#annX {{ font-size: {S(28)}px; }}
    QFrame#quote {{ background: rgba(24,34,61,170); border-left: {S(5)}px solid {C['accent']}; border-radius: {S(14)}px; }}
    QLabel#qt {{ font-size: {S(28)}px; font-style: italic; }}
    QLabel#qa {{ font-size: {S(20)}px; color: {C['muted']}; }}
    QLabel#title {{ font-size: {S(32)}px; font-weight: 700; }}
    QLabel#step {{ font-size: {S(17)}px; color: {C['muted']}; }}
    QLabel#qr {{ background: white; border-radius: {S(16)}px; padding: {S(8)}px; color: #0B1020; }}
    QLabel#status {{ font-size: {S(18)}px; }}
    QLabel#count {{ font-size: {S(20)}px; color: {C['amber']}; }}
    QPushButton#key {{ background: {C['key']}; color: white; border: 1px solid {C['border']};
        border-radius: {S(14)}px; font-size: {S(26)}px; min-height: {S(58)}px; }}
    QPushButton#key:pressed {{ background: {C['accent']}; }}
    QPushButton#dur {{ background: {C['accent']}; color: white; border: 0; border-radius: {S(16)}px;
        font-size: {S(30)}px; font-weight: 600; min-height: {S(84)}px; min-width: {S(150)}px; }}
    QPushButton#dur:pressed {{ background: #3B6FD6; }}
    QPushButton#ghost {{ background: transparent; color: {C['muted']}; border: 1px solid {C['border']};
        border-radius: {S(12)}px; font-size: {S(20)}px; padding: {S(10)}px {S(20)}px; }}
    QSpinBox {{ background: {C['bg1']}; color: white; border: 1px solid {C['border']}; border-radius: {S(10)}px;
        font-size: {S(24)}px; padding: {S(6)}px; }}
    QProgressBar {{ background: rgba(255,255,255,20); border: 0; border-radius: {S(3)}px; }}
    QProgressBar::chunk {{ background: {C['amber']}; border-radius: {S(3)}px; }}
    """


class LockScreen(QtWidgets.QWidget):
    pin_submitted = pyqtSignal(str)
    minutes_chosen = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.pin, self.quotes, self.qi, self._anims = "", [], -1, []
        self.wp, self._bg, self._wp_src = None, None, None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setStyleSheet(lock_css())
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(S(70), S(50), S(70), S(34))
        outer.setSpacing(S(16))
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(S(50))
        outer.addLayout(body, 1)
        leftw = QtWidgets.QWidget()                      # sol sütun dar tutulur: ortadaki logo görünür kalır
        leftw.setLayout(self._build_left())
        leftw.setFixedWidth(S(680))
        body.addWidget(leftw, 0)
        body.addStretch(1)
        body.addWidget(self._build_card(), 0, Qt.AlignVCenter)
        bottom = QtWidgets.QVBoxLayout()
        bottom.setSpacing(S(8))
        self.count = QtWidgets.QLabel()
        self.count.setObjectName("count")
        self.count.setAlignment(Qt.AlignCenter)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(S(6))
        bottom.addWidget(self.count)
        bottom.addWidget(self.bar)
        outer.addLayout(bottom)
        self.qtimer = QtCore.QTimer(self)
        self.qtimer.timeout.connect(self.next_quote)
        self.refresh_pin()
        self.update_clock()

    # ---- sol taraf: marka, saat, duyuru, söz
    def _build_left(self):
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(S(12))
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(S(18))
        self.lg_pardus, self.lg_school = QtWidgets.QLabel(), QtWidgets.QLabel()
        self.school = QtWidgets.QLabel()
        self.school.setObjectName("school")
        self.conn = QtWidgets.QLabel()
        self.conn.setObjectName("conn")
        for w in (self.lg_pardus, self.lg_school):
            w.setScaledContents(False)
        head.addWidget(self.lg_pardus)
        head.addWidget(self.lg_school)
        head.addWidget(self.school, 1)
        head.addWidget(self.conn)
        left.addLayout(head)
        left.addStretch(2)
        self.clock = QtWidgets.QLabel("00:00")
        self.clock.setObjectName("clock")
        self.date = QtWidgets.QLabel()
        self.date.setObjectName("date")
        left.addWidget(self.clock)
        left.addWidget(self.date)
        left.addStretch(2)
        self.ann = QtWidgets.QFrame()
        self.ann.setObjectName("ann")
        av = QtWidgets.QVBoxLayout(self.ann)
        av.setContentsMargins(S(26), S(18), S(26), S(18))
        at = QtWidgets.QLabel("📢  DUYURU")
        at.setObjectName("annT")
        self.ann_text = QtWidgets.QLabel()
        self.ann_text.setObjectName("annX")
        self.ann_text.setWordWrap(True)
        av.addWidget(at)
        av.addWidget(self.ann_text)
        self.ann.hide()
        left.addWidget(self.ann)
        self.qcard = QtWidgets.QFrame()
        self.qcard.setObjectName("quote")
        qv = QtWidgets.QVBoxLayout(self.qcard)
        qv.setContentsMargins(S(30), S(22), S(30), S(22))
        self.qt, self.qa = QtWidgets.QLabel(), QtWidgets.QLabel()
        self.qt.setObjectName("qt")
        self.qt.setWordWrap(True)
        self.qa.setObjectName("qa")
        qv.addWidget(self.qt)
        qv.addWidget(self.qa)
        self.qfx = QtWidgets.QGraphicsOpacityEffect(self.qcard)
        self.qcard.setGraphicsEffect(self.qfx)
        left.addWidget(self.qcard)
        return left

    # ---- sağ taraf: kart (karekod + PIN / süre seçimi)
    def _build_card(self):
        card = QtWidgets.QFrame()
        card.setObjectName("card")
        card.setFixedWidth(S(780))
        cv = QtWidgets.QVBoxLayout(card)
        cv.setContentsMargins(S(30), S(28), S(30), S(24))
        self.stack = QtWidgets.QStackedWidget()
        cv.addWidget(self.stack)

        p0 = QtWidgets.QWidget()
        v0 = QtWidgets.QVBoxLayout(p0)
        v0.setContentsMargins(0, 0, 0, 0)
        title = QtWidgets.QLabel("🔒  Tahta Kilitli")
        title.setObjectName("title")
        v0.addWidget(title)
        v0.addSpacing(S(10))
        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(S(30))
        lc = QtWidgets.QVBoxLayout()
        s1 = QtWidgets.QLabel("① Karekodu telefonunuzla okutun")
        s1.setObjectName("step")
        self.qr = QtWidgets.QLabel("Sunucuya\nbağlanılıyor...")
        self.qr.setObjectName("qr")
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setFixedSize(S(300), S(300))
        lc.addWidget(s1)
        lc.addWidget(self.qr)
        lc.addStretch(1)
        rc = QtWidgets.QVBoxLayout()
        s2 = QtWidgets.QLabel("② Telefonda görünen 6 haneli PIN'i girin")
        s2.setObjectName("step")
        rc.addWidget(s2)
        cells = QtWidgets.QHBoxLayout()
        cells.setSpacing(S(8))
        self.cells = []
        for _ in range(6):
            c = QtWidgets.QLabel()
            c.setAlignment(Qt.AlignCenter)
            c.setFixedSize(S(54), S(64))
            self.cells.append(c)
            cells.addWidget(c)
        rc.addLayout(cells)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(S(8))
        for i, k in enumerate(["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✕"]):
            b = QtWidgets.QPushButton(k)
            b.setObjectName("key")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _, k=k: self.key(k))
            grid.addWidget(b, i // 3, i % 3)
        rc.addLayout(grid)
        cols.addLayout(lc)
        cols.addLayout(rc, 1)
        v0.addLayout(cols)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        v0.addWidget(self.status)
        self.stack.addWidget(p0)

        p1 = QtWidgets.QWidget()
        v1 = QtWidgets.QVBoxLayout(p1)
        self.hello = QtWidgets.QLabel("Hoş geldiniz")
        self.hello.setObjectName("step")
        self.hello.setAlignment(Qt.AlignCenter)
        q = QtWidgets.QLabel("Tahta kaç dakika açık kalsın?")
        q.setObjectName("title")
        q.setAlignment(Qt.AlignCenter)
        self.durg = QtWidgets.QGridLayout()
        self.durg.setSpacing(S(14))
        row = QtWidgets.QHBoxLayout()
        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(5, 240)
        self.spin.setValue(40)
        self.spin.setSuffix(" dk")
        ok = QtWidgets.QPushButton("Özel süreyle aç")
        ok.setObjectName("ghost")
        ok.clicked.connect(lambda: self.minutes_chosen.emit(self.spin.value()))
        back = QtWidgets.QPushButton("Vazgeç")
        back.setObjectName("ghost")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        row.addStretch(1)
        row.addWidget(self.spin)
        row.addWidget(ok)
        row.addWidget(back)
        row.addStretch(1)
        v1.addWidget(self.hello)
        v1.addWidget(q)
        v1.addSpacing(S(16))
        v1.addLayout(self.durg)
        v1.addSpacing(S(16))
        v1.addLayout(row)
        v1.addStretch(1)
        self.stack.addWidget(p1)
        return card

    # ---- arka plan çizimi
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        if self._bg is not None:                          # ortasında Pardus logosu olan arkaplan görseli
            p.drawPixmap((self.width() - self._bg.width()) // 2, (self.height() - self._bg.height()) // 2, self._bg)
            g = QtGui.QLinearGradient(0, 0, self.width(), 0)   # yazıların okunması için kenarlara hafif karartma
            g.setColorAt(0, QtGui.QColor(7, 11, 24, 150))
            g.setColorAt(.5, QtGui.QColor(7, 11, 24, 25))
            g.setColorAt(1, QtGui.QColor(7, 11, 24, 150))
            p.fillRect(self.rect(), g)
            return
        g = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QtGui.QColor(C["bg1"]))
        g.setColorAt(1, QtGui.QColor(C["bg2"]))
        p.fillRect(self.rect(), g)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(79, 140, 255, 26))
        p.drawEllipse(QtCore.QPoint(int(self.width() * .88), int(self.height() * .08)), S(420), S(420))
        p.setBrush(QtGui.QColor(245, 179, 1, 16))
        p.drawEllipse(QtCore.QPoint(int(self.width() * .08), int(self.height() * .98)), S(320), S(320))

    def set_wallpaper(self, b64):
        if b64 == self._wp_src:
            return
        self._wp_src = b64
        self.wp = pixmap_from_b64(b64)
        self._rescale()
        self.update()

    def _rescale(self):
        if not self.wp:
            self._bg = None
            return
        size = self.size() if self.width() > 50 else QtWidgets.QApplication.primaryScreen().geometry().size()
        self._bg = self.wp.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

    def resizeEvent(self, e):
        self._rescale()
        super().resizeEvent(e)

    # ---- ayarlar, saat, söz
    def apply(self, st):
        self.set_wallpaper(st.get("wallpaper_b64", ""))
        self.school.setText(st.get("school", ""))
        has_wp = self._bg is not None
        for lbl, pm in ((self.lg_pardus, None if has_wp else pardus_logo(st)), (self.lg_school, school_logo(st))):
            if pm:
                lbl.setPixmap(pm.scaledToHeight(S(64), Qt.SmoothTransformation))
                lbl.show()
            else:
                lbl.hide()
        text = (st.get("announcement") or "").strip()
        self.ann_text.setText(text)
        self.ann.setVisible(bool(text))
        self.quotes = [q for q in st.get("quotes", []) if q.strip()] or FALLBACK_QUOTES
        self.qtimer.start(max(5, int(st.get("quote_interval", 20))) * 1000)
        self.set_durations(st.get("durations", [20, 40, 45, 80]))
        if self.qi < 0 or self.qi >= len(self.quotes):
            self.qi = -1
            self.next_quote(animate=False)

    def set_durations(self, durations):
        while self.durg.count():
            w = self.durg.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, m in enumerate(durations):
            b = QtWidgets.QPushButton(f"{m} dk")
            b.setObjectName("dur")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _, m=m: self.minutes_chosen.emit(m))
            self.durg.addWidget(b, i // 2, i % 2)

    def update_clock(self):
        now = datetime.datetime.now()
        self.clock.setText(now.strftime("%H:%M"))
        self.date.setText(f"{now.day} {MONTHS[now.month - 1]} {now.year}, {DAYS[now.weekday()]}")

    def next_quote(self, animate=True):
        if not self.quotes:
            return
        self.qi = random.choice([i for i in range(len(self.quotes)) if i != self.qi] or [0])
        text, _, author = self.quotes[self.qi].rpartition(" — ")
        if not text:
            text, author = author, ""

        def swap():
            self.qt.setText(f"“{text}”")
            self.qa.setText(f"— {author}" if author else "")
            fade(0.0, 1.0, 600)

        def fade(a, b, ms, then=None):
            an = QtCore.QPropertyAnimation(self.qfx, b"opacity", self)
            an.setDuration(ms)
            an.setStartValue(a)
            an.setEndValue(b)
            if then:
                an.finished.connect(then)
            self._anims = [an]
            an.start()
        if animate and self.isVisible():
            fade(1.0, 0.0, 450, swap)
        else:
            swap()

    def set_conn(self, ok):
        self.conn.setText("● Bağlı" if ok else "● Sunucuya bağlı değil")
        self.conn.setStyleSheet(f"color:{C['ok'] if ok else C['bad']};")

    def set_countdown(self, sec, total):
        self.count.setText(f"⏻  Kilit açılmazsa bilgisayar {sec // 60:02d}:{sec % 60:02d} sonra kapanacak")
        self.bar.setMaximum(max(1, total))
        self.bar.setValue(sec)

    # ---- PIN girişi
    def cell_css(self, filled):
        b = C["accent"] if filled else C["border"]
        return (f"background:{C['bg1']};border:2px solid {b};border-radius:{S(12)}px;"
                f"color:white;font-size:{S(26)}px;")

    def refresh_pin(self):
        for i, c in enumerate(self.cells):
            f = i < len(self.pin)
            c.setText("●" if f else "")
            c.setStyleSheet(self.cell_css(f))

    def key(self, k):
        if k == "⌫":
            self.pin = self.pin[:-1]
        elif k == "✕":
            self.pin = ""
        elif len(self.pin) < 6 and k.isdigit():
            self.pin += k
        self.refresh_pin()
        if len(self.pin) == 6:
            self.set_status("Doğrulanıyor...")
            self.pin_submitted.emit(self.pin)
            self.pin = ""
            self.refresh_pin()

    def keyPressEvent(self, e):
        t = e.text()
        if t.isdigit():
            self.key(t)
        elif e.key() == Qt.Key_Backspace:
            self.key("⌫")
        e.accept()

    def set_status(self, text, err=False):
        self.status.setStyleSheet(f"color:{C['bad'] if err else C['muted']};")
        self.status.setText(text)

    def set_qr(self, url):
        self.qr.setPixmap(qr_pixmap(url, S(280)))

    def closeEvent(self, e):
        e.ignore()


# ===================================================================== KÜÇÜK PENCERELER
class Panel(QtWidgets.QWidget):
    lock_clicked = pyqtSignal()
    shutdown_clicked = pyqtSignal()
    extend_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setObjectName("panel")
        self.setStyleSheet(f"""
            QWidget#panel {{ background:{C['bg1']}; border:1px solid {C['border']}; border-radius:{S(16)}px; }}
            QLabel {{ background:transparent; color:{C['text']}; font-family:'Noto Sans','Ubuntu',sans-serif; }}
            QLabel#cap {{ color:{C['muted']}; font-size:{S(15)}px; }}
            QLabel#time {{ font-size:{S(42)}px; font-weight:600; }}
            QPushButton {{ background:{C['key']}; color:white; border:1px solid {C['border']}; border-radius:{S(10)}px;
                           font-size:{S(18)}px; min-height:{S(46)}px; }}
            QPushButton:pressed {{ background:{C['accent']}; }}
            QPushButton#danger {{ border-color:{C['bad']}; color:{C['bad']}; }}
        """)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(S(18), S(14), S(18), S(12))
        v.setSpacing(S(8))
        cap = QtWidgets.QLabel("ETAP Kilit · kalan süre")
        cap.setObjectName("cap")
        self.time = QtWidgets.QLabel("--:--")
        self.time.setObjectName("time")
        self.b_ext = QtWidgets.QPushButton("⏱  Süre Ekle")
        b1 = QtWidgets.QPushButton("🔒  Kilitle")
        b2 = QtWidgets.QPushButton("⏻  Bilgisayarı Kapat")
        b2.setObjectName("danger")
        b3 = QtWidgets.QPushButton("👁  Bu pencereyi gizle")     # diğer düğmelerle aynı boyut ve stil
        self.b_ext.clicked.connect(self.extend_clicked)
        b1.clicked.connect(self.lock_clicked)
        b2.clicked.connect(self.shutdown_clicked)
        b3.clicked.connect(self.hide)
        for w in (cap, self.time, self.b_ext, b1, b2, b3):
            v.addWidget(w)
        self.setFixedWidth(S(300))

    def set_extend(self, minutes):
        self.b_ext.setText(f"⏱  Süre Ekle (+{int(minutes)} dk)")

    def set_remaining(self, sec):
        self.time.setText(f"{sec // 60:02d}:{sec % 60:02d}")

    def present(self):
        self.adjustSize()
        g = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.move(g.right() - self.width() - 14, g.bottom() - self.height() - 14)
        self.show()
        self.raise_()


class Popup(QtWidgets.QWidget):
    """Üstte duran, modern duyuru penceresi."""

    def __init__(self, text, secs):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet(f"""
            QWidget#pp {{ background:{C['bg1']}; border:2px solid {C['amber']}; border-radius:{S(18)}px; }}
            QLabel {{ background:transparent; color:{C['text']}; font-family:'Noto Sans','Ubuntu',sans-serif; }}
            QLabel#t {{ color:{C['amber']}; font-size:{S(18)}px; font-weight:700; letter-spacing:2px; }}
            QLabel#x {{ font-size:{S(30)}px; }}
            QPushButton {{ background:{C['accent']}; color:white; border:0; border-radius:{S(10)}px;
                           font-size:{S(20)}px; min-height:{S(48)}px; padding:0 {S(30)}px; }}
        """)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        f = QtWidgets.QFrame()
        f.setObjectName("pp")
        outer.addWidget(f)
        v = QtWidgets.QVBoxLayout(f)
        v.setContentsMargins(S(34), S(26), S(34), S(26))
        t = QtWidgets.QLabel("📢  DUYURU")
        t.setObjectName("t")
        x = QtWidgets.QLabel(text)
        x.setObjectName("x")
        x.setWordWrap(True)
        b = QtWidgets.QPushButton("Tamam")
        b.clicked.connect(self.close)
        v.addWidget(t)
        v.addWidget(x)
        v.addSpacing(S(10))
        v.addWidget(b, 0, Qt.AlignRight)
        self.setFixedWidth(S(760))
        QtCore.QTimer.singleShot(max(3, secs) * 1000, self.close)

    def present(self):
        self.adjustSize()
        g = QtWidgets.QApplication.primaryScreen().geometry()
        self.move(g.center().x() - self.width() // 2, S(90))
        self.show()
        self.raise_()


def confirm(text):
    d = QtWidgets.QDialog()
    d.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    d.setStyleSheet(f"""
        QDialog {{ background:{C['bg1']}; border:1px solid {C['border']}; border-radius:{S(16)}px; }}
        QLabel {{ color:{C['text']}; font-size:{S(26)}px; font-family:'Noto Sans','Ubuntu',sans-serif; }}
        QPushButton {{ background:{C['key']}; color:white; border:1px solid {C['border']}; border-radius:{S(10)}px;
                       font-size:{S(20)}px; min-height:{S(50)}px; min-width:{S(130)}px; }}
        QPushButton#yes {{ background:{C['bad']}; border:0; }}
    """)
    v = QtWidgets.QVBoxLayout(d)
    v.setContentsMargins(S(34), S(28), S(34), S(24))
    v.addWidget(QtWidgets.QLabel(text))
    h = QtWidgets.QHBoxLayout()
    no, yes = QtWidgets.QPushButton("Vazgeç"), QtWidgets.QPushButton("Evet, kapat")
    yes.setObjectName("yes")
    no.clicked.connect(d.reject)
    yes.clicked.connect(d.accept)
    h.addStretch(1)
    h.addWidget(no)
    h.addWidget(yes)
    v.addLayout(h)
    return d.exec_() == QtWidgets.QDialog.Accepted


class MirrorView(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background:black;")
        self.setAlignment(Qt.AlignCenter)

    def show_frame(self, data):
        pm = QtGui.QPixmap()
        if pm.loadFromData(data):
            self.setPixmap(pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def start(self):
        self.setGeometry(QtWidgets.QApplication.primaryScreen().geometry())
        self.show()

    def closeEvent(self, e):
        e.ignore()


# ===================================================================== DENETLEYİCİ
class Controller(QtCore.QObject):
    def __init__(self, cfg):
        super().__init__()
        self.cfg, self.st = cfg, load_settings(cfg)
        self.state, self.deadline, self.idle_total, self.n = "locked", 0, 1, 0
        self.warned, self.connected, self.popups = set(), False, []
        self.net = Net(cfg)
        self.lockscr = LockScreen()
        self.panel = Panel()
        self.mirror = MirrorView()
        icon = QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.tray = QtWidgets.QSystemTrayIcon(icon)
        self.tray_menu = QtWidgets.QMenu()
        self.tray_menu.setStyleSheet(
            f"QMenu {{ background:{C['bg1']}; color:{C['text']}; border:1px solid {C['border']}; padding:{S(6)}px; }}"
            f"QMenu::item {{ padding:{S(10)}px {S(28)}px; color:{C['text']}; }}"
            f"QMenu::item:selected {{ background:{C['accent']}; color:white; }}")
        self.tray_menu.addAction("Kontrol panelini göster", self.panel.present)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda *_: self.panel.present())

        self.net.sig_status.connect(self.on_status)
        self.net.sig_qr.connect(self.lockscr.set_qr)
        self.net.sig_pin.connect(self.on_pin_result)
        self.net.sig_cmd.connect(self.on_cmd)
        self.net.sig_settings.connect(self.on_settings)
        self.net.sig_frame.connect(self.on_frame)
        self.lockscr.pin_submitted.connect(lambda p: self.net.send({"type": "verify_pin", "pin": p}))
        self.lockscr.minutes_chosen.connect(self.unlock)
        self.panel.lock_clicked.connect(self.lock)
        self.panel.shutdown_clicked.connect(self.confirm_shutdown)
        self.panel.extend_clicked.connect(self.extend)

        self.panel.set_extend(self.st.get("extend_min", 10))
        self.lockscr.apply(self.st)
        self.lockscr.set_conn(False)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.net.start()
        self.lock()

    def remaining(self):
        return max(0, int(self.deadline - time.monotonic()))

    def power(self, what):
        subprocess.Popen(["sudo", "-n", "systemctl", what])

    def usb(self, block):
        if self.st.get("usb_block", True):
            subprocess.Popen(["sudo", "-n", "/usr/local/sbin/etap-usb", "block" if block else "allow"])

    def send_state(self):
        self.net.send({"type": "state", "state": self.state, "remaining": self.remaining()})

    # ---- durum makinesi
    def lock(self):
        self.state = "locked"
        self.idle_total = int(self.st.get("idle_shutdown_min", 25)) * 60     # otomatik kapanma sayacı
        self.deadline = time.monotonic() + self.idle_total
        self.warned.clear()
        self.panel.hide()
        self.mirror.hide()
        self.lockscr.pin = ""
        self.lockscr.refresh_pin()
        self.lockscr.stack.setCurrentIndex(0)
        self.lockscr.set_status("")
        self.lockscr.setGeometry(QtWidgets.QApplication.primaryScreen().geometry())
        self.lockscr.show()
        self.lockscr.raise_()
        self.lockscr.activateWindow()
        self.lockscr.grabKeyboard()
        self.usb(True)
        self.net.send({"type": "need_qr"})
        self.send_state()

    def unlock(self, minutes):
        self.state = "unlocked"
        self.deadline = time.monotonic() + minutes * 60                        # ders süresi sayacı
        self.warned.clear()
        self.lockscr.releaseKeyboard()
        self.lockscr.hide()
        self.usb(False)
        self.tray.show()
        self.panel.set_remaining(minutes * 60)
        self.panel.present()
        self.send_state()

    def extend(self):
        """Sağ alttaki 'Süre Ekle' düğmesi: ders süresini ayarlardaki dakika kadar uzatır."""
        if self.state != "unlocked":
            return
        add = int(self.st.get("extend_min", 10)) * 60
        self.deadline = max(self.deadline, time.monotonic()) + add
        rem = self.remaining()
        self.warned = {m for m in self.warned if rem <= m}      # uzayan süre için uyarılar yeniden kurulsun
        self.panel.set_remaining(rem)
        self.send_state()

    def tick(self):
        self.n += 1
        rem = self.remaining()
        if self.state == "locked":
            self.lockscr.update_clock()
            self.lockscr.set_countdown(rem, self.idle_total)
            if rem <= 0:
                self.power("poweroff")
                self.deadline = time.monotonic() + 3600
            if self.n % 45 == 0 and self.lockscr.stack.currentIndex() == 0:
                self.net.send({"type": "need_qr"})                              # karekodu yenile
            self.lockscr.raise_()
            self.lockscr.grabKeyboard()
        else:
            self.panel.set_remaining(rem)
            for mark in (300, 60):
                if rem <= mark and mark not in self.warned:
                    self.warned.add(mark)
                    self.panel.present()
                    self.show_msg(f"Kilitlenmeye {mark // 60} dakika kaldı.", 8)
            if rem <= 0:
                self.lock()
        if self.n % 5 == 0:
            self.send_state()

    # ---- ağdan gelenler
    def on_status(self, ok):
        self.connected = ok
        self.lockscr.set_conn(ok)
        if ok:
            self.net.send({"type": "need_qr"} if self.state == "locked" else {"type": "state", "state": self.state,
                                                                             "remaining": self.remaining()})

    def on_settings(self, d):
        d.pop("type", None)
        self.st.update(d)
        save_settings(self.st)
        self.panel.set_extend(self.st.get("extend_min", 10))
        self.lockscr.apply(self.st)

    def on_pin_result(self, ok, msg, teacher):
        if ok:
            self.lockscr.set_status("")
            self.lockscr.hello.setText(f"Hoş geldiniz, {teacher}" if teacher else "Hoş geldiniz")
            self.lockscr.stack.setCurrentIndex(1)
        else:
            self.lockscr.set_status(msg or "Hatalı PIN", True)

    def on_cmd(self, d):
        t = d.get("type")
        if t == "lock":
            self.lock()
        elif t == "unlock":
            self.unlock(int(d.get("minutes", 40)))
        elif t == "shutdown":
            self.power("poweroff")
        elif t == "reboot":
            self.power("reboot")
        elif t == "msg":
            self.show_msg(d.get("text", ""), int(d.get("secs", 15)))
        elif t == "mirror":
            if d.get("on") and self.state == "unlocked":
                self.mirror.start()
            else:
                self.mirror.hide()

    def on_frame(self, data):
        if self.mirror.isVisible():
            self.mirror.show_frame(data)

    def show_msg(self, text, secs):
        p = Popup(text, secs)
        self.popups = [x for x in self.popups if x.isVisible()] + [p]
        p.present()

    def confirm_shutdown(self):
        if confirm("Bilgisayar kapatılsın mı?"):
            self.power("poweroff")


def main():
    global K
    lockf = open("/tmp/etap-kilit.lock", "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    g = app.primaryScreen().geometry()
    K = max(0.5, min(g.height() / 1080, g.width() / 1920))
    ctrl = Controller(load_cfg())  # noqa: F841
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
