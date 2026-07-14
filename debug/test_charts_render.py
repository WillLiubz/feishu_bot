"""手工验证：用构造数据生成 PNG + xlsx，人工打开检查中文与图表效果。

运行：python debug/test_charts_render.py
产物：debug/output_charts/ 下的 query_N.png 与 result.xlsx
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import charts
import dquery

OUT = Path(__file__).parent / "output_charts"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    datasets = {
        1: (  # 折线：日期 + 数值
            [{"日期": f"202607{d:02d}", "收入(美元)": str(d * 120.5), "付费人数": str(d * 3)}
             for d in range(1, 11)],
            "SELECT ds, money FROM raw_scribe_log.pay",
            "7 月上旬收入总体平稳，7 月 10 日达到峰值 1205 美元。",
        ),
        2: (  # 饼图：少类别 + 单数值
            [{"渠道": n, "充值金额": v} for n, v in
             [("AppStore", "5200"), ("GooglePlay", "3100"), ("官网", "1800"), ("其他", "600")]],
            "SELECT channel, money FROM gamelog_raw.v_presto_log_payrecharge",
            "AppStore 渠道贡献最大，占比约 48.6%。",
        ),
        3: (  # 柱状：多类别
            [{"道具": f"道具{i}", "获得数量": str(100 - i * 7)} for i in range(1, 13)],
            "SELECT item_name, cnt FROM gameeco_raw.v_presto_log_roleitem",
            "道具1 获得数量最高，长尾道具获取量较低。",
        ),
    }

    conclusions = []
    for i, (rows, sql, conclusion) in datasets.items():
        dquery.write_csv_to(rows, OUT / f"query_{i}.csv")
        (OUT / f"query_{i}.sql").write_text(sql, encoding="utf-8")
        conclusions.append(conclusion)

    pngs = charts.render_pngs_for_dir(str(OUT))
    print(f"生成 PNG: {pngs}")

    xlsx = dquery.combine_to_excel(
        str(OUT), conclusions=conclusions,
        final_summary="三个维度的分析显示：收入平稳、AppStore 为主要渠道、道具获取呈长尾分布。"
    )
    print(f"生成 xlsx: {xlsx}")
    print("请人工打开检查：中文显示、图表类型、结论位置。")


if __name__ == "__main__":
    main()
