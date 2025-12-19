import flet as ft
import numpy as np


def main(page: ft.Page):
    # --- 1. 页面基础设置 ---
    page.title = "TLM Pro"
    page.theme_mode = "light"
    page.padding = 0  # 边距完全由 SafeArea 控制
    page.bgcolor = "#f0f2f5"  # 淡灰色背景

    # 关键修正 1：禁用页面级滚动，防止与 ListView 冲突
    page.scroll = None

    # --- 状态变量 ---
    spacings = [2, 3, 5, 7, 9, 11, 17]
    current_inputs = []

    # --- UI 组件定义 ---
    header = ft.Container(
        content=ft.Row(
            [
                ft.Icon("science", color="white", size=24),
                ft.Text("TLM提取_Cui", color="white", size=20, weight="bold")
            ],
            alignment="center"
        ),
        bgcolor="#1976D2",  # 工业蓝
        padding=ft.padding.symmetric(vertical=15),
        shadow=ft.BoxShadow(blur_radius=5, color="black12")
    )

    def create_field(label, suffix):
        return ft.TextField(
            label=label,
            suffix_text=suffix,
            keyboard_type="number",
            border_color="#1976D2",
            border_radius=8,
            text_size=16,
            height=50,
            content_padding=15,
            expand=True
        )

    width_input = create_field("通道宽度 W", "um")
    width_input.value = "100"

    voltage_input = create_field("测试电压 V", "V")
    voltage_input.value = "5.0"

    result_text = ft.Text(value="等待数据输入...", color="grey", size=14)

    # --- 图表组件 ---
    chart = ft.LineChart(
        data_series=[],
        left_axis=ft.ChartAxis(
            title=ft.Text("总电阻 (Ω)", size=12, weight="bold"),
            labels_size=35,
        ),
        bottom_axis=ft.ChartAxis(
            title=ft.Text("间距 d (um)", size=12, weight="bold"),
            labels_size=25,
            labels_interval=1,
        ),
        horizontal_grid_lines=ft.ChartGridLines(interval=100, color="black12", width=1),
        vertical_grid_lines=ft.ChartGridLines(interval=1, color="black12", width=1),
        tooltip_bgcolor="#ccffffff",
        min_y=0,
        expand=True,
    )

    chart_container = ft.Container(
        content=chart,
        height=350,
        padding=10,
        bgcolor="white",
        border_radius=10,
        border=ft.border.all(1, "#e0e0e0"),
    )

    input_column = ft.Column(spacing=10)
    for s in spacings:
        ci = ft.TextField(
            label=f"间距 {s} um 的电流",
            suffix_text="mA",
            keyboard_type="number",
            height=45,
            text_size=14,
            border_radius=8,
            content_padding=10,
            bgcolor="white"
        )
        current_inputs.append((s, ci))
        input_column.controls.append(ci)

    # --- 计算逻辑 ---
    def calculate_click(e):
        try:
            w = float(width_input.value)
            v = float(voltage_input.value)
            data_points = []

            for s, ci in current_inputs:
                if ci.value:
                    data_points.append((float(s), float(ci.value)))

            if len(data_points) < 2:
                result_text.value = "❌ 错误：至少输入两组数据"
                result_text.color = "red"
                page.update()
                return

            # 数据处理
            d_arr = np.array([x[0] for x in data_points])
            i_mA_arr = np.array([x[1] for x in data_points])

            # 恢复公式: R = |V / I|
            r_total = np.abs(v / (i_mA_arr / 1000.0))

            # 线性拟合
            slope, intercept = np.polyfit(d_arr, r_total, 1)

            # TLM 参数提取
            Rc_ohms = intercept / 2
            Rc_normalized = Rc_ohms * (w / 1000.0)
            Rsheet = slope * w
            LT = Rc_ohms * w / Rsheet
            rho_c = Rc_ohms * LT * w * 1e-8

            # R² 计算
            fitted = slope * d_arr + intercept
            r_squared = 1 - (np.sum((r_total - fitted) ** 2) / np.sum((r_total - np.mean(r_total)) ** 2))

            # 显示结果
            result_text.value = (
                f"拟合优度 R²: {r_squared:.5f}\n"
                f"方块电阻 Rsh: {Rsheet:.2f} Ω/□\n"
                f"接触电阻 Rc: {Rc_normalized:.4f} Ω·mm\n"
                f"原始接触电阻: {Rc_ohms:.2f} Ω\n"
                f"传输长度 LT: {LT:.4f} μm\n"
                f"比接触电阻率 ρc: {rho_c:.2e} Ω·cm²"
            )
            result_text.color = "#0D47A1"

            # 更新图表
            chart.min_y = min(r_total) * 0.8
            chart.max_y = max(r_total) * 1.1

            chart.data_series = [
                ft.LineChartData(
                    data_points=[ft.LineChartDataPoint(d, r, tooltip=f"{r:.0f}") for d, r in zip(d_arr, r_total)],
                    color="red",
                    stroke_width=0,
                    point=True,
                ),
                ft.LineChartData(
                    data_points=[
                        ft.LineChartDataPoint(min(d_arr), slope * min(d_arr) + intercept),
                        ft.LineChartDataPoint(max(d_arr), slope * max(d_arr) + intercept)
                    ],
                    color="blue",
                    stroke_width=3,
                )
            ]

        except Exception as ex:
            result_text.value = f"计算出错: {str(ex)}"
            result_text.color = "red"

        page.update()

    # --- 布局组装 ---
    card_params = ft.Container(
        content=ft.Column([
            ft.Text("基础参数 / Parameters", weight="bold", color="#1976D2"),
            ft.Row([width_input, voltage_input], spacing=10)
        ]),
        padding=15,
        bgcolor="white",
        border_radius=10,
        shadow=ft.BoxShadow(blur_radius=2, color="black12")
    )

    card_inputs = ft.Container(
        content=ft.Column([
            ft.Text("电流数据 / Current Data", weight="bold", color="#1976D2"),
            input_column,
            ft.Container(height=10),
            ft.ElevatedButton(
                "开始分析 / Analyze",
                icon="analytics",
                on_click=calculate_click,
                style=ft.ButtonStyle(
                    bgcolor="#1976D2",
                    color="white",
                    shape=ft.RoundedRectangleBorder(radius=8),
                    padding=15
                ),
                width=1000
            )
        ]),
        padding=15,
        bgcolor="white",
        border_radius=10,
        shadow=ft.BoxShadow(blur_radius=2, color="black12")
    )

    card_results = ft.Container(
        content=ft.Column([
            ft.Text("分析结果 / Results", weight="bold", color="#1976D2"),
            ft.Container(
                content=result_text,
                bgcolor="#E3F2FD",
                padding=10,
                border_radius=5,
                width=1000
            ),
            ft.Container(height=10),
            chart_container
        ]),
        padding=15,
        bgcolor="white",
        border_radius=10,
        shadow=ft.BoxShadow(blur_radius=2, color="black12")
    )

    # 使用 ListView 确保可滚动，并开启 expand
    main_view = ft.ListView(
        [
            header,
            ft.Container(
                content=ft.Column([
                    card_params,
                    ft.Container(height=10),
                    card_inputs,
                    ft.Container(height=10),
                    card_results,
                    ft.Container(height=50),  # 底部预留更多空间
                ]),
                padding=15
            )
        ],
        expand=True  # 列表本身需要扩展
    )

    # 关键修正 2：SafeArea 必须开启 expand=True 才能撑满屏幕
    page.add(ft.SafeArea(main_view, expand=True))


if __name__ == "__main__":
    ft.app(target=main)
