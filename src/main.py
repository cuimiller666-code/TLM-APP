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


def border_all(width=1, color="#000000"):
    if hasattr(ft, "border") and hasattr(ft.border, "all"):
        return ft.border.all(width, color)
    return ft.Border.all(width=width, color=color)


def align_value(name):
    if hasattr(ft, "alignment") and hasattr(ft.alignment, name):
        return getattr(ft.alignment, name)
    return getattr(ft.Alignment, name.upper())


def padding_only(**kwargs):
    if hasattr(ft, "padding") and hasattr(ft.padding, "only"):
        return ft.padding.only(**kwargs)
    return ft.Padding.only(**kwargs)


def margin_only(**kwargs):
    if hasattr(ft, "margin") and hasattr(ft.margin, "only"):
        return ft.margin.only(**kwargs)
    return ft.Margin.only(**kwargs)


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


def _hex_to_rgb(color):
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _png_chunk(chunk_type, data):
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _encode_rgb_png(width, height, pixels):
    raw_rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(pixels[y][x])
        raw_rows.append(bytes(row))
    raw = b"".join(raw_rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 6))
        + _png_chunk(b"IEND", b"")
    )


def _make_canvas(width, height, color="#ffffff"):
    rgb = _hex_to_rgb(color)
    return [[rgb for _ in range(width)] for _ in range(height)]


def _set_pixel(pixels, x, y, color):
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    if 0 <= x < width and 0 <= y < height:
        pixels[y][x] = color


def _draw_rect(pixels, x1, y1, x2, y2, color):
    color = _hex_to_rgb(color) if isinstance(color, str) else color
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            _set_pixel(pixels, x, y, color)


