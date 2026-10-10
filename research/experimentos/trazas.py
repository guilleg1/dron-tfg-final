"""Jornada de ejemplo (diagrama de vuelos) y esperas por peso del paquete con 30 pedidos por hora. Escribe trazas.json."""
import json, numpy as np, jornada
from jornada import *
out={'gantt':{},'waits':{}}
lam=25; jornada.LAM_FORECAST['lam']=lam; seed=1000*lam+5   # jornada cuya diferencia FIFO-MILP es la más próxima a la media de las 40
for p in ['FIFO','MILP con previsión']:
    orders=make_day(lam,seed); r=simulate(orders,POLICIES[p],keep_trace=True)
    om={o.id:o for o in orders}
    out['gantt'][p]={'trace':{d:[(a,b,om[i].w,om[i].d) for a,b,i in f] for d,f in r['trace'].items()},
                     'metrics':{k:v for k,v in r.items() if k not in('trace','waits')},
                     'queue':[(o.t,o.done) for o in orders]}
for lam in [30]:
    jornada.LAM_FORECAST['lam']=lam
    for p in ['FIFO','JV','JV+antigüedad','MILP con previsión']:
        w=[]
        for s in range(40):
            orders=make_day(lam,1000*lam+s); simulate(orders,POLICIES[p])
            w+=[((o.done-o.t)/60 if o.done is not None else None, o.w) for o in orders]
        out['waits'][p]=w
        print(p,flush=True)
json.dump(out,open('trazas.json','w'))
