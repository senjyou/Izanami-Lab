"""Low-cost coordinator timings. Set IZANAMI_OPTIMIZER_TIMINGS=0 to disable."""
import os
import time
from contextlib import contextmanager


class PerformanceLedger:
    def __init__(self):
        self.enabled=os.environ.get('IZANAMI_OPTIMIZER_TIMINGS','1')!='0'
        self.seconds={};self.calls={};self.phases={}
        self.current=None;self.phase_started=time.monotonic()

    @contextmanager
    def measure(self,name):
        if not self.enabled:
            yield;return
        began=time.monotonic()
        try:yield
        finally:
            self.seconds[name]=self.seconds.get(name,0.)+time.monotonic()-began
            self.calls[name]=self.calls.get(name,0)+1

    def phase(self,name):
        now=time.monotonic()
        if self.current is not None:
            self.phases[self.current]=self.phases.get(self.current,0.)+now-self.phase_started
        self.current=name;self.phase_started=now

    def snapshot(self,counts):
        phases=dict(self.phases)
        if self.current is not None:phases[self.current]=phases.get(self.current,0.)+time.monotonic()-self.phase_started
        return dict(enabled=self.enabled,seconds=dict(self.seconds),calls=dict(self.calls),
                    phases={name:dict(wall_seconds=seconds,completed_battles=counts.get(name,0),
                                     throughput=counts.get(name,0)/seconds if seconds else 0.) for name,seconds in phases.items()},
                    timing_scope='协调器计时；阶段墙钟含该阶段等待/统计/结果发布。Worker执行/等待累计时间可能并行重叠，不能相加为墙钟。GUI耗时在主进程另记。')
