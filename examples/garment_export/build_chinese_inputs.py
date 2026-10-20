"""A Chinese-only workbook with exactly the same public numerical business data."""
from pathlib import Path

from build_inputs import build_inputs
from scenario import TABLES


SCHEMA = {
    "orders": ("外贸订单", {"id": "订单编号", "customer": "客户", "product": "品名", "cartons": "箱数",
                            "minutes_per_carton": "每箱人工分钟", "due_hour": "截单时刻（开工后小时）"}),
    "teams": ("打包班组", {"id": "班组编号", "name": "班组名称", "workers": "人数", "efficiency": "效率系数",
                          "wage_cny_hour": "每人时薪（元）", "regular_hours": "正常工时（小时）", "max_hours": "最多工时（小时）"}),
    "warehouses": ("仓区安排", {"id": "仓区编号", "name": "仓区名称", "capacity": "容量（箱）",
                               "storage_cny_carton": "每箱仓储费（元）", "shipping_cny_carton": "每箱短驳费（元）",
                               "transfer_hours": "短驳用时（小时）"}),
    "policy": ("作业参数", {"start_time": "开工时刻", "setup_hours_per_order": "每单准备时间（小时）",
                          "overtime_multiplier": "加班工资倍数"}),
    "rules": ("业务规则", {"item": "事项", "description": "说明"}),
}
VALUES = {
    "DE-101": "德国一号", "UK-204": "英国二号", "FR-308": "法国三号", "NL-410": "荷兰四号",
    "US-512": "美国五号", "AU-616": "澳洲六号", "A": "甲组", "B": "乙组", "C": "丙组",
    "W1": "普通仓区", "W2": "近港快速仓区", "针织T恤": "针织短袖上衣",
    **{row["customer"]: row["customer"][:-1] for row in TABLES["orders"]},
}
INITIAL = """我们是一家服装外贸小公司，明天有六批货要打包出港，订单、班组和仓区都在附件里。
帮我排一下哪个班组做哪单、先做什么，再安排放哪个仓区。我想省点钱，也不想耽误客户截单，给我几种方案选。不能拆单、超仓区容量，也别让工人无限加班，具体规则按表里写的来。
先看看数据，帮我确认一下怎么安排、可以怎么求解，先不要开始算。"""
CONFIRM = """用遗传算法先小规模试排吧，六十个候选，最多四十代。费用和逾期分开看，不要合成一个分数。工资是每个人的时薪，准备时间也要付整组的工资。其他按表里的规则，开始吧。"""
UPDATE = """客户刚通知，英国那批衬衫的截单改到中午十二点半，比原来提前两个小时。另外乙组有一个人请假，只剩三个人，其余条件和报价不变。
在刚才的任务上重新排一下，还是同时看费用和逾期，计算规模也不变。新旧方案都保留下来，方便我比较。"""


def chinese_tables():
    result = {}
    for table, rows in TABLES.items():
        name, columns = SCHEMA[table]
        result[name] = []
        for row in rows:
            translated = {}
            for key, value in row.items():
                if isinstance(value, str):
                    value = VALUES.get(value, value).replace("due_hour", "截单时刻（开工后小时）")
                translated[columns[key]] = value
            result[name].append(translated)
    return result


if __name__ == "__main__":
    print(build_inputs(Path(__file__).parent / "inputs" / "chinese", tables=chinese_tables(),
                       filename="服装外贸排产数据.xlsx", texts=[
                           ("初始需求.txt", INITIAL), ("确认求解.txt", CONFIRM), ("更新需求.txt", UPDATE)]))
