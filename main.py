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
    page.title = "TLM计算"
    page.scroll = "adaptive"
    page.theme_mode = "light"
    page.padding = 20
    page.bgcolor = "#f0f2f5"

    # --- 安全存储逻辑 ---
    # 历史记录存储Key
    STORAGE_KEY = "tlm_history_json_safe"
    # 实时参数存储Key（新增：保存最后一次修改的参数）
    REAL_PARAMS_KEY = "tlm_real_params_safe"

    # ========== 新增：实时参数存储/读取 ==========
    def get_real_params():
        """读取最后一次修改的实时参数，无则返回默认值"""
        try:
            json_str = page.client_storage.get(REAL_PARAMS_KEY)
            if not json_str:
                return {
                    "spacing_count": "7",
                    "spacing_values": "2,3,5,7,9,11,17",
                    "width": "100",
                    "voltage": "5.0"
                }
            return json.loads(json_str)
        except:
            # 异常时返回默认值
            return {
                "spacing_count": "7",
                "spacing_values": "2,3,5,7,9,11,17",
                "width": "100",
                "voltage": "5.0"
            }

    def save_real_params(params):
        """自动保存实时参数到本地"""
        try:
            page.client_storage.set(REAL_PARAMS_KEY, json.dumps(params))
            return True
        except:
            return False

    # ========== 历史记录逻辑 ==========
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
    # 读取最后一次的实时参数（新增）
    real_params = get_real_params()

    name_input = ft.TextField(label="保存名称 (可选)", hint_text="例如: Sample A", bgcolor="white")

    # 加载历史参数（而非固定默认值）
    width_input = ft.TextField(
        label="通道宽度 W",
        suffix_text="um",
        value=real_params["width"],  # 加载最后一次值
        keyboard_type="number",
        bgcolor="white"
    )
    voltage_input = ft.TextField(
        label="测试电压 V",
        suffix_text="V",
        value=real_params["voltage"],  # 加载最后一次值
        keyboard_type="number",
        bgcolor="white"
    )

    # 自定义间距相关组件（加载历史参数）
    spacing_count_input = ft.TextField(
        label="间距数量",
        value=real_params["spacing_count"],  # 加载最后一次值
        keyboard_type="number",
        bgcolor="white",
        width=page.width - 40 if page.width else 300
    )

    spacing_values_input = ft.TextField(
        label="间距数值 (用逗号分隔)",
        value=real_params["spacing_values"],  # 加载最后一次值
        hint_text="例如: 2,3,5,7,9,11,17",
        bgcolor="white",
        width=page.width - 40 if page.width else 300
    )

    # ========== 新增：输入框修改时自动保存参数 ==========
    def auto_save_params(e):
        """输入框内容变化时，自动保存实时参数"""
        save_real_params({
            "spacing_count": spacing_count_input.value.strip(),
            "spacing_values": spacing_values_input.value.strip(),
            "width": width_input.value.strip(),
            "voltage": voltage_input.value.strip()
        })

    # 给输入框绑定自动保存事件
    spacing_count_input.on_change = auto_save_params
    spacing_values_input.on_change = auto_save_params
    width_input.on_change = auto_save_params
    voltage_input.on_change = auto_save_params

    # 电流输入框容器
    input_refs = []
    input_col = ft.Column(spacing=10)

    def update_spacing_fields(e):
        """根据输入的间距数量和数值更新输入框"""
        try:
            input_col.controls.clear()
            input_refs.clear()

            # 获取用户输入的间距数值
            spacing_text = spacing_values_input.value
            if spacing_text:
                spacings = [float(s.strip()) for s in spacing_text.split(',') if s.strip()]

                # 处理数量输入
                try:
                    count = int(spacing_count_input.value)
                    if count > 0:
                        if len(spacings) > count:
                            spacings = spacings[:count]
                        elif len(spacings) < count:
                            # 数量不足时补充生成
                            if spacings:
                                last = spacings[-1]
                                while len(spacings) < count:
                                    last += 2
                                    spacings.append(last)
                            else:
                                # 无输入时从2开始生成
                                for i in range(count):
                                    spacings.append(2 + i * 2)
                except:
                    pass  # 数量输入无效时使用所有输入的间距

                # 创建新的电流输入框
                for s in spacings:
                    field = ft.TextField(
                        label=f"间距 {s} um 电流",
                        suffix_text="mA",
                        keyboard_type="number",
                        bgcolor="white",
                        height=50,
                        width=page.width - 40 if page.width else 300
                    )
                    input_refs.append((s, field))
                    input_col.controls.append(field)

            page.update()
            # 自动保存修改后的间距参数
            auto_save_params(None)
        except Exception as ex:
            page.open(ft.SnackBar(ft.Text(f"更新间距失败: {str(ex)}"), bgcolor="red"))

    # 结果显示组件
    result_text = ft.Text("请输入数据点击计算...", size=16, color="grey")

    # 图表组件
    chart = ft.LineChart(
        data_series=[],
        left_axis=ft.ChartAxis(title=ft.Text("总电阻 (Ω)"), labels_size=30),
        bottom_axis=ft.ChartAxis(title=ft.Text("间距 d (um)"), labels_size=20),
        min_y=0, expand=True, height=300
    )

    # --- 核心计算功能 ---
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
        """加载历史记录到输入框"""
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
        # 加载后自动保存到实时参数
        auto_save_params(None)
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

    # 初始化间距输入框
    update_spacing_fields(None)

    # --- 页面布局 ---
    page.add(
        ft.Container(
            content=ft.Row([
                ft.Icon(name="science", color="white"),
                ft.Text("LM计算     v.0.4", size=22, weight="bold", color="white"),
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
        ft.Text("2. 间距设置", weight="bold"),
        spacing_count_input,  # 间距数量输入框（独占一行）
        spacing_values_input,  # 间距数值输入框（独占一行）
        # 更新间距按钮（用Container包裹设置margin）
        ft.Container(
            content=ft.ElevatedButton(
                "更新间距",
                icon="refresh",
                on_click=update_spacing_fields,
                width=page.width - 40 if page.width else 300
            ),
            margin=ft.margin.only(top=10)
        ),

        ft.Container(height=10),
        ft.Text("3. 电流输入 (mA)", weight="bold"),
        input_col,

        ft.Container(height=10),
        ft.Row([
            ft.ElevatedButton("计算", icon="play_arrow", on_click=on_calc_click, bgcolor="blue", color="white",
                              expand=True),
            ft.Container(width=10),
            ft.ElevatedButton("保存", icon="save", on_click=on_save_click, bgcolor="green", color="white", expand=True),
        ]),

        ft.Container(height=20),
        ft.Text("4. 分析结果", weight="bold"),
        ft.Container(content=result_text, bgcolor="#E3F2FD", padding=10, border_radius=5),

        ft.Container(height=10),
        ft.Container(content=chart, bgcolor="white", padding=5, border=ft.border.all(1, "grey")),

        # 作者信息（纵向排列：作者 + 日期）
        ft.Container(
            content=ft.Column([
                ft.Text("@CuiMiller", size=16, color="grey"),
                ft.Text("2025/12/21", size=12, color="grey"),
            ],
                spacing=5,  # 两行文本之间的间距
                alignment=ft.MainAxisAlignment.END,  # 列内元素右对齐
                horizontal_alignment=ft.CrossAxisAlignment.END  # 水平右对齐
            ),
            margin=ft.margin.only(top=30, bottom=30),
            alignment=ft.alignment.bottom_right
        )
    )


if __name__ == "__main__":
    ft.app(target=main)
