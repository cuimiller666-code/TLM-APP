import base64
import json
import os
import re
import shutil
import struct
import tempfile
import asyncio
import threading
import time
import traceback
import zlib
from pathlib import Path

import flet as ft


# --- 1. 纯 Python 核心算法：保留旧版计算代码 ---
def simple_linear_fit(x_list, y_list):
    x = [float(i) for i in x_list]
    y = [float(i) for i in y_list]
    n = len(x)

    if n < 2: return 0.0, 0.0, 0.0

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(i * j for i, j in zip(x, y))
    sum_xx = sum(i * i for i in x)

    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0: return 0.0, 0.0, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n

    y_mean = sum_y / n
    ss_tot = sum((i - y_mean) ** 2 for i in y)
    ss_res = sum((j - (slope * i + intercept)) ** 2 for i, j in zip(x, y))

    if ss_tot == 0:
        r2 = 0.0
    else:
        r2 = 1 - (ss_res / ss_tot)

    return slope, intercept, r2


HISTORY_LIMIT = 1500
HISTORY_KEY = "gpt_tlm_history_json_v1"
PRESETS_KEY = "gpt_tlm_presets_json_v1"
ACTIVE_PRESET_KEY = "gpt_tlm_active_preset_id_v1"
TIMER_STATE_KEY = "gpt_tlm_timer_state_json_v1"


def _new_id(prefix):
    return f"{prefix}_{int(time.time() * 1000)}"


