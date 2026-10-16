"""One strategy selector for the three explicit mature modes; legacy stays unchanged."""
import copy
from src.optimizer.combined_score import combine


def review(search,candidates,baseline_eligible,reserve):
    shared=search.settings.search_kind in ('memory','positions','layered')
    if shared:
        search.shared_review=True
        search.review_evidence_keys=set(candidates)|{search._key(search.original)}
        search.review_candidate_template=copy.deepcopy(search.search_start or search.original)
    if shared and search.settings.review_strategy=='quick':
        from src.optimizer.quick_review import review as execute
    else:
        from src.optimizer.statistical_review import review as execute
    try:
        execute(search,candidates,baseline_eligible,reserve)
    finally:
        if shared:combine(search)  # Only completed cohorts, even when stopping during extra finals.
