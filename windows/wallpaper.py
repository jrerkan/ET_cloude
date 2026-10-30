"""Kilit ekranı arkaplanı üretici (QPainter): ortasında Pardus logosu olan şık bir görsel.
Çıktı: 1920x1080 JPEG, base64 metni. Tahtalara ayarlarla birlikte gönderilir.
"""
import base64
from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import Qt, QPointF, QRectF

W, H = 1920, 1080


def _glow(p, cx, cy, r, color, alpha):
    g = QtGui.QRadialGradient(cx, cy, r)
    c0, c1 = QtGui.QColor(color), QtGui.QColor(color)
    c0.setAlpha(alpha)
    c1.setAlpha(0)
    g.setColorAt(0, c0)
    g.setColorAt(1, c1)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy), r, r)


def _to_b64(img, quality=86):
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "JPEG", quality)
    return base64.b64encode(bytes(ba)).decode()


def compose(pardus_b64=""):
    img = QtGui.QImage(W, H, QtGui.QImage.Format_RGB32)
    p = QtGui.QPainter(img)
    p.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.TextAntialiasing)
    g = QtGui.QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QtGui.QColor("#070B18"))
    g.setColorAt(.55, QtGui.QColor("#0F1A38"))
    g.setColorAt(1, QtGui.QColor("#16213A"))
    p.fillRect(img.rect(), g)

    cx, cy = W / 2, H / 2
    _glow(p, W * .12, H * .15, 640, "#4F8CFF", 48)
    _glow(p, W * .88, H * .88, 720, "#6D5BFF", 42)
    _glow(p, cx, cy, 520, "#4F8CFF", 78)

    p.setBrush(Qt.NoBrush)                                   # ince eş merkezli halkalar
    for i, r in enumerate((215, 300, 400, 520, 660)):
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 30 - i * 5), 2))
        p.drawEllipse(QPointF(cx, cy), r, r)

    p.setPen(Qt.NoPen)                                       # logonun arkasındaki cam disk
    p.setBrush(QtGui.QColor(255, 255, 255, 26))
    p.drawEllipse(QPointF(cx, cy), 168, 168)
    p.setBrush(QtGui.QColor(11, 16, 32, 150))
    p.drawEllipse(QPointF(cx, cy), 152, 152)

    logo = QtGui.QPixmap()
    if pardus_b64 and logo.loadFromData(base64.b64decode(pardus_b64)):
        logo = logo.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(int(cx - logo.width() / 2), int(cy - logo.height() / 2), logo)
    else:                                                    # logo yüklenmediyse yazı
        p.setPen(QtGui.QColor("#E8ECF8"))
        f = QtGui.QFont("Segoe UI", 44)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(cx - 150, cy - 50, 300, 100), Qt.AlignCenter, "PARDUS")

    bx, by = cx + 128, cy + 128                              # kilit rozeti (sağ-alt)
    p.setPen(QtGui.QPen(QtGui.QColor("#0F1A38"), 8))
    p.setBrush(QtGui.QColor("#F5B301"))
    p.drawEllipse(QPointF(bx, by), 50, 50)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#1A1400"))
    p.drawRoundedRect(QRectF(bx - 21, by - 2, 42, 32), 7, 7)
    p.setBrush(Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QColor("#1A1400"), 7))
    p.drawArc(QRectF(bx - 14, by - 30, 28, 36), 0, 180 * 16)
    p.end()
    return _to_b64(img)


def from_image_file(path):
    """Kullanıcının seçtiği görseli 1920x1080'e (ortadan kırparak) uydurur."""
    src = QtGui.QImage(path)
    if src.isNull():
        return ""
    img = src.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (img.width() - W) // 2, (img.height() - H) // 2
    return _to_b64(img.copy(x, y, W, H).convertToFormat(QtGui.QImage.Format_RGB32))
