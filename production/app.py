"""A small native Windows desktop for strategy-driven paper trading."""
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading, queue, json, os, sys, traceback
from simulator_core import Service, VERSION, ORDER, TITLES, DESCRIPTIONS, RULE_NOTE, CODES, NAMES, ROOT
from live_ui import LiveUI, reference_values, reference_label
from top5_ui import Top5UI
from seven_ui import SevenUI
from strategy_labels import StrategyLabels
from ui_helpers import sort_value, account_input

BG='#101720';PANEL='#182330';LINE='#2b3949';FG='#eef3f8';MUTED='#99adc1';ACCENT='#60dcc2';RED='#ff8f9a';GOLD='#f5c875'
def money(v):return f'{v:,.2f}'
def percent(v):return f'{v:+.2%}'

class App(SevenUI,Top5UI,LiveUI,tk.Tk):
    def __init__(self):
        super().__init__();self.title(f'简明ETF模拟交易 v{VERSION} · 21策略与七组合模拟');self.configure(bg=BG)
        self.ui_scale=max(1,float(self.tk.call('tk','scaling'))/1.333333)
        w=min(self.px(1320),self.winfo_screenwidth()-self.px(80));h=min(self.px(860),self.winfo_screenheight()-self.px(90))
        self.geometry(f'{w}x{h}+40+40');self.minsize(min(self.px(1120),w),min(self.px(760),h))
        try:self.iconbitmap(str(ROOT/'app_icon.ico'))
        except tk.TclError:pass
        self.style();self.service=None;self.selected=None;self.busy=False;self.events=queue.Queue();self.stop=threading.Event();self.controls=[];self.result=None
        self.status=tk.StringVar(value='正在加载策略与本地行情…');self.account=tk.StringVar();self.strategy=tk.StringVar();self.data_label=tk.StringVar(value='本地模拟 · 无实盘下单')
        self.strategy_labels=StrategyLabels();self.ranking_note=tk.StringVar(value=self.strategy_labels.note)
        self.build();self.protocol('WM_DELETE_WINDOW',self.close);self.after(100,self.poll)
        self.work(lambda:Service(),self.loaded,'正在读取本地行情与账户…')
    def px(self,value):return round(value*self.ui_scale)
    def place_dialog(self,win,width,height):
        sw,sh=self.winfo_screenwidth(),self.winfo_screenheight()
        w=min(self.px(width),sw-self.px(40));h=min(self.px(height),sh-self.px(80))
        x=max(0,min(sw-w,self.winfo_rootx()+(self.winfo_width()-w)//2))
        y=max(0,min(sh-h-self.px(40),self.winfo_rooty()+(self.winfo_height()-h)//2))
        win.geometry(f'{w}x{h}+{x}+{y}')
    def style(self):
        s=ttk.Style(self);s.theme_use('clam')
        s.configure('.',font=('Microsoft YaHei UI',10),background=BG,foreground=FG)
        s.configure('TFrame',background=BG);s.configure('Card.TFrame',background=PANEL)
        s.configure('TLabel',background=BG,foreground=FG);s.configure('Muted.TLabel',foreground=MUTED)
        s.configure('Card.TLabel',background=PANEL);s.configure('Metric.TLabel',background=PANEL,font=('Microsoft YaHei UI',22,'bold'))
        s.configure('TButton',background=LINE,foreground=FG,padding=(14,8),borderwidth=0)
        s.map('TButton',background=[('active','#3b5269'),('disabled','#1b2733')],foreground=[('disabled','#657587')])
        s.configure('Accent.TButton',background=ACCENT,foreground='#102722',font=('Microsoft YaHei UI',10,'bold'))
        s.map('Accent.TButton',background=[('active','#8aebd6'),('disabled','#28463f')],foreground=[('disabled','#82a097')])
        s.configure('TEntry',fieldbackground=PANEL,foreground=FG,insertcolor=FG,padding=6,bordercolor=LINE)
        s.configure('TCombobox',fieldbackground=PANEL,background=LINE,foreground=FG,arrowcolor=FG,padding=6)
        s.map('TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',FG),('disabled','#657587')])
        self.option_add('*TCombobox*Listbox.background',PANEL);self.option_add('*TCombobox*Listbox.foreground',FG);self.option_add('*TCombobox*Listbox.selectBackground',LINE)
        s.configure('TNotebook',background=BG,borderwidth=0);s.configure('TNotebook.Tab',background=BG,foreground=MUTED,padding=(25,12))
        s.map('TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',ACCENT)])
        s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=FG,rowheight=self.px(35),borderwidth=0)
        s.configure('Treeview.Heading',background=LINE,foreground=MUTED,padding=(5,9),font=('Microsoft YaHei UI',9))
        s.map('Treeview',background=[('selected','#2d554f')]);s.configure('TSeparator',background=LINE)
    def button(self,parent,text,command,accent=False,**kw):
        b=ttk.Button(parent,text=text,command=command,style='Accent.TButton' if accent else 'TButton',**kw);self.controls.append((b,'normal'));return b
    def entry(self,parent,var,width=12):
        e=ttk.Entry(parent,textvariable=var,width=width);self.controls.append((e,'normal'));return e
    def combo(self,parent,var,values=(),width=30):
        e=ttk.Combobox(parent,textvariable=var,values=values,width=width,state='readonly');self.controls.append((e,'readonly'));return e
    def build(self):
        head=ttk.Frame(self,padding=(24,19,24,15));head.pack(fill='x')
        ttk.Label(head,text='简明 ETF',font=('Microsoft YaHei UI',23,'bold')).pack(side='left')
        ttk.Label(head,text='  模拟交易',foreground=MUTED,font=('Microsoft YaHei UI',14)).pack(side='left',padx=(0,22))
        self.accounts=self.combo(head,self.account,width=25);self.accounts.pack(side='left');self.accounts.bind('<<ComboboxSelected>>',lambda _:self.select_account())
        self.new_account_button=self.button(head,'＋ 新建四资产账户',self.new_account);self.new_account_button.pack(side='left',padx=8)
        self.button(head,'刷新行情',self.update_data).pack(side='right')
        ttk.Label(head,textvariable=self.data_label,style='Muted.TLabel').pack(side='right',padx=14)
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True,padx=24)
        self.live_page=ttk.Frame(self.tabs,padding=(0,16));self.dash=ttk.Frame(self.tabs,padding=(0,16));self.comparison=ttk.Frame(self.tabs,padding=(0,16));self.history=ttk.Frame(self.tabs,padding=(0,16))
        for frame,label in [(self.live_page,'当天行情'),(self.dash,'历史账户与建议'),(self.comparison,'策略对比'),(self.history,'交易记录')]:self.tabs.add(frame,text=label)
        self.build_live();self.build_dashboard();self.build_compare();self.build_history();self.build_top5();self.build_seven()
        foot=ttk.Frame(self,padding=(24,9,24,12));foot.pack(fill='x')
        ttk.Label(foot,textvariable=self.status,foreground=MUTED).pack(side='left')
        self.stop_button=ttk.Button(foot,text='停止模拟',command=self.stop.set);self.stop_button.pack(side='right');self.stop_button.state(['disabled'])
    def build_dashboard(self):
        bar=ttk.Frame(self.dash);bar.pack(fill='x',pady=(0,14))
        self.strategies=self.combo(bar,self.strategy,self.strategy_labels.values(),width=55);self.strategies.pack(side='left')
        self.button(bar,'更换后续策略',self.switch_strategy).pack(side='left',padx=8)
        self.button(bar,'策略说明',self.strategy_detail).pack(side='left')
        self.day_label=tk.StringVar();ttk.Label(bar,textvariable=self.day_label,foreground=ACCENT).pack(side='right')
        ttk.Label(self.dash,textvariable=self.ranking_note,foreground=MUTED,wraplength=self.px(1190),justify='left').pack(anchor='w',pady=(0,12))
        cards=ttk.Frame(self.dash);cards.pack(fill='x',pady=(0,15));self.stats=[]
        for i,label in enumerate(['账户总资产 / 元','累计收益','最大回撤','可用现金 / 元']):
            cards.columnconfigure(i,weight=1);f=ttk.Frame(cards,style='Card.TFrame',padding=(18,12));f.grid(row=0,column=i,sticky='nsew',padx=(0,12 if i<3 else 0))
            ttk.Label(f,text=label,style='Card.TLabel',foreground=MUTED).pack(anchor='w');var=tk.StringVar(value='—');self.stats.append(var)
            ttk.Label(f,textvariable=var,style='Metric.TLabel',foreground=ACCENT if i==1 else FG).pack(anchor='w',pady=(6,0))
        middle=ttk.Frame(self.dash);middle.pack(fill='both',expand=True);middle.columnconfigure(0,weight=5);middle.columnconfigure(1,weight=6);middle.rowconfigure(0,weight=1)
        left=ttk.Frame(middle,style='Card.TFrame',padding=16);left.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        ttk.Label(left,text='账户资产曲线',style='Card.TLabel',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        self.chart=tk.Canvas(left,bg=PANEL,highlightthickness=0,height=self.px(200));self.chart.pack(fill='both',expand=True,pady=(5,0));self.chart.bind('<Configure>',lambda _:self.draw_chart())
        self.chart_note=tk.StringVar();ttk.Label(left,textvariable=self.chart_note,style='Card.TLabel',foreground=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(6,0))
        right=ttk.Frame(middle,style='Card.TFrame',padding=16);right.grid(row=0,column=1,sticky='nsew')
        self.advice_title=tk.StringVar(value='正在分析…');ttk.Label(right,textvariable=self.advice_title,style='Card.TLabel',foreground=ACCENT,font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w')
        ttk.Label(right,text='按账户收盘日生成 · 下一可执行日开盘模拟',style='Card.TLabel',foreground=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(4,10))
        self.positions=self.table(right,[('asset','资产',145),('qty','持有份数',85),('target','目标仓位',85),('action','估算操作',145)],4)
        self.cash_target=tk.StringVar();ttk.Label(right,textvariable=self.cash_target,style='Card.TLabel',foreground=MUTED).pack(anchor='w',pady=(10,0))
        self.button(right,'查看完整依据与退出条件',self.show_plan).pack(anchor='w',pady=(12,0))
        reason=ttk.Frame(self.dash,style='Card.TFrame',padding=(16,11));reason.pack(fill='x',pady=(14,12))
        self.reason_text=tk.StringVar();ttk.Label(reason,textvariable=self.reason_text,style='Card.TLabel',wraplength=self.px(1180),justify='left',font=('Microsoft YaHei UI',10)).pack(fill='x',anchor='w')
        controls=ttk.Frame(self.dash);controls.pack(fill='x')
        self.next_button=self.button(controls,'按方案模拟下一日',self.next_day,True);self.next_button.pack(side='left')
        ttk.Label(controls,text='或模拟至',foreground=MUTED).pack(side='left',padx=(20,8));self.end=tk.StringVar();self.entry(controls,self.end).pack(side='left')
        self.run_button=self.button(controls,'连续模拟',self.run_until);self.run_button.pack(side='left',padx=8)
        self.button(controls,'导出账户与方案',self.export).pack(side='right')
        self.button(controls,'接续最新收盘日线',self.attach_daily).pack(side='right',padx=8)
        ttk.Label(self.dash,text='份数按当前收盘价估算，成交按次日开盘重新计算。策略建议用于模拟练习，不保证收益。',foreground=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(9,0))
    def table(self,parent,columns,height=10):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=[c[0] for c in columns],show='headings',height=height,selectmode='browse')
        for key,label,width in columns:tree.heading(key,text=label);tree.column(key,width=self.px(width),minwidth=self.px(55),anchor='w' if key in ['asset','name','reason','kind'] else 'e',stretch=True)
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        tree.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);scroll.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.grid(row=1,column=0,sticky='ew')
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        tree.sort_labels={key:label for key,label,_ in columns};tree.sort_column=None;tree.sort_reverse=False
        for key,label,_ in columns:tree.heading(key,command=lambda c=key,t=tree:self.sort_table(t,c))
        return tree
    def sort_table(self,tree,column):
        reverse=tree.sort_column==column and not tree.sort_reverse
        tree.sort_column=column;tree.sort_reverse=reverse
        valid=[];missing=[]
        for row in tree.get_children():
            value=sort_value(tree.set(row,column))
            (missing if value is None else valid).append((value,row))
        valid.sort(key=lambda item:item[0],reverse=reverse)
        for index,(_,row) in enumerate(valid+missing):tree.move(row,'',index)
        for key,label in tree.sort_labels.items():tree.heading(key,text=label+(' ↓' if reverse else ' ↑') if key==column else label)
    def build_compare(self):
        ttk.Label(self.comparison,text='从2013年开始，比较有历史依据的策略',font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w')
        ttk.Label(self.comparison,text='D / F系列支持2013起；银行2017年上市，L系列仅支持2017-08-03以后。未上市或指标不足的资产不参与。',foreground=MUTED).pack(anchor='w',pady=(7,20))
        bar=ttk.Frame(self.comparison);bar.pack(fill='x',pady=(0,18));self.compare_start=tk.StringVar();self.compare_end=tk.StringVar();self.compare_capital=tk.StringVar(value='100000')
        for label,var,width in [('开始',self.compare_start,12),('结束',self.compare_end,12),('本金',self.compare_capital,12)]:
            ttk.Label(bar,text=label,foreground=MUTED).pack(side='left',padx=(0,8));self.entry(bar,var,width).pack(side='left',padx=(0,20))
        self.button(bar,'运行策略比较',self.compare,True).pack(side='left')
        self.button(bar,'2013起',lambda:self.compare_start.set(self.service.default_start())).pack(side='left',padx=8)
        self.compare_table=self.table(self.comparison,[('code','策略',60),('name','方案',300),('return','累计收益',105),('cagr','年化收益',105),('dd','最大回撤',105),('fees','累计佣金',110),('fills','成交笔数',90)],11)
        self.compare_note=tk.StringVar(value='默认从2013-01-04开始。2013起比较6种D/F策略，其他3种明确标注不可用；2017-08-03之后可同区间比较全部9种。')
        ttk.Label(self.comparison,textvariable=self.compare_note,foreground=MUTED,wraplength=self.px(1190)).pack(anchor='w',pady=16)
        bar=ttk.Frame(self.comparison);bar.pack(fill='x')
        self.button(bar,'以选中策略新建账户',self.from_comparison).pack(side='left');self.button(bar,'导出比较结果',self.export_comparison).pack(side='left',padx=10)
        ttk.Label(self.comparison,text='D 系列：趋势门槛 + 动量 / 波动率配比   ·   F 系列：分阶段四资产   ·   L 系列：创业板、银行四态 + 黄金 / 现金',foreground=MUTED).pack(anchor='w',pady=(15,0))
    def build_history(self):
        bar=ttk.Frame(self.history);bar.pack(fill='x',pady=(0,18))
        ttk.Label(bar,text='每一笔成交，都有当日依据',font=('Microsoft YaHei UI',17,'bold')).pack(side='left')
        self.button(bar,'导入账户备份',self.import_backup).pack(side='right');self.button(bar,'导出完整记录',self.export).pack(side='right',padx=10)
        self.history_table=self.table(self.history,[('day','成交日',110),('signal','信号日',110),('asset','资产',135),('side','方向',65),('qty','份数',95),('price','成交价',85),('fee','佣金',85),('reason','触发原因（双击查看）',400)],13)
        self.history_table.bind('<Double-1>',self.history_detail)
        self.history_note=tk.StringVar();ttk.Label(self.history,textvariable=self.history_note,foreground=MUTED,wraplength=self.px(1200)).pack(anchor='w',pady=16)
        ttk.Label(self.history,text=RULE_NOTE,foreground=MUTED,wraplength=self.px(1200)).pack(anchor='w')
    def work(self,fn,done,label,cancellable=False,on_error=None):
        if self.busy:return
        self.busy=True;self.stop.clear();self.status.set(label)
        for w,_ in self.controls:
            if w.winfo_exists():w.configure(state='disabled')
        self.stop_button.state(['!disabled'] if cancellable else ['disabled'])
        def worker():
            try:self.events.put(('done',done,fn()))
            except InterruptedError:self.events.put(('cancelled',on_error,None))
            except Exception as exc:self.events.put(('error',str(exc),traceback.format_exc(),on_error))
        threading.Thread(target=worker,daemon=True).start()
    def progress(self,text):self.events.put(('progress',text))
    def poll(self):
        try:
            while True:
                item=self.events.get_nowait()
                if item[0]=='progress':self.status.set(item[1]);continue
                self.busy=False;self.stop_button.state(['disabled'])
                for w,state in self.controls:
                    if w.winfo_exists():w.configure(state=state)
                if item[0]=='error':
                    self.safe_log(item[2])
                    if len(item)>3 and item[3]:item[3](item[1])
                    self.status.set('操作未完成：'+item[1]);messagebox.showerror('操作未完成',item[1],parent=self.grab_current() or self)
                    if self.service and self.selected:self.refresh()
                elif item[0]=='cancelled':
                    if item[1]:item[1]('已停止')
                    self.status.set('比较已停止；此前完整结果保留。')
                else:
                    self.status.set('已停止；已完成的模拟记录已保存。' if self.stop.is_set() else '就绪 · 账户自动保存在本机')
                    try:item[1](item[2])
                    except Exception as e:
                        self.safe_log(traceback.format_exc());messagebox.showerror('显示异常',str(e),parent=self)
                self.sync_simulation_controls()
        except queue.Empty:pass
        except Exception:
            self.report_callback_exception(*sys.exc_info())
        finally:
            if getattr(self,'close_requested',False) and not self.busy:self.destroy()
            else:
                try:self.top5_sync_header()
                except Exception:self.safe_log(traceback.format_exc())
                self.after(100,self.poll)
    def loaded(self,service):
        self.service=service
        self.init_live()
        self.init_top5()
        self.init_seven()
        prior=service.folder/'最近策略比较.json'
        if prior.exists():
            try:self.compared(json.loads(prior.read_text(encoding='utf8')))
            except (ValueError,KeyError):pass
        if not service.book.list():
            self.work(lambda:service.create('我的模拟账户',100000,service.default_start(),'D5'),lambda s:(self.created(s),self.tabs.select(self.live_page)),'正在建立2013起的10万元历史练习账户…');return
        self.selected=service.settings.get('selected');self.refresh()
    def created(self,s):self.selected=s['id'];self.refresh();self.tabs.select(self.dash)
    def select_account(self):
        if self.busy:return
        ix=self.accounts.current()
        if ix>=0:self.selected=self.account_rows[ix]['id'];self.refresh()
    def refresh(self):
        self.account_rows=self.service.book.list()
        if self.selected not in {x['id'] for x in self.account_rows}:self.selected=self.account_rows[0]['id']
        self.accounts.configure(values=[f'{x["name"]} · {i+1}' for i,x in enumerate(self.account_rows)])
        self.accounts.current(next(i for i,x in enumerate(self.account_rows) if x['id']==self.selected))
        self.service.settings['selected']=self.selected;self.service.save_settings()
        self.view=self.service.snapshot(self.selected);z=self.view;s=z['state'];m=z['market'];v=z['value'];o=z['observation'];code=s['auto']['strategy']
        self.strategy.set(self.strategy_labels.label(code));self.data_label.set('收盘日线至 '+self.service.market.latest)
        self.day_label.set(('历史演练' if s['day']<m.latest else '账户末日')+' · '+s['day']+' · 账户行情至 '+m.latest)
        for var,text in zip(self.stats,[money(v['equity']),percent(v['return_']),f'{z["metrics"]["max_drawdown"]:.2%}',money(v['cash'])]):var.set(text)
        self.advice_title.set(z['title']);self.clear_table(self.positions);by={r['symbol']:r for r in z['rows']}
        for c in CODES:
            r=by.get(c);action=f'{r["side"]} {r["qty"]:,}份' if r else '持有' if s['positions'][c]['qty'] else '观望'
            self.positions.insert('',tk.END,values=[NAMES[c]+' '+c[2:],f'{s["positions"][c]["qty"]:,}',f'{o["weights"][c]:.1%}',action])
        self.cash_target.set(f'目标现金 {max(0,1-sum(o["weights"].values())):.1%}  ·  实际仓位受价格、费用与整手约束')
        action=o.get('action','等待收盘判断');next_text=f'下一模拟日：{z["next"]}' if z['next'] else '已到行情末日：可更新行情，或新建历史账户继续练习。'
        self.reason_text.set(action+'\n'+next_text+('  提示：'+z['warnings'][0] if z['warnings'] else ''))
        self.chart_note.set(f'{s["start"]} → {s["day"]}  ·  佣金 {money(v["fees"])} 元  ·  分红 {money(v["dividends"])} 元')
        previous=getattr(self,'displayed_account_latest',None)
        if not self.end.get() or self.end.get()==previous:self.end.set(m.latest)
        self.displayed_account_latest=m.latest
        if not self.compare_start.get():self.compare_start.set(self.service.default_start())
        if not self.compare_end.get():self.compare_end.set(self.service.market.latest)
        self.sync_simulation_controls()
        self.clear_table(self.history_table);self.fills={}
        events=self.service.book.events(self.selected)
        for e in events:
            if e['kind']!='策略成交':continue
            d=e['data'];self.fills[e['id']]=e
            self.history_table.insert('',tk.END,iid=e['id'],values=[e['day'],d['signal_day'],NAMES[d['symbol']],d['side'],f'{d["qty"]:,}',f'{d["price"]:.4f}',money(d['fee']),d.get('reason','')])
        self.history_note.set(f'共 {len(self.fills)} 笔成交 · {len(events)} 条完整事件（含信号、委托、分红等，随备份导出）。'+(' 尚未推进到成交日，点击“按方案模拟下一日”开始。' if not self.fills else ''))
        self.draw_chart()
    def sync_simulation_controls(self):
        enabled=not self.busy and bool(getattr(self,'view',{}).get('next'))
        for button in (self.next_button,self.run_button):button.configure(state='normal' if enabled else 'disabled')
    @staticmethod
    def clear_table(tree):
        for row in tree.get_children():tree.delete(row)
        if hasattr(tree,'sort_labels'):
            for key,label in tree.sort_labels.items():tree.heading(key,text=label)
            tree.sort_column=None;tree.sort_reverse=False
    def draw_chart(self):
        if not hasattr(self,'view'):return
        c=self.chart;c.delete('all');w=c.winfo_width();h=c.winfo_height()
        if w<80 or h<60:return
        s=self.view['state'];rows=s['curve'];vals=[r['equity'] for r in rows];lo=min(vals+[s['initial']]);hi=max(vals+[s['initial']]);pad=max((hi-lo)*.15,s['initial']*.005);lo-=pad;hi+=pad
        left=self.px(68);right=w-self.px(14);top=self.px(20);bottom=h-self.px(26)
        y=lambda v:bottom-(v-lo)/(hi-lo)*(bottom-top)
        for i in range(4):
            v=lo+(hi-lo)*i/3;yy=y(v);c.create_line(left,yy,right,yy,fill=LINE);c.create_text(left-8,yy,text=f'{v/10000:.2f}万',fill=MUTED,anchor='e',font=('Microsoft YaHei UI',9))
        c.create_line(left,y(s['initial']),right,y(s['initial']),fill='#657587',dash=(4,5));c.create_text(right,y(s['initial'])-9,text='初始本金',fill=MUTED,anchor='e',font=('Microsoft YaHei UI',8))
        points=[]
        for i,v in enumerate(vals):points.extend([left+(right-left)*i/max(1,len(vals)-1),y(v)])
        if len(vals)>1:c.create_line(*points,fill=ACCENT,width=2)
        else:c.create_oval(left-3,y(vals[0])-3,left+3,y(vals[0])+3,fill=ACCENT,outline=ACCENT)
        c.create_text(left,h-7,text=rows[0]['day'],fill=MUTED,anchor='w',font=('Microsoft YaHei UI',8));c.create_text(right,h-7,text=rows[-1]['day'],fill=MUTED,anchor='e',font=('Microsoft YaHei UI',8))
    def new_account(self,code=None,start=None,capital=None):
        if self.busy:return
        win=tk.Toplevel(self);win.title('新建模拟账户');win.configure(bg=BG);self.place_dialog(win,700,505);win.transient(self);win.grab_set()
        area=ttk.Frame(win,padding=24);area.pack(fill='both',expand=True)
        ttk.Label(area,text='从一个收盘日开始练习',font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w',pady=(0,16))
        fields=[('账户名称',tk.StringVar(value='模拟账户 '+str(len(self.account_rows)+1))),('初始本金 / 元',tk.StringVar(value=str(capital or 100000))),('起始日期 YYYY-MM-DD',tk.StringVar(value=start or self.service.default_start()))]
        for label,var in fields:
            row=ttk.Frame(area);row.pack(fill='x',pady=7);ttk.Label(row,text=label,width=23).pack(side='left');ttk.Entry(row,textvariable=var,width=23).pack(side='right')
        choice=tk.StringVar(value=self.strategy_labels.label(code or 'D5'));combo=ttk.Combobox(area,textvariable=choice,values=self.strategy_labels.values(),state='readonly',width=55);combo.pack(fill='x',pady=12)
        ttk.Label(area,textvariable=self.ranking_note,foreground=MUTED,wraplength=self.px(640),justify='left').pack(anchor='w',pady=(0,12))
        ttk.Label(area,text=f'收盘历史截至 {self.service.market.latest}，默认从2013年练习。\nD/F支持2013起，L系列最早2017-08-03。',foreground=MUTED).pack(anchor='w',pady=(0,15))
        ttk.Button(area,text='日期设为最新收盘日',command=lambda:fields[2][1].set(self.service.market.latest)).pack(anchor='w',pady=(0,12))
        def create():
            name,amount,day=[v.get() for _,v in fields];selected=choice.get().split()[0]
            from bank_model import spec
            try:name,amount,day=account_input(name,amount,day,spec(selected)['anchor'],self.service.market.dates)
            except ValueError as exc:messagebox.showerror('请检查账户信息',str(exc),parent=win);return
            submit.configure(state='disabled')
            def completed(s):
                if win.winfo_exists():win.destroy()
                self.created(s)
            def failed(_):
                if win.winfo_exists():submit.configure(state='normal')
            self.work(lambda:self.service.create(name,amount,day,selected),completed,'正在建立账户并生成方案…',on_error=failed)
        submit=ttk.Button(area,text='创建并查看方案',style='Accent.TButton',command=create);submit.pack(fill='x')
    def next_day(self):
        z=self.view
        if not z['next']:return
        id=self.selected;end=z['next'];self.work(lambda:self.service.run(id,end,self.stop,self.progress),lambda _:self.refresh(),'正在按上一收盘方案模拟开盘…')
    def run_until(self):
        id=self.selected;end=self.end.get().strip();self.work(lambda:self.service.run(id,end,self.stop,self.progress),lambda _:self.refresh(),'正在逐日模拟，交易与信号自动保存…',cancellable=True)
    def switch_strategy(self):
        code=self.strategy.get().split()[0]
        if code==self.view['state']['auto']['strategy']:return
        id=self.selected;self.work(lambda:self.service.switch(id,code),lambda _:self.refresh(),'正在更换后续策略，已有历史保留…')
    def text_window(self,title,text):
        w=tk.Toplevel(self);w.title(title);w.configure(bg=BG);self.place_dialog(w,880,680);w.transient(self)
        f=ttk.Frame(w,padding=20);f.pack(fill='both',expand=True)
        box=tk.Text(f,bg=PANEL,fg=FG,insertbackground=FG,wrap='word',font=('Microsoft YaHei UI',11),relief='flat',padx=16,pady=15)
        sb=ttk.Scrollbar(f,command=box.yview);box.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');box.pack(fill='both',expand=True);box.insert('1.0',text);box.configure(state='disabled')
    def strategy_detail(self):
        code=self.strategy.get().split()[0]
        from bank_model import spec
        self.text_window('策略说明 · '+code,TITLES[code]+'\n\n'+DESCRIPTIONS[code]+'\n\n'+RULE_NOTE+'\n\n目标仓位允许单资产达到100%，现金和国债也不能保证组合收益。策略中的止盈、退出与持有条件均按原参数运行。\n短周：周五收盘确认；缺周五的节假日周在下周首个收盘确认。\n\n完整策略参数（复盘用）\n'+json.dumps(spec(code),ensure_ascii=False,indent=2))
    def show_plan(self):self.text_window('完整交易方案',self.service.report(self.selected))
    def history_detail(self,event=None):
        selection=self.history_table.selection()
        if not selection:messagebox.showinfo('选择成交','先选择一笔成交，再双击查看当时的信号和费用。',parent=self);return
        e=self.fills[selection[0]];d=e['data'];self.text_window('成交详情 · '+e['day'],f'{NAMES[d["symbol"]]} {d["side"]} {d["qty"]:,}份\n信号日 {d["signal_day"]} → 成交日 {e["day"]}\n价格 {d["price"]:.6f}，佣金 {d["fee"]:.2f}\n\n'+d.get('reason','')+'\n\n保存的原始依据\n'+json.dumps(d,ensure_ascii=False,indent=2))
    def update_data(self):
        if hasattr(self,'top5_page') and self.tabs.select()==str(self.top5_page):
            self.top5_refresh_market();return
        self.refresh_live()
    def compare(self):
        start=self.compare_start.get().strip();end=self.compare_end.get().strip();capital=self.compare_capital.get().strip()
        self.work(lambda:self.service.compare(start,end,capital,self.stop,self.progress),self.compared,'正在准备相同口径的策略比较…',cancellable=True)
    def compared(self,result):
        if self.strategy_labels.update(result):self.refresh_strategy_labels()
        self.result=result;self.clear_table(self.compare_table)
        for r in result['rows']:
            self.compare_table.insert('',tk.END,iid=r['code'],values=[r['code'],r['name'],percent(r['total_return']),percent(r['cagr']) if r['cagr'] is not None else '不足一年',f'{r["max_drawdown"]:.2%}',money(r['fees']),r['fills']])
        for r in result.get('skipped',[]):self.compare_table.insert('',tk.END,iid=r['code'],values=[r['code'],r['name']+'（2017起可用）','—','—','—','—','—'])
        self.compare_note.set(f'{result["start"]} → {result["end"]} · 本金 {money(result["capital"])} 元 · '+(f'{len(result["rows"])}种可用策略全部完成。' if result['completed'] else '已停止，仅显示完整跑完区间的策略。')+' 收益已计佣金、滑点和分红；未强制期末清仓。'+(' L系列缺银行早期历史，未纳入本区间排名。' if result.get('skipped') else ''))
    def refresh_strategy_labels(self):
        self.ranking_note.set(self.strategy_labels.note)
        code=self.strategy.get().split()[0] if self.strategy.get() else None
        self.strategies.configure(values=self.strategy_labels.values())
        if code in ORDER:self.strategy.set(self.strategy_labels.label(code))
        code=self.live_strategy.get().split()[0] if self.live_strategy.get() else 'T5VOTE'
        self.live_strategy_combo.configure(values=reference_values(self.strategy_labels))
        self.live_strategy.set(reference_label(self.strategy_labels,code))
        if hasattr(self,'live'):self.render_live()
    def from_comparison(self):
        rows=self.compare_table.selection()
        if not rows:messagebox.showinfo('选择策略','先运行比较，再选择一行策略。',parent=self);return
        if rows[0] in {r['code'] for r in self.result.get('skipped',[])}:
            messagebox.showinfo('此策略的历史起点','L系列依赖银行ETF，最早2017-08-03。请选择更晚起点，或使用D/F系列。',parent=self);return
        self.new_account(rows[0],self.result['start'],self.result['capital'])
    def export_comparison(self):
        if not self.result:messagebox.showinfo('尚无结果','请先运行策略比较。',parent=self);return
        path=filedialog.asksaveasfilename(parent=self,title='导出策略比较',initialfile='九策略比较.json',defaultextension='.json',filetypes=[('JSON完整结果','*.json')])
        if path:
            from simulator_core import write_json
            write_json(path,self.result);self.status.set('比较结果已导出：'+path)
    def export(self):
        base=filedialog.askdirectory(parent=self,title='选择成果存放文件夹')
        if not base:return
        dest=Path(base)/('模拟账户导出_'+datetime.now().strftime('%Y%m%d_%H%M%S'));id=self.selected
        self.work(lambda:self.service.export(id,dest),lambda p:(self.status.set('已导出：'+p),messagebox.showinfo('已导出','账户备份、交易方案、逐笔交易与每日资产已保存到：\n'+p,parent=self)),'正在导出完整账户与方案…')
    def import_backup(self):
        path=filedialog.askopenfilename(parent=self,title='导入本软件账户备份',filetypes=[('完整账户备份','*.zip')])
        if path:self.work(lambda:self.service.import_backup(path),self.created,'正在核对账户与行情，导入为独立副本…')
    def close(self):
        if self.busy:
            self.close_requested=True;self.stop.set();self.status.set('正在结束当前步骤并保存，完成后会自动关闭。');return
        self.destroy()
    def safe_log(self,text):
        try:
            if self.service:
                with (self.service.folder/'运行日志.txt').open('a',encoding='utf8') as f:f.write('\n'+datetime.now().isoformat()+'\n'+text)
        except OSError:pass
    def report_callback_exception(self,exc_type,exc_value,tb):
        """Visible, logged errors for file dialogs and direct UI callbacks too."""
        detail=''.join(traceback.format_exception(exc_type,exc_value,tb))
        self.safe_log(detail)
        self.status.set('操作未完成：'+str(exc_value))
        messagebox.showerror('操作未完成',str(exc_value),parent=self.grab_current() or self)

def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:pass
    # A second window must not change a strategy midway through a running account.
    if sys.platform=='win32':
        import hashlib
        kernel=ctypes.windll.kernel32;kernel.CreateMutexW.restype=ctypes.c_void_p
        folder=os.environ.get('SIMPLE_ETF_HOME') or str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'SimpleETFSimulator')
        # Keep the v1.3 lock too, so upgrading while an old window exists is safe.
        lock_paths=dict.fromkeys([folder,os.path.normcase(str(Path(folder).expanduser().resolve()))])
        mutexes=[]
        for lock_path in lock_paths:
            mutex=kernel.CreateMutexW(None,False,'Local\\SimpleETFSimulator_'+hashlib.sha256(lock_path.encode()).hexdigest()[:20]);mutexes.append(mutex)
            lock_error=kernel.GetLastError()
            if not mutex:
                root=tk.Tk();root.withdraw();messagebox.showerror('简明ETF模拟交易',f'无法建立账户保护锁（Windows错误 {lock_error}），本次未打开账户。请稍后重试。',parent=root);root.destroy();return
            if lock_error==183:
                root=tk.Tk();root.withdraw();messagebox.showinfo('简明ETF模拟交易','模拟器已经打开，请使用已打开的窗口。升级后请先关闭旧版窗口再启动。',parent=root);root.destroy();return
    if '--self-test' in sys.argv:
        from simulator_core import write_json
        folder=Path(os.environ.get('SIMPLE_ETF_HOME') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'SimpleETFSimulator')
        result=dict(ok=False,version=VERSION)
        try:
            import bear_gold
            from bank_model import cutoff
            bear_gold.load_reference();result['reference_ok']=True
            service=Service();s=service.create('打包自检',100000,service.market.dates[-10],'D5');s=service.run(s['id'],service.market.latest)
            result.update(history_before=service.market.latest,equity=s['curve'][-1]['equity'])
            from chinext_service import Top5Service
            top5=Top5Service(folder)
            comp=top5.compare('2023-01-03','2026-09-15',100000)
            expected=json.loads((ROOT/'top5_expected.json').read_text(encoding='utf-8'))
            assert len(comp['rows'])==6
            for row in comp['rows']:
                for key in ['final_equity','cagr','max_drawdown','trades']:
                    assert abs(row[key]-expected[row['id']][key])<1e-7,(row['id'],key)
            trial=top5.create_account('创业板打包验收','T5VOTE','2023-01-03',100000)
            trial=top5.advance_account(trial['account']['id'],'2023-03-31')
            repeated=top5.advance_account(trial['account']['id'],'2023-03-31')
            assert trial['trades']==repeated['trades'] and trial['ledger']==repeated['ledger']
            signal=top5.signal_summary();assert len(signal['rows'])==5
            result.update(top5_research_match=True,top5_paper_idempotent=True,top5_data=top5.info(),top5_signal_count=5)
            from top5_reference import reference_plan
            references=[reference_plan(top5,s['id'],100000) for s in top5.list_strategies()]
            assert len(reference_values(StrategyLabels()))==21
            assert len(references)==5 and all(abs(p['budgets']['sz159915']+p['cash']-100000)<1e-8 for p in references)
            result.update(live_reference_count=21,top5_reference_plans=references)
            from seven_service import SevenService, BY_ID as seven_catalog
            seven=SevenService(folder,service,top5)
            seven_results=seven.compare('2023-01-03','2026-09-15',100000)
            for r in seven_results:
                expected_seven=seven_catalog[r['strategy']]['results']['base']
                for key in ['final_equity','cagr','max_drawdown']:
                    assert abs(r['metrics'][key]-expected_seven['periods']['全期'][key])<1e-7
            result['seven_research_match']=True
            a=seven.create_account('A_T5VOTE_P3','七组合打包验收',100000,'2023-01-03')
            continued=seven.advance(a['id'],'2023-03-31')
            assert continued==seven.advance(a['id'],'2023-03-31')
            result['seven_account_idempotent']=True
            if '--top5-live-check' in sys.argv:
                result['top5_refresh']=top5.refresh()
                result['top5_live_signals']=top5.signal_summary()
            if '--live-check' in sys.argv:
                from intraday import LiveService
                live=LiveService(service)
                live.refresh(force_history=True,progress=lambda note:write_json(folder/'打包自检进度.json',dict(note=note)))
                result.update(history_after=service.market.latest,history_target=cutoff(),history_error=live.history_error,
                    live_quotes=len(live.batch['quotes']),live_received_at=live.batch['received_at'],
                    live_quote_dates={c:q['day'] for c,q in live.batch['quotes'].items()},live_plan_available=live.preview is not None)
                if live.history_error:raise RuntimeError(live.history_error)
                if service.market.latest<cutoff():raise RuntimeError('历史日线未达到此次验证的目标日期')
                if live.preview is None:
                    # Evening acceptance runs must preserve the stale-quote guard.
                    # Confirmed-close strategies remain usable independently.
                    if '报价已超过3小时' not in live.preview_note:raise RuntimeError(live.preview_note)
                    result['after_hours_stale_quote_guard']=live.preview_note
                else:result['plans']={code:live.plan(code,100000)['observation']['weights'] for code in ORDER}
            result['seven_latest']=seven.sync()
            result['seven_live_plans']={code:seven.run(code,terminal=False,intraday=True)['plan'] for code in seven_catalog}
            result['ok']=True
        except Exception as e:
            result.update(error=str(e),traceback=traceback.format_exc());write_json(folder/'打包自检结果.json',result);raise SystemExit(1)
        write_json(folder/'打包自检结果.json',result);return
    app=App();app.mainloop()
if __name__=='__main__':main()
