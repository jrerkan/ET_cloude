"""assets/app.ico dosyasını üretir (Pillow). GitHub Actions derlemesinden önce çalışır."""
from pathlib import Path
from PIL import Image, ImageDraw

N = 256
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
# degrade zemin
grad = Image.new("RGBA", (N, N))
px = grad.load()
for y in range(N):
    for x in range(N):
        t = (x + y) / (2 * N)
        px[x, y] = (int(79 + (109 - 79) * t), int(140 + (91 - 140) * t), int(255), 255)
mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), radius=58, fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)
d.rounded_rectangle((72, 118, 184, 200), radius=16, fill="white")           # kilit gövdesi
d.arc((86, 52, 170, 152), 180, 360, fill="white", width=18)                  # kilit kancası
d.rounded_rectangle((120, 148, 136, 176), radius=6, fill=(79, 140, 255, 255))  # anahtar deliği
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
img.save(out / "app.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("app.ico üretildi")
