#!/usr/bin/env python3
"""ETAP Kilit Yönetimi - Windows ana programı (PyQt5).
Sunucu (core.py) arka planda çalışır; bu dosya modern yönetim arayüzünü sağlar.
Ağ işlemleri asyncio iş parçacığında yapılır, arayüz hiçbir zaman beklemez.
"""
import base64, datetime, html, sys
from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QSpinBox, QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QCheckBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QScrollArea)

import core, theme, pkgbuild, webexport, wallpaper
from quotes_tr import DEFAULT_QUOTES

P = theme.P
KIND_LABEL = {"unlock": "Kilit açma", "lock": "Kilitleme", "shutdown": "Kapatma", "reboot": "Yeniden başlatma",
              "msg": "Mesaj", "mirror": "Ekran paylaşımı"}


# ------------------------------------------------------------------ yardımcılar
class Bridge(QtCore.QObject):
    """Arka plan (asyncio) sonuçlarını arayüz iş parçacığına güvenle taşır."""
    done = pyqtSignal(object, object)

    def __init__(self):
        super().__init__()
        self.done.connect(self._dispatch)

    def _dispatch(self, cb, res):
        if cb:
            cb(res)

    def run(self, coro, cb=None):
        fut = core.submit(coro)

        def fin(f):
            try:
                res = f.result()
            except Exception as e:
                core.log("error", f"İç hata: {e}")
                res = {"error": str(e)}
            self.done.emit(cb, res)
        fut.add_done_callback(fin)


bridge = Bridge()


def client_src():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "client_src" / "etap_client.py"
    return Path(__file__).resolve().parent.parent / "client" / "etap_client.py"


def app_icon(size=64):
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    g = QtGui.QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QtGui.QColor("#4F8CFF"))
    g.setColorAt(1, QtGui.QColor("#6D5BFF"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QtCore.QRectF(0, 0, size, size), size * .22, size * .22)
    p.setBrush(Qt.white)
    p.drawRoundedRect(QtCore.QRectF(size * .28, size * .46, size * .44, size * .32), size * .06, size * .06)
    p.setPen(QtGui.QPen(Qt.white, size * .07))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QtCore.QRectF(size * .34, size * .2, size * .32, size * .4), 0, 180 * 16)
    p.end()
    return pm


def make_check_icon():
    """Onay kutularındaki beyaz tik işaretini üretir (QSS image: için dosya gerekir)."""
    path = core.APPDIR / "check.png"
    pm = QtGui.QPixmap(32, 32)
    pm.fill(Qt.transparent)
    qp = QtGui.QPainter(pm)
    qp.setRenderHint(QtGui.QPainter.Antialiasing)
    qp.setPen(QtGui.QPen(Qt.white, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    qp.drawPolyline(QtGui.QPolygon([QtCore.QPoint(8, 17), QtCore.QPoint(14, 23), QtCore.QPoint(24, 10)]))
    qp.end()
    pm.save(str(path))
    return path.as_posix()


def card():
    f = QFrame()
    f.setObjectName("card")
    return f


def lbl(text, name=None, wrap=False):
    l = QLabel(text)
    if name:
        l.setObjectName(name)
    l.setWordWrap(wrap)
    return l


def btn(text, variant=None, slot=None):
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if slot:
        b.clicked.connect(lambda _=False: slot())
    b.setCursor(Qt.PointingHandCursor)
    return b


def header(title, sub):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    v.addWidget(lbl(title, "h1"))
    v.addWidget(lbl(sub, "sub"))
    return w


def page_layout(page, title, sub):
    v = QVBoxLayout(page)
    v.setContentsMargins(30, 26, 30, 24)
    v.setSpacing(16)
    v.addWidget(header(title, sub))
    return v


def fmt(sec):
    return "-" if sec is None else f"{sec // 60:02d}:{sec % 60:02d}"


def encode_logo(path, h=256):
    img = QtGui.QImage(path)
    if img.isNull():
        return ""
    if img.height() > h:
        img = img.scaledToHeight(h, Qt.SmoothTransformation)
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(ba)).decode()


class Stat(QFrame):
    def __init__(self, title, color):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 14, 20, 14)
        v.setSpacing(0)
        v.addWidget(lbl(title, "muted"))
        self.v = lbl("0", "statv")
        self.v.setStyleSheet(f"color:{color};")
        v.addWidget(self.v)

    def set(self, n):
        self.v.setText(str(n))


class AllBox(QCheckBox):
    """Tümünü Seç / Seçimi Kaldır: 'kısmi' durumdan tıklanınca hepsini seçer."""

    def nextCheckState(self):
        self.setCheckState(Qt.Unchecked if self.checkState() == Qt.Checked else Qt.Checked)