def _format_number(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _split_number_text(text):
    return [p for p in re.split(r"[,，;；\s]+", text or "") if p.strip()]


def build_spacings(spacing_text, count_value):
    values = [float(p.strip()) for p in _split_number_text(spacing_text)]
    try:
        count = int(float(str(count_value).strip()))
    except Exception:
        count = len(values)

    if count <= 0:
        raise ValueError("TLM 数量必须大于 0")

    if not values:
        values = [2 + i * 2 for i in range(count)]

    if len(values) > count:
        values = values[:count]

    if len(values) < count:
        if len(values) >= 2:
            step = values[-1] - values[-2]
            if step <= 0:
                step = 2
        else:
            step = 2
        last = values[-1]
        while len(values) < count:
            last += step
            values.append(last)

    return values


def spacings_to_text(spacings):
    return ",".join(_format_number(s) for s in spacings)


def default_preset():
    return {
        "id": "default",
        "name": "默认 7 点 TLM",
        "width": 100.0,
        "voltage": 5.0,
        "tlm_count": 7,
        "spacings": [2, 3, 5, 7, 9, 11, 17],
    }


def normalize_preset(preset):
    base = default_preset()
    merged = {**base, **(preset or {})}
    spacings = merged.get("spacings")
    if not isinstance(spacings, list):
        spacings = build_spacings(merged.get("spacing_values", ""), merged.get("tlm_count", 7))
    count = int(merged.get("tlm_count") or len(spacings) or 1)
    spacings = build_spacings(spacings_to_text(spacings), count)
    return {
        "id": str(merged.get("id") or _new_id("preset")),
        "name": str(merged.get("name") or "未命名预设"),
        "width": float(merged.get("width") or base["width"]),
        "voltage": float(merged.get("voltage") or base["voltage"]),
        "tlm_count": count,
        "spacings": spacings,
    }


def safe_filename(name):
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or "TLM"


def is_android_runtime():
    return os.name != "nt" and (
        Path("/storage/emulated/0").exists()
        or Path("/sdcard").exists()
        or bool(os.environ.get("ANDROID_DATA"))
    )


def default_export_dir():
    candidates = []
    android_runtime = is_android_runtime()

    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidates.append(Path(userprofile) / "Pictures" / "TLM")

    if android_runtime:
        for android_path in (
            "/storage/emulated/0/1aTLM",
            "/sdcard/1aTLM",
            "/storage/self/primary/1aTLM",
            "/storage/emulated/0/Download/1aTLM",
            "/sdcard/Download/1aTLM",
            "/storage/emulated/0/Android/media/com.cuimiller.tlm_app/1aTLM",
            "/sdcard/Android/media/com.cuimiller.tlm_app/1aTLM",
            "/storage/emulated/0/Pictures/TLM",
            "/sdcard/Pictures/TLM",
        ):
            candidates.append(Path(android_path))

    home = Path.home()
    if not android_runtime:
        candidates.append(home / "Pictures" / "TLM")

    app_data = os.environ.get("FLET_APP_STORAGE_DATA")
    if app_data and not android_runtime:
        candidates.append(Path(app_data) / "exports")

    if not android_runtime:
        candidates.append(Path(tempfile.gettempdir()) / "TLM")

    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            test_file = directory / ".write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return directory
        except Exception:
            continue

    if android_runtime:
        raise PermissionError("无法写入手机存储 1aTLM。请在系统设置中给 TLM APP 授予文件/所有文件访问权限。")

    return Path(tempfile.gettempdir())


def normalize_android_save_path(path):
    text = str(path or "")
    if text.startswith("/document/primary:"):
        rel_path = text.removeprefix("/document/primary:").lstrip("/")
        if rel_path:
            return str(Path("/storage/emulated/0") / rel_path)
    if text.startswith("content://") or text.startswith("/document/"):
        return None
    return text


def find_cjk_font_path():
    candidates = [
        os.environ.get("TLM_FONT_PATH"),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/system/fonts/NotoSansCJK-Regular.ttc",
        "/system/fonts/NotoSansSC-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


_FONT_5X7 = {
    " ": ["000", "000", "000", "000", "000", "000", "000"],
    ".": ["0", "0", "0", "0", "0", "0", "1"],
    ",": ["0", "0", "0", "0", "0", "1", "1"],
    ":": ["0", "1", "0", "0", "0", "1", "0"],
    "-": ["000", "000", "000", "111", "000", "000", "000"],
    "_": ["000", "000", "000", "000", "000", "000", "111"],
    "/": ["001", "001", "010", "010", "100", "100", "000"],
    "(": ["01", "10", "10", "10", "10", "10", "01"],
    ")": ["10", "01", "01", "01", "01", "01", "10"],
    "0": ["111", "101", "101", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "010", "010", "111"],
    "2": ["111", "001", "001", "111", "100", "100", "111"],
    "3": ["111", "001", "001", "111", "001", "001", "111"],
    "4": ["101", "101", "101", "111", "001", "001", "001"],
    "5": ["111", "100", "100", "111", "001", "001", "111"],
    "6": ["111", "100", "100", "111", "101", "101", "111"],
    "7": ["111", "001", "001", "010", "010", "100", "100"],
    "8": ["111", "101", "101", "111", "101", "101", "111"],
    "9": ["111", "101", "101", "111", "001", "001", "111"],
    "A": ["010", "101", "101", "111", "101", "101", "101"],
    "B": ["110", "101", "101", "110", "101", "101", "110"],
    "C": ["111", "100", "100", "100", "100", "100", "111"],
    "D": ["110", "101", "101", "101", "101", "101", "110"],
    "E": ["111", "100", "100", "110", "100", "100", "111"],
    "F": ["111", "100", "100", "110", "100", "100", "100"],
    "G": ["111", "100", "100", "101", "101", "101", "111"],
    "H": ["101", "101", "101", "111", "101", "101", "101"],
    "I": ["111", "010", "010", "010", "010", "010", "111"],
    "J": ["001", "001", "001", "001", "101", "101", "111"],
    "K": ["101", "101", "110", "100", "110", "101", "101"],
    "L": ["100", "100", "100", "100", "100", "100", "111"],
    "M": ["101", "111", "111", "101", "101", "101", "101"],
    "N": ["101", "111", "111", "111", "101", "101", "101"],
    "O": ["111", "101", "101", "101", "101", "101", "111"],
    "P": ["111", "101", "101", "111", "100", "100", "100"],
    "Q": ["111", "101", "101", "101", "111", "001", "001"],
    "R": ["111", "101", "101", "111", "110", "101", "101"],
    "S": ["111", "100", "100", "111", "001", "001", "111"],
    "T": ["111", "010", "010", "010", "010", "010", "010"],
    "U": ["101", "101", "101", "101", "101", "101", "111"],
    "V": ["101", "101", "101", "101", "101", "101", "010"],
    "W": ["101", "101", "101", "101", "111", "111", "101"],
    "X": ["101", "101", "101", "010", "101", "101", "101"],
    "Y": ["101", "101", "101", "010", "010", "010", "010"],
    "Z": ["111", "001", "001", "010", "100", "100", "111"],
}


def _rgb(color):
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    return bytes(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _put_rect(buf, width, height, x1, y1, x2, y2, color):
    color = _rgb(color) if isinstance(color, str) else color
    x1, x2 = sorted((int(x1), int(x2)))
    y1, y2 = sorted((int(y1), int(y2)))
    x1, x2 = max(0, min(width - 1, x1)), max(0, min(width - 1, x2))
    y1, y2 = max(0, min(height - 1, y1)), max(0, min(height - 1, y2))
    for y in range(y1, y2 + 1):
        row = (y * width + x1) * 3
        for _ in range(x1, x2 + 1):
            buf[row:row + 3] = color
            row += 3


def _put_line(buf, width, height, x1, y1, x2, y2, color, thickness=1):
    color = _rgb(color) if isinstance(color, str) else color
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    dx = abs(x2 - x1)
    dy = -abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx + dy
    r = max(0, int(thickness) // 2)
    while True:
        _put_rect(buf, width, height, x1 - r, y1 - r, x1 + r, y1 + r, color)
        if x1 == x2 and y1 == y2:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x1 += sx
        if e2 <= dx:
            err += dx
            y1 += sy


def _put_circle(buf, width, height, cx, cy, radius, color):
    color = _rgb(color) if isinstance(color, str) else color
    cx, cy, radius = int(round(cx)), int(round(cy)), int(radius)
    r2 = radius * radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                _put_rect(buf, width, height, x, y, x, y, color)


def _safe_ascii(text):
    text = str(text or "")
    text = text.replace("Ω", "OHM").replace("μ", "U").replace("²", "2").replace("ρ", "RHO")
    text = re.sub(r"[^A-Za-z0-9 .,_:/()\\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _put_text(buf, width, height, x, y, text, color="#111827", scale=4):
    color = _rgb(color) if isinstance(color, str) else color
    cursor = int(x)
    for ch in _safe_ascii(text).upper():
        glyph = _FONT_5X7.get(ch, _FONT_5X7[" "])
        glyph_width = max(len(row) for row in glyph)
        for row_index, row in enumerate(glyph):
            for col_index, bit in enumerate(row):
                if bit == "1":
                    _put_rect(
                        buf,
                        width,
                        height,
                        cursor + col_index * scale,
                        y + row_index * scale,
                        cursor + (col_index + 1) * scale - 1,
                        y + (row_index + 1) * scale - 1,
                        color,
                    )
        cursor += (glyph_width + 1) * scale
    return cursor


def _png_bytes(width, height, buf):
    rows = []
    stride = width * 3
    for y in range(height):
        rows.append(b"\x00" + bytes(buf[y * stride:(y + 1) * stride]))
    raw = b"".join(rows)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def generate_16x9_png_basic(data, output_dir=None):
    output_dir = Path(output_dir or default_export_dir())
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    export_time = time.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"{safe_filename(data.get('name'))}_{stamp}_16x9.png"
    path = output_dir / filename

    width, height = 1600, 900
    buf = bytearray(_rgb("#f7f9fc") * (width * height))
    d_list = [float(v) for v in data["d_list"]]
    r_list = [float(v) for v in data["r_list"]]
    currents = [float(v) for v in data["currents"]]
    slope = float(data["slope"])
    intercept = float(data["intercept"])

    _put_text(buf, width, height, 70, 42, data.get("name") or "TLM ANALYSIS", "#111827", 7)
    _put_text(buf, width, height, 70, 106, f"W={data['w']:.4g} um  V={data['v']:.4g} V  {export_time}", "#425466", 4)

    chart_x, chart_y, chart_w, chart_h = 80, 170, 560, 500
    _put_rect(buf, width, height, chart_x, chart_y, chart_x + chart_w, chart_y + chart_h, "#ffffff")
    _put_line(buf, width, height, chart_x, chart_y, chart_x + chart_w, chart_y, "#cbd5e1", 2)
    _put_line(buf, width, height, chart_x, chart_y + chart_h, chart_x + chart_w, chart_y + chart_h, "#334155", 3)
    _put_line(buf, width, height, chart_x, chart_y, chart_x, chart_y + chart_h, "#334155", 3)
    _put_line(buf, width, height, chart_x + chart_w, chart_y, chart_x + chart_w, chart_y + chart_h, "#cbd5e1", 2)
    for i in range(1, 5):
        gx = chart_x + chart_w * i / 5
        gy = chart_y + chart_h * i / 5
        _put_line(buf, width, height, gx, chart_y, gx, chart_y + chart_h, "#e2e8f0", 1)
        _put_line(buf, width, height, chart_x, gy, chart_x + chart_w, gy, "#e2e8f0", 1)

    x_min, x_max = min(d_list), max(d_list)
    if x_min == x_max:
        x_min -= 1
        x_max += 1
    x_pad = max((x_max - x_min) * 0.08, 0.5)
    line_x = [x_min - x_pad, x_max + x_pad]
    line_y = [slope * x + intercept for x in line_x]
    y_values = r_list + line_y
    y_min, y_max = min(y_values), max(y_values)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    y_pad = max((y_max - y_min) * 0.12, 1)
    y_min -= y_pad
    y_max += y_pad
    x_min, x_max = line_x

    def map_x(value):
        return chart_x + (float(value) - x_min) / (x_max - x_min) * chart_w

    def map_y(value):
        return chart_y + chart_h - (float(value) - y_min) / (y_max - y_min) * chart_h

    _put_line(buf, width, height, map_x(line_x[0]), map_y(line_y[0]), map_x(line_x[1]), map_y(line_y[1]), "#2196f3", 8)
    for d, r in zip(d_list, r_list):
        _put_circle(buf, width, height, map_x(d), map_y(r), 15, "#f44336")
    _put_text(buf, width, height, chart_x + 120, chart_y + chart_h + 26, "SPACING D (UM)", "#425466", 4)
    _put_text(buf, width, height, chart_x + 18, chart_y + 18, "R (OHM)", "#425466", 4)

    info_x, info_y = 760, 200
    _put_text(buf, width, height, info_x, info_y, "RESULTS", "#111827", 7)
    lines = [
        f"R2  {data['r2']:.5f}",
        f"RSH {data['Rsh']:.2f} OHM/SQ",
        f"RC  {data['Rc_norm']:.4f} OHM.MM",
        f"LT  {data['LT']:.4f} UM",
        f"RHO {data['rho_c']:.2E} OHM.CM2",
    ]
    for index, line in enumerate(lines):
        _put_text(buf, width, height, info_x, info_y + 78 + index * 56, line, "#1565c0", 5)

    table_x, table_y, table_w, row_h = 80, 730, 1320, 52
    _put_rect(buf, width, height, table_x, table_y, table_x + table_w, table_y + row_h * 3, "#ffffff")
    _put_rect(buf, width, height, table_x, table_y, table_x + table_w, table_y + row_h, "#eef3f8")
    for row_index in range(4):
        y = table_y + row_index * row_h
        _put_line(buf, width, height, table_x, y, table_x + table_w, y, "#334155", 2)
    _put_line(buf, width, height, table_x, table_y, table_x, table_y + row_h * 3, "#334155", 2)
    _put_line(buf, width, height, table_x + table_w, table_y, table_x + table_w, table_y + row_h * 3, "#334155", 2)
    _put_text(buf, width, height, table_x + 34, table_y + 14, "INPUTS", "#111827", 4)
    d_values = ", ".join(_format_number(d) for d in d_list)
    i_values = ", ".join(f"{current:g}" for current in currents)
    _put_text(buf, width, height, table_x + 34, table_y + row_h + 14, f"D (UM): {d_values}", "#111827", 4)
    _put_text(buf, width, height, table_x + 34, table_y + row_h * 2 + 14, f"I (MA): {i_values}", "#111827", 4)

    path.write_bytes(_png_bytes(width, height, buf))
    return str(path)


def _font_candidates(bold=False):
    names = ["timesbd.ttf", "Times New Roman Bold.ttf"] if bold else ["times.ttf", "Times New Roman.ttf"]
    paths = []
    for name in names:
        paths.extend([
            Path(r"C:\Windows\Fonts") / name,
            Path("/system/fonts") / name,
        ])
    if bold:
        paths.extend([
            Path("/system/fonts/NotoSerif-Bold.ttf"),
            Path("/system/fonts/Roboto-Bold.ttf"),
            Path("/system/fonts/NotoSans-Bold.ttf"),
        ])
    else:
        paths.extend([
            Path("/system/fonts/NotoSerif-Regular.ttf"),
            Path("/system/fonts/Roboto-Regular.ttf"),
            Path("/system/fonts/NotoSans-Regular.ttf"),
        ])
    return paths


def generate_16x9_png_pillow(data, output_dir=None):
    from PIL import Image, ImageDraw, ImageFont

    output_dir = Path(output_dir or default_export_dir())
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    export_time = time.strftime("%Y-%m-%d %H:%M:%S")
    path = output_dir / f"{safe_filename(data.get('name'))}_{stamp}_16x9.png"

    def font(size, bold=False):
        for candidate in _font_candidates(bold):
            if candidate.exists():
                try:
                    return ImageFont.truetype(str(candidate), size=size)
                except Exception:
                    pass
        try:
            return ImageFont.truetype("DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf", size=size)
        except Exception:
            return ImageFont.load_default()

    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#f7f9fc")
    draw = ImageDraw.Draw(image)

    title_font = font(58, bold=True)
    subtitle_font = font(30)
    label_font = font(28, bold=True)
    text_font = font(30)
    metric_font = font(42, bold=True)

    title = _safe_ascii(data.get("name") or "TLM Analysis")
    draw.text((70, 36), title, fill="#111827", font=title_font)
    draw.text(
        (70, 108),
        f"W={data['w']:.4g} um    V={data['v']:.4g} V    {export_time}",
        fill="#425466",
        font=subtitle_font,
    )

    d_list = [float(v) for v in data["d_list"]]
    r_list = [float(v) for v in data["r_list"]]
    currents = [float(v) for v in data["currents"]]
    slope = float(data["slope"])
    intercept = float(data["intercept"])

    chart_x, chart_y, chart_w, chart_h = 80, 175, 560, 500
    draw.rectangle((chart_x, chart_y, chart_x + chart_w, chart_y + chart_h), fill="white", outline="#cbd5e1", width=2)
    for i in range(1, 5):
        gx = chart_x + chart_w * i / 5
        gy = chart_y + chart_h * i / 5
        draw.line((gx, chart_y, gx, chart_y + chart_h), fill="#e2e8f0", width=1)
        draw.line((chart_x, gy, chart_x + chart_w, gy), fill="#e2e8f0", width=1)
    draw.line((chart_x, chart_y + chart_h, chart_x + chart_w, chart_y + chart_h), fill="#334155", width=4)
    draw.line((chart_x, chart_y, chart_x, chart_y + chart_h), fill="#334155", width=4)

    x_min, x_max = min(d_list), max(d_list)
    if x_min == x_max:
        x_min -= 1
        x_max += 1
    x_pad = max((x_max - x_min) * 0.08, 0.5)
    line_x = [x_min - x_pad, x_max + x_pad]
    line_y = [slope * x + intercept for x in line_x]
    y_values = r_list + line_y
    y_min, y_max = min(y_values), max(y_values)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    y_pad = max((y_max - y_min) * 0.12, 1)
    y_min -= y_pad
    y_max += y_pad
    x_min, x_max = line_x

    def map_x(value):
        return chart_x + (float(value) - x_min) / (x_max - x_min) * chart_w

    def map_y(value):
        return chart_y + chart_h - (float(value) - y_min) / (y_max - y_min) * chart_h

    draw.line((map_x(line_x[0]), map_y(line_y[0]), map_x(line_x[1]), map_y(line_y[1])), fill="#2196f3", width=9)
    for d, r in zip(d_list, r_list):
        x, y = map_x(d), map_y(r)
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill="#f44336", outline="#b91c1c")
    draw.text((chart_x + 150, chart_y + chart_h + 26), "Spacing d (um)", fill="#425466", font=text_font)
    draw.text((chart_x + 18, chart_y + 18), "R (ohm)", fill="#425466", font=text_font)

    info_x, info_y = 760, 198
    draw.text((info_x, info_y), "Results", fill="#111827", font=title_font)
    metrics = [
        ("R2", f"{data['r2']:.5f}"),
        ("Rsh", f"{data['Rsh']:.2f} ohm/sq"),
        ("Rc", f"{data['Rc_norm']:.4f} ohm.mm"),
        ("LT", f"{data['LT']:.4f} um"),
        ("rho", f"{data['rho_c']:.2E} ohm.cm2"),
    ]
    for index, (label, value) in enumerate(metrics):
        y = info_y + 92 + index * 58
        draw.text((info_x, y), label, fill="#5b677a", font=label_font)
        draw.text((info_x + 110, y - 8), value, fill="#1565c0", font=metric_font)

    table_x, table_y, table_w, row_h = 80, 730, 1320, 52
    draw.rectangle((table_x, table_y, table_x + table_w, table_y + row_h * 3), fill="white", outline="#334155", width=3)
    draw.rectangle((table_x, table_y, table_x + table_w, table_y + row_h), fill="#eef3f8")
    for row_index in range(1, 3):
        y = table_y + row_index * row_h
        draw.line((table_x, y, table_x + table_w, y), fill="#334155", width=2)
    draw.text((table_x + 34, table_y + 10), "Inputs", fill="#111827", font=label_font)
    draw.text((table_x + 34, table_y + row_h + 10), f"D (um): {', '.join(_format_number(d) for d in d_list)}", fill="#111827", font=text_font)
    draw.text((table_x + 34, table_y + row_h * 2 + 10), f"I (mA): {', '.join(f'{i:g}' for i in currents)}", fill="#111827", font=text_font)

    image.save(path, format="PNG", optimize=True)
    return str(path)


def generate_16x9_png(data, output_dir=None):
    try:
        return generate_16x9_png_pillow(data, output_dir)
    except Exception as ex:
        if is_android_runtime():
            raise RuntimeError(f"高清图片导出组件 Pillow 不可用，无法生成顺滑字体图片: {ex}")
        return generate_16x9_png_basic(data, output_dir)


def main(page):
    page.title = "Cui TLM App"
    page.scroll = "adaptive"
    page.theme_mode = "light"
    page.padding = 16
    page.bgcolor = "#f4f7fb"

    def show_message(text, color="#1f77b4"):
        try:
            page.open(ft.SnackBar(ft.Text(text), bgcolor=color))
        except Exception:
            page.snack_bar = ft.SnackBar(ft.Text(text), bgcolor=color)
            page.snack_bar.open = True
            page.update()

    def storage_get_json(key, default):
        try:
            value = page.client_storage.get(key)
            if not value:
                return default
            return json.loads(value)
        except Exception:
            return default

    def storage_set_json(key, value):
        try:
            page.client_storage.set(key, json.dumps(value, ensure_ascii=False))
            return True
        except Exception:
            return False

    def get_presets():
        raw = storage_get_json(PRESETS_KEY, None)
        if not raw:
            presets = [default_preset()]
            storage_set_json(PRESETS_KEY, presets)
            return presets
        presets = []
        for item in raw:
            try:
                presets.append(normalize_preset(item))
            except Exception:
                pass
        if not presets:
            presets = [default_preset()]
        return presets

    def save_presets(presets):
        storage_set_json(PRESETS_KEY, presets)

    def get_active_preset_id(presets):
        try:
            active_id = page.client_storage.get(ACTIVE_PRESET_KEY)
        except Exception:
            active_id = None
        preset_ids = {p["id"] for p in presets}
        if active_id in preset_ids:
            return active_id
        return presets[0]["id"]

    def set_active_preset_id(preset_id):
        try:
            page.client_storage.set(ACTIVE_PRESET_KEY, preset_id)
            return True
        except Exception:
            return False

    def get_history():
        history = storage_get_json(HISTORY_KEY, [])
        return history if isinstance(history, list) else []

    def save_to_history(data):
        history = get_history()
        record = {
            "id": int(time.time() * 1000),
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "name": data["name"],
            "preset_id": data["preset_id"],
            "preset_name": data["preset_name"],
            "preset_snapshot": data["preset_snapshot"],
            "w": data["w"],
            "v": data["v"],
            "inputs": data["inputs"],
            "results": {
                "r2": data["r2"],
                "Rsh": data["Rsh"],
                "Rc_norm": data["Rc_norm"],
                "LT": data["LT"],
                "rho_c": data["rho_c"],
            },
        }
        history.insert(0, record)
        history = history[:HISTORY_LIMIT]
        storage_set_json(HISTORY_KEY, history)
        return True

    presets_state = {"items": get_presets()}
    active_preset_id = get_active_preset_id(presets_state["items"])
    app_state = {
        "active_preset": next(p for p in presets_state["items"] if p["id"] == active_preset_id),
        "last_export_path": None,
    }

    set_active_preset_id(app_state["active_preset"]["id"])

    def option(key, text):
        dropdown_mod = getattr(ft, "dropdown", None)
        option_cls = getattr(dropdown_mod, "Option", None)
        if option_cls:
            try:
                return option_cls(key=key, text=text)
            except Exception:
                return option_cls(key)
        for attr in ("DropdownOption", "Option"):
            option_cls = getattr(ft, attr, None)
            if option_cls:
                try:
                    return option_cls(key=key, text=text)
                except Exception:
                    return option_cls(key)
        raise RuntimeError("当前 Flet 版本不支持 Dropdown option")

    preset_dropdown = ft.Dropdown(label="预设", bgcolor="white", expand=True)
    name_input = ft.TextField(label="保存名称", hint_text="例如 Sample A", bgcolor="white")
    summary_text = ft.Text(size=13, color="#52616f")
    input_refs = []
    input_col = ft.Column(spacing=8)
    result_text = ft.Text("选择预设并输入电流后点击计算", size=15, color="#6b7280")

    chart = ft.LineChart(
        data_series=[],
        left_axis=ft.ChartAxis(title=ft.Text("总电阻 (Ω)"), labels_size=32),
        bottom_axis=ft.ChartAxis(title=ft.Text("间距 d (um)"), labels_size=24),
        min_y=0,
        expand=True,
        height=320,
    )

    pending_save_as = {"path": None}
    save_file_picker_state = {"control": None}

    def on_save_file_result(e):
        target = getattr(e, "path", None)
        if not target:
            pending_save_as["path"] = None
            return
        try:
            source = pending_save_as.get("path")
            if source:
                target = normalize_android_save_path(target)
                if not target:
                    raise RuntimeError("Android 文件选择器返回的是文档 URI，无法直接写入。请使用保存到相册按钮。")
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                show_message(f"已导出: {target}", "green")
        except Exception as ex:
            show_message(f"导出失败: {ex}", "red")
        finally:
            pending_save_as["path"] = None

    def get_save_file_picker():
        if save_file_picker_state["control"] is None:
            picker = ft.FilePicker()
            picker.on_result = on_save_file_result
            save_file_picker_state["control"] = picker
            try:
                page.overlay.append(picker)
                page.update()
            except Exception:
                pass
        return save_file_picker_state["control"]

    export_state = {"capture": None, "dialog": None}

    def get_export_capture_dialog():
        if not hasattr(ft, "Screenshot"):
            return None, None
        if export_state["capture"] is None:
            capture = ft.Screenshot()
            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("正在生成导出图"),
                content=ft.Container(
                    content=capture,
                    width=960,
                    height=540,
                ),
            )
            export_state["capture"] = capture
            export_state["dialog"] = dialog
        return export_state["capture"], export_state["dialog"]

    share_service = None
    if hasattr(ft, "Share"):
        try:
            share_service = ft.Share()
        except Exception:
            share_service = None

    def refresh_preset_dropdown():
        preset_dropdown.options = [option(p["id"], p["name"]) for p in presets_state["items"]]
        preset_dropdown.value = app_state["active_preset"]["id"]

    def update_summary():
        preset = app_state["active_preset"]
        summary_text.value = (
            f"W={preset['width']:g} μm    V={preset['voltage']:g} V    "
            f"TLM 数量={preset['tlm_count']}    间距={spacings_to_text(preset['spacings'])} μm"
        )

    def apply_preset(preset, clear_inputs=True):
        app_state["active_preset"] = normalize_preset(preset)
        set_active_preset_id(app_state["active_preset"]["id"])
        refresh_preset_dropdown()
        update_summary()
        rebuild_current_inputs(clear_inputs=clear_inputs)

    def rebuild_current_inputs(clear_inputs=True):
        existing_values = {}
        if not clear_inputs:
            for spacing, field in input_refs:
                existing_values[float(spacing)] = field.value

        input_refs.clear()
        input_col.controls.clear()

        for spacing in app_state["active_preset"]["spacings"]:
            field = ft.TextField(
                label=f"d = {_format_number(spacing)} μm",
                suffix_text="mA",
                keyboard_type="number",
                bgcolor="white",
                height=52,
            )
            if not clear_inputs and float(spacing) in existing_values:
                field.value = existing_values[float(spacing)]
            input_refs.append((float(spacing), field))
            input_col.controls.append(field)

    def get_current_input_pairs():
        d_list = []
        currents = []
        inputs_data = []
        for spacing, field in input_refs:
            text = (field.value or "").strip()
            if not text:
                continue
            current = float(text)
            d_list.append(float(spacing))
            currents.append(current)
            inputs_data.append([float(spacing), current])
        return d_list, currents, inputs_data

    def perform_calculation(update_ui=True):
        try:
            preset = app_state["active_preset"]
            w_val = float(preset["width"])
            v_val = float(preset["voltage"])
            d_list, currents, inputs_data = get_current_input_pairs()
            r_list = []

            for current in currents:
                r_calc = abs(v_val / (current / 1000.0))
                r_list.append(r_calc)

            if len(d_list) < 2:
                if update_ui:
                    result_text.value = "错误: 至少需要 2 个电流数据点"
                    result_text.color = "red"
                    page.update()
                return None

            slope, intercept, r2 = simple_linear_fit(d_list, r_list)

            Rc_ohms = intercept / 2
            Rc_norm = Rc_ohms * (w_val / 1000.0)
            Rsh = slope * w_val
            LT = Rc_ohms * w_val / Rsh if Rsh != 0 else 0
            rho_c = Rc_ohms * LT * w_val * 1e-8

            if update_ui:
                d_min = min(d_list)
                d_max = max(d_list)
                if d_min == d_max:
                    d_min -= 1
                    d_max += 1

                y_min = min(r_list)
                y_max = max(r_list)
                if y_min == y_max:
                    y_min = max(0, y_min - 1)
                    y_max = y_max + 1

                chart.min_y = y_min * 0.8 if y_min > 0 else y_min * 1.2
                chart.max_y = y_max * 1.1 if y_max > 0 else y_max * 0.8
                chart.data_series = [
                    ft.LineChartData(
                        data_points=[
                            ft.LineChartDataPoint(x=d, y=r)
                            for d, r in zip(d_list, r_list)
                        ],
                        color="red",
                        stroke_width=0,
                        point=True,
                    ),
                    ft.LineChartData(
                        data_points=[
                            ft.LineChartDataPoint(x=d_min, y=slope * d_min + intercept),
                            ft.LineChartDataPoint(x=d_max, y=slope * d_max + intercept),
                        ],
                        color="blue",
                        stroke_width=3,
                    ),
                ]

                result_text.value = (
                    f"拟合优度 R²: {r2:.5f}\n"
                    f"方块电阻 Rsh: {Rsh:.2f} Ω/□\n"
                    f"接触电阻 Rc: {Rc_norm:.4f} Ω·mm\n"
                    f"传输长度 LT: {LT:.4f} μm\n"
                    f"比接触电阻率 ρc: {rho_c:.2e} Ω·cm²"
                )
                result_text.color = "blue"
                page.update()

            record_name = (name_input.value or "").strip() or time.strftime("TLM_%Y%m%d_%H%M%S")
            return {
                "name": record_name,
                "preset_id": preset["id"],
                "preset_name": preset["name"],
                "preset_snapshot": preset.copy(),
                "w": w_val,
                "v": v_val,
                "inputs": inputs_data,
                "d_list": d_list,
                "currents": currents,
                "r_list": r_list,
                "slope": slope,
                "intercept": intercept,
                "r2": r2,
                "Rc_ohms": Rc_ohms,
                "Rc_norm": Rc_norm,
                "Rsh": Rsh,
                "LT": LT,
                "rho_c": rho_c,
            }
        except ZeroDivisionError:
            if update_ui:
                result_text.value = "计算错误: 电流不能为 0"
                result_text.color = "red"
                page.update()
            return None
        except Exception as ex:
            if update_ui:
                result_text.value = f"计算错误: {ex}"
                result_text.color = "red"
                page.update()
            return None

    def on_preset_change(e):
        preset_id = preset_dropdown.value
        preset = next((p for p in presets_state["items"] if p["id"] == preset_id), None)
        if preset:
            apply_preset(preset, clear_inputs=True)
            page.update()

    preset_dropdown.on_change = on_preset_change

    def on_calc_click(e):
        perform_calculation(update_ui=True)

    def on_save_click(e):
        if not (name_input.value or "").strip():
            show_message("请先输入保存名称", "red")
            return
        data = perform_calculation(update_ui=True)
        if data and save_to_history(data):
            show_message(f"已保存记录: {data['name']}", "green")

    def export_table_row(left, right, header=False):
        bg = "#eef3f8" if header else "white"
        weight = "bold" if header else None
        return ft.Row(
            controls=[
                ft.Container(
                    content=ft.Text(left, size=14 if header else 13, weight=weight),
                    width=420,
                    height=24,
                    bgcolor=bg,
                    alignment=ft.alignment.center,
                    border=ft.border.all(1, "#334155"),
                ),
                ft.Container(
                    content=ft.Text(right, size=14 if header else 13, weight=weight),
                    width=420,
                    height=24,
                    bgcolor=bg,
                    alignment=ft.alignment.center,
                    border=ft.border.all(1, "#334155"),
                ),
            ],
            spacing=0,
        )

    def build_flet_export_image(data):
        d_list = data["d_list"]
        r_list = data["r_list"]
        slope = data["slope"]
        intercept = data["intercept"]
        x_min = min(d_list)
        x_max = max(d_list)
        x_pad = max((x_max - x_min) * 0.08, 0.5)
        line_x = [x_min - x_pad, x_max + x_pad]
        line_y = [slope * x + intercept for x in line_x]

        y_values = r_list + line_y
        y_min = min(y_values)
        y_max = max(y_values)
        y_pad = max((y_max - y_min) * 0.12, 1)
        chart_min_y = y_min - y_pad
        chart_max_y = y_max + y_pad

        export_chart = ft.LineChart(
            data_series=[
                ft.LineChartData(
                    data_points=[
                        ft.LineChartDataPoint(x=d, y=r)
                        for d, r in zip(d_list, r_list)
                    ],
                    color="red",
                    stroke_width=0,
                    point=True,
                ),
                ft.LineChartData(
                    data_points=[
                        ft.LineChartDataPoint(x=line_x[0], y=line_y[0]),
                        ft.LineChartDataPoint(x=line_x[1], y=line_y[1]),
                    ],
                    color="blue",
                    stroke_width=3,
                ),
            ],
            left_axis=ft.ChartAxis(title=ft.Text("总电阻 R (Ω)"), labels_size=36),
            bottom_axis=ft.ChartAxis(title=ft.Text("间距 d (μm)"), labels_size=24),
            min_y=chart_min_y,
            max_y=chart_max_y,
            min_x=line_x[0],
            max_x=line_x[1],
            width=320,
            height=320,
        )

        table_rows = [export_table_row("间距 d (μm)", "电流 I (mA)", header=True)]
        table_rows.extend(
            export_table_row(_format_number(d), f"{current:g}")
            for d, current in zip(data["d_list"], data["currents"])
        )

        export_time = time.strftime("%Y-%m-%d %H:%M:%S")
        return ft.Container(
            width=960,
            height=540,
            bgcolor="#f7f9fc",
            padding=ft.padding.only(left=48, right=48, top=20, bottom=18),
            content=ft.Column(
                controls=[
                    ft.Text(data.get("name") or "TLM Analysis", size=25, weight="bold", color="#111827"),
                    ft.Text(
                        f"预设: {data.get('preset_name', '-')}    "
                        f"W={data['w']:.4g} μm    V={data['v']:.4g} V    "
                        f"导出时间: {export_time}",
                        size=13,
                        color="#425466",
                    ),
                    ft.Container(height=14),
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=export_chart,
                                width=320,
                                height=320,
                                bgcolor="white",
                                border=ft.border.all(1, "#cbd5e1"),
                            ),
                            ft.Container(width=86),
                            ft.Container(
                                content=ft.Column(
                                    controls=[
                                        ft.Text("结果", size=22, weight="bold"),
                                        ft.Text("Rc", size=13, color="#5b677a"),
                                        ft.Text(f"{data['Rc_norm']:.4f} Ω·mm", size=20, weight="bold", color="#111827"),
                                        ft.Text("Rsh", size=13, color="#5b677a"),
                                        ft.Text(f"{data['Rsh']:.2f} Ω/□", size=20, weight="bold", color="#111827"),
                                        ft.Text("R²", size=13, color="#5b677a"),
                                        ft.Text(f"{data['r2']:.5f}", size=20, weight="bold", color="#111827"),
                                    ],
                                    spacing=8,
                                ),
                                width=300,
                                height=300,
                                padding=ft.padding.only(top=40),
                            ),
                        ],
                        spacing=0,
                    ),
                    ft.Container(height=14),
                    ft.Column(controls=table_rows, spacing=0),
                ],
                spacing=0,
            ),
        )

    async def generate_16x9_png_with_flet(data):
        export_capture, export_preview_dialog = get_export_capture_dialog()
        if not export_capture:
            raise RuntimeError("当前 Flet 版本不支持 Screenshot")

        output_dir = default_export_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"{safe_filename(data.get('name'))}_{stamp}_16x9.png"

        export_capture.content = build_flet_export_image(data)
        try:
            page.open(export_preview_dialog)
            page.update()
            await asyncio.sleep(0.25)
            capture_result = export_capture.capture(pixel_ratio=2)
            if hasattr(capture_result, "__await__"):
                capture_result = await capture_result
            if isinstance(capture_result, str):
                if "," in capture_result:
                    capture_result = capture_result.split(",", 1)[1]
                image_bytes = base64.b64decode(capture_result)
            else:
                image_bytes = bytes(capture_result)
            path.write_bytes(image_bytes)
            return str(path)
        finally:
            try:
                page.close(export_preview_dialog)
            except Exception:
                pass

    async def export_current_png():
        data = perform_calculation(update_ui=True)
        if not data:
            return None
        try:
            path = await generate_16x9_png_with_flet(data)
            app_state["last_export_path"] = path
            return path
        except Exception:
            pass
        try:
            path = generate_16x9_png(data, default_export_dir())
            app_state["last_export_path"] = path
            return path
        except Exception as ex:
            show_message(f"生成图片失败: {ex}", "red")
            return None

    async def on_save_album_click(e):
        path = await export_current_png()
        if path:
            show_message(f"已生成 16:9 图片: {path}", "green")

    async def on_save_as_click(e):
        path = await export_current_png()
        if not path:
            return
        if os.name != "nt":
            show_message(f"已保存到 1aTLM: {path}", "green")
            return
        file_name = Path(path).name
        pending_save_as["path"] = path
        save_file_picker = get_save_file_picker()
        try:
            with open(path, "rb") as f:
                src_bytes = f.read()
            result = save_file_picker.save_file(
                dialog_title="导出 TLM 图片",
                file_name=file_name,
                allowed_extensions=["png"],
                src_bytes=src_bytes,
            )
            if hasattr(result, "__await__"):
                saved_path = await result
                if saved_path:
                    show_message(f"已导出: {saved_path}", "green")
                    pending_save_as["path"] = None
        except TypeError:
            try:
                save_file_picker.save_file(
                    dialog_title="导出 TLM 图片",
                    file_name=file_name,
                    allowed_extensions=["png"],
                )
            except Exception as ex:
                show_message(f"导出失败: {ex}", "red")
                pending_save_as["path"] = None
        except Exception as ex:
            show_message(f"导出失败: {ex}", "red")
            pending_save_as["path"] = None

    async def on_share_click(e):
        path = await export_current_png()
        if not path:
            return
        show_message(f"当前 Flet 版本没有系统分享接口。图片已保存，请从文件管理或相册分享: {path}", "#f59e0b")

    # --- 设置界面 ---
    settings_selected_id = {"value": app_state["active_preset"]["id"]}
    settings_preset_dropdown = ft.Dropdown(label="编辑预设", bgcolor="white", expand=True)
    preset_name_input = ft.TextField(label="预设名称", bgcolor="white")
    width_input = ft.TextField(label="通道宽度 W", suffix_text="μm", keyboard_type="number", bgcolor="white", col={"xs": 12, "sm": 6})
    voltage_input = ft.TextField(label="测试电压 V", suffix_text="V", keyboard_type="number", bgcolor="white", col={"xs": 12, "sm": 6})
    tlm_count_input = ft.TextField(label="TLM 数量", keyboard_type="number", bgcolor="white")
    spacing_values_input = ft.TextField(label="间距列表", suffix_text="μm", bgcolor="white")
    spacing_preview = ft.Text(size=12, color="#52616f")

    def dialog_width(default_width):
        page_width = page.width or default_width + 80
        return max(280, min(default_width, page_width - 48))

    def dialog_height(default_height):
        page_height = page.height or default_height + 180
        return max(340, min(default_height, page_height - 140))

    def fill_settings_fields(preset):
        settings_selected_id["value"] = preset["id"]
        settings_preset_dropdown.value = preset["id"]
        preset_name_input.value = preset["name"]
        width_input.value = _format_number(preset["width"])
        voltage_input.value = _format_number(preset["voltage"])
        tlm_count_input.value = str(preset["tlm_count"])
        spacing_values_input.value = spacings_to_text(preset["spacings"])
        update_spacing_preview()

    def refresh_settings_dropdown():
        settings_preset_dropdown.options = [option(p["id"], p["name"]) for p in presets_state["items"]]

    def update_spacing_preview(e=None):
        try:
            spacings = build_spacings(spacing_values_input.value, tlm_count_input.value)
            spacing_preview.value = f"当前间距: {spacings_to_text(spacings)} μm"
            spacing_preview.color = "#52616f"
        except Exception as ex:
            spacing_preview.value = f"间距设置错误: {ex}"
            spacing_preview.color = "red"
        try:
            page.update()
        except Exception:
            pass

    tlm_count_input.on_change = update_spacing_preview
    spacing_values_input.on_change = update_spacing_preview

    def on_settings_dropdown_change(e):
        preset = next((p for p in presets_state["items"] if p["id"] == settings_preset_dropdown.value), None)
        if preset:
            fill_settings_fields(preset)
            page.update()

    settings_preset_dropdown.on_change = on_settings_dropdown_change

    def preset_from_settings(existing_id=None):
        name = (preset_name_input.value or "").strip()
        if not name:
            raise ValueError("预设名称不能为空")
        spacings = build_spacings(spacing_values_input.value, tlm_count_input.value)
        width = float(width_input.value)
        if width <= 0:
            raise ValueError("通道宽度 W 必须大于 0")
        return {
            "id": existing_id or _new_id("preset"),
            "name": name,
            "width": width,
            "voltage": float(voltage_input.value),
            "tlm_count": len(spacings),
            "spacings": spacings,
        }

    def save_settings_preset(e):
        try:
            preset_id = settings_selected_id["value"]
            is_existing = any(p["id"] == preset_id for p in presets_state["items"])
            preset = preset_from_settings(preset_id if is_existing else None)
            if is_existing:
                presets_state["items"] = [
                    preset if p["id"] == preset_id else p
                    for p in presets_state["items"]
                ]
            else:
                presets_state["items"].append(preset)
            save_presets(presets_state["items"])
            apply_preset(preset, clear_inputs=True)
            refresh_settings_dropdown()
            fill_settings_fields(preset)
            show_message(f"已保存预设: {preset['name']}", "green")
        except Exception as ex:
            show_message(f"保存预设失败: {ex}", "red")

    def new_settings_preset(e):
        settings_selected_id["value"] = None
        settings_preset_dropdown.value = None
        preset_name_input.value = "新预设"
        width_input.value = "100"
        voltage_input.value = "5"
        tlm_count_input.value = "7"
        spacing_values_input.value = "2,3,5,7,9,11,17"
        update_spacing_preview()
        page.update()

    def delete_settings_preset(e):
        preset_id = settings_selected_id["value"]
        if len(presets_state["items"]) <= 1:
            show_message("至少保留一个预设", "red")
            return
        presets_state["items"] = [p for p in presets_state["items"] if p["id"] != preset_id]
        save_presets(presets_state["items"])
        apply_preset(presets_state["items"][0], clear_inputs=True)
        refresh_settings_dropdown()
        fill_settings_fields(app_state["active_preset"])
        show_message("已删除预设", "green")

    def use_settings_preset(e):
        preset_id = settings_selected_id["value"]
        preset = next((p for p in presets_state["items"] if p["id"] == preset_id), None)
        if preset:
            apply_preset(preset, clear_inputs=True)
            page.close(settings_dialog)
            page.update()

    settings_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("设置"),
        content=ft.Container(
            width=dialog_width(620),
            height=dialog_height(520),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            settings_preset_dropdown,
                            ft.IconButton("add", tooltip="新建预设", on_click=new_settings_preset),
                            ft.IconButton("delete", tooltip="删除预设", icon_color="red", on_click=delete_settings_preset),
                        ]
                    ),
                    preset_name_input,
                    ft.ResponsiveRow([width_input, voltage_input], columns=12, spacing=8, run_spacing=8),
                    tlm_count_input,
                    spacing_values_input,
                    spacing_preview,
                ],
                spacing=10,
                scroll="auto",
            ),
        ),
        actions=[
            ft.TextButton("取消", on_click=lambda e: page.close(settings_dialog)),
            ft.ElevatedButton("使用", icon="check", on_click=use_settings_preset),
            ft.ElevatedButton("保存", icon="save", bgcolor="blue", color="white", on_click=save_settings_preset),
        ],
    )

    def open_settings_dialog(e):
        refresh_settings_dropdown()
        fill_settings_fields(app_state["active_preset"])
        settings_dialog.content.width = dialog_width(620)
        settings_dialog.content.height = dialog_height(520)
        page.open(settings_dialog)

    # --- 历史记录界面 ---
    history_list_view = ft.Column(scroll="auto", spacing=6)

    def delete_history_item(item_id):
        history = [r for r in get_history() if r.get("id") != item_id]
        storage_set_json(HISTORY_KEY, history)
        open_history_dialog(None)

    def restore_record(record):
        snapshot = record.get("preset_snapshot") or default_preset()
        snapshot = normalize_preset(snapshot)
        existing = next((p for p in presets_state["items"] if p["id"] == snapshot["id"]), None)
        existing_matches_snapshot = False
        if existing:
            existing_matches_snapshot = (
                existing["tlm_count"] == snapshot["tlm_count"]
                and [float(x) for x in existing["spacings"]] == [float(x) for x in snapshot["spacings"]]
                and float(existing["width"]) == float(snapshot["width"])
                and float(existing["voltage"]) == float(snapshot["voltage"])
            )

        if not existing_matches_snapshot:
            snapshot["id"] = _new_id("preset")
            snapshot["name"] = f"记录预设-{record.get('name', 'TLM')}"
            presets_state["items"].append(snapshot)
            save_presets(presets_state["items"])
        else:
            snapshot = existing

        apply_preset(snapshot, clear_inputs=True)
        saved_inputs = {float(d): current for d, current in record.get("inputs", [])}
        for spacing, field in input_refs:
            field.value = str(saved_inputs.get(float(spacing), ""))

        name_input.value = record.get("name", "")
        page.close(history_dialog)
        perform_calculation(update_ui=True)
        show_message(f"已加载记录: {name_input.value}", "green")

    history_dialog = ft.AlertDialog(
        title=ft.Text(f"历史记录 (最多 {HISTORY_LIMIT} 条)"),
        content=ft.Container(content=history_list_view, width=dialog_width(680), height=dialog_height(500)),
        actions=[ft.TextButton("关闭", on_click=lambda e: page.close(history_dialog))],
    )

    def open_history_dialog(e):
        history = get_history()
        history_list_view.controls.clear()
        if not history:
            history_list_view.controls.append(ft.Text("暂无记录", color="#6b7280"))
        else:
            for record in history:
                def on_restore(ev, rec=record):
                    restore_record(rec)

                def on_delete(ev, rid=record.get("id")):
                    delete_history_item(rid)

                results = record.get("results", {})
                sub = (
                    f"{record.get('time', '')}    {record.get('preset_name', '')}    "
                    f"R²={results.get('r2', 0):.5f}"
                )
                history_list_view.controls.append(
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(record.get("name", "未命名"), weight="bold"),
                                        ft.Text(sub, size=12, color="#6b7280"),
                                    ],
                                    expand=True,
                                    spacing=2,
                                ),
                                ft.IconButton("restore", tooltip="加载", icon_color="blue", on_click=on_restore),
                                ft.IconButton("delete", tooltip="删除", icon_color="red", on_click=on_delete),
                            ]
                        ),
                        padding=10,
                        bgcolor="white",
                        border_radius=6,
                        border=ft.border.all(1, "#d9e2ec"),
                        on_click=on_restore,
                    )
                )
        history_dialog.content.width = dialog_width(680)
        history_dialog.content.height = dialog_height(500)
        page.open(history_dialog)

    # --- 首页 / 页面切换 ---
    def set_page_controls(*controls):
        page.controls.clear()
        page.add(*controls)

    def render_home_page(e=None):
        page.scroll = "adaptive"
        set_page_controls(
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(name="home", color="white"),
                        ft.Text("实验室工具", size=24, weight="bold", color="white"),
                    ]
                ),
                bgcolor="#1565c0",
                padding=16,
                border_radius=6,
            ),
            ft.Container(height=24),
            ft.Text("请选择要使用的功能", size=20, weight="bold", color="#111827"),
            ft.Text("TLM 计算和实验计时分开进入，数据记录与预设仍会保存在本地。", size=13, color="#52616f"),
            ft.Container(height=16),
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(name="science", color="#1565c0", size=42),
                        ft.Column(
                            controls=[
                                ft.Text("TLM 计算", size=22, weight="bold", color="#111827"),
                                ft.Text("选择预设，输入不同间距下的电流并导出 16:9 图片。", size=13, color="#52616f"),
                            ],
                            spacing=4,
                            expand=True,
                        ),
                        ft.Icon(name="chevron_right", color="#64748b"),
                    ]
                ),
                bgcolor="white",
                padding=18,
                border_radius=8,
                border=ft.border.all(1, "#d9e2ec"),
                on_click=render_tlm_page,
            ),
            ft.Container(height=12),
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(name="timer", color="#047857", size=42),
                        ft.Column(
                            controls=[
                                ft.Text("计时器", size=22, weight="bold", color="#111827"),
                                ft.Text("秒级倒计时、3/5/10/14 分钟倒计时、自定义备注和正计时。", size=13, color="#52616f"),
                            ],
                            spacing=4,
                            expand=True,
                        ),
                        ft.Icon(name="chevron_right", color="#64748b"),
                    ]
                ),
                bgcolor="white",
                padding=18,
                border_radius=8,
                border=ft.border.all(1, "#d9e2ec"),
                on_click=render_timer_page,
            ),
            ft.Container(height=28),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("@CuiMiller", size=16, color="#6b7280"),
                        ft.Text("2026 V2.1", size=12, color="#8a94a6"),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                ),
                alignment=ft.alignment.bottom_right,
            ),
        )

    def header_bar(title, icon_name, color, actions):
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        "arrow_back",
                        tooltip="返回首页",
                        icon_color="white",
                        icon_size=24,
                        width=40,
                        height=40,
                        on_click=render_home_page,
                    ),
                    ft.Icon(name=icon_name, color="white", size=28),
                    ft.Text(title, size=22, weight="bold", color="white", expand=True, no_wrap=True),
                    *actions,
                ],
                spacing=2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=color,
            padding=ft.padding.only(left=8, right=8, top=10, bottom=10),
            border_radius=6,
        )

    def header_button(icon_name, tooltip, handler):
        return ft.IconButton(
            icon_name,
            tooltip=tooltip,
            icon_color="white",
            icon_size=24,
            width=40,
            height=40,
            on_click=handler,
        )

    # --- 计时器页 ---
    timer_state = {
        "countdown_stop": None,
        "countdown_token": 0,
        "countdown_running": False,
        "countdown_end_epoch": None,
        "countdown_total": 0,
        "countdown_note": "",
        "stopwatch_stop": None,
        "stopwatch_token": 0,
        "stopwatch_elapsed": 0,
        "stopwatch_running": False,
        "stopwatch_start_epoch": None,
        "stopwatch_note": "",
    }

    def format_minutes_seconds(total_seconds):
        seconds = max(0, int(total_seconds))
        return f"{seconds // 60} 分 {seconds % 60:02d} 秒"

    def format_stopwatch(total_seconds):
        seconds = max(0, int(total_seconds))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remain = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{remain:02d}"

    second_countdown_input = ft.TextField(
        label="秒级倒计时",
        hint_text="例如 300",
        suffix_text="秒",
        keyboard_type="number",
        bgcolor="white",
        expand=True,
    )
    countdown_note_input = ft.TextField(
        label="备注",
        hint_text=" RTP / 后烘 / HMDS",
        bgcolor="white",
        expand=True,
    )
    custom_minutes_input = ft.TextField(
        label="自定义倒计时",
        hint_text="例如 2.5",
        suffix_text="分钟",
        keyboard_type="number",
        bgcolor="white",
        expand=True,
    )
    countdown_seconds_text = ft.Text("剩余 0 秒", size=36, weight="bold", color="#1565c0")
    countdown_mmss_text = ft.Text("0 分 00 秒", size=20, color="#111827")
    countdown_note_text = ft.Text("备注: -", size=13, color="#52616f")
    countdown_status_text = ft.Text("倒计时未开始", size=13, color="#64748b")

    stopwatch_note_input = ft.TextField(
        label="正计时备注",
        hint_text="例如 显影 / 前烘",
        bgcolor="white",
    )
    stopwatch_display = ft.Text("00:00:00", size=38, weight="bold", color="#047857")
    stopwatch_seconds_text = ft.Text("已计时 0 秒（0 分 00 秒）", size=16, color="#111827")
    stopwatch_note_text = ft.Text("备注: -", size=13, color="#52616f")
    stopwatch_status_text = ft.Text("正计时未开始", size=13, color="#64748b")

    def save_timer_state():
        storage_set_json(
            TIMER_STATE_KEY,
            {
                "countdown_running": timer_state["countdown_running"],
                "countdown_end_epoch": timer_state["countdown_end_epoch"],
                "countdown_total": timer_state["countdown_total"],
                "countdown_note": timer_state["countdown_note"],
                "stopwatch_running": timer_state["stopwatch_running"],
                "stopwatch_start_epoch": timer_state["stopwatch_start_epoch"],
                "stopwatch_elapsed": timer_state["stopwatch_elapsed"],
                "stopwatch_note": timer_state["stopwatch_note"],
            },
        )

    def update_countdown_display(remaining, note=None, status=None):
        remaining = max(0, int(remaining))
        countdown_seconds_text.value = f"剩余 {remaining} 秒"
        countdown_mmss_text.value = format_minutes_seconds(remaining)
        if note is not None:
            countdown_note_text.value = f"备注: {note}" if note else "备注: -"
        if status is not None:
            countdown_status_text.value = status
        try:
            page.update()
        except Exception:
            pass

    def stop_countdown(update_status=True):
        stop_event = timer_state.get("countdown_stop")
        if stop_event:
            stop_event.set()
        timer_state["countdown_running"] = False
        timer_state["countdown_end_epoch"] = None
        timer_state["countdown_total"] = 0
        save_timer_state()
        if update_status:
            countdown_status_text.value = "倒计时已停止"
            try:
                page.update()
            except Exception:
                pass

    def refresh_countdown_from_clock(update_page=True):
        if not timer_state["countdown_running"]:
            return
        end_epoch = timer_state.get("countdown_end_epoch")
        if not end_epoch:
            return
        remaining = max(0, int(round(end_epoch - time.time())))
        note = timer_state.get("countdown_note", "")
        if remaining <= 0:
            timer_state["countdown_running"] = False
            timer_state["countdown_end_epoch"] = None
            update_countdown_display(0, note, "倒计时完成")
            save_timer_state()
        else:
            update_countdown_display(remaining, note, "倒计时进行中")
        if update_page:
            try:
                page.update()
            except Exception:
                pass

    def start_countdown(total_seconds, note=""):
        try:
            seconds = int(round(float(total_seconds)))
        except Exception:
            show_message("请输入有效的倒计时时长", "red")
            return
        if seconds <= 0:
            show_message("倒计时时长必须大于 0", "red")
            return

        stop_countdown(update_status=False)
        timer_state["countdown_token"] += 1
        token = timer_state["countdown_token"]
        stop_event = threading.Event()
        timer_state["countdown_stop"] = stop_event
        timer_state["countdown_running"] = True
        timer_state["countdown_end_epoch"] = time.time() + seconds
        timer_state["countdown_total"] = seconds
        timer_state["countdown_note"] = note
        save_timer_state()
        update_countdown_display(seconds, note, "倒计时进行中")

        def worker():
            while not stop_event.is_set() and token == timer_state["countdown_token"]:
                time.sleep(1)
                if stop_event.is_set() or token != timer_state["countdown_token"]:
                    break
                refresh_countdown_from_clock(update_page=False)
                if not timer_state["countdown_running"]:
                    break

            if not stop_event.is_set() and token == timer_state["countdown_token"]:
                refresh_countdown_from_clock(update_page=False)

        threading.Thread(target=worker, daemon=True).start()

    def start_seconds_countdown(e):
        start_countdown(second_countdown_input.value, countdown_note_input.value.strip())

    def start_minutes_countdown(minutes, note=None):
        remark = countdown_note_input.value.strip() if note is None else note
        start_countdown(float(minutes) * 60, remark)

    def start_custom_minutes_countdown(e):
        try:
            minutes = float(custom_minutes_input.value)
        except Exception:
            show_message("请输入有效的自定义分钟数", "red")
            return
        start_minutes_countdown(minutes)

    def reset_countdown(e):
        stop_countdown(update_status=False)
        timer_state["countdown_token"] += 1
        timer_state["countdown_note"] = ""
        save_timer_state()
        update_countdown_display(0, "", "倒计时未开始")

    def update_stopwatch_display(elapsed, note=None, status=None):
        elapsed = max(0, int(elapsed))
        timer_state["stopwatch_elapsed"] = elapsed
        stopwatch_display.value = format_stopwatch(elapsed)
        stopwatch_seconds_text.value = f"已计时 {elapsed} 秒（{format_minutes_seconds(elapsed)}）"
        if note is not None:
            stopwatch_note_text.value = f"备注: {note}" if note else "备注: -"
        if status is not None:
            stopwatch_status_text.value = status
        try:
            page.update()
        except Exception:
            pass

    def start_stopwatch(e):
        if timer_state["stopwatch_running"]:
            return
        note = stopwatch_note_input.value.strip()
        timer_state["stopwatch_token"] += 1
        token = timer_state["stopwatch_token"]
        stop_event = threading.Event()
        timer_state["stopwatch_stop"] = stop_event
        timer_state["stopwatch_running"] = True
        timer_state["stopwatch_start_epoch"] = time.time() - timer_state["stopwatch_elapsed"]
        timer_state["stopwatch_note"] = note
        save_timer_state()
        update_stopwatch_display(timer_state["stopwatch_elapsed"], note, "正计时进行中")

        def worker():
            while not stop_event.is_set() and token == timer_state["stopwatch_token"]:
                refresh_stopwatch_from_clock(update_page=False)
                time.sleep(1)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_stopwatch_from_clock(update_page=True):
        if not timer_state["stopwatch_running"]:
            return
        start_epoch = timer_state.get("stopwatch_start_epoch")
        if not start_epoch:
            return
        elapsed = max(0, int(time.time() - start_epoch))
        update_stopwatch_display(elapsed, timer_state.get("stopwatch_note", ""), "正计时进行中")
        if update_page:
            try:
                page.update()
            except Exception:
                pass

    def pause_stopwatch(e):
        stop_event = timer_state.get("stopwatch_stop")
        if stop_event:
            stop_event.set()
        refresh_stopwatch_from_clock(update_page=False)
        timer_state["stopwatch_running"] = False
        timer_state["stopwatch_start_epoch"] = None
        save_timer_state()
        stopwatch_status_text.value = "正计时已暂停"
        try:
            page.update()
        except Exception:
            pass

    def reset_stopwatch(e):
        pause_stopwatch(None)
        timer_state["stopwatch_token"] += 1
        timer_state["stopwatch_note"] = ""
        timer_state["stopwatch_elapsed"] = 0
        save_timer_state()
        update_stopwatch_display(0, "", "正计时未开始")

    def refresh_timers_from_clock(e=None):
        refresh_countdown_from_clock(update_page=False)
        refresh_stopwatch_from_clock(update_page=False)
        try:
            page.update()
        except Exception:
            pass

    def restore_timer_state():
        saved = storage_get_json(TIMER_STATE_KEY, {})
        if not isinstance(saved, dict):
            return
        if saved.get("countdown_running") and saved.get("countdown_end_epoch"):
            timer_state["countdown_running"] = True
            timer_state["countdown_end_epoch"] = float(saved["countdown_end_epoch"])
            timer_state["countdown_total"] = int(saved.get("countdown_total") or 0)
            timer_state["countdown_note"] = str(saved.get("countdown_note") or "")
            refresh_countdown_from_clock(update_page=False)
            if timer_state["countdown_running"]:
                timer_state["countdown_token"] += 1
                token = timer_state["countdown_token"]
                stop_event = threading.Event()
                timer_state["countdown_stop"] = stop_event

                def countdown_worker():
                    while not stop_event.is_set() and token == timer_state["countdown_token"]:
                        time.sleep(1)
                        if stop_event.is_set() or token != timer_state["countdown_token"]:
                            break
                        refresh_countdown_from_clock(update_page=False)
                        if not timer_state["countdown_running"]:
                            break

                threading.Thread(target=countdown_worker, daemon=True).start()
        elif saved.get("countdown_note"):
            update_countdown_display(0, str(saved.get("countdown_note") or ""), "倒计时未开始")

        timer_state["stopwatch_elapsed"] = int(saved.get("stopwatch_elapsed") or 0)
        timer_state["stopwatch_note"] = str(saved.get("stopwatch_note") or "")
        if saved.get("stopwatch_running") and saved.get("stopwatch_start_epoch"):
            timer_state["stopwatch_running"] = True
            timer_state["stopwatch_start_epoch"] = float(saved["stopwatch_start_epoch"])
            refresh_stopwatch_from_clock(update_page=False)
            timer_state["stopwatch_token"] += 1
            token = timer_state["stopwatch_token"]
            stop_event = threading.Event()
            timer_state["stopwatch_stop"] = stop_event

            def stopwatch_worker():
                while not stop_event.is_set() and token == timer_state["stopwatch_token"]:
                    refresh_stopwatch_from_clock(update_page=False)
                    time.sleep(1)

            threading.Thread(target=stopwatch_worker, daemon=True).start()
        elif timer_state["stopwatch_elapsed"]:
            update_stopwatch_display(timer_state["stopwatch_elapsed"], timer_state["stopwatch_note"], "正计时已暂停")

    page.on_app_lifecycle_state_change = refresh_timers_from_clock

    def render_timer_page(e=None):
        refresh_timers_from_clock()
        page.scroll = "adaptive"
        set_page_controls(
            header_bar(
                "计时器",
                "timer",
                "#047857",
                [header_button("science", "TLM 计算", render_tlm_page)],
            ),
            ft.Container(height=10),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("秒级倒计时", weight="bold", size=18),
                        ft.ResponsiveRow(
                            controls=[
                                ft.Container(content=second_countdown_input, col={"xs": 12, "sm": 6}),
                                ft.Container(content=countdown_note_input, col={"xs": 12, "sm": 6}),
                            ],
                            columns=12,
                            spacing=8,
                            run_spacing=8,
                        ),
                        ft.ResponsiveRow(
                            controls=[
                                ft.ElevatedButton("开始秒级倒计时", icon="play_arrow", bgcolor="blue", color="white", col={"xs": 12, "sm": 4}, on_click=start_seconds_countdown),
                                ft.ElevatedButton("停止", icon="stop", col={"xs": 6, "sm": 4}, on_click=lambda e: stop_countdown()),
                                ft.ElevatedButton("重置", icon="restart_alt", col={"xs": 6, "sm": 4}, on_click=reset_countdown),
                            ],
                            columns=12,
                            spacing=8,
                            run_spacing=8,
                        ),
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    countdown_seconds_text,
                                    countdown_mmss_text,
                                    countdown_note_text,
                                    countdown_status_text,
                                ],
                                spacing=4,
                            ),
                            bgcolor="#eaf3ff",
                            padding=14,
                            border_radius=6,
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor="white",
                padding=14,
                border_radius=8,
                border=ft.border.all(1, "#d9e2ec"),
            ),
            ft.Container(height=10),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("分钟倒计时", weight="bold", size=18),
                        ft.ResponsiveRow(
                            controls=[
                                ft.ElevatedButton("3 分钟", icon="timer", col={"xs": 6, "sm": 6}, on_click=lambda e: start_minutes_countdown(3)),
                                ft.ElevatedButton("5 分钟", icon="timer", col={"xs": 6, "sm": 6}, on_click=lambda e: start_minutes_countdown(5)),
                            ],
                            columns=12,
                            spacing=8,
                            run_spacing=8,
                        ),
                        ft.ResponsiveRow(
                            controls=[
                                ft.ElevatedButton("10 分钟", icon="timer", col={"xs": 6, "sm": 6}, on_click=lambda e: start_minutes_countdown(10)),
                                ft.ElevatedButton("14 分钟", icon="timer", col={"xs": 6, "sm": 6}, on_click=lambda e: start_minutes_countdown(14)),
                            ],
                            columns=12,
                            spacing=8,
                            run_spacing=8,
                        ),
                        ft.ResponsiveRow(
                            controls=[
                                ft.Container(content=custom_minutes_input, col={"xs": 12, "sm": 7}),
                                ft.ElevatedButton("开始自定义", icon="play_arrow", bgcolor="#047857", color="white", col={"xs": 12, "sm": 5}, on_click=start_custom_minutes_countdown),
                            ],
                            columns=12,
                            spacing=8,
                            run_spacing=8,
                        ),
                        ft.Text("备注使用上方备注输入框，开始任意倒计时都会一并显示。", size=12, color="#64748b"),
                    ],
                    spacing=10,
                ),
                bgcolor="white",
                padding=14,
                border_radius=8,
                border=ft.border.all(1, "#d9e2ec"),
            ),
            ft.Container(height=10),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("正计时", weight="bold", size=18),
                        stopwatch_note_input,
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    stopwatch_display,
                                    stopwatch_seconds_text,
                                    stopwatch_note_text,
                                    stopwatch_status_text,
                                ],
                                spacing=4,
                            ),
                            bgcolor="#ecfdf5",
                            padding=14,
                            border_radius=6,
                        ),
                        ft.ResponsiveRow(
                            controls=[
                                ft.ElevatedButton("开始", icon="play_arrow", bgcolor="#047857", color="white", col={"xs": 4, "sm": 4}, on_click=start_stopwatch),
                                ft.ElevatedButton("暂停", icon="pause", col={"xs": 4, "sm": 4}, on_click=pause_stopwatch),
                                ft.ElevatedButton("重置", icon="restart_alt", col={"xs": 4, "sm": 4}, on_click=reset_stopwatch),
                            ],
                            columns=12,
                            spacing=8,
                            run_spacing=8,
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor="white",
                padding=14,
                border_radius=8,
                border=ft.border.all(1, "#d9e2ec"),
            ),
        )

    def render_tlm_page(e=None):
        page.scroll = "adaptive"
        set_page_controls(
            header_bar(
                "TLM 计算",
                "science",
                "#1565c0",
                [
                    header_button("timer", "计时器", render_timer_page),
                    header_button("settings", "设置", open_settings_dialog),
                    header_button("history", "历史", open_history_dialog),
                ],
            ),
            ft.Container(height=8),
            ft.Row(
                controls=[
                    preset_dropdown,
                    ft.IconButton("edit", tooltip="编辑预设", on_click=open_settings_dialog),
                ]
            ),
            summary_text,
            name_input,
            ft.Container(height=6),
            ft.Text("电流输入 (mA)", weight="bold"),
            input_col,
            ft.Container(height=6),
            ft.Row(
                controls=[
                    ft.ElevatedButton("计算", icon="play_arrow", bgcolor="blue", color="white", expand=True, on_click=on_calc_click),
                    ft.ElevatedButton("保存记录", icon="save", bgcolor="green", color="white", expand=True, on_click=on_save_click),
                ]
            ),
            ft.Row(
                controls=[
                    ft.ElevatedButton("保存到相册", icon="photo_library", expand=True, on_click=on_save_album_click),
                    ft.ElevatedButton("另存图片", icon="download", expand=True, on_click=on_save_as_click),
                    ft.ElevatedButton("分享", icon="share", expand=True, on_click=on_share_click),
                ]
            ),
            ft.Container(height=12),
            ft.Text("分析结果", weight="bold"),
            ft.Container(content=result_text, bgcolor="#eaf3ff", padding=12, border_radius=6),
            ft.Container(height=8),
            ft.Container(content=chart, bgcolor="white", padding=8, border=ft.border.all(1, "#d9e2ec")),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("@CuiMiller", size=16, color="#6b7280"),
                        ft.Text("2026 V2.1", size=12, color="#8a94a6"),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                ),
                alignment=ft.alignment.bottom_right,
                margin=ft.margin.only(top=24, bottom=20),
            ),
        )

    # --- 初始 UI 状态 ---
    refresh_preset_dropdown()
    update_summary()
    rebuild_current_inputs(clear_inputs=True)
    restore_timer_state()
    render_home_page()


def safe_main(page):
    try:
        main(page)
    except Exception as ex:
        try:
            page.title = "TLM APP 启动错误"
            page.scroll = "adaptive"
            page.padding = 16
            page.bgcolor = "#fff7ed"
            page.controls.clear()
            page.add(
                ft.Text("启动失败", size=26, weight="bold", color="red"),
                ft.Text(str(ex), selectable=True),
                ft.Text(traceback.format_exc(), selectable=True, size=12),
            )
            page.update()
        except Exception:
            raise


if __name__ == "__main__":
    ft.app(target=safe_main)
