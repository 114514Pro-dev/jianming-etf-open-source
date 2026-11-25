"""Local EMTL read-only pilot; syncs only coarse status to the site."""
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import version
import re


SYNC_BASE = 'https://8.210.39.161/api/d0-control/sync/'


class SyncFailed(Exception):
    pass


def send_sync(action, value, session_factory=None):
    """Do not forward any broker data, cookies, or passwords to the website."""
    try:
        if session_factory is None:
            from requests import Session
            session_factory = Session
        if action == 'claim' and isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{32}', value):
            payload = {'code': value}
        elif action == 'report' and value[1] in ('verified', 'failed') and re.fullmatch(r'[A-Za-z0-9_-]{32}', value[0]):
            payload = {'sync_token': value[0], 'state': value[1]}
        else:
            raise ValueError
        with session_factory() as session:
            session.trust_env = False
            response = session.post(SYNC_BASE + action, json=payload, timeout=(5, 8), allow_redirects=False)
            if response.status_code != 200:
                raise ValueError
            result = response.json()
            if action == 'claim':
                token = result['sync_token']
                if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', token):
                    raise ValueError
                return token
            if result.get('ok') is not True:
                raise ValueError
    except Exception:
        raise SyncFailed('无法同步：请核对网络，或在网站生成新的配对码。') from None


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
    ttk.Label(panel, text='只登录及查询，不提交或撤销委托。\n只向网站同步核对状态，不发送凭据或账户数据。').pack(anchor='w', pady=(0, 12))
    ttk.Label(panel, text='网站生成的一次性配对码').pack(anchor='w')
    code = ttk.Entry(panel, width=36)
    code.pack(fill='x', pady=(2, 4))
    link_label = tk.StringVar(value='尚未连接网站。')
    ttk.Label(panel, textvariable=link_label, wraplength=365).pack(anchor='w', pady=(0, 8))
    ttk.Label(panel, text='证券资金账号').pack(anchor='w')
    account = ttk.Entry(panel, width=36)
    account.pack(fill='x', pady=(2, 8))
    ttk.Label(panel, text='证券交易密码').pack(anchor='w')
    password = ttk.Entry(panel, width=36, show='•')
    password.pack(fill='x', pady=(2, 12))
    result = tk.StringVar(value='尚未开始验收。')
    ttk.Label(panel, textvariable=result, wraplength=365, justify='left').pack(anchor='w', pady=(0, 12))
    messages = queue.Queue()
    sync_token = None

    def collect():
        nonlocal sync_token
        try:
            kind, token, message, sync_result = messages.get_nowait()
        except queue.Empty:
            root.after(100, collect)
            return
        sync_token = token
        if kind == 'pair':
            link_label.set(message)
        else:
            result.set(message)
            if sync_result:
                link_label.set(sync_result)
        for button in (pair, submit):
            button.state(['!disabled'])

    def start_pair():
        entered = code.get().strip()
        code.delete(0, tk.END)
        for button in (pair, submit):
            button.state(['disabled'])
        link_label.set('正在与网站配对…')

        def worker():
            try:
                token = send_sync('claim', entered)
                messages.put(('pair', token, '网站已确认连接。完成只读核对后会同步一次状态。', None))
            except SyncFailed as error:
                messages.put(('pair', None, str(error), None))

        threading.Thread(target=worker, daemon=True).start()
        root.after(100, collect)

    def start():
        for button in (pair, submit):
            button.state(['disabled'])
        result.set('正在直连东方财富进行只读核对…')
        username, supplied = account.get().strip(), password.get()
        token = sync_token
        password.delete(0, tk.END)

        def worker():
            try:
                value = check_account(username, supplied)
                state = 'verified'
                message = (f'只读核对成功 · 账户尾号 {value.account_tail}\n'
                           f'可用资金 ¥{value.available_cash:,.2f}；持仓 {value.position_count} 项；'
                           f'当日委托 {value.open_and_closed_order_count} 条。\n'
                           '已断开连接。请与券商官方客户端核对；这不表示下单已验证。')
            except CheckError as error:
                state = 'failed'
                message = str(error)
            link_result = '未连接网站，核对结果仅显示在本机。'
            if token:
                try:
                    send_sync('report', (token, state))
                    link_result = '状态已同步。如需再次同步，请生成新配对码。'
                except SyncFailed as error:
                    link_result = str(error)
            messages.put(('check', None, message, link_result))

        threading.Thread(target=worker, daemon=True).start()
        root.after(100, collect)

    controls = ttk.Frame(panel)
    controls.pack(fill='x')
    pair = ttk.Button(controls, text='连接网站', command=start_pair)
    pair.pack(side='left', padx=(0, 8))
    submit = ttk.Button(controls, text='登录并只读核对', command=start)
    submit.pack(side='left')
    code.focus_set()
    root.mainloop()


if __name__ == '__main__':
    main()
