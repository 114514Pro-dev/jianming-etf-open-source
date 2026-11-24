"""Small, independent display and form helpers; no account side effects."""
import math
import re
from datetime import date

def sort_value(value):
    """Sort formatted money/percent numerically; missing values remain last."""
    text=str(value).strip()
    if text in ('','—','-','不足一年','不适用'):return None
    cleaned=text.replace(',','').replace('−','-').replace('元','').replace('份','').replace('%','')
    try:
        number=float(cleaned)
        if math.isfinite(number):return (0,number)
    except ValueError:pass
    return (1,text.casefold())

def account_input(name,amount,day,earliest,dates):
    name=name.strip();day=day.strip()
    if not name or len(name)>40:raise ValueError('账户名称为1至40字，请保留一个便于识别的名称。')
    try:capital=float(amount)
    except (ValueError,TypeError):raise ValueError('本金请填写数字，例如100000。') from None
    if not math.isfinite(capital) or not 1000<=capital<=1e9:raise ValueError('模拟本金须为1000至10亿元之间的有效数字。')
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError
        date.fromisoformat(day)
    except ValueError:raise ValueError('日期请按YYYY-MM-DD填写，例如2026-09-16。') from None
    if day<earliest:raise ValueError('这个策略最早支持 '+earliest+'，请调整起始日期或选择D/F系列。')
    if day not in dates:raise ValueError('起始日期须为已保存的交易日；可点击“日期设为最新收盘日”。')
    return name,capital,day