# ------------------------------------------------------------------ Tahtalar
class BoardsPage(QWidget):
    COLS = ["", "Tahta", "IP adresi", "Bağlantı", "Kilit", "Süre", "Öğretmen", "MAC"]

    def __init__(self, main):
        super().__init__()
        self.main, self.ids, self._updating = main, [], False
        v = page_layout(self, "Tahtalar", "İşlem yapmak istediğiniz tahtaları işaretleyin")
        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.st = {k: Stat(t, c) for k, t, c in (("total", "Toplam tahta", P["text"]), ("online", "Çevrimiçi", P["ok"]),
                                                  ("open", "Kilidi açık", P["accent"]), ("locked", "Kilitli", P["amber"]))}
        for s in self.st.values():
            stats.addWidget(s)
        v.addLayout(stats)

        tb = card()
        r2 = QHBoxLayout(tb)
        r2.setContentsMargins(16, 12, 16, 12)
        r2.setSpacing(8)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(40)
        self.minutes.setSuffix(" dk")
        r2.addWidget(self.minutes)
        r2.addWidget(btn("🔓  Kilidi Aç", "primary", lambda: self.act("unlock", minutes=self.minutes.value())))
        r2.addWidget(btn("🔒  Kilitle", None, lambda: self.act("lock")))
        r2.addSpacing(10)
        r2.addWidget(btn("⏻  Uyandır (WOL)", None, lambda: self.act("wol")))
        r2.addWidget(btn("↻  Yeniden Başlat", None, lambda: self.act("reboot")))
        r2.addWidget(btn("Kapat", "danger", lambda: self.act("shutdown")))
        r2.addStretch(1)
        r2.addWidget(btn("🖥  Ekranı Paylaş", "amber", lambda: self.act("mirror", on=True)))
        r2.addWidget(btn("Paylaşımı Durdur", None, lambda: self.act("mirror", on=False)))
        v.addWidget(tb)

        lc = card()
        lv = QVBoxLayout(lc)
        lv.setContentsMargins(14, 12, 14, 8)
        lv.setSpacing(6)
        top = QHBoxLayout()
        self.chk_all = AllBox("Tümünü Seç / Seçimi Kaldır")
        self.chk_all.setTristate(True)
        self.chk_all.setCursor(Qt.PointingHandCursor)
        self.chk_all.clicked.connect(lambda _=False: self.set_all_checked(self.chk_all.checkState() == Qt.Checked))
        self.sel_lbl = lbl("0 / 0 tahta seçili", "muted")
        top.addWidget(self.chk_all)
        top.addSpacing(14)
        top.addWidget(self.sel_lbl)
        top.addStretch(1)
        top.addWidget(btn("Çevrimdışı tahtaları listeden kaldır", None, self.forget))
        lv.addLayout(top)

        t = self.table = QTableWidget(0, len(self.COLS))
        t.setHorizontalHeaderLabels(self.COLS)
        t.setSelectionMode(QTableWidget.NoSelection)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(False)
        t.setFocusPolicy(Qt.NoFocus)
        t.setMouseTracking(True)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for i, w in enumerate([46, 0, 130, 120, 100, 150, 160, 150]):
            if w:
                t.setColumnWidth(i, w)
        t.itemChanged.connect(self.on_item_changed)
        t.cellClicked.connect(self.on_cell)
        lv.addWidget(t)
        v.addWidget(lc, 1)

    # ---- seçim
    def selected_ids(self):
        out = []
        for r, i in enumerate(self.ids):
            it = self.table.item(r, 0)
            if it is not None and it.checkState() == Qt.Checked:
                out.append(i)
        return out

    def set_all_checked(self, on):
        self._updating = True
        for r in range(len(self.ids)):
            self.table.item(r, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self._updating = False
        for r in range(len(self.ids)):
            self.style_row(r)
        self.update_sel()

    def on_cell(self, r, c):
        if c == 0:                      # onay kutusunun kendisi zaten kendi tıklamasını işler
            return
        it = self.table.item(r, 0)
        it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def on_item_changed(self, it):
        if self._updating or it.column() != 0:
            return
        self.style_row(it.row())
        self.update_sel()

    def style_row(self, r):
        """Seçili satır: mavi zemin + kalın beyaz tahta adı."""
        on = self.table.item(r, 0).checkState() == Qt.Checked
        brush = QtGui.QBrush(QtGui.QColor(79, 140, 255, 85)) if on else QtGui.QBrush()
        was, self._updating = self._updating, True          # boyama itemChanged döngüsü başlatmasın
        for c in range(self.table.columnCount()):
            it = self.table.item(r, c)
            if it is None:
                continue
            it.setBackground(brush)
            if c == 1:
                f = it.font()
                f.setBold(on)
                it.setFont(f)
                it.setForeground(QtGui.QColor("white" if on else P["text"]))
        self._updating = was

    def update_sel(self):
        n, tot = len(self.selected_ids()), len(self.ids)
        self.sel_lbl.setText(f"{n} / {tot} tahta seçili")
        self.chk_all.setCheckState(Qt.Unchecked if n == 0 else Qt.Checked if n == tot else Qt.PartiallyChecked)

    def forget(self):
        core.forget(self.selected_ids())
        self.main.toast("İşaretli çevrimdışı tahtalar listeden kaldırıldı")

    # ---- işlemler
    def act(self, kind, **extra):
        ids = self.selected_ids()
        if not ids:
            return self.main.toast("Önce listeden tahta işaretleyin", False)
        if kind in ("shutdown", "reboot"):
            word = "kapatılsın" if kind == "shutdown" else "yeniden başlatılsın"
            if QMessageBox.question(self, "Onay", f"{len(ids)} tahta {word} mı?") != QMessageBox.Yes:
                return
        if kind == "wol":
            def done(n):
                ok = isinstance(n, int) and n > 0
                self.main.toast(f"{n} tahtaya uyandırma sinyali gönderildi" if ok else
                                "MAC adresi bilinen tahta yok (tahta en az bir kez açılıp bağlanmış olmalı)", ok)
            return bridge.run(core.wol(ids), done)
        if kind == "mirror":
            on = extra["on"]
            return bridge.run(core.mirror(ids, on), lambda r: self.main.report("Ekran paylaşımı" if on else "Paylaşımı durdurma", r))
        bridge.run(core.send_to(ids, {"type": kind, **extra}), lambda r: self.main.report(KIND_LABEL.get(kind, kind), r))

    # ---- yenileme (saniyede bir)
    def refresh(self, snap):
        self.st["total"].set(len(snap))
        self.st["online"].set(sum(1 for b in snap if b["online"]))
        self.st["open"].set(sum(1 for b in snap if b["online"] and b["state"] == "unlocked"))
        self.st["locked"].set(sum(1 for b in snap if b["online"] and b["state"] == "locked"))
        new_ids = [b["id"] for b in snap]
        keep = set(self.selected_ids())
        restructure = new_ids != self.ids
        self._updating = True
        if restructure:
            self.table.setRowCount(len(snap))
            self.ids = new_ids
        for r, b in enumerate(snap):
            it0 = self.table.item(r, 0)
            if it0 is None:
                it0 = QTableWidgetItem()
                it0.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                it0.setCheckState(Qt.Unchecked)
                self.table.setItem(r, 0, it0)
            if restructure:
                it0.setCheckState(Qt.Checked if b["id"] in keep else Qt.Unchecked)
            if b["online"]:
                state = "🔒 Kilitli" if b["state"] == "locked" else "🔓 Açık"
                rem = ("kapanmaya " if b["state"] == "locked" else "kilide ") + fmt(b["remaining"])
            else:
                state, rem = "", ""
            conn = ("● Çevrimiçi" if b["online"] else "● Kapalı") + ("  🖥" if b["mirror"] else "")
            vals = [b["id"], b["ip"] or "-", conn, state, rem, b["teacher"] or "", b["mac"] or ""]
            for c, val in enumerate(vals, start=1):
                it = self.table.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    it.setFlags(Qt.ItemIsEnabled)
                    self.table.setItem(r, c, it)
                if it.text() != val:
                    it.setText(val)
                if c == 3:
                    it.setForeground(QtGui.QColor(P["ok"] if b["online"] else P["bad"]))
        self._updating = False
        if restructure:
            for r in range(len(snap)):
                self.style_row(r)
        self.update_sel()


# ------------------------------------------------------------------ Duyuru
class AnnouncePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = page_layout(self, "Duyuru", "Kilit ekranında duyuru gösterin veya açılır mesaj yayınlayın")
        c1 = card()
        v1 = QVBoxLayout(c1)
        v1.setContentsMargins(20, 18, 20, 18)
        v1.setSpacing(10)
        v1.addWidget(lbl("📢  Kilit ekranı duyurusu", "cardT"))
        v1.addWidget(lbl("Tüm tahtaların kilit ekranında saat ve sözün yanında görünür. Yeni açılan tahtalara da otomatik gider.",
                         "muted", True))
        self.ann = QPlainTextEdit()
        self.ann.setPlaceholderText("Örn: Yarın 3. ders sınav yapılacaktır. Lütfen tahtayı kapatmayı unutmayın.")
        self.ann.setFixedHeight(100)
        self.ann.setPlainText(core.cfg.get("announcement", {}).get("text", ""))
        r = QHBoxLayout()
        self.dur = QSpinBox()
        self.dur.setRange(0, 1440)
        self.dur.setSpecialValueText("Sürekli")
        self.dur.setSuffix(" dk sonra kalksın")
        r.addWidget(self.dur)
        r.addStretch(1)
        r.addWidget(btn("Temizle", None, self.clear))
        r.addWidget(btn("Yayınla", "primary", self.publish))
        v1.addWidget(self.ann)
        v1.addLayout(r)
        v.addWidget(c1)

        c2 = card()
        v2 = QVBoxLayout(c2)
        v2.setContentsMargins(20, 18, 20, 18)
        v2.setSpacing(10)
        v2.addWidget(lbl("💬  Açılır pencere mesajı", "cardT"))
        v2.addWidget(lbl("İşaretli tahtalara (işaret yoksa tüm çevrimiçi tahtalara) ekranın üstünde pencere olarak çıkar.",
                         "muted", True))
        self.msg = QLineEdit()
        self.msg.setPlaceholderText("Mesajınız...")
        r2 = QHBoxLayout()
        self.secs = QSpinBox()
        self.secs.setRange(3, 300)
        self.secs.setValue(15)
        self.secs.setSuffix(" sn açık kalsın")
        r2.addWidget(self.secs)
        r2.addStretch(1)
        r2.addWidget(btn("Gönder", "primary", self.popup))
        v2.addWidget(self.msg)
        v2.addLayout(r2)
        v.addWidget(c2)
        v.addStretch(1)

    def publish(self):
        text = self.ann.toPlainText().strip()
        if not text:
            return self.main.toast("Duyuru metni boş", False)
        bridge.run(core.set_announcement(text, self.dur.value()), lambda r: self.main.toast("Duyuru tahtalara gönderildi"))

    def clear(self):
        self.ann.clear()
        bridge.run(core.set_announcement("", 0), lambda r: self.main.toast("Duyuru kaldırıldı"))

    def popup(self):
        text = self.msg.text().strip()
        if not text:
            return self.main.toast("Mesaj boş", False)
        ids = self.main.pages["boards"].selected_ids() or [b["id"] for b in core.snapshot() if b["online"]]
        bridge.run(core.send_to(ids, {"type": "msg", "text": text, "secs": self.secs.value()}),
                   lambda r: self.main.report("Mesaj", r))


# ------------------------------------------------------------------ Dosya
class FilesPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.path = main, ""
        v = page_layout(self, "Dosya Gönder", "Sınav kâğıdı, video veya dokümanı tahtaların masaüstüne iletin")
        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(20, 18, 20, 18)
        cv.setSpacing(12)
        self.info = lbl("Henüz dosya seçilmedi", "muted")
        r = QHBoxLayout()
        r.addWidget(btn("📁  Dosya seç…", None, self.pick))
        r.addWidget(self.info, 1)
        cv.addLayout(r)
        cv.addWidget(lbl("Gönderim, Tahtalar sayfasında işaretli tahtalara yapılır. İşaret yoksa tüm çevrimiçi tahtalara gider.",
                         "muted", True))
        cv.addWidget(btn("Masaüstlerine Gönder", "primary", self.send), 0, Qt.AlignLeft)
        v.addWidget(c)
        v.addStretch(1)

    def pick(self):
        p, _ = QFileDialog.getOpenFileName(self, "Gönderilecek dosya")
        if p:
            self.path = p
            self.info.setText(f"{Path(p).name}  ({Path(p).stat().st_size / 1_048_576:.1f} MB)")

    def send(self):
        if not self.path:
            return self.main.toast("Önce dosya seçin", False)
        ids = self.main.pages["boards"].selected_ids() or [b["id"] for b in core.snapshot() if b["online"]]
        bridge.run(core.send_file_path(ids, self.path), lambda r: self.main.report("Dosya gönderme", r))


# ------------------------------------------------------------------ Terminal
class TerminalPage(QWidget):
    sig_row = pyqtSignal(str, dict)

    def __init__(self, main):
        super().__init__()
        self.main, self.running, self.cnt = main, False, [0, 0, 0]
        v = page_layout(self, "Uzak Terminal", "Komut yalnızca Tahtalar sayfasında işaretlediğiniz tahtalara gönderilir")
        tc = card()
        tv = QVBoxLayout(tc)
        tv.setContentsMargins(20, 14, 20, 14)
        tv.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(lbl("🎯  Hedef tahtalar", "cardT"))
        top.addStretch(1)
        top.addWidget(btn("Tümünü seç", None, lambda: main.pages["boards"].set_all_checked(True)))
        top.addWidget(btn("Seçimi kaldır", None, lambda: main.pages["boards"].set_all_checked(False)))
        top.addWidget(btn("Tahtalar sayfasında düzenle", None, lambda: main.goto_key("boards")))
        tv.addLayout(top)
        self.targets = lbl("", None, True)
        tv.addWidget(self.targets)
        v.addWidget(tc)

        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(10)
        r = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("Örn: uptime")
        self.cmd.returnPressed.connect(self.run)
        self.run_btn = btn("Çalıştır", "primary", self.run)
        r.addWidget(self.cmd, 1)
        r.addWidget(self.run_btn)
        cv.addLayout(r)
        q = QHBoxLayout()
        for text in ("uptime", "df -h /", "free -m", "ip -br a"):
            q.addWidget(btn(text, None, lambda t=text: (self.cmd.setText(t), self.run())))
        q.addStretch(1)
        cv.addLayout(q)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        cv.addWidget(self.out, 1)
        v.addWidget(c, 1)
        self.sig_row.connect(self.add_row)

    def refresh_targets(self):
        e = html.escape
        ids = self.main.pages["boards"].selected_ids()
        if not ids:
            text = (f"<span style='color:{P['amber']}'>Hiç tahta işaretli değil.</span> "
                    "Tahtalar sayfasında işaretleyin ya da “Tümünü seç”e basın.")
        else:
            names = ", ".join(e(i) for i in ids[:8]) + (f" … (+{len(ids) - 8})" if len(ids) > 8 else "")
            snap = {b["id"]: b for b in core.snapshot()}
            off = [i for i in ids if not snap.get(i, {}).get("online")]
            text = f"<b>{len(ids)}</b> tahta hedefte: {names}"
            if off:
                text += f"<br><span style='color:{P['bad']}'>⚠ {len(off)} tanesi çevrimdışı; komut bunlara ulaşmayacak.</span>"
        if self.targets.text() != text:
            self.targets.setText(text)

    def run(self):
        cmd = self.cmd.text().strip()
        ids = self.main.pages["boards"].selected_ids()
        if self.running:
            return
        if not cmd:
            return self.main.toast("Bir komut yazın", False)
        if not ids:
            return self.main.toast("Önce Tahtalar sayfasında hedef tahtaları işaretleyin", False)
        self.running, self.cnt = True, [0, 0, 0]
        self.run_btn.setEnabled(False)
        self.out.clear()
        self.out.append(f"<span style='color:{P['accent']}'>▶ <b>{html.escape(cmd)}</b> → {len(ids)} tahta</span>")
        bridge.run(core.exec_on(ids, cmd, on_result=lambda i, r: self.sig_row.emit(i, r)), self.finish)

    def add_row(self, bid, r):
        e = html.escape
        if r.get("error"):
            head, self.cnt[2] = f"<span style='color:{P['bad']}'>✖ <b>{e(bid)}</b> — ulaşılamadı: {e(r['error'])}</span>", self.cnt[2] + 1
        elif r.get("rc") == 0:
            head, self.cnt[0] = f"<span style='color:{P['ok']}'>✔ <b>{e(bid)}</b> — tamam</span>", self.cnt[0] + 1
        else:
            head, self.cnt[1] = (f"<span style='color:{P['amber']}'>⚠ <b>{e(bid)}</b> — komut hata koduyla bitti "
                                 f"({r.get('rc')})</span>"), self.cnt[1] + 1
        out = (r.get("out") or "").rstrip()
        self.out.append(head + (f"<pre style='margin:2px 0 10px 18px;color:{P['muted']}'>{e(out)}</pre>" if out else ""))

    def finish(self, res):
        self.running = False
        self.run_btn.setEnabled(True)
        if isinstance(res, dict) and "error" in res and len(res) == 1:
            return self.out.append(f"<span style='color:{P['bad']}'>İç hata: {html.escape(res['error'])}</span>")
        ok, warn, fail = self.cnt
        self.out.append(f"<br><b>Özet:</b> {ok} başarılı · {warn} hata koduyla · {fail} ulaşılamadı")
        if fail:
            self.main.toast(f"{fail} tahtaya komut ulaşmadı", False)


# ------------------------------------------------------------------ Yetkilendirme
class AuthPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        outer.addWidget(sc)
        body = QWidget()
        sc.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(30, 26, 30, 24)
        v.setSpacing(16)
        v.addWidget(header("Yetkilendirme", "Öğretmen girişi ve karekod sayfası"))

        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(20, 18, 20, 18)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(lbl("🔑  Ortak öğretmen kodu", "cardT"), 0, 0, 1, 3)
        g.addWidget(lbl("Öğretmenlere tek tek parola tanımlamaya gerek yok. Öğretmen bu kodu telefonunda bir kez girer, "
                        "telefon hatırlanır; sonraki karekod okutmalarında hiçbir şey yazmadan doğrudan PIN görür. "
                        "Öğrencilerin öğrenmemesi gereken tek bilgi bu koddur; şüphe halinde yeni kod üretin.",
                        "muted", True), 1, 0, 1, 3)
        g.addWidget(lbl("Öğretmen kodu", "muted"), 2, 0)
        self.code = QLineEdit()
        self.code.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        g.addWidget(self.code, 2, 1)
        g.addWidget(btn("Yeni kod üret", None, lambda: self.code.setText(core.new_teacher_code())), 2, 2)
        g.addWidget(lbl("Telefon hatırlama süresi", "muted"), 3, 0)
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setSuffix(" gün")
        g.addWidget(self.days, 3, 1)
        r = QHBoxLayout()
        r.addWidget(btn("Kodu kaydet", "primary", self.save_code))
        r.addWidget(btn("Kayıtlı telefonları sıfırla", "danger", self.reset))
        r.addStretch(1)
        g.addLayout(r, 4, 0, 1, 3)
        g.setColumnStretch(1, 1)
        v.addWidget(c)

        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(20, 18, 20, 18)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(lbl("📱  Karekod sayfası", "cardT"), 0, 0, 1, 2)
        g.addWidget(lbl("Telefon karekodu okutunca açılacak sayfa. Yerel sayfa bu bilgisayarda çalışır (telefon okul "
                        "ağında olmalı). Harici sayfa kendi web sitenizdeki PHP dosyasıdır; telefon mobil internetle de "
                        "erişebilir. Ana program kodu kendi içinde doğruladığı için sunucuya bağlanmaz.", "muted", True), 1, 0, 1, 2)
        g.addWidget(lbl("Sayfa türü", "muted"), 2, 0)
        self.mode = QComboBox()
        self.mode.addItem("Yerel sayfa (bu bilgisayar, aynı ağ)", "local")
        self.mode.addItem("Harici web sitesi (PHP)", "external")
        g.addWidget(self.mode, 2, 1)
        g.addWidget(lbl("Harici sayfa adresi", "muted"), 3, 0)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://okulunuz.com/etap/kod.php")
        g.addWidget(self.url, 3, 1)
        g.addWidget(lbl("Kod geçerlilik süresi", "muted"), 4, 0)
        self.ttl = QSpinBox()
        self.ttl.setRange(60, 600)
        self.ttl.setSuffix(" saniye")
        g.addWidget(self.ttl, 4, 1)
        self.warn = lbl("", None, True)
        g.addWidget(self.warn, 5, 0, 1, 2)
        r = QHBoxLayout()
        r.addWidget(btn("Kaydet", "primary", self.save_qr))
        r.addWidget(btn("📦  PHP dosyalarını dışa aktar…", None, self.export))
        r.addWidget(btn("Test bağlantısını aç", None, self.test))
        r.addStretch(1)
        g.addLayout(r, 6, 0, 1, 2)
        g.setColumnStretch(1, 1)
        v.addWidget(c)
        v.addStretch(1)
        self.refresh()

    def refresh(self):
        cfg = core.cfg
        self.code.setText(cfg["teacher_code"])
        self.days.setValue(cfg["remember_days"])
        self.mode.setCurrentIndex(1 if cfg["qr_mode"] == "external" else 0)
        self.url.setText(cfg["qr_url"])
        self.ttl.setValue(cfg["nonce_ttl"])
        self.update_warn()

    def update_warn(self):
        text = ("<span style='color:%s'>⚠ Harici sunucudaki dosyalar güncel değil. “PHP dosyalarını dışa aktar”, ardından "
                "yalnızca <b>config.php</b> dosyasını web sitenize yeniden yükleyin.</span>" % P["amber"]) if core.ext_outdated() else ""
        if self.warn.text() != text:
            self.warn.setText(text)

    def save_code(self):
        code = self.code.text().strip()
        if len(code) < 6:
            return self.main.toast("Kod en az 6 karakter olmalı", False)
        core.cfg["remember_days"] = self.days.value()
        if code != core.cfg["teacher_code"]:
            core.set_teacher_code(code)
        core.save_cfg()
        self.update_warn()
        self.main.toast("Kaydedildi. Telefonlar yeni kodu bir kez girecek")

    def reset(self):
        if QMessageBox.question(self, "Onay", "Kayıtlı tüm öğretmen telefonları sıfırlansın mı?\n"
                                "Öğretmenler kodu telefonlarında yeniden girmek zorunda kalır.") == QMessageBox.Yes:
            core.reset_devices()
            self.update_warn()
            self.main.toast("Kayıtlı telefonlar sıfırlandı")

    def save_qr(self):
        mode, url = self.mode.currentData(), self.url.text().strip()
        if mode == "external" and not url.lower().startswith(("http://", "https://")):
            return self.main.toast("Harici sayfa adresi http:// veya https:// ile başlamalı", False)
        core.cfg.update(qr_mode=mode, qr_url=url, nonce_ttl=self.ttl.value())
        core.save_cfg()
        self.update_warn()
        self.main.toast("Karekod ayarları kaydedildi")

    def export(self):
        folder = QFileDialog.getExistingDirectory(self, "Dosyaların yazılacağı klasörü seçin")
        if not folder:
            return
        out = Path(folder) / "etap-kod"
        try:
            webexport.export(out, core.cfg)
        except Exception as e:
            return QMessageBox.critical(self, "Hata", str(e))
        core.cfg["ext_export_sig"] = core.ext_sig()
        core.save_cfg()
        self.update_warn()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(out)))
        self.main.toast("Dosyalar hazır. OKU-BENI.txt dosyasındaki adımları izleyin")

    def test(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(core.make_qr_url("TEST-TAHTA")))


