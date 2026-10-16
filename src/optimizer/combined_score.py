"""Shared champion from actual comparable completed review + final seed scores.
Review samples were used for selection: this is an estimator, not holdout proof.
"""
import copy
import statistics
from src.optimizer import objective as obj


def combine(search):
    info=search.independent_validation or {}
    phases=[r for r in info.get('rounds',[]) if r.get('completed') and r.get('seeds')]
    if not phases:
        search.combined_champion=dict(available=False,reason='没有完成的独立决赛；保留上一完整阶段')
        return
    final=phases[-1];records=final['candidates'];keys=[r['configuration_key'] for r in records]
    if not keys:return
    # Latest completed review participation for each member. The intersection
    # defines one uniform evidence cohort; incomplete later cache entries excluded.
    review_by_key={}
    for row in (search.statistical_review or {}).get('rounds',[]):
        if row.get('completed') is False:continue
        for key in row.get('configuration_keys',[]):review_by_key[key]=set(row.get('seeds') or [])
    common_review=set.intersection(*(review_by_key.get(k,set()) for k in keys))
    common_final=set(final['seeds']).intersection(*(set(r.get('seeds') or []) for r in records))
    common_review={s for s in common_review if all((k,s) in search.cache for k in keys)}
    common_final={s for s in common_final if all((k,s) in search.cache for k in keys)}
    if not common_review or common_final!=set(final['seeds']):
        search.combined_champion=dict(available=False,reason='完整共同复评/决赛样本不足，保留独立决赛冠军',
            review_seeds=sorted(common_review),final_seeds=sorted(common_final))
        return
    seeds=sorted(common_review|common_final)
    _objective=getattr(getattr(search,'settings',None),'objective','mean') or 'mean'
    def _rank(key,seed_set):
        return obj.rank_key([search.cache[key,s] for s in seed_set],_objective)
    candidates=[]
    for r in records:
        k=r['configuration_key']
        candidates.append(dict(configuration_key=k,state=copy.deepcopy(r['state']),eligible=r.get('eligible',False),
            review_mean=_rank(k,common_review),
            independent_mean=_rank(k,common_final),
            combined_mean=_rank(k,seeds),seeds=seeds,seed_count=len(seeds)))
    legal=[r for r in candidates if r['eligible']]
    if not legal:return
    winner=min(legal,key=lambda r:(-r['combined_mean'],r['configuration_key']))
    baseline=next((r for r in candidates if r['configuration_key']==search._key(search.original)),None)
    different=winner['configuration_key']!=final['winner_key']
    # Only the independent comparison can supply holdout evidence. Do not turn
    # the selected review sample into a new confidence claim.
    comparisons=final.get('comparisons',[])
    relevant=[r for r in comparisons if r.get('eligible')]
    distinguishable=(not different and len(legal)>1 and len(relevant)==len(legal)-1 and
        {r.get('configuration_key') for r in relevant}=={r['configuration_key'] for r in legal if r['configuration_key']!=winner['configuration_key']} and
        all(r.get('conclusion','').startswith('领先证据') for r in relevant))
    search.combined_champion=dict(available=True,provisional=True,winner_key=winner['configuration_key'],
        independent_winner_key=final['winner_key'],combined_mean=winner['combined_mean'],
        baseline_combined_mean=baseline['combined_mean'] if baseline else None,
        review_seeds=sorted(common_review),final_seeds=sorted(common_final),seeds=seeds,
        review_seed_count=len(common_review),independent_seed_count=len(common_final),combined_seed_count=len(seeds),
        candidates=candidates,ranking_differs=different,
        notice='综合评分与独立决赛排名不同，候选可能十分接近。' if different else '',
        conclusion='独立决赛领先证据较充分（配对t近似假设下）' if distinguishable else '暂无法统计区分。',
        limitation='综合样本含搜索复评，不等同全部独立验证；仅本次完成共同样本组排名，不证明全局最优')
    search.best=copy.deepcopy(winner['state'])
    # Keep legacy mean's meaning: the chosen snapshot's independent-final mean,
    # not the combined estimator. Independent winner is unchanged in final info.
    search.best_mean=winner['independent_mean'];search.best_validation_count=len(common_final)
    search.validation_seed_list=sorted(common_final)
    search.baseline_mean=baseline['independent_mean'] if baseline else None
    search.baseline_validation_seeds=sorted(common_final) if baseline else []
    key=winner['configuration_key']
    if all((key,s) in search.cache for s in search.search_seed_list):
        search.best_search=_rank(key,search.search_seed_list)

