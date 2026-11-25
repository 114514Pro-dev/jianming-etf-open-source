"""Local EMTL read-only pilot; syncs only coarse status to the site."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from importlib.metadata import version
import re
import time


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
                tokens = (result['sync_token'], result['signal_token'])
                if not all(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{32}', token) for token in tokens):
                    raise ValueError
                return tokens
            if result.get('ok') is not True:
                raise ValueError
    except Exception:
        raise SyncFailed('无法同步：请核对网络，或在网站生成新的配对码。') from None


TARGET_SYMBOLS = ('SZSE.159915', 'SHSE.512800', 'SHSE.518880', 'SHSE.511010')


def describe_target(target):
    if (not isinstance(target, dict) or target.get('schema') != 'jianming-etf.confirmed-target.v1'
            or target.get('strategy') != 'D0' or not isinstance(target.get('signal_id'), str)):
        raise ValueError
    confirmed = date.fromisoformat(target['confirmed_day'])
    execution = date.fromisoformat(target['execution_day'])
    start = datetime.fromisoformat(target['eligible_at'])
    if start.utcoffset() is None or start.date() != execution or execution <= confirmed:
        raise ValueError
    weights = target['targets']
    if not isinstance(weights, dict) or set(weights) != set(TARGET_SYMBOLS):
        raise ValueError
    values = [quantity(weights[s]) for s in TARGET_SYMBOLS]
    cash = quantity(target['cash_weight'])
    if any(value > 1 for value in values + [cash]) or abs(sum(values) + cash - 1) > Decimal('0.000001'):
        raise ValueError
    detail = ' · '.join(f'{symbol[5:]} {weight:.1%}' for symbol, weight in zip(TARGET_SYMBOLS, values))
    return f'D0 {confirmed}，最早执行 {start:%Y-%m-%d %H:%M %z}\n{detail} · 现金 {cash:.1%}'


def listen_signals(token, stop, emit, session_factory=None):
    """Wait for target-only responses. Contains no order-generation or dealer calls."""
    if session_factory is None:
        from requests import Session
        session_factory = Session
    after = ''
    with session_factory() as session:
        session.trust_env = False
        while not stop.is_set():
            try:
                session.cookies.clear()
                res = session.get(SYNC_BASE + 'signal', headers={'Authorization': 'Bearer ' + token},
                                  params={'after': after}, timeout=(5, 15), allow_redirects=False)
                received = round(time.time() * 1000)
                if res.status_code in (401, 403):
                    emit('信号订阅已结束。请在网站重新生成配对码。')
                    return
                if res.status_code != 200:
                    raise ValueError
                data = res.json()
                cursor = data['cursor']
                if not re.fullmatch(r'[a-f0-9]{16}', cursor):
                    raise ValueError
                if data.get('unchanged') is True:
                    if not after or cursor != after:
                        raise ValueError
                    continue
                if cursor == after:
                    raise ValueError
                if data['signal'] is None:
                    emit('信号通道已连接，等待新的已确认 D0 信号。')
                else:
                    text = describe_target(data['signal'])
                    age = received - data['published_at_ms']
                    timing = f'距网站发布时间约 {age} 毫秒（含等待及两端时钟误差）' if age >= 0 else '两端时钟不同步，无法估算到达时间'
                    emit(f'已收到 D0 目标 · {timing}\n{text}\n仅收信号，不产生真实委托。')
                after = cursor
            except Exception:
                if not stop.is_set():
                    emit('信号通道暂不可用，等待重连；不会下单。')
                stop.wait(1)


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
    signal_updates = queue.Queue()
    signal_status = tk.StringVar(value='请先配对。')
    ttk.Label(panel, textvariable=signal_status, wraplength=365, justify='left').pack(anchor='w', pady=(0, 12))
    sync_token = None
    signal_stop = threading.Event()

    def collect_signals():
        try:
            while True:
                source, message = signal_updates.get_nowait()
                if source is signal_stop and not source.is_set():
                    signal_status.set(message)
        except queue.Empty:
            root.after(100, collect_signals)

    def start_signals(token):
        nonlocal signal_stop
        signal_stop.set()
        signal_stop = stop = threading.Event()
        signal_status.set('已配对，正在等待网站信号…')
        threading.Thread(target=listen_signals,
                         args=(token, stop, lambda message: signal_updates.put((stop, message))), daemon=True).start()

    def collect():
        nonlocal sync_token
        try:
            kind, token, message, sync_result = messages.get_nowait()
        except queue.Empty:
            root.after(100, collect)
            return
        if kind == 'pair':
            link_label.set(message)
            if token:
                sync_token, feed_token = token
                start_signals(feed_token)
            else:
                sync_token = None
        else:
            sync_token = None
            result.set(message)
            if sync_result:
                link_label.set(sync_result)
        for button in (pair, submit):
            button.state(['!disabled'])

    def start_pair():
        entered = code.get().strip()
        signal_stop.set()
        signal_status.set('等待新配对。')
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
    root.after(100, collect_signals)

    def close():
        signal_stop.set()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', close)
    root.mainloop()


if __name__ == '__main__':
    main()
