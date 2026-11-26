"""Turn trip constraints into calendar context and focused search queries."""

from datetime import date, timedelta

from chinese_calendar import get_holiday_detail, is_workday

HOLIDAYS = {
    "New Year's Day": "元旦", "Spring Festival": "春节", "Tomb-sweeping Day": "清明节",
    "Labour Day": "劳动节", "Dragon Boat Festival": "端午节",
    "Mid-autumn Festival": "中秋节", "National Day": "国庆节",
}

def trip_profile(city: str, start: str, days: int, budget: float, audience: str) -> dict:
    first = date.fromisoformat(start)
    dates = [first + timedelta(days=i) for i in range(days)]
    seasons = list(dict.fromkeys(
        "春季" if 3 <= d.month <= 5 else "夏季" if 6 <= d.month <= 8
        else "秋季" if 9 <= d.month <= 11 else "冬季" for d in dates
    ))
    holidays, rest_days, known = set(), 0, True
    for d in dates:
        try:
            holiday, name = get_holiday_detail(d)
            if holiday and name:
                holidays.add(HOLIDAYS.get(name, name))
            rest_days += not is_workday(d)
        except NotImplementedError:
            known = False
    calendar = "、".join(sorted(holidays)) or "未遇法定节假日"
    if not known:
        calendar = "该年份调休安排未收录，节假日待确认"
    daily = budget / days
    level = "经济型" if daily < 300 else "舒适型" if daily < 700 else "品质型"
    season = "、".join(seasons)
    preferences = {
        "个人": "公共交通 独自旅行",
        "情侣": "情侣 浪漫 夜景",
        "亲子家庭": "亲子 少走路 儿童",
        "老年人": "长辈 轻松 无障碍",
    }.get(audience, audience)
    queries = [
        f"{city} {days}天 {season} {audience} 旅游攻略 site:xiaohongshu.com",
        f"{city} {days}日游 人均{budget:g}元 {level} {preferences} 路线攻略",
        f"{city} {first.year}年{first.month}月 {calendar if holidays else season} 景点 开放 预约 文旅",
    ]
    return {
        "city": city, "start": start, "end": dates[-1].isoformat(), "days": days,
        "budget": budget, "daily_budget": daily, "audience": audience,
        "season": season, "calendar": calendar, "rest_days": rest_days if known else None,
        "level": level, "queries": queries,
    }


def describe(profile: dict) -> str:
    rest = f"休息日{profile['rest_days']}天" if profile['rest_days'] is not None else "休息日待确认"
    return (
        f"{profile['city']}｜{profile['start']} 至 {profile['end']}｜{profile['days']}天｜"
        f"{profile['season']}｜{profile['calendar']}（{rest}）｜{profile['audience']}｜"
        f"总预算{profile['budget']:g}元/人，日均{profile['daily_budget']:.0f}元/人（{profile['level']}）"
    )