# ------------------------------------------------------------------ Günlük
class LogPage(QWidget):
    ICON = {"info": "•", "warning": "⚠", "error": "✖"}

    def __init__(self, main):
        super().__init__()
        self.last = 0
        v = page_layout(self, "Günlük", "Bağlantılar, komutlar ve hatalar")
        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(16, 14, 16, 14)
        r = QHBoxLayout()
        r.addWidget(btn("Günlük dosyasını aç", None,
                        lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(core.LOGFILE)))))
        r.addWidget(btn("Ekranı temizle", None, lambda: self.out.clear()))
        r.addStretch(1)
        cv.addLayout(r)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(1000)
        self.out.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        cv.addWidget(self.out, 1)
        v.addWidget(c, 1)

    def refresh(self):
        try:
            new = [e for e in list(core.events) if e[0] > self.last]
        except RuntimeError:
            return
        for seq, ts, lvl, msg in new:
            self.out.appendPlainText(f"{ts}  {self.ICON.get(lvl, '•')} {msg}")
            self.last = seq


# ------------------------------------------------------------------ Kurulum paketi
class PackagePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = page_layout(self, "Tahta Kurulum Paketi", "Pardus ETAP tahtalar için hazır kurulum dosyası (.deb) oluşturun")
        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(20, 18, 20, 18)
        cv.setSpacing(10)
        self.summary = lbl("", None, True)
        cv.addWidget(self.summary)
        cv.addWidget(btn("📦  Pardus Kurulum Paketi Oluştur (.deb)", "primary", self.build), 0, Qt.AlignLeft)
        v.addWidget(c)
        c2 = card()
        v2 = QVBoxLayout(c2)
        v2.setContentsMargins(20, 18, 20, 18)
        v2.setSpacing(8)
        v2.addWidget(lbl("Tahtaya kurulum", "cardT"))
        v2.addWidget(lbl("1.  Oluşan .deb dosyasını USB bellekle ya da ağ üzerinden tahtaya kopyalayın.\n"
                         "2.  Tahtada terminal açıp şu komutu çalıştırın (tahta internete/Pardus deposuna erişebilmeli):\n"
                         "        sudo apt install ./etap-kilit_*.deb\n"
                         "3.  Tahtayı yeniden başlatın. Açılışta kilit ekranı gelir ve tahta bu programa otomatik bağlanır.\n\n"
                         "Sunucu IP'si veya port değişirse paketi yeniden oluşturup tahtalara yeniden kurmanız gerekir.\n"
                         "Okul adı, logolar, arkaplan, sözler, duyurular ve süreler ise paket gerekmeden anında güncellenir.",
                         "muted", True))
        v.addWidget(c2)
        v.addStretch(1)

    def refresh(self):
        ip = core.server_ip()
        warn = "<br>⚠ Sunucu IP'si 127.0.0.1 görünüyor; Ayarlar'dan doğru IP'yi seçin." if ip.startswith("127.") else ""
        self.summary.setText(f"Tahtalar şu sunucuya bağlanacak:  <b>{ip}:{core.cfg['http_port']}</b>   ·   "
                             f"Okul: <b>{html.escape(core.cfg['school'])}</b>{warn}")

    def build(self):
        default = f"etap-kilit_{datetime.date.today():%Y%m%d}.deb"
        path, _ = QFileDialog.getSaveFileName(self, "Paketi kaydet", default, "Debian paketi (*.deb)")
        if not path:
            return
        try:
            ver = pkgbuild.build_deb(path, core.cfg, core.server_ip(), client_src())
            self.main.toast(f"Paket oluşturuldu (sürüm {ver})")
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))


