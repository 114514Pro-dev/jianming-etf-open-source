"""One isolated computation from market-only inputs. No saved account access."""
from pathlib import Path
import json,sys,threading,contextlib
from copy import deepcopy
from functools import lru_cache


def compute(request):
    from web_signal_model import original_model,top_model,seven_model
    from web_signal_activity import attach_activity
    group=request['group']; snap=request['data']; results=[]
    if group=='original':
        import trade_book as ledger
        from suite_book import SuiteBook
        class MemoryBook(SuiteBook):
            def __init__(self):self.state=None;self.fills=[]
            @contextlib.contextmanager
            def connection(self):yield self
            def execute(self,query,params):
                assert query.startswith('INSERT INTO accounts');self.state=json.loads(params[-1])
            def get(self,identity,con=None):return self.state
            def save(self,con,state):ledger.validate(state);state['revision']+=1;self.state=state
            def event(self,con,state,kind,payload,*args,**kwargs):
                if kind=='策略成交':self.fills.append(dict(payload,time=state['day']+' 09:30:00'))
        market=ledger.Market(snap);original=market.observation
        cached=lru_cache(maxsize=60000)(original)
        market.observation=lambda code,day:deepcopy(cached(code,day))
        for code in request['strategies']:
            book=MemoryBook();book.create(code,100000,'2023-01-03',market,code)
            state=book.advance(book.state['id'],market,market.latest)
            results.append(attach_activity(original_model(state,market),book.fills))
    elif group=='top5':
        from chinext_service import Top5Service,BY_ID
        from top5_reference import reference_plan
        class ReadOnlyTop5(Top5Service):
            def __init__(self):self.settings={'snapshot_id':request['snapshot']};self._lock=threading.RLock();self._signals_cache={}
            def _snapshot(self,sid=None):return snap
        service=ReadOnlyTop5()
        for code in request['strategies']:
            ref=reference_plan(service,code,100000)
            signals=service._signals(code,request['snapshot']);last=signals.iloc[-1]
            state=ref['reference_state']
            rule=BY_ID[code]['parameters']+'。'+BY_ID[code]['description']
            row=top_model(code,state,last,str(signals.index[-1]),rule,'sz159915')
            # Replay the identical native reference to read its fill events. The
            # shared reference API and all saved account response shapes stay intact.
            import chinext_engine as engine
            _,_,book,_,_=engine.simulate(service._frames(request['snapshot'])[1],signals,'2023-01-03',
                'SIGNAL-ACTIVITY-'+code,fixed_hold=20 if code=='T5WEEK' else None,initial=100000,terminal_liquidation=False)
            native=book.attrs['state']
            assert native['shares']==state['shares'] and abs(native['cash']-state['cash'])<1e-7
            attach_activity(row,book.attrs['events'],'sz159915')
            row['reasons'].append(ref['reason']);results.append(row)
    elif group=='seven':
        from seven_service import SevenService
        class ReadOnlySeven(SevenService):
            def __init__(self):self.cache={};self.signal_cache={};self.settings={'snapshot':request['snapshot']}
            def snapshot(self,sid=None):return snap
        service=ReadOnlySeven()
        for code in request['strategies']:
            result=service.run(code,'2023-01-03',request['end'],100000,terminal=False,intraday=True)
            results.append(attach_activity(seven_model(result,service,'sz159915'),result['events']))
    else:raise ValueError('Unknown domestic group')
    from chinext_engine import clean_json
    return clean_json(results)


if __name__=='__main__':
    request=json.loads(Path(sys.argv[1]).read_text('utf8'))
    Path(sys.argv[2]).write_text(json.dumps(compute(request),ensure_ascii=False,allow_nan=False),encoding='utf8')
