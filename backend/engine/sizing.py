"""Sizing (plan section 7, step 7): cheapest catalogue plan that fits CPU AND memory, rounded UP."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    plan_id: str
    vcpu: int
    ram_gb: int
    price: int


def catalogue(cfg):
    """Catalogue plans ordered by price (the 'step' order for the prod one-step rule)."""
    plans = [Plan(pid, int(p["vcpu"]), int(p["ram_gb"]), int(p["monthly_inr"])) for pid, p in cfg.plans.items()]
    return sorted(plans, key=lambda p: p.price)


def needs(vcpu, ram_gb, cpu_p, mem_p, cpu_target, mem_target):
    return vcpu * cpu_p / cpu_target, ram_gb * mem_p / mem_target


def cheapest_fit(cat, need_vcpu, need_ram):
    for p in cat:
        if p.vcpu >= need_vcpu and p.ram_gb >= need_ram:
            return p
    return None


def index_of(cat, plan_id):
    return next(i for i, p in enumerate(cat) if p.plan_id == plan_id)


def size(cat, current_id, need_vcpu, need_ram, prod):
    """Target plan; prod moves at most ONE step down per change. Returns (plan, note)."""
    fit = cheapest_fit(cat, need_vcpu, need_ram)
    if fit is None:
        return None, "no catalogue plan fits"
    cur = index_of(cat, current_id)
    i = index_of(cat, fit.plan_id)
    if prod and i < cur - 1:
        return cat[cur - 1], f"prod one-step rule: {fit.plan_id} fits, moving only to {cat[cur - 1].plan_id}"
    return fit, f"cheapest plan with ≥ {need_vcpu:.2f} vCPU and ≥ {need_ram:.2f} GB is {fit.plan_id}"