# ------------------------------------------------------------------ Ayarlar
class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        outer.addWidget(sc)
        body = QWidget()
        sc.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(30, 26, 30, 24)
        v.setSpacing(16)
        v.addWidget(header("Ayarlar", "Okul bilgileri, kilit ekranı görünümü ve davranışı"))
        cfg = core.cfg
        self.logo = {"pardus": cfg.get("pardus_logo_b64", ""), "school": cfg.get("school_logo_b64", "")}
        self.wp = {"b64": cfg.get("wallpaper_b64", "")}

        # --- okul
        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(20, 18, 20, 18)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(lbl("🏫  Okul", "cardT"), 0, 0, 1, 4)
        g.addWidget(lbl("Okul adı", "muted"), 1, 0)
        self.school = QLineEdit(cfg["school"])
        g.addWidget(self.school, 1, 1, 1, 3)
        self.prev = {}
        for row, (key, title) in enumerate((("pardus", "Pardus logosu"), ("school", "Okul logosu")), start=2):
            g.addWidget(lbl(title, "muted"), row, 0)
            p = QLabel()
            p.setFixedSize(64, 40)
            self.prev[key] = p
            g.addWidget(p, row, 1)
            g.addWidget(btn("Seç…", None, lambda k=key: self.pick_logo(k)), row, 2)
            g.addWidget(btn("Kaldır", None, lambda k=key: self.set_logo(k, "")), row, 3)
            self.set_logo(key, self.logo[key])
        g.addWidget(lbl("Pardus logosunu resmî kaynaktan indirip buradan seçin (PNG önerilir, şeffaf zeminli olursa daha şık "
                        "görünür).", "muted", True), 4, 0, 1, 4)
        v.addWidget(c)

        # --- kilit ekranı arkaplanı
        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(20, 18, 20, 18)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(lbl("🖼  Kilit ekranı arkaplanı", "cardT"), 0, 0, 1, 3)
        self.wp_prev = QLabel()
        self.wp_prev.setFixedSize(320, 180)
        self.wp_prev.setStyleSheet(f"border:1px solid {P['border']}; border-radius:10px;")
        g.addWidget(self.wp_prev, 1, 0, 4, 1)
        self.wp_mode = QComboBox()
        for key, text in (("auto", "Otomatik: ortasında Pardus logosu"), ("custom", "Özel görsel (kendi tasarımınız)"),
                          ("none", "Yok (varsayılan degrade)")):
            self.wp_mode.addItem(text, key)
        self.wp_mode.setCurrentIndex(max(0, self.wp_mode.findData(cfg.get("wallpaper_mode", "auto"))))
        g.addWidget(self.wp_mode, 1, 1, 1, 2)
        self.wp_pick = btn("Özel görsel seç…", None, self.pick_wallpaper)
        g.addWidget(self.wp_pick, 2, 1)
        g.addWidget(btn("Yeniden oluştur", None, self.regen), 2, 2)
        g.addWidget(lbl("Otomatik modda Pardus logosu ekranın ortasına, kilit rozetiyle birlikte yerleştirilir. Özel görselde "
                        "logoyu görselin ortasına koymanız önerilir. 16:9 görseller en iyi sonucu verir.", "muted", True),
                    3, 1, 2, 2)
        g.setColumnStretch(1, 1)
        v.addWidget(c)
        self.wp_mode.currentIndexChanged.connect(self.on_wp_mode)
        self.wp_pick.setEnabled(self.wp_mode.currentData() == "custom")
        self.show_wp()

        # --- ağ
        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(20, 18, 20, 18)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(lbl("🌐  Ağ", "cardT"), 0, 0, 1, 2)
        g.addWidget(lbl("Sunucu IP adresi", "muted"), 1, 0)
        self.ip = QComboBox()
        self.ip.setEditable(True)
        ips = core.local_ips()
        self.ip.addItems(ips)
        self.ip.setCurrentText(cfg["server_ip"] or (ips[0] if ips else ""))
        g.addWidget(self.ip, 1, 1)
        g.addWidget(lbl("Port", "muted"), 2, 0)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(cfg["http_port"])
        g.addWidget(self.port, 2, 1)
        g.addWidget(lbl("IP veya port değişirse yeni paket oluşturup tahtalara kurmalı, programı yeniden başlatmalısınız. "
                        "Sabit IP için modemden DHCP rezervasyonu önerilir.", "muted", True), 3, 0, 1, 2)
        g.setColumnStretch(1, 1)
        v.addWidget(c)

        # --- kilit davranışı
        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(20, 18, 20, 18)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(lbl("🔒  Kilit davranışı", "cardT"), 0, 0, 1, 2)
        g.addWidget(lbl("Kilitliyken otomatik kapanma", "muted"), 1, 0)
        self.idle = QSpinBox()
        self.idle.setRange(1, 240)
        self.idle.setSuffix(" dakika")
        self.idle.setValue(cfg["idle_shutdown_min"])
        g.addWidget(self.idle, 1, 1)
        g.addWidget(lbl("Süre seçenekleri (dk, virgülle)", "muted"), 2, 0)
        self.durs = QLineEdit(", ".join(map(str, cfg["durations"])))
        g.addWidget(self.durs, 2, 1)
        g.addWidget(lbl("“Süre Ekle” düğmesi", "muted"), 3, 0)
        self.extend = QSpinBox()
        self.extend.setRange(1, 120)
        self.extend.setSuffix(" dakika ekler")
        self.extend.setValue(cfg["extend_min"])
        g.addWidget(self.extend, 3, 1)
        self.usb = QCheckBox("Kilitliyken yeni takılan USB aygıtları engelle")
        self.usb.setChecked(cfg["usb_block"])
        g.addWidget(self.usb, 4, 0, 1, 2)
        g.setColumnStretch(1, 1)
        v.addWidget(c)

        # --- sözler
        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(20, 18, 20, 18)
        cv.setSpacing(10)
        cv.addWidget(lbl("💡  Kilit ekranı sözleri", "cardT"))
        cv.addWidget(lbl("Her satır bir söz. Yazar için son kısmı \" — Yazar\" biçiminde ekleyin.", "muted"))
        self.quotes = QPlainTextEdit("\n".join(cfg["quotes"]))
        self.quotes.setMinimumHeight(220)
        r = QHBoxLayout()
        r.addWidget(lbl("Değişim aralığı", "muted"))
        self.qint = QSpinBox()
        self.qint.setRange(5, 600)
        self.qint.setSuffix(" sn")
        self.qint.setValue(cfg["quote_interval"])
        r.addWidget(self.qint)
        r.addStretch(1)
        r.addWidget(btn("Varsayılan sözlere dön", None, lambda: self.quotes.setPlainText("\n".join(DEFAULT_QUOTES))))
        cv.addWidget(self.quotes)
        cv.addLayout(r)
        v.addWidget(c)

        v.addWidget(btn("Kaydet ve tahtalara uygula", "primary", self.save), 0, Qt.AlignLeft)
        v.addStretch(1)

    # ---- logolar
    def set_logo(self, key, b64):
        self.logo[key] = b64
        pm = QtGui.QPixmap()
        if b64 and pm.loadFromData(base64.b64decode(b64)):
            self.prev[key].setPixmap(pm.scaled(64, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.prev[key].setText("")
        else:
            self.prev[key].setPixmap(QtGui.QPixmap())
            self.prev[key].setText("—")
        if key == "pardus" and hasattr(self, "wp_mode") and self.wp_mode.currentData() == "auto":
            self.regen()

    def pick_logo(self, key):
        p, _ = QFileDialog.getOpenFileName(self, "Logo seç", "", "Görseller (*.png *.jpg *.jpeg *.bmp)")
        if p:
            b64 = encode_logo(p)
            if b64:
                self.set_logo(key, b64)
            else:
                self.main.toast("Görsel okunamadı", False)

    # ---- arkaplan
    def show_wp(self):
        pm = QtGui.QPixmap()
        if self.wp["b64"] and pm.loadFromData(base64.b64decode(self.wp["b64"])):
            self.wp_prev.setPixmap(pm.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.wp_prev.setPixmap(QtGui.QPixmap())
            self.wp_prev.setText("Varsayılan degrade")
            self.wp_prev.setAlignment(Qt.AlignCenter)

    def regen(self):
        self.wp["b64"] = wallpaper.compose(self.logo["pardus"])
        self.show_wp()

    def on_wp_mode(self):
        mode = self.wp_mode.currentData()
        self.wp_pick.setEnabled(mode == "custom")
        if mode == "auto":
            self.regen()
        elif mode == "none":
            self.wp["b64"] = ""
            self.show_wp()

    def pick_wallpaper(self):
        p, _ = QFileDialog.getOpenFileName(self, "Arkaplan görseli seç", "", "Görseller (*.png *.jpg *.jpeg *.bmp)")
        if p:
            b64 = wallpaper.from_image_file(p)
            if b64:
                self.wp["b64"] = b64
                self.show_wp()
            else:
                self.main.toast("Görsel okunamadı", False)

    # ---- kaydet
    def save(self):
        cfg = core.cfg
        try:
            durs = sorted({int(x) for x in self.durs.text().replace(";", ",").split(",") if x.strip()})
            assert durs and all(1 <= d <= 480 for d in durs)
        except Exception:
            return self.main.toast("Süre seçenekleri geçersiz (örn: 20, 40, 45, 80)", False)
        mode = self.wp_mode.currentData()
        if mode == "auto":
            self.regen()
        elif mode == "custom" and not self.wp["b64"]:
            return self.main.toast("Özel görsel seçin ya da başka bir arkaplan türü belirleyin", False)
        restart = cfg["http_port"] != self.port.value()
        cfg.update(school=self.school.text().strip() or "Okul", server_ip=self.ip.currentText().strip(),
                   http_port=self.port.value(), idle_shutdown_min=self.idle.value(), durations=durs,
                   extend_min=self.extend.value(), usb_block=self.usb.isChecked(), quote_interval=self.qint.value(),
                   quotes=[q.strip() for q in self.quotes.toPlainText().splitlines() if q.strip()],
                   pardus_logo_b64=self.logo["pardus"], school_logo_b64=self.logo["school"],
                   wallpaper_mode=mode, wallpaper_b64=self.wp["b64"])
        core.save_cfg()
        bridge.run(core.push_settings())
        self.main.update_school()
        self.main.toast("Ayarlar kaydedildi" + (" — port için programı yeniden başlatın" if restart else " ve tahtalara gönderildi"))


# ------------------------------------------------------------------ ana pencere
class Main(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.quitting = False
        self.setWindowTitle("ETAP Kilit Yönetimi")
        self.setWindowIcon(QtGui.QIcon(app_icon(256)))
        self.resize(1280, 820)
        self.setMinimumSize(1100, 700)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 22, 16, 16)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(app_icon(40))
        brand.addWidget(ic)
        brand.addWidget(lbl("ETAP Kilit", "brand"))
        brand.addStretch(1)
        sv.addLayout(brand)
        self.school_lbl = lbl("", "muted", True)
        sv.addWidget(self.school_lbl)
        sv.addSpacing(16)

        self.stack = QtWidgets.QStackedWidget()
        self.pages, self.nav, self.index = {}, {}, {}
        group = QtWidgets.QButtonGroup(self)
        defs = [("boards", "🖥   Tahtalar", BoardsPage), ("announce", "📢   Duyuru", AnnouncePage),
                ("files", "📁   Dosya Gönder", FilesPage), ("terminal", "⌨   Uzak Terminal", TerminalPage),
                ("auth", "🔑   Yetkilendirme", AuthPage), ("package", "📦   Kurulum Paketi", PackagePage),
                ("logs", "🧾   Günlük", LogPage), ("settings", "⚙   Ayarlar", SettingsPage)]
        for i, (key, text, cls) in enumerate(defs):
            page = cls(self)
            self.pages[key], self.index[key] = page, i
            self.stack.addWidget(page)
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            group.addButton(b, i)
            self.nav[key] = b
            sv.addWidget(b)
            if i == 0:
                b.setChecked(True)
        group.idClicked.connect(self.goto)
        sv.addStretch(1)
        self.srv = lbl("", "muted", True)
        sv.addWidget(self.srv)

        h.addWidget(side)
        h.addWidget(self.stack, 1)

        self.toast_lbl = QLabel(self)
        self.toast_lbl.setObjectName("toast")
        self.toast_lbl.hide()
        self.toast_timer = QtCore.QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast_lbl.hide)

        # Sistem tepsisi simgesi: menü, uygulama temasından bağımsız olarak okunaklı koyu stille açılır
        self.tray = QtWidgets.QSystemTrayIcon(QtGui.QIcon(app_icon(64)), self)
        self.tray_menu = QtWidgets.QMenu()
        self.tray_menu.setStyleSheet(theme.menu_qss())
        self.tray_menu.addAction("Aç", self.show_normal)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Çıkış", self.quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.setToolTip("ETAP Kilit Yönetimi")
        self.tray.activated.connect(lambda r: self.show_normal() if r == QtWidgets.QSystemTrayIcon.Trigger else None)
        self.tray.show()

        self.update_school()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.tick()

    def goto(self, i):
        self.stack.setCurrentIndex(i)
        page = self.stack.widget(i)
        if isinstance(page, (PackagePage, AuthPage)):
            page.refresh()

    def goto_key(self, key):
        self.nav[key].setChecked(True)
        self.goto(self.index[key])

    def update_school(self):
        self.school_lbl.setText(core.cfg["school"])
        self.pages["package"].refresh()

    def tick(self):
        self.pages["boards"].refresh(core.snapshot())
        self.pages["terminal"].refresh_targets()
        self.pages["auth"].update_warn()
        self.pages["logs"].refresh()
        if core.status["error"]:
            self.srv.setText(f"<span style='color:{P['bad']}'>● Sunucu başlatılamadı:<br>{html.escape(core.status['error'])}</span>")
        elif core.status["ok"]:
            self.srv.setText(f"<span style='color:{P['ok']}'>● Sunucu çalışıyor</span><br>"
                             f"{core.server_ip()}:{core.cfg['http_port']}")

    def toast(self, text, ok=True):
        self.toast_lbl.setStyleSheet(f"border-color:{P['accent'] if ok else P['bad']};")
        self.toast_lbl.setText(text)
        self.toast_lbl.adjustSize()
        self.toast_lbl.move((self.width() - self.toast_lbl.width()) // 2 + 125, self.height() - 70)
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self.toast_timer.start(4500 if not ok else 3000)

    def report(self, label, r):
        """Toplu komut sonucunu anında bildirir: kaç tahtaya ulaştı, hangileri başarısız."""
        if "error" in r and "failed" not in r:
            return self.toast(f"{label}: işlem başarısız ({r['error']})", False)
        n, failed = r.get("sent", 0), r.get("failed", {})
        if failed:
            names = ", ".join(list(failed)[:3]) + (" …" if len(failed) > 3 else "")
            self.toast(f"{label}: {n} tahtaya iletildi, {len(failed)} tahtaya İLETİLEMEDİ ({names})", False)
        else:
            self.toast(f"{label}: {n} tahtaya iletildi")

    def show_normal(self):
        self.showNormal()
        self.activateWindow()

    def quit(self):
        if QMessageBox.question(self, "Çıkış", "Program kapanırsa tahtalar yönetilemez. Çıkılsın mı?") == QMessageBox.Yes:
            self.quitting = True
            QtWidgets.QApplication.quit()

    def closeEvent(self, e):
        if self.quitting:
            return e.accept()
        e.ignore()
        self.hide()
        self.tray.showMessage("ETAP Kilit", "Program arka planda çalışmaya devam ediyor.",
                              QtWidgets.QSystemTrayIcon.Information, 3000)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ETAP Kilit Yönetimi")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss(make_check_icon()))
    lock = QtCore.QLockFile(QtCore.QDir.temp().filePath("etap-kilit-yonetim.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "ETAP Kilit", "Program zaten çalışıyor (sistem tepsisine bakın).")
        return 0
    core.start()
    win = Main()
    if "--minimized" not in sys.argv:
        win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
