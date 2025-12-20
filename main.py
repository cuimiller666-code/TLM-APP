import flet as ft
import math
import time
import json


# --- 1. 纯 Python 核心算法 ---
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


# --- 2. 主程序 ---
def main(page):
    page.title = "TLM计算_Cui v.0.3"
    page.scroll = "adaptive"
    page.theme_mode = "light"
    page.padding = 20
    page.bgcolor = "#f0f2f5"

    # --- 安全存储逻辑 ---
    STORAGE_KEY = "tlm_history_json_safe"

    def get_history():
        try:
            json_str = page.client_storage.get(STORAGE_KEY)
            if not json_str: return []
            return json.loads(json_str)
        except:
            return []

    def save_to_history(name, w, v, inputs):
        try:
            history = get_history()
            record = {
                "id": int(time.time() * 1000),
                "time": time.strftime("%m-%d %H:%M"),
                "name": name,
                "w": w,
                "v": v,
                "inputs": inputs
            }
            history.insert(0, record)
            if len(history) > 20: history.pop()
            page.client_storage.set(STORAGE_KEY, json.dumps(history))
            return True
        except:
            return False

    def delete_history_item(item_id):
        history = get_history()
        new_history = [r for r in history if r['id'] != item_id]
        page.client_storage.set(STORAGE_KEY, json.dumps(new_history))
        open_history_dialog(None)

        # --- UI 组件 ---

    name_input = ft.TextField(label="保存名称 (可选)", hint_text="例如: Sample A", bgcolor="white")

    # 【修改】这里去掉了 expand=True，因为变成单行后默认就会撑满
    width_input = ft.TextField(label="通道宽度 W", suffix_text="um", value="100", keyboard_type="number",
                               bgcolor="white")
    voltage_input = ft.TextField(label="测试电压 V", suffix_text="V", value="5.0", keyboard_type="number",
                                 bgcolor="white")

    spacings = [2, 3, 5, 7, 9, 11, 17]
    input_refs = []
    input_col = ft.Column(spacing=10)

    for s in spacings:
        field = ft.TextField(
            label=f"间距 {s} um 电流", suffix_text="mA", keyboard_type="number",
            bgcolor="white", height=50
        )
        input_refs.append((s, field))
        input_col.controls.append(field)

    result_text = ft.Text("请输入数据点击计算...", size=16, color="grey")

    chart = ft.LineChart(
        data_series=[],
        left_axis=ft.ChartAxis(title=ft.Text("总电阻 (Ω)"), labels_size=30),
        bottom_axis=ft.ChartAxis(title=ft.Text("间距 d (um)"), labels_size=20),
        min_y=0, expand=True, height=300
    )

    # --- 核心功能 ---
    def perform_calculation():
        try:
            w_val = float(width_input.value)
            v_val = float(voltage_input.value)
            d_list = []
            r_list = []
            inputs_data = []

            for s, field in input_refs:
                if field.value:
                    val = float(field.value)
                    d_list.append(float(s))
                    r_calc = abs(v_val / (val / 1000.0))
                    r_list.append(r_calc)
                    inputs_data.append([float(s), val])

            if len(d_list) < 2:
                result_text.value = "错误: 数据不足"
                result_text.color = "red"
                page.update()
                return None

            slope, intercept, r2 = simple_linear_fit(d_list, r_list)

            Rc_ohms = intercept / 2
            Rc_norm = Rc_ohms * (w_val / 1000.0)
            Rsh = slope * w_val
            LT = Rc_ohms * w_val / Rsh if Rsh != 0 else 0
            rho_c = Rc_ohms * LT * w_val * 1e-8

            d_min = min(d_list)
            d_max = max(d_list)

            chart.min_y = min(r_list) * 0.8
            chart.max_y = max(r_list) * 1.1

            chart.data_series = [
                ft.LineChartData(
                    data_points=[ft.LineChartDataPoint(x=d, y=r) for d, r in zip(d_list, r_list)],
                    color="red", stroke_width=0, point=True
                ),
                ft.LineChartData(
                    data_points=[
                        ft.LineChartDataPoint(x=d_min, y=slope * d_min + intercept),
                        ft.LineChartDataPoint(x=d_max, y=slope * d_max + intercept)
                    ],
                    color="blue", stroke_width=3
                )
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
            return {"w": w_val, "v": v_val, "inputs": inputs_data}

        except Exception as ex:
            result_text.value = f"计算错误: {str(ex)}"
            result_text.color = "red"
            page.update()
            return None

    def on_calc_click(e):
        perform_calculation()

    def on_save_click(e):
        name = name_input.value
        if not name:
            page.open(ft.SnackBar(ft.Text("请先输入保存名称"), bgcolor="red"))
            return

        data = perform_calculation()
        if data:
            if save_to_history(name, data['w'], data['v'], data['inputs']):
                page.open(ft.SnackBar(ft.Text(f"已保存: {name}"), bgcolor="green"))
            else:
                page.open(ft.SnackBar(ft.Text("保存失败"), bgcolor="red"))

    # --- 历史记录弹窗逻辑 ---
    def restore_record(record):
        width_input.value = str(record['w'])
        voltage_input.value = str(record['v'])
        name_input.value = record['name']

        saved_inputs = dict(record['inputs'])
        for s, field in input_refs:
            if float(s) in saved_inputs:
                field.value = str(saved_inputs[float(s)])
            else:
                field.value = ""

        page.close(history_dialog)
        perform_calculation()
        page.open(ft.SnackBar(ft.Text(f"已加载: {record['name']}"), bgcolor="blue"))

    history_list_view = ft.Column(scroll="auto")
    history_dialog = ft.AlertDialog(
        title=ft.Text("历史记录"),
        content=ft.Container(
            content=history_list_view,
            width=600, height=400
        ),
        actions=[
            ft.TextButton("关闭", on_click=lambda e: page.close(history_dialog))
        ]
    )

    def open_history_dialog(e):
        history = get_history()
        history_list_view.controls.clear()

        if not history:
            history_list_view.controls.append(ft.Text("暂无记录", color="grey"))
        else:
            for r in history:
                def on_restore(e, rec=r):
                    restore_record(rec)

                def on_del(e, rid=r['id']):
                    delete_history_item(rid)

                item = ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(r['name'], weight="bold"),
                            ft.Text(r['time'], size=12, color="grey")
                        ], expand=True),
                        ft.IconButton("restore", icon_color="blue", tooltip="加载", on_click=on_restore),
                        ft.IconButton("delete", icon_color="red", tooltip="删除", on_click=on_del),
                    ]),
                    padding=10, bgcolor="#f5f5f5", border_radius=5, margin=ft.margin.only(bottom=5),
                    on_click=on_restore
                )
                history_list_view.controls.append(item)

        page.open(history_dialog)

    # --- 页面布局 ---
    page.add(
        ft.Container(
            content=ft.Row([
                ft.Icon(name="science", color="white"),
                ft.Text("TLM Pro v7.2", size=20, weight="bold", color="white"),
                ft.Container(expand=True),
                ft.IconButton("history", icon_color="white", tooltip="历史", on_click=open_history_dialog)
            ]),
            bgcolor="blue", padding=15, border_radius=5
        ),
        ft.Container(height=10),

        ft.Text("1. 设置与保存", weight="bold"),
        name_input,


        width_input,
        voltage_input,

        ft.Container(height=10),
        ft.Text("2. 电流输入 (mA)", weight="bold"),
        input_col,

        ft.Container(height=10),
        ft.Row([
            ft.ElevatedButton("计算", icon="play_arrow", on_click=on_calc_click, bgcolor="blue", color="white",
                              expand=True),
            ft.Container(width=10),
            ft.ElevatedButton("保存", icon="save", on_click=on_save_click, bgcolor="green", color="white", expand=True),
        ]),

        ft.Container(height=20),
        ft.Text("3. 分析结果", weight="bold"),
        ft.Container(content=result_text, bgcolor="#E3F2FD", padding=10, border_radius=5),

        ft.Container(height=10),
        ft.Container(content=chart, bgcolor="white", padding=5, border=ft.border.all(1, "grey"))
    )


if __name__ == "__main__":
    ft.app(target=main)
