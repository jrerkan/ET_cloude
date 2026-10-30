"""ETAP Kilit - sunucu çekirdeği.
Arayüzden bağımsızdır; ayrı bir iş parçacığında asyncio döngüsü çalıştırır.

Kimlik doğrulama (öğretmen başına parola YOK):
  * Tahta kilit ekranında imzalı bir karekod gösterir:  ?b=<tahta>&n=<nonce>&t=<zaman>&s=<imza>
  * Telefon sayfası (yerel veya harici PHP) imzayı doğrular, öğretmeni tanır ve 6 haneli kodu üretir:
        kod = HMAC-SHA256(qr_secret, "code|b|n|t")  ->  ilk 4 bayt & 0x7fffffff  mod 10^6
  * Ana program aynı hesabı yapıp tahtanın girdiği PIN ile karşılaştırır (harici sunucuya bağlanmaz).
  * Öğretmen tanıma: tek bir "ortak öğretmen kodu" + telefonda "bu cihazı hatırla" (imzalı çerez).
"""
import asyncio, base64, collections, hashlib, hmac, html, io, json, logging, logging.handlers
import os, secrets, shutil, socket, threading, time, zlib
from pathlib import Path
from urllib.parse import quote
from aiohttp import web, WSMsgType
from quotes_tr import DEFAULT_QUOTES

APPDIR = Path(os.environ.get("APPDATA") or Path.home()) / "ETAPKilit"
APPDIR.mkdir(parents=True, exist_ok=True)
CFG_FILE, BOARDS_FILE = APPDIR / "config.json", APPDIR / "boards.json"
LOGFILE = APPDIR / "etap-kilit.log"
FILES = APPDIR / "shared"
FILES.mkdir(exist_ok=True)

DEFAULTS = {
    "school": "Okul Adı", "server_ip": "", "http_port": 8080, "discovery_port": 45454,
    "idle_shutdown_min": 25, "durations": [20, 40, 45, 80], "extend_min": 10, "usb_block": True,
    "quote_interval": 20, "quotes": DEFAULT_QUOTES, "announcement": {"text": "", "until": 0},
    "pardus_logo_b64": "", "school_logo_b64": "",
    "wallpaper_mode": "auto", "wallpaper_b64": "",
    "qr_mode": "local", "qr_url": "", "qr_secret": "", "ext_export_sig": "",
    "teacher_code": "", "teacher_code_salt": "", "teacher_code_hash": "", "auth_ver": 1, "remember_days": 90,
    "mirror_fps": 5, "mirror_width": 1280, "mirror_quality": 55, "nonce_ttl": 90,
}

