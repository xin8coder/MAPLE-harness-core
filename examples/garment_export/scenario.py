"""Fictitious export packing operation with explicit public business rules."""

INITIAL_REQUEST = """我们是一家做服装外贸的小公司，明天有六批货要验货、贴标、打包，再送到港口仓。订单、三个打包班组和两个仓区都在 Excel 里。麻烦安排一下每单由哪个班组做、先做哪单、放哪个仓区。不要拆单，也不要超出仓区容量或让工人无限加班。

我想同时看看省钱和赶得上截单的方案，不要先把两个目标硬合成一个分数。费用按表里的人工、仓储和短驳报价算，延误按迟了多久、影响多少箱算。注意表里的工资是每个人的时薪，不是整个班组的；比如甲组三个人各做一小时，人工费就是66元。换单准备也要付整组人的工资，加班只对超过8小时的部分按1.5倍付。

请先用遗传算法小规模试排，给我一组可以选择的方案。每个方案都要看得到订单开始和完成时间、班组工时、仓区占用、总成本和逾期情况。时间统一写成从早上8点开工以后过了几个小时，别把时钟时间和时长混在一起。数据都是模拟业务数据。"""

UPDATE_REQUEST = """客户刚通知，之前那批英国的衬衫，也就是 UK-204，港口截单改到中午十二点半，比原来提前两个小时。另外乙组明天有一名工人请假，从四人变成三人，其余条件和报价不变。请在刚才的安排上重新排一下，仍然同时比较成本和逾期。把新一轮的方案保留下来，我想和第一轮分别看。"""

TABLES = {
    "orders": [
        {"id": "DE-101", "customer": "德国客户A", "product": "针织T恤", "cartons": 60, "minutes_per_carton": 6, "due_hour": 4.0},
        {"id": "UK-204", "customer": "英国客户B", "product": "衬衫", "cartons": 80, "minutes_per_carton": 8, "due_hour": 6.5},
        {"id": "FR-308", "customer": "法国客户C", "product": "运动上衣", "cartons": 50, "minutes_per_carton": 7, "due_hour": 5.0},
        {"id": "NL-410", "customer": "荷兰客户D", "product": "童装", "cartons": 45, "minutes_per_carton": 9, "due_hour": 7.0},
        {"id": "US-512", "customer": "美国客户E", "product": "卫衣", "cartons": 65, "minutes_per_carton": 7, "due_hour": 8.0},
        {"id": "AU-616", "customer": "澳大利亚客户F", "product": "休闲裤", "cartons": 55, "minutes_per_carton": 8, "due_hour": 7.5},
    ],
    "teams": [
        {"id": "A", "name": "甲组", "workers": 3, "efficiency": 1.0, "wage_cny_hour": 22, "regular_hours": 8, "max_hours": 10},
        {"id": "B", "name": "乙组", "workers": 4, "efficiency": 1.25, "wage_cny_hour": 32, "regular_hours": 8, "max_hours": 10},
        {"id": "C", "name": "丙组", "workers": 2, "efficiency": 0.95, "wage_cny_hour": 24, "regular_hours": 8, "max_hours": 10},
    ],
    "warehouses": [
        {"id": "W1", "name": "普通仓区", "capacity": 180, "storage_cny_carton": 0.8, "shipping_cny_carton": 1.2, "transfer_hours": 1.5},
        {"id": "W2", "name": "近港快速仓区", "capacity": 220, "storage_cny_carton": 1.8, "shipping_cny_carton": 2.5, "transfer_hours": 0.35},
    ],
    "policy": [{"start_time": "08:00", "setup_hours_per_order": 0.25, "overtime_multiplier": 1.5}],
    "rules": [
        {"item": "时间与工序", "description": "从明天08:00起按小时计时，due_hour是港口截单时刻。所有订单08:00均已到齐。每单只能交给一个完整班组，不拆单、不并行加工；同一班组按分配的顺序连续作业，班组间可并行。"},
        {"item": "加工用时", "description": "每单换单准备需要0.25小时，再按箱数乘每箱人工分钟、除以班组人数和效率、再换成小时，得到打包时间。准备也占用整组人员。"},
        {"item": "人工费用", "description": "临时打包班组按实际作业工时计费，不为未作业的闲置时间付费。每人前8小时按表中时薪，超过8小时的部分按1.5倍时薪。整组最多工作10小时。人工费包含换单准备时间。"},
        {"item": "仓储安排", "description": "每单只能占用一个仓区。本日计划为每单一次性预留箱位，所有分配到该仓区的订单箱数合计不能超容量，不考虑日内箱位周转。仓储费和短驳费都按箱数一次计费。"},
        {"item": "逾期统计", "description": "订单打包完成后，加上所选仓区的短驳小时数，得到到达港口仓的时刻。晚于截单的小时数乘该单箱数，再对所有订单相加，作为逾期箱小时；提前的不扣分。逾期允许存在，作为第二个目标。"},
        {"item": "两个目标", "description": "总成本是各班组人工费加各订单仓储费和短驳费，单位人民币元，越少越好。另一个目标是逾期箱小时，越少越好。不要加权合并这两个目标，不将逾期额外计入总成本。"},
        {"item": "输出", "description": "方案中列出每单的班组、仓区、开始时刻、打包完成时刻、到港时刻、逾期小时、箱数；各班组人数、总工时和加班工时；各仓区容量和占用；人工、仓储、短驳成本。"},
    ],
}


def natural_language_data() -> str:
    lines = ["下面这些口述数据与 Excel 完全相同。时间都从早上8点算起。"]
    for row in TABLES["orders"]:
        lines.append(f"{row['id']}，{row['customer']}，{row['product']}，{row['cartons']}箱，每箱需{row['minutes_per_carton']}人工分钟，开工后{row['due_hour']}小时截单。")
    for row in TABLES["teams"]:
        lines.append(f"{row['name']}（{row['id']}）：{row['workers']}人，效率{row['efficiency']}，每人每小时{row['wage_cny_hour']}元，正常8小时，最多10小时。")
    for row in TABLES["warehouses"]:
        lines.append(f"{row['name']}（{row['id']}）：{row['capacity']}箱位，每箱仓储{row['storage_cny_carton']}元、短驳{row['shipping_cny_carton']}元，短驳{row['transfer_hours']}小时。")
    lines.extend(row["description"] for row in TABLES["rules"])
    return "\n".join(lines)