def _draw_line(pixels, x1, y1, x2, y2, color, thickness=1):
    color = _hex_to_rgb(color) if isinstance(color, str) else color
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    dx = abs(x2 - x1)
    dy = -abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx + dy
    radius = max(0, int(thickness) // 2)

    while True:
        for yy in range(y1 - radius, y1 + radius + 1):
            for xx in range(x1 - radius, x1 + radius + 1):
                _set_pixel(pixels, xx, yy, color)
        if x1 == x2 and y1 == y2:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x1 += sx
        if e2 <= dx:
            err += dx
            y1 += sy


def _draw_circle(pixels, cx, cy, radius, color):
    color = _hex_to_rgb(color) if isinstance(color, str) else color
    cx, cy, radius = int(round(cx)), int(round(cy)), int(radius)
    r2 = radius * radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                _set_pixel(pixels, x, y, color)


def chart_png_base64(d_list=None, r_list=None, slope=0.0, intercept=0.0, width=640, height=420):
    d_list = [float(x) for x in (d_list or [])]
    r_list = [float(y) for y in (r_list or [])]
    pixels = _make_canvas(width, height, "#ffffff")
    _draw_rect(pixels, 0, 0, width - 1, height - 1, "#ffffff")

    left = max(34, int(width * 0.10))
    right = width - max(16, int(width * 0.04))
    top = max(16, int(height * 0.06))
    bottom = height - max(30, int(height * 0.10))

    _draw_rect(pixels, left, top, right, bottom, "#ffffff")
    for i in range(6):
        x = left + (right - left) * i / 5
        y = top + (bottom - top) * i / 5
        _draw_line(pixels, x, top, x, bottom, "#e2e8f0", 1)
        _draw_line(pixels, left, y, right, y, "#e2e8f0", 1)
    _draw_line(pixels, left, bottom, right, bottom, "#334155", 2)
    _draw_line(pixels, left, top, left, bottom, "#334155", 2)
    _draw_line(pixels, right, top, right, bottom, "#cbd5e1", 1)
    _draw_line(pixels, left, top, right, top, "#cbd5e1", 1)

    if len(d_list) >= 2 and len(r_list) >= 2:
        x_min = min(d_list)
        x_max = max(d_list)
        if x_min == x_max:
            x_min -= 1
            x_max += 1
        x_pad = max((x_max - x_min) * 0.08, 0.5)
        line_x = [x_min - x_pad, x_max + x_pad]
        line_y = [slope * x + intercept for x in line_x]
        y_values = r_list + line_y
        y_min = min(y_values)
        y_max = max(y_values)
        if y_min == y_max:
            y_min -= 1
            y_max += 1
        y_pad = max((y_max - y_min) * 0.12, 1)
        y_min -= y_pad
        y_max += y_pad
        x_min, x_max = line_x

        def map_x(value):
            return left + (float(value) - x_min) / (x_max - x_min) * (right - left)

        def map_y(value):
            return bottom - (float(value) - y_min) / (y_max - y_min) * (bottom - top)

        _draw_line(
            pixels,
            map_x(line_x[0]),
            map_y(line_y[0]),
            map_x(line_x[1]),
            map_y(line_y[1]),
            "#2563eb",
            3,
        )
        for d, r in zip(d_list, r_list):
            _draw_circle(pixels, map_x(d), map_y(r), max(4, int(width * 0.012)), "#dc2626")

    png = _encode_rgb_png(width, height, pixels)
    return base64.b64encode(png).decode("ascii")


def default_export_dir():
    candidates = []

    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidates.append(Path(userprofile) / "Pictures" / "TLM")

    if os.name != "nt":
        for android_path in ("/storage/emulated/0/Pictures/TLM", "/sdcard/Pictures/TLM"):
            path = Path(android_path)
            if path.parent.exists():
                candidates.append(path)

    home = Path.home()
    candidates.append(home / "Pictures" / "TLM")

    app_data = os.environ.get("FLET_APP_STORAGE_DATA")
    if app_data:
        candidates.append(Path(app_data) / "exports")

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

    return Path(tempfile.gettempdir())


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


def generate_16x9_png(data, output_dir=None):
    output_dir = Path(output_dir or default_export_dir())
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    export_time = time.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"{safe_filename(data.get('name'))}_{stamp}_16x9.png"
    path = output_dir / filename

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font_prop = None
    font_path = find_cjk_font_path()
    if font_path:
        try:
            font_manager.fontManager.addfont(str(font_path))
        except Exception:
            pass
        font_prop = font_manager.FontProperties(fname=str(font_path))
        try:
            plt.rcParams["font.family"] = font_prop.get_name()
            plt.rcParams["font.sans-serif"] = [
                font_prop.get_name(),
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
            ]
        except Exception:
            pass
    plt.rcParams["axes.unicode_minus"] = False

    d_list = data["d_list"]
    r_list = data["r_list"]
    currents = data["currents"]
    slope = data["slope"]
    intercept = data["intercept"]

    x_min = min(d_list)
    x_max = max(d_list)
    x_pad = max((x_max - x_min) * 0.08, 0.5)
    line_x = [x_min - x_pad, x_max + x_pad]
    line_y = [slope * x + intercept for x in line_x]

    fig = plt.figure(figsize=(16, 9), dpi=120)
    ax = fig.add_axes([0.08, 0.32, 0.304, 0.54])
    info_ax = fig.add_axes([0.50, 0.40, 0.32, 0.36])
    info_ax.axis("off")

    fig.patch.set_facecolor("#f7f9fc")
    ax.set_facecolor("white")
    ax.scatter(d_list, r_list, s=80, color="#d62728", label="测量值")
    ax.plot(line_x, line_y, color="#1f77b4", linewidth=3, label="线性拟合")
    ax.set_xlabel("间距 d (μm)", fontsize=13, fontproperties=font_prop)
    ax.set_ylabel("总电阻 R (Ω)", fontsize=13, fontproperties=font_prop)
    ax.grid(True, color="#d9e2ec", linewidth=0.8)
    ax.legend(loc="best", prop=font_prop)
    try:
        ax.set_box_aspect(1)
    except Exception:
        pass
    ax.set_xlim(line_x[0], line_x[1])

    y_values = r_list + line_y
    y_min = min(y_values)
    y_max = max(y_values)
    y_pad = max((y_max - y_min) * 0.12, 1)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    title = data.get("name") or "TLM Analysis"
    fig.suptitle(
        title,
        fontsize=24,
        fontweight="bold",
        x=0.08,
        y=0.965,
        ha="left",
        fontproperties=font_prop,
    )
    fig.text(
        0.08,
        0.91,
        f"预设: {data.get('preset_name', '-')}"
        f"    W={data['w']:.4g} μm    V={data['v']:.4g} V"
        f"    导出时间: {export_time}",
        fontsize=13,
        color="#425466",
        fontproperties=font_prop,
    )

    metrics = [
        ("Rc", f"{data['Rc_norm']:.4f} Ω·mm"),
        ("Rsh", f"{data['Rsh']:.2f} Ω/□"),
        ("R²", f"{data['r2']:.5f}"),
    ]

    info_ax.text(0, 0.98, "结果", fontsize=20, fontweight="bold", va="top", fontproperties=font_prop)
    y = 0.78
    for label, value in metrics:
        info_ax.text(0, y, label, fontsize=13, color="#5b677a", va="top", fontproperties=font_prop)
        info_ax.text(
            0,
            y - 0.095,
            value,
            fontsize=18,
            color="#111827",
            va="top",
            fontweight="bold",
            fontproperties=font_prop,
        )
        y -= 0.27

    rows = [
        [f"{_format_number(d)}", f"{i:g}"]
        for d, i in zip(d_list, currents)
    ]
    table_ax = fig.add_axes([0.08, 0.035, 0.84, 0.19])
    table_ax.axis("off")
    table = table_ax.table(
        cellText=rows,
        colLabels=["间距 d (μm)", "电流 I (mA)"],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(13)
    table.scale(1, 1.55)
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor("#334155")
        cell.set_linewidth(1.0)
        if font_prop:
            cell.get_text().set_fontproperties(font_prop)
        if row == 0:
            cell.set_facecolor("#eef3f8")
            cell.get_text().set_fontweight("bold")
            cell.get_text().set_fontsize(14)
        else:
            cell.get_text().set_fontsize(13)

    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(path)


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

    chart_caption = ft.Text("红点为测量值，蓝线为线性拟合。横轴: 间距 d (μm)，纵轴: 总电阻 R (Ω)", size=12, color="#52616f")
    chart_image = ft.Image(
        src=chart_png_base64(width=720, height=420),
        width=720,
        height=420,
        fit=ft.BoxFit.CONTAIN,
    )
    chart = ft.Column(
        controls=[chart_caption, chart_image],
        spacing=6,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
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
                suffix="mA",
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

                chart_image.src = chart_png_base64(d_list, r_list, slope, intercept, width=720, height=420)

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
                    alignment=align_value("center"),
                    border=border_all(1, "#334155"),
                ),
                ft.Container(
                    content=ft.Text(right, size=14 if header else 13, weight=weight),
                    width=420,
                    height=24,
                    bgcolor=bg,
                    alignment=align_value("center"),
                    border=border_all(1, "#334155"),
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

        export_chart = ft.Column(
            controls=[
                ft.Text("总电阻 R (Ω)", size=12, color="#425466"),
                ft.Image(
                    src=chart_png_base64(d_list, r_list, slope, intercept, width=320, height=320),
                    width=320,
                    height=320,
                    fit=ft.BoxFit.CONTAIN,
                ),
                ft.Text("间距 d (μm)", size=12, color="#425466"),
            ],
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
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
            padding=padding_only(left=48, right=48, top=20, bottom=18),
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
                height=350,
                bgcolor="white",
                border=border_all(1, "#cbd5e1"),
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
                                padding=padding_only(top=40),
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

        if share_service and hasattr(ft, "ShareFile"):
            try:
                share_file = ft.ShareFile.from_path(path, name=Path(path).name)
                result = share_service.share_files(
                    [share_file],
                    title="分享 TLM 16:9 图片",
                    text=f"TLM 结果: {name_input.value or Path(path).stem}",
                    subject="TLM Analysis",
                )
                if hasattr(result, "__await__"):
                    await result
                show_message("已打开系统分享面板", "green")
                return
            except Exception:
                pass

        show_message(f"当前 Flet 环境不支持系统分享，图片已保存: {path}", "#f59e0b")

    # --- 设置界面 ---
    settings_selected_id = {"value": app_state["active_preset"]["id"]}
    settings_preset_dropdown = ft.Dropdown(label="编辑预设", bgcolor="white", expand=True)
    preset_name_input = ft.TextField(label="预设名称", bgcolor="white")
    width_input = ft.TextField(label="通道宽度 W", suffix="μm", keyboard_type="number", bgcolor="white")
    voltage_input = ft.TextField(label="测试电压 V", suffix="V", keyboard_type="number", bgcolor="white")
    tlm_count_input = ft.TextField(label="TLM 数量", keyboard_type="number", bgcolor="white")
    spacing_values_input = ft.TextField(label="间距列表", suffix="μm", bgcolor="white")
    spacing_preview = ft.Text(size=12, color="#52616f")

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
            width=620,
            height=520,
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
                    ft.Row([width_input, voltage_input]),
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
            ft.ElevatedButton("使用此预设", icon="check", on_click=use_settings_preset),
            ft.ElevatedButton("保存预设", icon="save", bgcolor="blue", color="white", on_click=save_settings_preset),
        ],
    )

    def open_settings_dialog(e):
        refresh_settings_dropdown()
        fill_settings_fields(app_state["active_preset"])
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
        content=ft.Container(content=history_list_view, width=680, height=500),
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
                        border=border_all(1, "#d9e2ec"),
                        on_click=on_restore,
                    )
                )
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
                        ft.Icon("home", color="white"),
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
                        ft.Icon("science", color="#1565c0", size=42),
                        ft.Column(
                            controls=[
                                ft.Text("TLM 计算", size=22, weight="bold", color="#111827"),
                                ft.Text("选择预设，输入不同间距下的电流并导出 16:9 图片。", size=13, color="#52616f"),
                            ],
                            spacing=4,
                            expand=True,
                        ),
                        ft.Icon("chevron_right", color="#64748b"),
                    ]
                ),
                bgcolor="white",
                padding=18,
                border_radius=8,
                border=border_all(1, "#d9e2ec"),
                on_click=render_tlm_page,
            ),
            ft.Container(height=12),
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon("timer", color="#047857", size=42),
                        ft.Column(
                            controls=[
                                ft.Text("计时器", size=22, weight="bold", color="#111827"),
                                ft.Text("秒级倒计时、3/5/10/14 分钟倒计时、自定义备注和正计时。", size=13, color="#52616f"),
                            ],
                            spacing=4,
                            expand=True,
                        ),
                        ft.Icon("chevron_right", color="#64748b"),
                    ]
                ),
                bgcolor="white",
                padding=18,
                border_radius=8,
                border=border_all(1, "#d9e2ec"),
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
                alignment=align_value("bottom_right"),
            ),
        )

    # --- 计时器页 ---
    timer_state = {
        "countdown_stop": None,
        "countdown_token": 0,
        "countdown_running": False,
        "stopwatch_stop": None,
        "stopwatch_token": 0,
        "stopwatch_elapsed": 0,
        "stopwatch_running": False,
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
        suffix="秒",
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
        suffix="分钟",
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
        if update_status:
            countdown_status_text.value = "倒计时已停止"
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
        update_countdown_display(seconds, note, "倒计时进行中")

        def worker():
            remaining = seconds
            while remaining > 0 and not stop_event.is_set() and token == timer_state["countdown_token"]:
                time.sleep(1)
                if stop_event.is_set() or token != timer_state["countdown_token"]:
                    break
                remaining -= 1
                update_countdown_display(remaining, note, "倒计时进行中" if remaining else "倒计时完成")

            if not stop_event.is_set() and token == timer_state["countdown_token"]:
                timer_state["countdown_running"] = False
                update_countdown_display(0, note, "倒计时完成")

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
        start_at = time.monotonic() - timer_state["stopwatch_elapsed"]
        update_stopwatch_display(timer_state["stopwatch_elapsed"], note, "正计时进行中")

        def worker():
            while not stop_event.is_set() and token == timer_state["stopwatch_token"]:
                elapsed = int(time.monotonic() - start_at)
                update_stopwatch_display(elapsed, note, "正计时进行中")
                time.sleep(1)

        threading.Thread(target=worker, daemon=True).start()

    def pause_stopwatch(e):
        stop_event = timer_state.get("stopwatch_stop")
        if stop_event:
            stop_event.set()
        timer_state["stopwatch_running"] = False
        stopwatch_status_text.value = "正计时已暂停"
        try:
            page.update()
        except Exception:
            pass

    def reset_stopwatch(e):
        pause_stopwatch(None)
        timer_state["stopwatch_token"] += 1
        update_stopwatch_display(0, "", "正计时未开始")

    def render_timer_page(e=None):
        page.scroll = "adaptive"
        set_page_controls(
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.IconButton("arrow_back", tooltip="返回首页", icon_color="white", on_click=render_home_page),
                        ft.Icon("timer", color="white"),
                        ft.Text("计时器", size=22, weight="bold", color="white"),
                        ft.Container(expand=True),
                        ft.IconButton("science", tooltip="TLM 计算", icon_color="white", on_click=render_tlm_page),
                    ]
                ),
                bgcolor="#047857",
                padding=12,
                border_radius=6,
            ),
            ft.Container(height=10),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("秒级倒计时", weight="bold", size=18),
                        ft.Row([second_countdown_input, countdown_note_input]),
                        ft.Row(
                            controls=[
                                ft.ElevatedButton("开始秒级倒计时", icon="play_arrow", bgcolor="blue", color="white", expand=True, on_click=start_seconds_countdown),
                                ft.ElevatedButton("停止", icon="stop", expand=True, on_click=lambda e: stop_countdown()),
                                ft.ElevatedButton("重置", icon="restart_alt", expand=True, on_click=reset_countdown),
                            ]
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
                border=border_all(1, "#d9e2ec"),
            ),
            ft.Container(height=10),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("分钟倒计时", weight="bold", size=18),
                        ft.Row(
                            controls=[
                                ft.ElevatedButton("3 分钟", icon="timer", expand=True, on_click=lambda e: start_minutes_countdown(3)),
                                ft.ElevatedButton("5 分钟", icon="timer", expand=True, on_click=lambda e: start_minutes_countdown(5)),
                            ]
                        ),
                        ft.Row(
                            controls=[
                                ft.ElevatedButton("10 分钟", icon="timer", expand=True, on_click=lambda e: start_minutes_countdown(10)),
                                ft.ElevatedButton("14 分钟", icon="timer", expand=True, on_click=lambda e: start_minutes_countdown(14)),
                            ]
                        ),
                        ft.Row(
                            controls=[
                                custom_minutes_input,
                                ft.ElevatedButton("开始自定义", icon="play_arrow", bgcolor="#047857", color="white", on_click=start_custom_minutes_countdown),
                            ]
                        ),
                        ft.Text("备注使用上方备注输入框，开始任意倒计时都会一并显示。", size=12, color="#64748b"),
                    ],
                    spacing=10,
                ),
                bgcolor="white",
                padding=14,
                border_radius=8,
                border=border_all(1, "#d9e2ec"),
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
                        ft.Row(
                            controls=[
                                ft.ElevatedButton("开始", icon="play_arrow", bgcolor="#047857", color="white", expand=True, on_click=start_stopwatch),
                                ft.ElevatedButton("暂停", icon="pause", expand=True, on_click=pause_stopwatch),
                                ft.ElevatedButton("重置", icon="restart_alt", expand=True, on_click=reset_stopwatch),
                            ]
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor="white",
                padding=14,
                border_radius=8,
                border=border_all(1, "#d9e2ec"),
            ),
        )

    def render_tlm_page(e=None):
        page.scroll = "adaptive"
        set_page_controls(
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.IconButton("arrow_back", tooltip="返回首页", icon_color="white", on_click=render_home_page),
                        ft.Icon("science", color="white"),
                        ft.Text("TLM 计算", size=22, weight="bold", color="white"),
                        ft.Container(expand=True),
                        ft.IconButton("timer", tooltip="计时器", icon_color="white", on_click=render_timer_page),
                        ft.IconButton("settings", tooltip="设置", icon_color="white", on_click=open_settings_dialog),
                        ft.IconButton("history", tooltip="历史", icon_color="white", on_click=open_history_dialog),
                    ],
                ),
                bgcolor="#1565c0",
                padding=12,
                border_radius=6,
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
            ft.Container(content=chart, bgcolor="white", padding=8, border=border_all(1, "#d9e2ec")),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("@CuiMiller", size=16, color="#6b7280"),
                        ft.Text("2026 V2.1", size=12, color="#8a94a6"),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                ),
                alignment=align_value("bottom_right"),
                margin=margin_only(top=24, bottom=20),
            ),
        )

    # --- 初始 UI 状态 ---
    refresh_preset_dropdown()
    update_summary()
    rebuild_current_inputs(clear_inputs=True)
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
            page.clean()
            page.add(
                ft.Text("启动失败", size=26, weight="bold", color="red"),
                ft.Text(str(ex), selectable=True),
                ft.Text(traceback.format_exc(), selectable=True, size=12),
            )
            page.update()
        except Exception:
            raise


if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(safe_main)
    else:
        ft.app(target=safe_main)