# ---------------------------------------------------------------- günlük
_log = logging.getLogger("etap")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _h = logging.handlers.RotatingFileHandler(LOGFILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _log.addHandler(_h)
events = collections.deque(maxlen=500)     # (sıra, saat, seviye, mesaj) - arayüzdeki Günlük sayfası okur
_seq = [0]


def log(level, msg):
    getattr(_log, level)(msg)
    _seq[0] += 1
    events.append((_seq[0], time.strftime("%H:%M:%S"), level, msg))


# ---------------------------------------------------------------- ayarlar
def _gen_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # karışabilecek 0/O/1/I yok
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _load_cfg():
    c = dict(DEFAULTS)
    if CFG_FILE.exists():
        try:
            c.update(json.loads(CFG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    changed = not CFG_FILE.exists()
    for k in ("psk", "qr_secret"):
        if not c.get(k):
            c[k] = secrets.token_hex(16)
            changed = True
    if not c.get("teacher_code"):
        code = _gen_code()
        salt = secrets.token_hex(8)
        c.update(teacher_code=code, teacher_code_salt=salt, teacher_code_hash=_sha(salt + code))
        changed = True
    if changed:
        CFG_FILE.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    return c


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


cfg = _load_cfg()


def save_cfg():
    CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- durum
boards = {}      # board_id -> {id, ws, ip, mac, online, state, remaining, teacher}
nonces = {}      # nonce -> {b, t, exp, teacher}
fails = {}       # board_id -> [sayı, bloke_bitiş]
ip_fails = {}    # telefon ip -> [sayı, ilk_zaman]
execs = {}       # rid -> (board_id, Future)
mirror_ids = set()
mirror_state = {"task": None, "last": 0}
status = {"ok": False, "error": ""}
loop = None
_tl = threading.local()


def _load_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_boards():
    data = {i: {"mac": b.get("mac"), "ip": b.get("ip")} for i, b in boards.items()}
    BOARDS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


for _id, _v in _load_json(BOARDS_FILE).items():
    boards[_id] = {"id": _id, "ws": None, "ip": _v.get("ip"), "mac": _v.get("mac"),
                   "online": False, "state": "?", "remaining": None, "teacher": ""}


# ---------------------------------------------------------------- ağ bilgisi
def _route_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def local_ips():
    ips = set()
    try:
        for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(r[4][0])
    except OSError:
        pass
    r = _route_ip()
    if r:
        ips.add(r)
    ips = {i for i in ips if not i.startswith("127.") and not i.startswith("169.254.")}
    return sorted(ips, key=lambda i: (i != r, i))


def server_ip():
    return cfg["server_ip"] or _route_ip() or (local_ips() or ["127.0.0.1"])[0]


# ---------------------------------------------------------------- kimlik doğrulama çekirdeği
def _hm(msg):
    return hmac.new(cfg["qr_secret"].encode(), msg.encode(), hashlib.sha256).hexdigest()


def qr_sig(b, n, t):
    return _hm(f"{b}|{n}|{t}")[:32]


def code6(b, n, t):
    d = _hm(f"code|{b}|{n}|{t}")
    return f"{(int(d[:8], 16) & 0x7fffffff) % 1_000_000:06d}"


def _b64e(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _dev_sig(payload):
    key = f"{cfg['qr_secret']}|dev|{cfg['auth_ver']}".encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(name):
    """Telefona verilen 'hatırlanan cihaz' çerezi."""
    body = json.dumps({"n": name, "e": int(time.time()) + cfg["remember_days"] * 86400, "v": cfg["auth_ver"]},
                      ensure_ascii=False)
    payload = _b64e(body.encode())
    return payload + "." + _dev_sig(payload)


def verify_token(tok):
    try:
        payload, _, sig = tok.partition(".")
        if not payload or not hmac.compare_digest(sig, _dev_sig(payload)):
            return None
        d = json.loads(_b64d(payload))
        if d["v"] != cfg["auth_ver"] or d["e"] < time.time():
            return None
        return (d.get("n") or "").strip() or "Öğretmen"
    except Exception:
        return None


def check_teacher_code(code):
    return hmac.compare_digest(cfg["teacher_code_hash"], _sha(cfg["teacher_code_salt"] + code.strip()))


def new_teacher_code():
    return _gen_code()


def set_teacher_code(code):
    """Kodu değiştirir ve tüm hatırlanan cihazları geçersiz kılar."""
    salt = secrets.token_hex(8)
    cfg.update(teacher_code=code.strip(), teacher_code_salt=salt, teacher_code_hash=_sha(salt + code.strip()))
    cfg["auth_ver"] += 1
    save_cfg()
    log("info", "Öğretmen kodu değiştirildi; kayıtlı cihazlar sıfırlandı")


def reset_devices():
    cfg["auth_ver"] += 1
    save_cfg()
    log("info", "Kayıtlı öğretmen cihazları sıfırlandı")


def make_qr_url(bid):
    n = secrets.token_urlsafe(9)
    t = int(time.time())
    nonces[n] = {"b": bid, "t": t, "exp": t + cfg["nonce_ttl"], "teacher": ""}
    q = f"b={quote(bid, safe='')}&n={n}&t={t}&s={qr_sig(bid, n, t)}"
    base = cfg["qr_url"].strip()
    if cfg["qr_mode"] == "external" and base:
        return f"{base}{'&' if '?' in base else '?'}{q}"
    return f"http://{server_ip()}:{cfg['http_port']}/auth?{q}"


def check_pin(bid, pin):
    now = time.time()
    f = fails.setdefault(bid, [0, 0])
    if now < f[1]:
        return False, "Çok fazla hatalı deneme. Biraz bekleyin.", ""
    for n, v in list(nonces.items()):
        if v["b"] == bid and v["exp"] >= now and hmac.compare_digest(code6(bid, n, v["t"]), pin):
            for k in [k for k, x in nonces.items() if x["b"] == bid]:
                nonces.pop(k, None)               # PIN tek kullanımlık
            f[0] = 0
            return True, "", v.get("teacher", "")
    f[0] += 1
    if f[0] >= 5:
        f[0], f[1] = 0, now + 60
        log("warning", f"{bid}: 5 hatalı PIN denemesi, 60 sn bloke")
    return False, "Hatalı veya süresi dolmuş PIN.", ""


def ext_sig():
    """Harici sayfaya yüklenen config.php'nin dayandığı değerlerin özeti."""
    v = [cfg["qr_secret"], cfg["auth_ver"], cfg["teacher_code_hash"], cfg["teacher_code_salt"],
         cfg["nonce_ttl"], cfg["remember_days"], cfg["school"]]
    return _sha(json.dumps(v, ensure_ascii=False))[:16]


def ext_outdated():
    return cfg["qr_mode"] == "external" and cfg.get("ext_export_sig") != ext_sig()


# ---------------------------------------------------------------- ayarlar -> tahtalar
def settings_payload(images=True):
    ann = cfg.get("announcement") or {}
    text = ann.get("text", "")
    if text and ann.get("until") and ann["until"] < time.time():
        text = ""
    p = {"type": "settings", "school": cfg["school"], "quotes": cfg["quotes"],
         "quote_interval": cfg["quote_interval"], "announcement": text,
         "idle_shutdown_min": cfg["idle_shutdown_min"], "durations": cfg["durations"],
         "extend_min": cfg["extend_min"], "usb_block": cfg["usb_block"]}
    if images:
        p.update(pardus_logo_b64=cfg["pardus_logo_b64"], school_logo_b64=cfg["school_logo_b64"],
                 wallpaper_b64=cfg["wallpaper_b64"])
    return p


async def _push(b, obj, timeout=4):
    """Başarılıysa '' , değilse hata metni döner."""
    ws = b.get("ws")
    if not b.get("online") or ws is None:
        return "Tahta çevrimdışı"
    try:
        await asyncio.wait_for(ws.send_str(json.dumps(obj)), timeout)
        return ""
    except asyncio.TimeoutError:
        return "Zaman aşımı (tahta yanıt vermiyor)"
    except Exception:
        return "Bağlantı hatası"


async def push_settings(ids=None, images=True):
    payload = settings_payload(images)
    targets = [b for b in list(boards.values()) if b.get("online") and (ids is None or b["id"] in ids)]
    await asyncio.gather(*(_push(b, payload) for b in targets))
    return {"ok": True, "sent": len(targets)}


async def set_announcement(text, minutes=0):
    cfg["announcement"] = {"text": text.strip(), "until": time.time() + minutes * 60 if minutes else 0}
    save_cfg()
    log("info", f"Kilit ekranı duyurusu {'yayınlandı' if text.strip() else 'kaldırıldı'}")
    return await push_settings(images=False)


# ---------------------------------------------------------------- telefon sayfası (yerel mod)
CSS = ("body{font-family:system-ui,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;"
       "justify-content:center;background:linear-gradient(135deg,#0B1020,#16213A);color:#E8ECF8}"
       ".c{width:min(400px,92vw);background:#18223D;border:1px solid #2A3A66;border-radius:20px;padding:28px;text-align:center}"
       "h1{font-size:20px;margin:0 0 4px}p{color:#8FA0C4;margin:6px 0 16px}label{display:block;text-align:left;color:#8FA0C4}"
       "input,button{font-size:18px;padding:14px;width:100%;margin:6px 0;box-sizing:border-box;border-radius:12px;border:1px solid #2A3A66}"
       "input{background:#0B1020;color:#fff}input[type=checkbox]{width:auto;margin-right:8px}"
       "button{background:#4F8CFF;color:#fff;border:0;font-weight:600}"
       ".pin{font-size:54px;letter-spacing:10px;font-weight:700;margin:18px 0;color:#F5B301}.e{color:#F87171}")


def _page(body, cookie=None):
    r = web.Response(content_type="text/html", text=(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<style>{CSS}</style><div class=c><h1>{html.escape(cfg['school'])}</h1>{body}</div>"))
    r.headers["Cache-Control"] = "no-store"
    if cookie:
        r.set_cookie("etap_t", cookie, max_age=cfg["remember_days"] * 86400, httponly=True, samesite="Lax", path="/")
    return r


def _qr_error(b, n, t, s):
    """Karekod geçerli mi? Hata metni ya da '' döner."""
    if not (b and n and t.isdigit() and hmac.compare_digest(qr_sig(b, n, t), s)):
        return "Geçersiz karekod."
    v = nonces.get(n)
    if not v or v["b"] != b or v["exp"] < time.time():
        return "Karekodun süresi doldu."
    return ""


def _code_page(b, n, t, name, cookie=None):
    nonces[n]["teacher"] = name
    left = max(0, int(nonces[n]["exp"] - time.time()))
    return _page(f"<p>Merhaba <b>{html.escape(name)}</b>, tahtaya şu PIN'i girin:</p><div class=pin>{code6(b, n, int(t))}</div>"
                 f"<p>Bu kod yaklaşık {left} sn geçerli ve tek kullanımlıktır.</p>", cookie)


def _form(b, n, t, s, err=""):
    e = f"<p class=e>{html.escape(err)}</p>" if err else ""
    hid = "".join(f"<input type=hidden name={k} value='{html.escape(v)}'>" for k, v in (("b", b), ("n", n), ("t", t), ("s", s)))
    return _page(f"<p>Tahta: <b>{html.escape(b)}</b></p>{e}<form method=post>{hid}"
                 "<input name=name placeholder='Adınız Soyadınız (isteğe bağlı)' autocomplete=name>"
                 "<input name=code type=password placeholder='Öğretmen kodu' autocomplete=off>"
                 "<label><input type=checkbox name=remember value=1 checked>Bu telefonu hatırla</label>"
                 "<button>PIN Üret</button></form>")


async def auth_get(request):
    q = request.query
    b, n, t, s = (q.get(k, "") for k in "bnts")
    err = _qr_error(b, n, t, s)
    if err:
        return _page(f"<p class=e>{err}</p><p>Tahtadaki yenilenmiş karekodu okutun.</p>")
    name = verify_token(request.cookies.get("etap_t", ""))
    return _code_page(b, n, t, name) if name else _form(b, n, t, s)


async def auth_post(request):
    d = await request.post()
    b, n, t, s = (d.get(k, "") for k in "bnts")
    err = _qr_error(b, n, t, s)
    if err:
        return _page(f"<p class=e>{err}</p>")
    ip = request.remote
    cnt = ip_fails.get(ip, [0, time.time()])
    if time.time() - cnt[1] > 600:
        cnt = [0, time.time()]
    if cnt[0] >= 8:
        return _page("<p class=e>Çok fazla hatalı deneme. 10 dakika sonra tekrar deneyin.</p>")
    if not check_teacher_code(d.get("code", "")):
        cnt[0] += 1
        ip_fails[ip] = cnt
        log("warning", f"Hatalı öğretmen kodu denemesi ({ip})")
        return _form(b, n, t, s, "Öğretmen kodu hatalı.")
    ip_fails.pop(ip, None)
    name = (d.get("name", "").strip()[:40]) or "Öğretmen"
    return _code_page(b, n, t, name, make_token(name) if d.get("remember") else None)


# ---------------------------------------------------------------- tahta WebSocket
async def ws_client(request):
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2 ** 24)
    await ws.prepare(request)
    bid = None
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            d = json.loads(msg.data)
            t = d.get("type")
            if t == "hello":
                if not hmac.compare_digest(str(d.get("psk", "")), cfg["psk"]):
                    log("warning", f"Hatalı anahtarla bağlantı denemesi ({request.remote})")
                    break
                bid = str(d["id"])[:64]
                b = boards.setdefault(bid, {"id": bid, "teacher": ""})
                b.update(ws=ws, ip=request.remote, mac=d.get("mac") or b.get("mac"),
                         online=True, state="locked", remaining=None)
                _save_boards()
                log("info", f"{bid} bağlandı ({request.remote})")
                await ws.send_str(json.dumps(settings_payload()))
            elif bid is None:
                break
            elif t == "need_qr":
                for k in [k for k, v in nonces.items() if v["exp"] < time.time()]:
                    nonces.pop(k, None)
                await ws.send_str(json.dumps({"type": "qr", "url": make_qr_url(bid)}))
            elif t == "verify_pin":
                ok, m, teacher = check_pin(bid, str(d.get("pin", "")))
                if ok:
                    boards[bid]["teacher"] = teacher
                    log("info", f"{bid}: kilit açıldı" + (f" ({teacher})" if teacher else ""))
                else:
                    log("warning", f"{bid}: hatalı PIN")
                await ws.send_str(json.dumps({"type": "pin_result", "ok": ok, "msg": m, "teacher": teacher}))
            elif t == "state":
                boards[bid].update(state=d.get("state"), remaining=d.get("remaining"))
            elif t == "exec_result":
                ent = execs.get(d.get("rid"))
                if ent and not ent[1].done():
                    ent[1].set_result({"ok": True, "rc": d.get("rc"), "out": d.get("out", ""), "error": ""})
    finally:
        if bid and boards.get(bid, {}).get("ws") is ws:
            boards[bid].update(online=False, ws=None, state="?")
            mirror_ids.discard(bid)
            log("warning", f"{bid} bağlantısı koptu")
            for rid, (owner, fut) in list(execs.items()):      # bekleyen komutlar hemen hata alsın
                if owner == bid and not fut.done():
                    fut.set_result({"ok": False, "rc": None, "out": "", "error": "Komut sırasında bağlantı koptu"})
    return ws


async def get_file(request):
    if not hmac.compare_digest(request.headers.get("X-PSK", ""), cfg["psk"]):
        raise web.HTTPForbidden()
    p = FILES / Path(request.match_info["name"]).name
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p)


# ---------------------------------------------------------------- arayüzün kullandığı API
def snapshot():
    out = []
    for b in sorted(boards.values(), key=lambda x: x["id"].lower()):
        d = {k: b.get(k) for k in ("id", "ip", "mac", "online", "state", "remaining", "teacher")}
        d["mirror"] = b["id"] in mirror_ids
        out.append(d)
    return out


def forget(ids):
    for i in ids:
        if i in boards and not boards[i].get("online"):
            boards.pop(i)
    _save_boards()


async def send_to(ids, obj):
    """Tüm hedeflere EŞZAMANLI gönderir. {'sent': n, 'ok': [...], 'failed': {id: neden}} döner."""
    ok, failed = [], {}

    async def one(i):
        b = boards.get(i)
        err = await _push(b, obj) if b else "Tahta bulunamadı"
        if err:
            failed[i] = err
        else:
            ok.append(i)
    await asyncio.gather(*(one(i) for i in ids))
    if failed:
        log("warning", f"'{obj.get('type')}' komutu {len(failed)} tahtaya iletilemedi: " +
            ", ".join(f"{k} ({v})" for k, v in failed.items()))
    else:
        log("info", f"'{obj.get('type')}' komutu {len(ok)} tahtaya iletildi")
    return {"sent": len(ok), "ok": ok, "failed": failed}


async def send_file(ids, name):
    url = f"http://{server_ip()}:{cfg['http_port']}/files/{quote(name)}"
    return await send_to(ids, {"type": "file", "name": name, "url": url})


async def send_file_path(ids, path):
    """Dosyayı paylaşım klasörüne (arayüzü dondurmadan) kopyalar ve tahtalara iletir."""
    name = Path(path).name
    await asyncio.get_running_loop().run_in_executor(None, shutil.copyfile, path, FILES / name)
    return await send_file(ids, name)


async def _run_exec(b, cmd):
    rid = secrets.token_hex(4)
    fut = asyncio.get_running_loop().create_future()
    execs[rid] = (b["id"], fut)
    try:
        err = await _push(b, {"type": "exec", "rid": rid, "cmd": cmd})
        if err:
            return {"ok": False, "rc": None, "out": "", "error": err}
        return await asyncio.wait_for(fut, 70)
    except asyncio.TimeoutError:
        return {"ok": False, "rc": None, "out": "", "error": "Yanıt zaman aşımı (70 sn)"}
    finally:
        execs.pop(rid, None)


async def exec_on(ids, cmd, on_result=None):
    """Komutu seçili tahtalarda eşzamanlı çalıştırır; her tahtanın sonucu biter bitmez on_result(id, sonuç) çağrılır."""
    results = {}

    def done(i, r):
        results[i] = r
        if on_result:
            on_result(i, r)

    async def one(i):
        b = boards.get(i)
        if not b or not b.get("online"):
            return done(i, {"ok": False, "rc": None, "out": "", "error": "Tahta çevrimdışı"})
        done(i, await _run_exec(b, cmd))
    await asyncio.gather(*(one(i) for i in ids))
    bad = [i for i, r in results.items() if not r["ok"]]
    log("warning" if bad else "info", f"Terminal '{cmd}': {len(results) - len(bad)} başarılı, {len(bad)} ulaşılamadı")
    return results


def _wol_sync(ids):
    n = 0
    for i in ids:
        mac = boards.get(i, {}).get("mac")
        if not mac:
            continue
        pkt = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "").replace("-", "")) * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for ip in local_ips() + [""]:
                bc = "255.255.255.255" if not ip else ip.rsplit(".", 1)[0] + ".255"
                for port in (9, 7):
                    try:
                        s.sendto(pkt, (bc, port))
                    except OSError:
                        pass
        n += 1
    log("info", f"{n} tahtaya WOL sinyali gönderildi")
    return n


async def wol(ids):
    return await asyncio.get_running_loop().run_in_executor(None, _wol_sync, ids)


# ---------------------------------------------------------------- ekran yansıtma
def _grab_jpeg():
    import mss
    from PIL import Image
    sct = getattr(_tl, "sct", None)
    if sct is None:
        sct = _tl.sct = mss.mss()
    shot = sct.grab(sct.monitors[1])
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    w = cfg["mirror_width"]
    if img.width > w:
        img = img.resize((w, int(img.height * w / img.width)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=cfg["mirror_quality"])
    return buf.getvalue()


async def _mirror_loop():
    lp = asyncio.get_running_loop()
    last_sent = 0
    try:
        while mirror_ids:
            t0 = time.time()
            frame = await lp.run_in_executor(None, _grab_jpeg)
            crc = zlib.crc32(frame)
            if crc != mirror_state["last"] or t0 - last_sent > 1.0:
                mirror_state["last"], last_sent = crc, t0
                targets = [boards[i]["ws"] for i in list(mirror_ids)
                           if boards.get(i, {}).get("online") and boards[i].get("ws")]
                await asyncio.gather(*(asyncio.wait_for(w.send_bytes(frame), 2) for w in targets),
                                     return_exceptions=True)
            await asyncio.sleep(max(0, 1 / cfg["mirror_fps"] - (time.time() - t0)))
    finally:
        mirror_state["task"] = None


async def mirror(ids, on):
    res = await send_to(ids, {"type": "mirror", "on": on})
    for i in res["ok"]:
        (mirror_ids.add if on else mirror_ids.discard)(i)
    if not on:
        for i in ids:
            mirror_ids.discard(i)
    mirror_state["last"] = 0
    if mirror_ids and mirror_state["task"] is None:
        mirror_state["task"] = asyncio.create_task(_mirror_loop())
    return res


# ---------------------------------------------------------------- arka plan görevleri
async def _beacon():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        msg = f"ETAPLOCK|{server_ip()}|{cfg['http_port']}".encode()
        for t in ["255.255.255.255"] + [ip.rsplit(".", 1)[0] + ".255" for ip in local_ips()]:
            try:
                s.sendto(msg, (t, cfg["discovery_port"]))
            except OSError:
                pass
        await asyncio.sleep(5)


async def _maintenance():
    while True:
        await asyncio.sleep(5)
        ann = cfg.get("announcement") or {}
        if ann.get("text") and ann.get("until") and ann["until"] < time.time():
            cfg["announcement"] = {"text": "", "until": 0}
            save_cfg()
            await push_settings(images=False)


async def _serve():
    app = web.Application()
    app.add_routes([web.get("/ws", ws_client), web.get("/auth", auth_get),
                    web.post("/auth", auth_post), web.get("/files/{name}", get_file)])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", cfg["http_port"]).start()
        status["ok"] = True
        log("info", f"Sunucu başlatıldı: {server_ip()}:{cfg['http_port']}")
    except OSError as e:
        status["error"] = str(e)
        log("error", f"Sunucu başlatılamadı: {e}")
    asyncio.create_task(_beacon())
    asyncio.create_task(_maintenance())


def _thread_main():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_serve())
    loop.run_forever()


def start():
    global loop
    loop = asyncio.new_event_loop()
    threading.Thread(target=_thread_main, daemon=True).start()


def submit(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop)
