"""Local EMTL compatibility pilot. This module has no trading or web endpoint."""
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import version
import re


class CheckError(Exception):
    """A fixed, user-facing diagnosis; never embeds broker payloads."""


@dataclass(frozen=True)
class CheckResult:
    account_tail: str
    available_cash: Decimal
    position_count: int
    open_and_closed_order_count: int


def broker_factory(**kwargs):
    if version('emtl') != '0.3.1':
        raise RuntimeError('Unapproved EMTL version')
    from emtl import TradingClient
    from requests import Session

    def session():
        result = Session()
        result.trust_env = False
        return result

    return TradingClient(session_factory=session, connect_timeout=5, read_timeout=10,
                         captcha_read_timeout=8, captcha_max_attempts=2, **kwargs)


def rows(payload):
    if (not isinstance(payload, dict) or type(payload.get('Status')) is not int or payload['Status'] != 0
            or not isinstance(payload.get('Data'), list) or not all(isinstance(x, dict) for x in payload['Data'])):
        raise ValueError
    return payload['Data']


def quantity(value):
    if type(value) not in (str, int, float):
        raise ValueError
    number = Decimal(str(value))
    if not number.is_finite() or not 0 <= number <= Decimal('1000000000000'):
        raise ValueError
    return number


def check_account(username, password, factory=broker_factory):
    """Authenticate and check read-only response fields, then drop the session."""
    if not re.fullmatch(r'[0-9]{6,20}', username) or not password.strip() or len(password) > 128:
        raise CheckError('请填写证券资金账号及交易密码。')
    client = None
    stage = '无法初始化 EMTL，请核对应用依赖。'
    try:
        client = factory(username=username, password=password)
        stage = '券商登录未成功：请核对交易密码、账户权限、网络或验证码，不要连续重试。'
        if not client.login(duration=5):
            raise ValueError
        stage = '已收到登录确认，但未能读取或核实资金／持仓。不能据此开启下单。'
        assets = rows(client.query_asset_and_position())
        if len(assets) != 1 or not isinstance(assets[0].get('positions'), list):
            raise ValueError
        cash = quantity(assets[0]['Kyzj'])
        positions = assets[0]['positions']
        codes = set()
        for pos in positions:
            code = pos['Zqdm']
            if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code) or code in codes:
                raise ValueError
            codes.add(code)
            holding, sellable = quantity(pos['Zqsl']), quantity(pos['Kysl'])
            if sellable > holding or any(value != value.to_integral_value() for value in (holding, sellable)):
                raise ValueError
        stage = '已核实资金／持仓，但未能读取当日委托。不能据此开启下单。'
        orders = rows(client.query_orders())
        if len(orders) >= 100:
            raise ValueError
        return CheckResult(username[-4:], cash, len(positions), len(orders))
    except Exception:
        raise CheckError(stage) from None
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def main():
    import tkinter as tk
    from tkinter import ttk
    import queue
    import threading

    root = tk.Tk()
    root.title('简明 ETF · 东方财富本机只读验收')
    panel = ttk.Frame(root, padding=20)
    panel.pack(expand=True, fill='both')
    ttk.Label(panel, text='只登录及查询，不提交或撤销委托。\n凭据不保存，不发送给简明 ETF 网站。').pack(anchor='w', pady=(0, 12))
    ttk.Label(panel, text='证券资金账号').pack(anchor='w')
    account = ttk.Entry(panel, width=36)
    account.pack(fill='x', pady=(2, 8))
    ttk.Label(panel, text='证券交易密码').pack(anchor='w')
    password = ttk.Entry(panel, width=36, show='•')
    password.pack(fill='x', pady=(2, 12))
    result = tk.StringVar(value='尚未开始验收。')
    ttk.Label(panel, textvariable=result, wraplength=365, justify='left').pack(anchor='w', pady=(0, 12))
    messages = queue.Queue()

    def collect():
        try:
            message = messages.get_nowait()
        except queue.Empty:
            root.after(100, collect)
        else:
            result.set(message)
            submit.state(['!disabled'])

    def start():
        submit.state(['disabled'])
        result.set('正在直连东方财富进行只读核对…')
        username, supplied = account.get().strip(), password.get()
        password.delete(0, tk.END)

        def worker():
            try:
                value = check_account(username, supplied)
                message = (f'只读核对成功 · 账户尾号 {value.account_tail}\n'
                           f'可用资金 ¥{value.available_cash:,.2f}；持仓 {value.position_count} 项；'
                           f'当日委托 {value.open_and_closed_order_count} 条。\n'
                           '已断开连接。请与券商官方客户端核对；这不表示下单已验证。')
            except CheckError as error:
                message = str(error)
            messages.put(message)

        threading.Thread(target=worker, daemon=True).start()
        root.after(100, collect)

    submit = ttk.Button(panel, text='登录并只读核对', command=start)
    submit.pack(anchor='w')
    account.focus_set()
    root.mainloop()


if __name__ == '__main__':
    main()
