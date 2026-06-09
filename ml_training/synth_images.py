"""Generador procedural de imagenes de paquetes para las 3 clases del CU-11.

Es un PLACEHOLDER realista para arrancar sin datasets externos: dibuja cajas
limpias, dañadas y con etiqueta ilegible. El pipeline (MobileNetV2) es real; para
produccion, reemplazar por fotos reales (Roboflow/Parcel3D) y reentrenar.

Clases por indice: 0=SIN_DAÑO, 1=POSIBLE_DAÑO, 2=ETIQUETA_ILEGIBLE.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def gen_image(idx: int, rng: np.random.Generator, size: int = 160) -> np.ndarray:
    bg = int(rng.integers(200, 245))
    bgc = (bg, bg, bg)
    arr = np.full((size, size, 3), bg, np.uint8)
    arr = (arr.astype(np.int16) + rng.integers(-12, 12, (size, size, 3))).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)

    # Caja de carton
    w = int(rng.integers(int(size * 0.45), int(size * 0.75)))
    h = int(rng.integers(int(size * 0.45), int(size * 0.75)))
    x0 = int(rng.integers(5, size - w - 5))
    y0 = int(rng.integers(5, size - h - 5))
    x1, y1 = x0 + w, y0 + h
    col = (int(rng.integers(150, 205)), int(rng.integers(110, 160)), int(rng.integers(70, 115)))
    d.rectangle([x0, y0, x1, y1], fill=col, outline=(90, 60, 30), width=2)
    midx, midy = (x0 + x1) // 2, (y0 + y1) // 2
    d.line([(midx, y0), (midx, y1)], fill=(120, 90, 50), width=3)  # cinta vertical
    d.line([(x0, midy), (x1, midy)], fill=(120, 90, 50), width=2)  # cinta horizontal

    if idx == 1:  # POSIBLE_DAÑO: gashes, esquina rota, abolladuras
        for _ in range(int(rng.integers(4, 8))):
            d.line(
                [(int(rng.integers(x0, x1)), int(rng.integers(y0, y1))),
                 (int(rng.integers(x0, x1)), int(rng.integers(y0, y1)))],
                fill=(40, 30, 20), width=int(rng.integers(2, 5)),
            )
        s = int(rng.integers(15, 35))
        corner = int(rng.integers(0, 4))
        if corner == 0:
            d.polygon([(x0, y0), (x0 + s, y0), (x0, y0 + s)], fill=bgc)
        elif corner == 1:
            d.polygon([(x1, y0), (x1 - s, y0), (x1, y0 + s)], fill=bgc)
        elif corner == 2:
            d.polygon([(x0, y1), (x0 + s, y1), (x0, y1 - s)], fill=bgc)
        else:
            d.polygon([(x1, y1), (x1 - s, y1), (x1, y1 - s)], fill=bgc)
        for _ in range(int(rng.integers(1, 4))):
            cx, cy = int(rng.integers(x0, x1)), int(rng.integers(y0, y1))
            r = int(rng.integers(5, 14))
            dc = (max(col[0] - 60, 0), max(col[1] - 60, 0), max(col[2] - 40, 0))
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dc)

    elif idx == 2:  # ETIQUETA_ILEGIBLE: etiqueta blanca con garabatos + blur
        lw = int(rng.integers(40, 70))
        lh = int(rng.integers(22, 38))
        lx = int(rng.integers(x0 + 3, max(x0 + 4, x1 - lw - 3)))
        ly = int(rng.integers(y0 + 3, max(y0 + 4, y1 - lh - 3)))
        d.rectangle([lx, ly, lx + lw, ly + lh], fill=(245, 245, 245), outline=(150, 150, 150))
        for _ in range(int(rng.integers(8, 16))):
            g = int(rng.integers(40, 120))
            d.line(
                [(int(rng.integers(lx, lx + lw)), int(rng.integers(ly, ly + lh))),
                 (int(rng.integers(lx, lx + lw)), int(rng.integers(ly, ly + lh)))],
                fill=(g, g, g), width=1,
            )
        region = img.crop((lx, ly, lx + lw, ly + lh)).filter(
            ImageFilter.GaussianBlur(float(rng.integers(2, 4)))
        )
        img.paste(region, (lx, ly))

    out = np.asarray(img).astype(np.int16)
    out = (out + int(rng.integers(-15, 15))).clip(0, 255).astype(np.uint8)
    return out


def gen_dataset(n_por_clase: int = 240, size: int = 160, seed: int = 42):
    rng = np.random.default_rng(seed)
    X, y = [], []
    for idx in range(3):
        for _ in range(n_por_clase):
            X.append(gen_image(idx, rng, size))
            y.append(idx)
    return np.stack(X), np.array(y, dtype="int64")
