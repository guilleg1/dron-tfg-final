import json, numpy as np
from comun import paired, holm
R=json.load(open('barrido.json'))
D={}
for kind,lam,seed,pol,fl,m in R:
    if kind=='demanda': D.setdefault((lam,pol),{})[seed]=m
F={}
for kind,lam,seed,pol,fl,m in R:
    if kind=='flota': F.setdefault((lam,pol,fl),{})[seed]=m
for (lam,pol),v in D.items():
    if lam in (15,20,25,30) and pol in ('FIFO','MILP con previsión') and seed<30: pass
# fleet baseline from demand runs (seeds<30)
for lam in (15,20,25,30):
    for pol in ('FIFO','MILP con previsión'):
        F[(lam,pol,'2L+2M+1P')]={s:m for s,m in D[(lam,pol)].items() if s<30}
pols=['FIFO','JV','JV+antigüedad','MILP horizonte','MILP con previsión']
lams=sorted({k[0] for k in D})
def boot(x,n=5000,seed=0):
    x=np.asarray(x,float); rng=np.random.default_rng(seed); b=rng.choice(x,(n,len(x))).mean(1); return np.percentile(b,[2.5,97.5])
summ={}
for lam in lams:
    for p in pols:
        ds=D[(lam,p)]; ks=sorted(ds)
        row={}
        for met in ['promise','served','wait_mean','wait_p95','promise_heavy','promise_far','e_per_kgkm','e_per_del','kgkm']:
            x=[ds[s][met] for s in ks]; lo,hi=boot(x); row[met]=(float(np.mean(x)),float(lo),float(hi))
        summ[f'{lam}|{p}']=row
        print(f'{lam:3.0f} {p:18s} prom {row["promise"][0]*100:5.1f} p95 {row["wait_p95"][0]:5.1f} med {row["wait_mean"][0]:5.1f} pesados {row["promise_heavy"][0]*100:5.1f} lejanos {row["promise_far"][0]*100:5.1f} Wh/kgkm {row["e_per_kgkm"][0]:5.2f} serv {row["served"][0]*100:5.1f}')
# paired vs FIFO
comps=[]
for lam in lams:
    for p in pols[1:]:
        for met in ['promise','wait_p95','promise_heavy']:
            a=D[(lam,'FIFO')]; b=D[(lam,p)]; ks=sorted(set(a)&set(b))
            x=[a[s][met] for s in ks]; y=[b[s][met] for s in ks]
            r=paired(x,y); comps.append(dict(lam=lam,pol=p,met=met,**{k:float(v) for k,v in r.items()}))
ph=holm([c['p'] for c in comps])
for c,h in zip(comps,ph): c['p_holm']=float(h)
for c in comps:
    if c['lam'] in (20,25,30,35) and c['met'] in ('promise','wait_p95'):
        sc=100 if c['met']=='promise' else 1
        print(f"{c['lam']:3.0f} {c['pol']:18s} {c['met']:9s} Δ {c['mean']*sc:+6.2f} [{c['lo']*sc:+6.2f},{c['hi']*sc:+6.2f}] pHolm {c['p_holm']:.1e} rb {c['rb']:+.2f} gana {c['win']:.2f} pierde {c['loss']:.2f}")
fsum={}
for (lam,pol,fl),ds in sorted(F.items()):
    ks=sorted(ds); row={met:float(np.mean([ds[s][met] for s in ks])) for met in ['promise','wait_p95','promise_heavy','e_per_kgkm']}
    fsum[f'{lam}|{pol}|{fl}']=row
    print(f'flota {lam:3.0f} {pol:18s} {fl:9s} prom {row["promise"]*100:5.1f} p95 {row["wait_p95"]:5.1f} pesados {row["promise_heavy"]*100:5.1f} Wh/kgkm {row["e_per_kgkm"]:5.2f}')
json.dump(dict(summary=summ,comps=comps,fleet=fsum),open('analisis.json','w'),indent=1)
