import flet as ft
import numpy as np


def main(page: ft.Page):
    # App 窗口标题
    page.title = "TLM_Cui"
    page.scroll = "adaptive"
    page.theme_mode = "light"
    page.padding = 20

    # --- 状态变量 ---
    spacings = [2, 3, 5, 7, 9, 11, 17]
    current_inputs = []

    # --- UI 组件 ---
    width_input = ft.TextField(label="通道宽度 W (um)", value="100", suffix_text="um", keyboard_type="number")
    voltage_input = ft.TextField(label="测试电压 V (V)", value="5.0", suffix_text="V", keyboard_type="number")

    result_text = ft.Text(value="请输入数据后点击计算", color="blue700", size=16, weight="bold")

    # 图表组件
    chart = ft.LineChart(
        data_series=[],
        border=ft.border.all(1, "black54"),
        horizontal_grid_lines=ft.ChartGridLines(interval=50, color="black12", width=1),
        vertical_grid_lines=ft.ChartGridLines(interval=2, color="black12", width=1),
        left_axis=ft.ChartAxis(title=ft.Text("总电阻 (Ω)"), labels_size=40),
        bottom_axis=ft.ChartAxis(title=ft.Text("间距 d (um)"), labels_size=32),
        height=300,
        expand=True,
    )

    input_column = ft.Column(spacing=10)
    for s in spacings:
        ci = ft.TextField(label=f"间距 {s} um 的电流", suffix_text="mA", keyboard_type="number")
        current_inputs.append((s, ci))
        input_column.controls.append(ci)

    def calculate_click(e):
        try:
            w = float(width_input.value)
            v = float(voltage_input.value)
            data_points = []
            for s, ci in current_inputs:
                if ci.value:
                    data_points.append((float(s), float(ci.value)))

            if len(data_points) < 2:
                result_text.value = "错误：数据不足"
                page.update()
                return

            d_arr = np.array([x[0] for x in data_points])
            i_mA_arr = np.array([x[1] for x in data_points])
            r_total = v / (i_mA_arr / 1000.0)

            slope, intercept = np.polyfit(d_arr, r_total, 1)
            Rc = intercept / 2
            Rsheet = slope * w
            LT = Rc * w / Rsheet
            rho_c = Rc * LT * w * 1e-8

            fitted = slope * d_arr + intercept
            r_squared = 1 - (np.sum((r_total - fitted) ** 2) / np.sum((r_total - np.mean(r_total)) ** 2))

            result_text.value = (
                f"拟合优度 R²: {r_squared:.6f}\n"
                f"薄层电阻 Rsheet: {Rsheet:.2f} Ω/□\n"
                f"接触电阻 Rc: {Rc * (w / 1000):.4f} Ω·mm\n"
                f"传输长度 LT: {LT:.4f} μm\n"
                f"比接触电阻率 ρc: {rho_c:.2e} Ω·cm²"
            )

            chart.data_series = [
                ft.LineChartData(data_points=[ft.LineChartDataPoint(d, r) for d, r in zip(d_arr, r_total)],
                                 show_points=True, color="red", point_size=10),
                ft.LineChartData(data_points=[ft.LineChartDataPoint(min(d_arr), slope * min(d_arr) + intercept),
                                              ft.LineChartDataPoint(max(d_arr), slope * max(d_arr) + intercept)],
                                 show_points=False, color="blue", stroke_width=2)
            ]
        except Exception as ex:
            result_text.value = f"计算出错: {str(ex)}"
        page.update()

    page.add(
        ft.Row([ft.Icon("analytics", color="blue"), ft.Text("TLM_Cui 控制台", size=20, weight="bold")]),
        ft.Divider(),
        ft.Column([
            width_input, voltage_input,
            ft.Text("电流输入 (mA):", weight="bold"),
            input_column,
            ft.ElevatedButton("执行提取", icon="play_arrow", on_click=calculate_click),
        ], scroll="adaptive", height=400),
        ft.Divider(),
        ft.Container(content=result_text, padding=10, bgcolor="bluegrey50", border_radius=10),
        ft.Container(content=chart, padding=10)
    )


if __name__ == "__main__":
    ft.app(target=main)
