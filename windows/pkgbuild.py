"""Pardus ETAP tahtaları için .deb paketi üretici (saf Python, dpkg gerekmez)."""
import base64, io, json, tarfile, time
from pathlib import Path

USB_HELPER = """#!/bin/bash
# Kilitliyken YENİ takılan USB aygıtlar yetkilendirilmez; mevcut dokunmatik panel/fare çalışmaya devam eder.
case "$1" in
  block) v=0 ;;
  allow) v=1 ;;
  *) exit 1 ;;
esac
for f in /sys/bus/usb/devices/usb*/authorized_default; do echo "$v" > "$f"; done
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=ETAP Kilit
Exec=/usr/bin/python3 /opt/etap-kilit/etap_client.py
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""

POSTINST = r"""#!/bin/sh
set -e
chmod 755 /usr/local/sbin/etap-usb || true
cat > /etc/sudoers.d/etap-kilit <<'EOF'
ALL ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot, /bin/systemctl poweroff, /bin/systemctl reboot, /usr/local/sbin/etap-usb
EOF
chmod 440 /etc/sudoers.d/etap-kilit
if ! visudo -cf /etc/sudoers.d/etap-kilit >/dev/null 2>&1; then
  rm -f /etc/sudoers.d/etap-kilit
  echo "etap-kilit: sudoers dosyasi gecersiz, kaldirildi" >&2
fi
IFACE=$(ip route 2>/dev/null | awk '/default/{print $5; exit}')
if [ -n "$IFACE" ] && command -v ethtool >/dev/null 2>&1; then
cat > /etc/systemd/system/etap-wol.service <<EOF
[Unit]
Description=ETAP Wake-on-LAN
After=network.target
[Service]
Type=oneshot
ExecStart=$(command -v ethtool) -s $IFACE wol g
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload || true
  systemctl enable etap-wol.service || true
  systemctl start etap-wol.service || true
fi
exit 0
"""

POSTRM = r"""#!/bin/sh
set -e
case "$1" in
  remove|purge)
    rm -f /etc/sudoers.d/etap-kilit
    systemctl disable etap-wol.service >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/etap-wol.service
    systemctl daemon-reload >/dev/null 2>&1 || true
    ;;
esac
exit 0
"""


def _tar_gz(entries):
    """entries: [(yol, bayt, mod)] -> .tar.gz baytları (root sahipli, üst dizinler otomatik)."""
    bio = io.BytesIO()
    now = int(time.time())
    dirs = set()
    for path, _, _ in entries:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    with tarfile.open(fileobj=bio, mode="w:gz", format=tarfile.GNU_FORMAT) as tf:
        for d in sorted(dirs):
            ti = tarfile.TarInfo(f"./{d}")
            ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, now
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            tf.addfile(ti)
        for path, data, mode in entries:
            ti = tarfile.TarInfo(f"./{path}")
            ti.size, ti.mode, ti.mtime = len(data), mode, now
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            tf.addfile(ti, io.BytesIO(data))
    return bio.getvalue()


def _ar(members):
    out = bytearray(b"!<arch>\n")
    now = int(time.time())
    for name, data in members:
        out += (f"{name:<16}{now:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n").encode()
        out += data
        if len(data) % 2:
            out += b"\n"
    return bytes(out)


def build_deb(out_path, cfg, server_ip, client_src):
    """cfg: core.cfg sözlüğü; server_ip: tahtaların bağlanacağı adres; client_src: etap_client.py yolu."""
    version = time.strftime("1.0.%Y%m%d%H%M")
    conf = {"board_id": "", "server": server_ip, "port": cfg["http_port"], "psk": cfg["psk"],
            "discovery_port": cfg["discovery_port"], "idle_shutdown_min": cfg["idle_shutdown_min"],
            "durations": cfg["durations"], "usb_block": cfg["usb_block"]}
    data = [
        ("opt/etap-kilit/etap_client.py", Path(client_src).read_bytes(), 0o755),
        ("opt/etap-kilit/config.json", json.dumps(conf, ensure_ascii=False, indent=2).encode(), 0o644),
        ("usr/local/sbin/etap-usb", USB_HELPER.encode(), 0o755),
        ("etc/xdg/autostart/etap-kilit.desktop", DESKTOP.encode(), 0o644),
    ]
    for kind in ("pardus", "school"):
        b64 = cfg.get(f"{kind}_logo_b64")
        if b64:
            data.append((f"opt/etap-kilit/assets/{kind}-logo.png", base64.b64decode(b64), 0o644))
    control = (
        "Package: etap-kilit\n"
        f"Version: {version}\n"
        "Section: education\n"
        "Priority: optional\n"
        "Architecture: all\n"
        "Depends: python3, python3-pyqt5, python3-aiohttp, python3-qrcode, ethtool\n"
        "Maintainer: ETAP Kilit <etap-kilit@localhost>\n"
        "Description: ETAP akilli tahta kilit ve yonetim istemcisi\n"
        " Kilit ekrani, karekod/PIN dogrulama, sureli kullanim ve uzaktan yonetim.\n"
    )
    ctrl = [("control", control.encode(), 0o644),
            ("postinst", POSTINST.encode(), 0o755),
            ("postrm", POSTRM.encode(), 0o755)]
    ctrl_tar = _tar_gz([(n, d, m) for n, d, m in ctrl])
    # kontrol arşivinde dizin girdisi "./" olmamalı; yolları "./control" biçiminde bırakıyoruz
    deb = _ar([("debian-binary", b"2.0\n"), ("control.tar.gz", ctrl_tar), ("data.tar.gz", _tar_gz(data))])
    Path(out_path).write_bytes(deb)
    return version
