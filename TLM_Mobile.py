import numpy as np


def simple_tlm_analysis():
    print("=== TLM ===\n")

    # 默认间距
    default_spacings = [2,3,5,7,9,11,17]

    # 选择是否使用默认间距
    use_default = input("是否使用默认间距 (2,3,5,7,9,11,17 um)? (y/n, 默认y): ").strip().lower()
    use_default = use_default != 'n'

    # 输入参数
    width = float(input("请输入宽度 W (um，默认100): ") or 100)

    data = []

    if use_default:
        print(f"\n使用默认间距: {default_spacings} um")
        print("请输入对应的电流值 (5V电压下，电流单位: mA)")

        for spacing in default_spacings:
            current = input(f"间距 {spacing} um 对应的电流 (mA): ").strip()
            if current:
                try:
                    data.append((spacing, float(current)))
                except:
                    print("输入错误，跳过此数据点")
    else:
        print("\n请输入间距和对应的电流值 (5V电压下，电流单位: mA)")
        print("格式: 间距(um) 电流(mA)，每行一组，输入空行结束")

        while True:
            line = input("> ").strip()
            if not line:
                break
            try:
                d, i = map(float, line.split())
                data.append((d, i))
            except:
                print("输入格式错误，请重新输入")

    if len(data) < 2:
        print("错误：至少需要2组数据")
        return

    # 提取数据
    spacings = np.array([d for d, i in data])
    currents_mA = np.array([i for d, i in data])

    # 将电流从mA转换为A
    currents_A = currents_mA / 1000.0

    # 计算总电阻 (1V电压下)
    total_resistance = 5.0 / currents_A

    # 线性拟合
    slope, intercept = np.polyfit(spacings, total_resistance, 1)

    # 计算参数
    Rc = intercept / 2  # 接触电阻 (Ω)
    Rsheet = slope * width  # 薄层电阻 (Ω/□)
    LT = Rc * width / Rsheet  # 传输长度 (μm)
    rho_c = Rc * LT * width * 1e4  # 特定接触电阻率 (Ω·cm²)

    # 归一化接触电阻 (mΩ·mm)
    Rc_normalized = Rc * width / 1000  # Ω·μm = mΩ·mm

    # 计算R²
    fitted_resistance = slope * spacings + intercept
    ss_res = np.sum((total_resistance - fitted_resistance) ** 2)
    ss_tot = np.sum((total_resistance - np.mean(total_resistance)) ** 2)
    r_squared = 1 - (ss_res / ss_tot)

    # 显示结果
    print("\n=== TLM分析结果 ===")
    print(f"接触电阻 Rc: {Rc_normalized:.2f} Ω·mm")
    print(f"薄层电阻 Rsheet: {Rsheet:.2f} Ω/□")
    print(f"传输长度 LT: {LT:.2f} μm")
    print(f"特定接触电阻率 ρc: {rho_c:.2e} Ω·cm²")
    print(f"拟合优度 R²: {r_squared:.6f}")
    print(f"拟合方程: R_total = {slope:.4e} × d + {intercept:.4e}")

    # 显示输入数据
    print("\n=== 输入数据 ===")
    print("间距(um)\t电流(mA)\t电阻(Ω)")
    for d, i in data:
        r = 5.0 / (i / 1000.0)
        print(f"{d}\t\t{i}\t\t{r:.2f}")


if __name__ == "__main__":
    simple_tlm_analysis()