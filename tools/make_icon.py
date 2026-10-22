"""Generate assets/icon.ico (a label with a barcode and "SL"). Run: python tools/make_icon.py"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 256
BLUE = (30, 90, 170)

im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((14, 34, 242, 222), 30, fill=(255, 255, 255), outline=BLUE, width=12)
d.ellipse((30, 50, 52, 72), fill=BLUE)  # label hole
try:
    font = ImageFont.truetype("arialbd.ttf", 92)
except OSError:
    font = ImageFont.load_default()
d.text((72, 40), "SL", font=font, fill=BLUE)
x = 40
for w in (6, 3, 9, 3, 6, 12, 3, 6, 9, 3, 6, 4, 8):
    d.rectangle((x, 148, x + w, 200), fill=(25, 25, 25))
    x += w + 5
im.save(os.path.join(ROOT, "assets", "icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("assets/icon.ico written")
