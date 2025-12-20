import flet as ft
import numpy as np
import time
import json

def main(page: ft.Page):
    # --- 1. 页面基础配置 ---
    page.title = "TLM Pro"
    page.theme_mode = "light"
    page.padding = 0
    page.bgcolor = "#f0f2f5"
    
    # 路由模式下，必须禁用页面级滚动，否则和 ListView 冲突导致空白
    page.scroll = None 

    # --- 全局状态变量 ---
    current_detail_record = {} 

    # --- 核心逻辑函数 ---

    # 1. 保存数据
    def save_data(name, w, v, inputs, result_text, chart_data):
        if not name:
            page.show_snack_bar(ft.SnackBar(ft.Text("⚠️ 请先输入保存名称"), bgcolor="red"))
            return
        
        record = {
            "id": int(time.time() * 1000),
            "time": time.strftime("%Y-%m-%d %H:%M", time.localtime()),
            "name": name,
            "w": w,
            "v": v,
            "inputs": inputs,
            "result_str": result_text,
            "chart_data": chart_data
        }

        history = page.client_storage.get("tlm_history") or []
        history.insert(0, record)
        page.client_storage.set("tlm_history", history)
        
        page.show_snack_bar(ft.SnackBar(ft.Text(f"✅ 已保存: {name}"), bgcolor="green"))

    # 2. 删除记录
    def delete_record(e, record_id, update_list_callback):
        history = page.client_storage.get("tlm_history") or []
        new_history = [r for r in history if r["id"] != record_id]
        page.client_storage.set("tlm_history", new_history)
        page.show_snack_bar(ft.SnackBar(ft.Text("已删除"), bgcolor="grey"))
        update_list_callback()

    # --- 视图构建工厂 ---

    # 【视图 1】主页 (Home)
    def view_home():
        spacings = [2, 3, 5, 7, 9, 11, 17]
        current_inputs_refs = [] 
        
        name_input = ft.TextField(
            label="保存名称 (如: Sample A1)", prefix_icon=ft.icons.LABEL_OUTLINE,
            border_radius=8, height=50, content_padding=10, text_size=14, bgcolor="white"
        )
        width_input = ft.TextField(
            label="通道宽度 W", suffix_text="um", value="100", keyboard_type="number", 
            border_radius=8, height=50, content_padding=10, expand=True
        )
        voltage_input = ft.TextField(
            label="测试电压 V", suffix_text="V", value="5.0", keyboard_type="number", 
            border_radius=8, height=50, content_padding=10, expand=True
        )
        result_display = ft.Text(value="等待数据输入...", color="grey", size=14)
        
        chart = ft.LineChart(
            data_series=[],
            left_axis=ft.ChartAxis(title=ft.Text("总电阻 (Ω)"), labels_size=35),
            bottom_axis=ft.ChartAxis(title=ft.Text("间距 d (um)"), labels_size=25, labels_interval=1),
            horizontal_grid_lines=ft.ChartGridLines(interval=100, color="black12", width=1),
            vertical_grid_lines=ft.ChartGridLines(interval=1, color="black12", width=1),
            tooltip_bgcolor="#ccffffff", min_y=0, expand=True,
        )

        input_col = ft.Column(spacing=10)
        for s in spacings:
            ci = ft.TextField(
                label=f"间距 {s} um 的电流", suffix_text="mA", keyboard_type="number",
                height=45, text_size=14, border_radius=8, content_padding=10, bgcolor="white"
            )
            current_inputs_refs.append((s, ci))
            input_col.controls.append(ci)

        def on_calc(e):
            try:
                w_val = float(width_input.value)
                v_val = float(voltage_input.value)
                data_points = []
                input_values_for_save = []

                for s, ci in current_inputs_refs:
                    if ci.value:
                        val = float(ci.value)
                        data_points.append((float(s), val))
                        input_values_for_save.append((s, val))

                if len(data_points) < 2:
                    result_display.value = "❌ 至少输入两组数据"
                    result_display.color = "red"
                    result_display.update()
                    return

                d_arr = np.array([x[0] for x in data_points])
                i_mA_arr = np.array([x[1] for x in data_points])
                r_total = np.abs(v_val / (i_mA_arr / 1000.0))

                slope, intercept = np.polyfit(d_arr, r_total, 1)
                
                Rc_ohms = intercept / 2
                Rc_normalized = Rc_ohms * (w_val / 1000.0)
                Rsheet = slope * w_val
                LT = Rc_ohms * w_val / Rsheet
                rho_c = Rc_ohms * LT * w_val * 1e-8
                fitted = slope * d_arr + intercept
                r_squared = 1 - (np.sum((r_total - fitted) ** 2) / np.sum((r_total - np.mean(r_total)) ** 2))

                res_str = (
                    f"拟合优度 R²: {r_squared:.5f}\n"
                    f"方块电阻 Rsh: {Rsheet:.2f} Ω/□\n"
                    f"接触电阻 Rc: {Rc_normalized:.4f} Ω·mm\n"
                    f"原始接触电阻: {Rc_ohms:.2f} Ω\n"
                    f"传输长度 LT: {LT:.4f} μm\n"
                    f"比接触电阻率 ρc: {rho_c:.2e} Ω·cm²"
                )
                result_display.value = res_str
                result_display.color = "#0D47A1"
                result_display.update()

                chart.min_y = min(r_total) * 0.8
                chart.max_y = max(r_total) * 1.1
                chart.data_series = [
                    ft.LineChartData(
                        data_points=[ft.LineChartDataPoint(d, r, tooltip=f"{r:.0f}") for d, r in zip(d_arr, r_total)],
                        color="red", stroke_width=0, point=True,
                    ),
                    ft.LineChartData(
                        data_points=[
                            ft.LineChartDataPoint(min(d_arr), slope * min(d_arr) + intercept),
                            ft.LineChartDataPoint(max(d_arr), slope * max(d_arr) + intercept)
                        ],
                        color="blue", stroke_width=3,
                    )
                ]
                chart.update()

                save_btn.on_click = lambda e: save_data(
                    name_input.value, w_val, v_val, input_values_for_save, res_str, 
                    {"slope": slope, "intercept": intercept, "d_min": min(d_arr), "d_max": max(d_arr)}
                )
                save_btn.disabled = False
                save_btn.text = "保存当前结果 (Save)"
                save_btn.update()

            except Exception as ex:
                result_display.value = f"计算错误: {ex}"
                result_display.update()

        calc_btn = ft.ElevatedButton("开始分析 / Analyze", icon="analytics", on_click=on_calc, 
                                     style=ft.ButtonStyle(bgcolor="#1976D2", color="white", shape=ft.RoundedRectangleBorder(radius=8), padding=15), width=1000)
        
        save_btn = ft.ElevatedButton("请先点击计算", icon="save", disabled=True,
                                     style=ft.ButtonStyle(bgcolor="green", color="white", shape=ft.RoundedRectangleBorder(radius=8), padding=15), width=1000)

        return ft.View(
            "/",
            [
                # 【关键修复】这里必须加 expand=True，否则空白
                ft.SafeArea(
                    ft.Column([
                        ft.Container(
                            content=ft.Row([
                                ft.Icon("science", color="white"),
                                ft.Text("TLM Pro v1.1", color="white", size=20, weight="bold"),
                                ft.Container(expand=True),
                                ft.IconButton(ft.icons.HISTORY, icon_color="white", tooltip="历史记录", 
                                              on_click=lambda _: page.go("/history"))
                            ]),
                            bgcolor="#1976D2", padding=15, shadow=ft.BoxShadow(blur_radius=5, color="black12")
                        ),
                        ft.Expanded(
                            ft.ListView([
                                ft.Container(
                                    content=ft.Column([
                                        ft.Container(
                                            content=ft.Column([
                                                ft.Text("1. 设置 (Settings)", weight="bold", color="#1976D2"),
                                                name_input,
                                                ft.Row([width_input, voltage_input], spacing=10)
                                            ]),
                                            padding=15, bgcolor="white", border_radius=10, shadow=ft.BoxShadow(blur_radius=2, color="black12")
                                        ),
                                        ft.Container(height=10),
                                        ft.Container(
                                            content=ft.Column([
                                                ft.Text("2. 数据录入 (Data)", weight="bold", color="#1976D2"),
                                                input_col,
                                                ft.Container(height=10),
                                                calc_btn,
                                                ft.Container(height=10),
                                                save_btn
                                            ]),
                                            padding=15, bgcolor="white", border_radius=10, shadow=ft.BoxShadow(blur_radius=2, color="black12")
                                        ),
                                        ft.Container(height=10),
                                        ft.Container(
                                            content=ft.Column([
                                                ft.Text("3. 分析结果 (Result)", weight="bold", color="#1976D2"),
                                                ft.Container(result_display, bgcolor="#E3F2FD", padding=10, border_radius=5, width=1000),
                                                ft.Container(height=10),
                                                ft.Container(chart, height=300, padding=10, bgcolor="white", border=ft.border.all(1, "#e0e0e0"), border_radius=10)
                                            ]),
                                            padding=15, bgcolor="white", border_radius=10, shadow=ft.BoxShadow(blur_radius=2, color="black12")
                                        ),
                                        ft.Container(height=30)
                                    ]),
                                    padding=15
                                )
                            ])
                        )
                    ], expand=True), # Column 也要 expand
                    expand=True # SafeArea 也要 expand
                )
            ]
        )

    # 【视图 2】历史记录页 (History)
    def view_history():
        history_list = ft.ListView(expand=True, spacing=10, padding=15)
        
        def render_list():
            data = page.client_storage.get("tlm_history") or []
            history_list.controls.clear()
            if not data:
                history_list.controls.append(ft.Text("暂无历史记录", text_align="center", color="grey"))
            
            for record in data:
                def on_click_detail(e, r=record):
                    nonlocal current_detail_record
                    page.session.set("detail_data", r) 
                    page.go("/detail")

                def on_click_delete(e, r_id=record['id']):
                    delete_record(e, r_id, render_list)

                item = ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.icons.INSERT_CHART_OUTLINED, color="#1976D2"),
                        ft.Column([
                            ft.Text(record['name'], weight="bold", size=16),
                            ft.Text(record['time'], size=12, color="grey")
                        ], expand=True, spacing=2),
                        ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color="red", on_click=on_click_delete),
                        ft.IconButton(ft.icons.CHEVRON_RIGHT, on_click=on_click_detail)
                    ], alignment="spaceBetween"),
                    bgcolor="white", padding=15, border_radius=10,
                    shadow=ft.BoxShadow(blur_radius=2, color="black12"),
                    on_click=on_click_detail
                )
                history_list.controls.append(item)
            page.update()

        render_list()

        return ft.View(
            "/history",
            [
                # 【关键修复】这里也加 expand=True
                ft.SafeArea(
                    ft.Column([
                        ft.Container(
                            content=ft.Row([
                                ft.IconButton(ft.icons.ARROW_BACK, icon_color="white", on_click=lambda _: page.go("/")),
                                ft.Text("历史记录 (History)", color="white", size=20, weight="bold")
                            ]),
                            bgcolor="#1976D2", padding=15, shadow=ft.BoxShadow(blur_radius=5, color="black12")
                        ),
                        ft.Expanded(history_list)
                    ], expand=True),
                    expand=True
                )
            ]
        )

    # 【视图 3】详情页 (Detail)
    def view_detail():
        record = page.session.get("detail_data")
        if not record:
            return ft.View("/detail", [ft.Text("数据丢失")])

        chart_data = record['chart_data']
        inputs = record['inputs'] 
        v = record['v']
        
        d_arr = [i[0] for i in inputs]
        i_arr = [i[1] for i in inputs]
        r_arr = [abs(v / (curr/1000.0)) for curr in i_arr]

        detail_chart = ft.LineChart(
            data_series=[
                ft.LineChartData(
                    data_points=[ft.LineChartDataPoint(d, r, tooltip=f"{r:.0f}") for d, r in zip(d_arr, r_arr)],
                    color="red", stroke_width=0, point=True,
                ),
                ft.LineChartData(
                    data_points=[
                        ft.LineChartDataPoint(chart_data['d_min'], chart_data['slope'] * chart_data['d_min'] + chart_data['intercept']),
                        ft.LineChartDataPoint(chart_data['d_max'], chart_data['slope'] * chart_data['d_max'] + chart_data['intercept'])
                    ],
                    color="blue", stroke_width=3,
                )
            ],
            left_axis=ft.ChartAxis(title=ft.Text("总电阻"), labels_size=35),
            bottom_axis=ft.ChartAxis(title=ft.Text("间距"), labels_size=25),
            horizontal_grid_lines=ft.ChartGridLines(interval=100, color="black12", width=1),
            vertical_grid_lines=ft.ChartGridLines(interval=1, color="black12", width=1),
            min_y=0, expand=True,
        )

        input_rows = ft.Column()
        for d, i in inputs:
            input_rows.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(f"间距 {d} um:", width=100, color="grey"),
                        ft.Text(f"{i} mA", weight="bold")
                    ]),
                    padding=ft.padding.only(bottom=5)
                )
            )

        return ft.View(
            "/detail",
            [
                # 【关键修复】这里也加 expand=True
                ft.SafeArea(
                    ft.Column([
                        ft.Container(
                            content=ft.Row([
                                ft.IconButton(ft.icons.ARROW_BACK, icon_color="white", on_click=lambda _: page.go("/history")),
                                ft.Text(record['name'], color="white", size=20, weight="bold")
                            ]),
                            bgcolor="#1976D2", padding=15, shadow=ft.BoxShadow(blur_radius=5, color="black12")
                        ),
                        ft.Expanded(
                            ft.ListView([
                                ft.Container(
                                    content=ft.Column([
                                        ft.Text(f"保存时间: {record['time']}", size=12, color="grey"),
                                        ft.Divider(),
                                        ft.Text("基础参数:", weight="bold", color="#1976D2"),
                                        ft.Text(f"W = {record['w']} um, V = {record['v']} V"),
                                        ft.Divider(),
                                        ft.Text("原始数据:", weight="bold", color="#1976D2"),
                                        input_rows,
                                        ft.Divider(),
                                        ft.Text("分析结果:", weight="bold", color="#1976D2"),
                                        ft.Container(
                                            content=ft.Text(record['result_str'], color="#0D47A1"),
                                            bgcolor="#E3F2FD", padding=10, border_radius=5, width=1000
                                        ),
                                        ft.Container(height=10),
                                        ft.Container(detail_chart, height=300, padding=10, bgcolor="white", border=ft.border.all(1, "#e0e0e0"), border_radius=10)
                                    ]),
                                    padding=15
                                )
                            ])
                        )
                    ], expand=True),
                    expand=True
                )
            ]
        )

    def route_change(route):
        page.views.clear()
        page.views.append(view_home())
        
        if page.route == "/history":
            page.views.append(view_history())
        elif page.route == "/detail":
            page.views.append(view_detail())
            
        page.update()

    def view_pop(view):
        page.views.pop()
        top_view = page.views[-1]
        page.go(top_view.route)

    page.on_route_change = route_change
    page.on_view_pop = view_pop
    
    page.go(page.route)

if __name__ == "__main__":
    ft.app(target=main)
