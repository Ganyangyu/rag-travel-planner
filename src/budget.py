"""One ledger for conditional group and per-person travel cost estimates."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _amount(value, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name}必须是非负金额")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f"{name}必须是非负金额") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name}必须是非负金额")
    return number


def _count(value, name: str) -> int:
    number = _amount(value, name)
    if number < 1 or number != number.to_integral_value():
        raise ValueError(f"{name}必须是正整数")
    return int(number)


def _money(number: Decimal) -> str:
    return format(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def calculate_budget(profile: dict, budget: dict) -> dict:
    """Convert each price basis to group spend before dividing by group size.

    Rates are explicit planning assumptions, not verified current prices. Unknown
    group size is evaluated as a clearly labelled one-person, single-room case.
    """
    people_known = budget.get("people") is not None
    people = _count(budget["people"], "人数") if people_known else 1
    rooms_known = budget.get("rooms") is not None
    rooms = _count(budget["rooms"], "房间数") if rooms_known else people
    days = _count(profile["days"], "天数")
    nights = days - 1
    limit = _amount(profile["budget"], "全程人均预算") * people
    assumptions = []
    if not people_known:
        assumptions.append("人数尚未提供，以下仅测算 N=1 的条件情景，不代表实际出行人数；人群标签不用于推断人数。")
    if not rooms_known:
        assumptions.append(f"房型与房间数未确认，暂按 {people} 人、{rooms} 间单人入住的房间测算；合住后须按实际房间数重算。")
    assumptions.append("房价、餐饮、门票与交通单价均为测算假设，并非已核实成交价；不计入未经证实的年龄优惠。")

    room_rate = _amount(budget["room_rate"], "每房每晚房价")
    meal_rate = _amount(budget["meals_per_person_day"], "每日人均餐费")
    tickets = _amount(budget["tickets_per_person"], "全程人均门票")
    reserve = _amount(budget["reserve_per_person"], "全程人均预留")
    transport = budget["transport"]
    transport_price = _amount(transport["unit_price"], "交通单价")
    quantity = _amount(transport["quantity"], "交通次数")
    if quantity != quantity.to_integral_value():
        raise ValueError("交通次数必须是非负整数")
    if transport["basis"] == "vehicle":
        vehicles = _count(transport["vehicles"], "车辆数") if transport.get("vehicles") is not None else 1
        transport_total = transport_price * quantity * vehicles
        transport_formula = f"{_money(transport_price)}元/车次 × {int(quantity)}次 × {vehicles}辆"
        if transport.get("vehicles") is None:
            assumptions.append("车辆数未知，暂按 1 辆测算；须核实人数、载客量及实际用车次数后重算。")
    elif transport["basis"] == "person":
        transport_total = transport_price * quantity * people
        transport_formula = f"{_money(transport_price)}元/人次 × {int(quantity)}次 × {people}人"
    else:
        raise ValueError("交通计价口径必须为 person 或 vehicle")

    values = [
        ("住宿", room_rate * rooms * nights, f"{_money(room_rate)}元/房/晚 × {rooms}间 × {nights}晚"),
        ("餐饮", meal_rate * people * days, f"{_money(meal_rate)}元/人/天 × {people}人 × {days}天"),
        ("门票", tickets * people, f"{_money(tickets)}元/人（全程） × {people}人"),
        ("市内交通", transport_total, transport_formula),
        ("预留金额", reserve * people, f"{_money(reserve)}元/人（全程） × {people}人"),
    ]
    rows = [dict(category=name, team=total, person=total / people, formula=formula)
            for name, total, formula in values]
    team_spend = sum((row["team"] for row in rows[:-1]), Decimal(0))
    plan_total = team_spend + rows[-1]["team"]
    return {
        "people": people, "people_known": people_known, "rooms": rooms, "nights": nights,
        "rows": rows, "assumptions": assumptions, "team_spend": team_spend,
        "per_person_spend": team_spend / people, "plan_total": plan_total,
        "plan_per_person": plan_total / people, "limit": limit,
        "difference": limit - plan_total,
    }


def summary_budget(ledger: dict) -> str:
    difference = ledger["difference"]
    state = (f"预计超预算 {_money(-difference / ledger['people'])} 元/人"
             if difference < 0 else f"预计剩余 {_money(difference / ledger['people'])} 元/人")
    return (f"按当前估算，预计人均支出 {_money(ledger['per_person_spend'])} 元，"
            f"含预留计划 {_money(ledger['plan_per_person'])} 元/人，{state}。"
            + ("此结论仅适用于下述单人单间条件情景。" if not ledger["people_known"] else ""))


def render_budget(ledger: dict) -> str:
    lines = [*ledger["assumptions"], "",
             "| 项目 | 计价假设与换算 | 团队金额（元） | 折算人均（元） |",
             "|---|---|---:|---:|"]
    lines.extend(f"| {r['category']} | {r['formula']} | {_money(r['team'])} | {_money(r['person'])} |"
                 for r in ledger["rows"])
    lines.extend([
        f"| 预计支出（不含预留） | 按实际计价口径合计 | {_money(ledger['team_spend'])} | {_money(ledger['per_person_spend'])} |",
        f"| 含预留的计划总额 | 支出加预留，预留不重复计入支出 | {_money(ledger['plan_total'])} | {_money(ledger['plan_per_person'])} |",
        f"| 预算上限 | 人均预算 × {ledger['people']}人 | {_money(ledger['limit'])} | {_money(ledger['limit'] / ledger['people'])} |",
        f"| 与上限差额 | 正数为结余，负数为超支 | {_money(ledger['difference'])} | {_money(ledger['difference'] / ledger['people'])} |",
        "", summary_budget(ledger),
        "日均预算仅展示消费水平，不限制单日开销。跨城往返交通、机场或车站往返接驳均未计入；普通市内游览交通已计入。如需接驳，须另增实际费用后重算。",
    ])
    if ledger["difference"] < 0:
        largest = max(ledger["rows"][:-1], key=lambda row: row["team"])
        lines.append(f"优先调整占比最大的{largest['category']}（团队 {_money(largest['team'])} 元）；再核实房价、实际合住安排和接驳方式，重新计算后再确认预订。")
    else:
        lines.append("实际房价、合住安排、车辆与接驳方式改变后，须用实际计价口径重算，不能沿用此估算结论。")
    return "\n".join(lines)
