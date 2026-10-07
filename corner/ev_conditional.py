"""EV v2: decisive-settlement conditional estimates over frozen evidence.

No source approval or capture is performed here. Settlement evidence must come
from a trusted versioned adapter; test assertions do not authorize production.
The unchanged v1 engine supplies quote eligibility and the binary pricing kernel.
"""
from dataclasses import dataclass, replace
from enum import Enum
from uuid import UUID

from corner import ev as v1, evaluations as codec

ENGINE_NAME = v1.ENGINE_NAME
ENGINE_VERSION = '2.0.0'
BASIS = 'decisive_settlement_conditional'
PROBABILITY_BASIS = 'win_given_decisive_settlement'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def object_json(text):
    import json
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=pairs)
    require(isinstance(value, dict) and bool(value), 'nonempty semantic contract required')
    return codec.canonical_json(codec._encode(value, identifiers=False))


@dataclass(frozen=True)
class SettlementPolicy:
    name: str
    version: str
    revision: str
    conditioning_contract_json: str
    invalidation_behavior_json: str
    calculation_basis: str = BASIS
    decisive_structure: str = 'two_way'
    push_behavior: str = 'absent'

    def __post_init__(self):
        require(all(isinstance(x, str) and x.strip() for x in (self.name, self.version, self.revision)),
                'pinned settlement policy identity required')
        require((self.calculation_basis, self.decisive_structure, self.push_behavior) ==
                (BASIS, 'two_way', 'absent'), 'unsupported settlement compatibility policy')
        for field in ('conditioning_contract_json', 'invalidation_behavior_json'):
            object.__setattr__(self, field, object_json(getattr(self, field)))


@dataclass(frozen=True)
class Configuration:
    version: str
    pricing: v1.EVConfiguration
    settlement: SettlementPolicy
    calculation_basis: str = BASIS
    fair_probability_basis: str = PROBABILITY_BASIS
    invalidation_probability_model: str = 'none'

    def __post_init__(self):
        require(isinstance(self.version, str) and bool(self.version.strip()), 'configuration version required')
        require(type(self.pricing) is v1.EVConfiguration and type(self.settlement) is SettlementPolicy,
                'explicit pricing and settlement policies required')
        require((self.calculation_basis, self.fair_probability_basis, self.invalidation_probability_model) ==
                (BASIS, PROBABILITY_BASIS, 'none'), 'unsupported calculation basis/model')


@dataclass(frozen=True)
class SettlementEvidence:
    sportsbook_id: str
    market_id: str
    outcome_ids: tuple[str, ...]
    assertion_id: str
    assertion_sha256: str
    policy_revision: str
    conditioning_contract_json: str
    invalidation_behavior_json: str
    decisive_structure: str = 'two_way'
    push_behavior: str = 'absent'

    def __post_init__(self):
        for field in ('sportsbook_id', 'market_id', 'assertion_id'):
            object.__setattr__(self, field, str(UUID(getattr(self, field))))
        ids = tuple(sorted(str(UUID(x)) for x in self.outcome_ids))
        require(bool(ids) and len(ids) == len(set(ids)), 'distinct settlement outcome IDs required')
        object.__setattr__(self, 'outcome_ids', ids)
        require(isinstance(self.assertion_sha256, str) and len(self.assertion_sha256) == 64
                and all(c in '0123456789abcdef' for c in self.assertion_sha256), 'assertion SHA-256 required')
        require(isinstance(self.policy_revision, str) and bool(self.policy_revision.strip()),
                'assertion policy revision required')
        for field in ('conditioning_contract_json', 'invalidation_behavior_json'):
            object.__setattr__(self, field, object_json(getattr(self, field)))


@dataclass(frozen=True)
class EvaluationCommand:
    snapshot: v1.EVSnapshot
    configuration: Configuration
    settlements: tuple[SettlementEvidence, ...]
    context_json: str = '{}'

    def __post_init__(self):
        require(type(self.snapshot) is v1.EVSnapshot and type(self.configuration) is Configuration,
                'v2 snapshot/configuration required')
        items = tuple(self.settlements)
        require(all(type(x) is SettlementEvidence for x in items), 'settlement evidence required')
        require(len({x.sportsbook_id for x in items}) == len(items), 'duplicate settlement sportsbook')
        object.__setattr__(self, 'settlements', tuple(sorted(items, key=lambda x: x.sportsbook_id)))


class Reason(str, Enum):
    MISSING = 'missing_decisive_settlement_evidence'
    INCOMPATIBLE = 'incompatible_decisive_settlement_conditions'


def evaluate(command):
    """A rejected compatibility gate never exposes a probability or estimate.

    The unchanged v1 kernel identifies eligible contributing books and computes
    tentative binary math. Those results are released only if the v2 gate passes.
    Its internal legacy contract label is not persisted as the v2 contract.
    """
    snapshot, config = command.snapshot, command.configuration
    kernel_snapshot = replace(snapshot, contract=replace(snapshot.contract, settlement_policy='two_way_no_push'))
    result = v1.evaluate_ev(kernel_snapshot, config.pricing)
    result = replace(result, snapshot=snapshot, configuration=config,
                     engine_name=ENGINE_NAME, engine_version=ENGINE_VERSION)

    def reject(reason):
        return replace(result, reason=reason, fair_probability=None, ev_ratio=None, reference_estimates=())

    if snapshot.contract.settlement_policy != 'decisive_two_way':
        return reject(v1.Reason.UNSUPPORTED_SETTLEMENT)
    expected = tuple(sorted(o.outcome_id for o in snapshot.contract.outcomes))
    supplied_books = {q.sportsbook_id for q in snapshot.quotes} | set(config.pricing.reference_sportsbook_ids)
    for item in command.settlements:
        require(item.market_id == snapshot.contract.market_id and item.outcome_ids == expected
                and item.sportsbook_id in supplied_books, 'settlement evidence subject mismatch')
    if result.reason is not None:
        return result
    target = next(q for q in snapshot.quotes if q.observation_id == snapshot.target_observation_id)
    required = {target.sportsbook_id} | {r.sportsbook_id for r in result.reference_estimates}
    evidence = {x.sportsbook_id: x for x in command.settlements}
    if not required <= evidence.keys():
        return reject(Reason.MISSING)
    for book in required:
        item = evidence[book]
        if (item.decisive_structure, item.push_behavior, item.policy_revision,
            item.conditioning_contract_json, item.invalidation_behavior_json) != (
                'two_way', 'absent', config.settlement.revision,
                config.settlement.conditioning_contract_json, config.settlement.invalidation_behavior_json):
            return reject(Reason.INCOMPATIBLE)
    return result
