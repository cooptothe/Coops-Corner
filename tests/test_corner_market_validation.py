"""Pure synthetic authority proofs. No actual feed/bookmaker is approved here."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json
import unittest
from uuid import UUID

from corner import market_validation as v


def uid(number):
    return str(UUID(int=number))


NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
SECOND = timedelta(seconds=1)
MICROSECOND = timedelta(microseconds=1)
PROVIDER, EVENT, MARKET, COMPETITION = map(uid, range(1, 5))
BOOKS = tuple(map(uid, range(10, 13)))
OUTCOMES = ((uid(20), 'participant_a'), (uid(21), 'participant_b'))
IDENTITY = v.PolicyIdentity('synthetic-test-policy', '1', 'synthetic-only-revision')


def retained(doc, identifier=100, authority='synthetic-phase-authority',
             source_type='explicit_status', received_at=NOW):
    content = v.canonical(doc).encode()
    return v.RetainedEvidence(uid(identifier), authority, source_type, content,
                              v.sha256(content), received_at, 'synthetic://retained/document')


def phase_document(status='NOT_STARTED_CONFIRMED', **changes):
    return dict(format=v.PHASE_FORMAT, provider_id=PROVIDER, external_event_id='event-123',
                status=status, source_asserted_at=v._encode(NOW)) | changes


def phase_grant(**changes):
    return replace(v.PhaseSourceGrant('synthetic-phase-authority', 'explicit_status', PROVIDER,
        (('NOT_STARTED_CONFIRMED', 'supported_pregame'), ('LIVE', 'unsupported_live'),
         ('FINAL', 'unsupported_completed')), 30 * SECOND, 20 * SECOND), **changes)


def rules_document(book=BOOKS[0], **changes):
    return dict(format=v.RULES_FORMAT,
                binding=dict(sportsbook_id=book, competition_id=COMPETITION,
                             market_type='moneyline', scope='full_game'),
                rules_revision='synthetic-rules-1', effective_from=v._encode(NOW - timedelta(days=1)),
                effective_until=None,
                terms=dict(structure='two_way', outcome_labels=['participant_a', 'participant_b'],
                           overtime='included', tie='impossible', push='impossible',
                           refund_rule='synthetic_abandonment_refund_v1',
                           void_rule='synthetic_void_conditions_v1')) | changes


class MarketValidationTests(unittest.TestCase):
    def setUp(self):
        self.event = v.EventBinding(EVENT, ((PROVIDER, 'event-123'),))
        self.contract = v.ContractBinding(EVENT, MARKET, COMPETITION, 'moneyline', 'full_game', OUTCOMES)
        self.phase_policy = v.PhasePolicy(IDENTITY, (phase_grant(),))

    def phase(self, evidence=None, policy=None, at=NOW, event=None):
        return v.validate_phase(assertion_id=uid(200), event=event or self.event,
                                policy=policy or self.phase_policy,
                                evidence=(retained(phase_document()),) if evidence is None else evidence,
                                asserted_at=at)

    def settlement(self, book=BOOKS[0], docs=None, policy=None, at=NOW, contract=None):
        evidence = tuple(retained(doc, 110 + i, 'synthetic-rules-authority', 'reviewed_rules')
                         for i, doc in enumerate(docs or [rules_document(book)]))
        if policy is None:
            policy = v.SettlementPolicy(IDENTITY, tuple(v.SettlementSourceGrant(
                e.authority, e.source_type, e.content_sha256, **json.loads(e.content)['binding'])
                for e in evidence))
        return v.validate_settlement(assertion_id=uid(201 + BOOKS.index(book)),
            contract=contract or self.contract, sportsbook_id=book, policy=policy,
            evidence=evidence, asserted_at=at)

    def gate(self, phase=None, settlements=None, at=NOW, contract=None):
        return v.check_ev_v1_capability(phase=phase or self.phase(),
            settlements=tuple(self.settlement(book) for book in BOOKS) if settlements is None else settlements,
            contract=contract or self.contract, required_sportsbook_ids=BOOKS, at=at)

    def test_positive_phase_requires_explicit_admitted_status_and_retains_provenance(self):
        assertion = self.phase()
        result = assertion.result
        self.assertEqual('supported_pregame', result['classification'])
        self.assertEqual(v._encode(NOW + 20 * SECOND), result['valid_until'])
        command = json.loads(assertion.command_snapshot)
        self.assertEqual(v.VALIDATOR_REVISION, command['validator_revision'])
        self.assertEqual(IDENTITY.revision, command['policy']['identity']['revision'])
        self.assertEqual(retained(phase_document()).content_sha256,
                         command['evidence'][0]['content_sha256'])
        self.assertEqual((uid(200), assertion.result_sha256), assertion.reference)

    def test_future_schedule_false_completed_and_null_scores_cannot_authorize(self):
        for status in ('scheduled', 'upcoming', 'UNKNOWN'):
            doc = phase_document(status, commence_time=v._encode(NOW + timedelta(days=1)),
                                 completed=False, scores=None)
            assertion = self.phase((retained(doc),))
            self.assertEqual('unknown', assertion.result['classification'])
            self.assertEqual('unsupported_phase', self.gate(phase=assertion))

    def test_empty_evidence_or_no_approved_sources_is_unknown(self):
        self.assertEqual('unknown', self.phase(()).result['classification'])
        policy = v.PhasePolicy(IDENTITY, ())
        self.assertEqual('unknown', self.phase(policy=policy).result['classification'])

    def test_source_type_and_authority_are_both_required(self):
        for changes in ({'authority': 'unapproved'}, {'source_type': 'schedule_inference'}):
            evidence = replace(retained(phase_document()), **changes)
            result = self.phase((evidence,)).result
            self.assertEqual('unknown', result['classification'])
            self.assertIn([evidence.id, 'unapproved_source'], result['diagnostics'])

    def test_live_and_completed_are_successful_nonpregame_assertions(self):
        for status, classification in [('LIVE', 'unsupported_live'), ('FINAL', 'unsupported_completed')]:
            assertion = self.phase((retained(phase_document(status)),))
            self.assertEqual(classification, assertion.result['classification'])
            self.assertEqual('unsupported_phase', self.gate(phase=assertion))

    def test_conflicting_admissible_sources_do_not_choose_latest(self):
        old = retained(phase_document(source_asserted_at=v._encode(NOW - SECOND)), 100,
                       received_at=NOW - SECOND)
        newer = retained(phase_document('LIVE'), 101)
        first = self.phase((old, newer))
        self.assertEqual('conflicting_phase_evidence', first.result['reason'])
        self.assertEqual(first, self.phase((newer, old)))

    def test_unknown_admissible_status_conflicts_with_positive(self):
        result = self.phase((retained(phase_document()), retained(phase_document('UNKNOWN'), 101))).result
        self.assertEqual('unknown', result['classification'])

    def test_source_age_is_not_refreshed_by_later_receipt(self):
        item = retained(phase_document(source_asserted_at=v._encode(NOW - 31 * SECOND)))
        self.assertEqual('unknown', self.phase((item,)).result['classification'])

    def test_receipt_and_source_age_boundaries(self):
        item = retained(phase_document(source_asserted_at=v._encode(NOW - 20 * SECOND)),
                        received_at=NOW - 20 * SECOND)
        self.assertEqual('supported_pregame', self.phase((item,)).result['classification'])
        self.assertEqual('unknown', self.phase((item,), at=NOW + MICROSECOND).result['classification'])
        policy = v.PhasePolicy(IDENTITY, (phase_grant(max_source_age=10 * SECOND),))
        item = retained(phase_document(source_asserted_at=v._encode(NOW - 10 * SECOND)))
        self.assertEqual('supported_pregame', self.phase((item,), policy).result['classification'])
        self.assertEqual('unknown', self.phase((item,), policy, NOW + MICROSECOND).result['classification'])

    def test_phase_assertion_expires_without_mutation(self):
        assertion = self.phase()
        original = assertion.result_snapshot
        self.assertIsNone(self.gate(phase=assertion, at=NOW + 20 * SECOND))
        self.assertEqual('assertion_expired', self.gate(phase=assertion, at=NOW + 20 * SECOND + MICROSECOND))
        self.assertEqual(original, assertion.result_snapshot)

    def test_future_receipt_source_time_and_assertion_are_errors(self):
        for item in (retained(phase_document(), received_at=NOW + SECOND),
                     retained(phase_document(source_asserted_at=v._encode(NOW + SECOND)))):
            with self.assertRaises(v.ValidationError):
                self.phase((item,))
        with self.assertRaises(v.ValidationError):
            self.gate(at=NOW - SECOND)

    def test_wrong_event_or_provider_binding_is_error(self):
        for changes in ({'external_event_id': 'different-event'}, {'provider_id': uid(999)}):
            with self.assertRaises(v.ValidationError):
                self.phase((retained(phase_document(**changes)),))
        with self.assertRaises(v.ValidationError):
            self.gate(phase=self.phase(event=replace(self.event, event_id=uid(999))))

    def test_malformed_or_unsupported_evidence_is_not_unknown(self):
        for doc in ({'format': v.PHASE_FORMAT}, phase_document(format='future-format'),
                    phase_document(source_asserted_at='not-a-time')):
            with self.assertRaises(v.ValidationError):
                self.phase((retained(doc),))
        for content in (b'not JSON', b'{"format":1,"format":2}', b'{"x":NaN}'):
            bad = replace(retained(phase_document()), content=content, content_sha256=v.sha256(content))
            with self.assertRaises(v.ValidationError):
                self.phase((bad,))

    def test_digest_mismatch_is_error_even_for_unapproved_source(self):
        with self.assertRaisesRegex(v.ValidationError, 'digest mismatch'):
            replace(retained(phase_document()), authority='unapproved', content=b'changed')

    def test_positive_rules_path_requires_exact_approved_content(self):
        assertion = self.settlement()
        self.assertEqual('no_push_two_way', assertion.result['classification'])
        self.assertIsNone(self.gate())
        policy = v.SettlementPolicy(IDENTITY, ())
        self.assertEqual('unknown', self.settlement(policy=policy).result['classification'])

    def test_outcome_count_without_rules_is_unknown(self):
        assertion = v.validate_settlement(assertion_id=uid(220), contract=self.contract,
            sportsbook_id=BOOKS[0], policy=v.SettlementPolicy(IDENTITY, ()), evidence=(), asserted_at=NOW)
        self.assertEqual('unknown', assertion.result['classification'])

    def test_mutable_url_cannot_approve_new_rules_bytes(self):
        original = self.settlement()
        command = json.loads(original.command_snapshot)
        policy = v.SettlementPolicy(IDENTITY, tuple(v.SettlementSourceGrant(**s)
                                                   for s in command['policy']['sources']))
        doc = rules_document(rules_revision='replacement-revision')
        self.assertEqual('unknown', self.settlement(docs=[doc], policy=policy).result['classification'])

    def test_settlement_binding_mismatch_is_error(self):
        for field, value in [('sportsbook_id', BOOKS[1]), ('competition_id', uid(999)),
                             ('market_type', 'spread'), ('scope', 'first_half')]:
            doc = rules_document()
            doc['binding'][field] = value
            with self.assertRaises(v.ValidationError):
                self.settlement(docs=[doc])
        with self.assertRaises(v.ValidationError):
            self.gate(settlements=(self.settlement(contract=replace(self.contract, market_id=uid(999))),))

    def test_rules_effective_interval_is_half_open_and_independent_of_receipt_age(self):
        at_start = rules_document(effective_from=v._encode(NOW), effective_until=v._encode(NOW + SECOND))
        self.assertEqual('no_push_two_way', self.settlement(docs=[at_start]).result['classification'])
        self.assertEqual('unknown', self.settlement(docs=[at_start], at=NOW + SECOND).result['classification'])
        self.assertEqual('unknown', self.settlement(docs=[rules_document(
            effective_from=v._encode(NOW + SECOND))]).result['classification'])
        self.assertEqual('no_push_two_way', self.settlement(at=NOW + timedelta(days=100)).result['classification'])
        assertions = (self.settlement(docs=[at_start]), self.settlement(BOOKS[1]), self.settlement(BOOKS[2]))
        self.assertEqual('assertion_expired', self.gate(settlements=assertions, at=NOW + SECOND))

    def test_overlapping_conflicting_rules_fail_closed(self):
        first, second = rules_document(), rules_document(rules_revision='conflicting-revision')
        second['terms']['overtime'] = 'excluded'
        self.assertEqual('conflicting_settlement_evidence', self.settlement(docs=[first, second]).result['reason'])

    def test_three_way_classification_does_not_grant_ev_v1_capability(self):
        contract = replace(self.contract, outcomes=OUTCOMES + ((uid(22), 'draw'),))
        assertions = []
        for book in BOOKS:
            doc = rules_document(book)
            doc['terms'].update(structure='three_way', outcome_labels=['participant_a', 'participant_b', 'draw'],
                                tie='draw_selection')
            assertion = self.settlement(book, docs=[doc], contract=contract)
            self.assertEqual('three_way', assertion.result['classification'])
            assertions.append(assertion)
        self.assertEqual('unsupported_contract', self.gate(settlements=assertions, contract=contract))

    def test_push_and_quarter_line_are_classifications_not_supported_engine_contracts(self):
        for changes, classification in [({'tie': 'refund'}, 'push_capable'),
                                        ({'push': 'refund'}, 'push_capable'),
                                        ({'structure': 'quarter_line', 'push': 'split'}, 'quarter_line'),
                                        ({'tie': 'loss'}, 'unknown')]:
            doc = rules_document()
            doc['terms'].update(changes)
            assertion = self.settlement(docs=[doc])
            self.assertEqual(classification, assertion.result['classification'])
            self.assertEqual('unsupported_settlement', self.gate(settlements=(
                assertion, self.settlement(BOOKS[1]), self.settlement(BOOKS[2]))))

    def test_missing_rules_fields_contradictory_rules_and_wrong_outcomes_are_errors(self):
        docs = []
        doc = rules_document()
        del doc['terms']['void_rule']
        docs.append(doc)
        doc = rules_document()
        doc['terms']['tie'] = 'draw_selection'
        docs.append(doc)
        doc = rules_document()
        doc['terms']['outcome_labels'] = ['participant_a', 'someone_else']
        docs.append(doc)
        docs.append(rules_document(effective_until=v._encode(NOW - timedelta(days=2))))
        for doc in docs:
            with self.assertRaises(v.ValidationError):
                self.settlement(docs=[doc])

    def test_every_required_book_needs_its_own_assertion(self):
        self.assertEqual('missing_settlement_assertion', self.gate(settlements=(self.settlement(),)))
        with self.assertRaises(v.ValidationError):
            self.gate(settlements=(self.settlement(), self.settlement()))

    def test_same_outcome_and_classification_do_not_prove_book_rules_compatible(self):
        for key, value in [('overtime', 'excluded'), ('refund_rule', 'other-refund-rule'),
                            ('void_rule', 'other-void-rule')]:
            doc = rules_document()
            doc['terms'][key] = value
            changed = self.settlement(docs=[doc])
            self.assertEqual('no_push_two_way', changed.result['classification'])
            self.assertEqual('incompatible_settlement_rules', self.gate(settlements=(
                changed, self.settlement(BOOKS[1]), self.settlement(BOOKS[2]))))

    def test_immutability_and_frozen_assertion_replay(self):
        assertion = self.phase()
        with self.assertRaises(FrozenInstanceError):
            assertion.result_snapshot = 'changed'
        decoded = assertion.result
        decoded['classification'] = 'changed'
        later = self.phase((retained(phase_document('LIVE')),))
        self.assertEqual('unsupported_live', later.result['classification'])
        self.assertEqual('supported_pregame', assertion.result['classification'])
        self.assertEqual(assertion, self.phase())

    def test_unordered_inputs_canonicalize_without_losing_raw_bytes(self):
        one = retained(phase_document(), 100)
        two = retained(phase_document(), 101)
        self.assertEqual(self.phase((one, two)), self.phase((two, one)))
        contract = replace(self.contract, outcomes=tuple(reversed(OUTCOMES)))
        self.assertEqual(self.settlement(), self.settlement(contract=contract))
        json_text = json.dumps(phase_document(), indent=4).encode()
        changed = replace(one, content=json_text, content_sha256=v.sha256(json_text))
        self.assertNotEqual(self.phase((one,)).command_sha256, self.phase((changed,)).command_sha256)

    def test_policy_changes_are_part_of_command_identity(self):
        changed = replace(self.phase_policy, identity=replace(IDENTITY, version='2'))
        first, second = self.phase(), self.phase(policy=changed)
        self.assertEqual(first.result['classification'], second.result['classification'])
        self.assertNotEqual(first.command_sha256, second.command_sha256)

    def test_assertion_digest_and_even_rehashed_wrong_result_are_errors(self):
        assertion = self.phase()
        result = json.loads(assertion.result_snapshot)
        result['classification'] = 'unsupported_live'
        altered = v.canonical(result)
        for forged in (replace(assertion, result_snapshot=altered),
                       replace(assertion, result_snapshot=altered, result_sha256=v.sha256(altered.encode()))):
            with self.assertRaises(v.ValidationError):
                forged.result

    def test_unsupported_assertion_format_and_build_are_errors(self):
        assertion = self.phase()
        for key, value in [('format', 'unsupported'), ('validator_revision', 'unknown-build')]:
            command = json.loads(assertion.command_snapshot)
            command[key] = value
            command_text = v.canonical(command)
            digest = v.sha256(command_text.encode())
            result = json.loads(assertion.result_snapshot)
            result['command_sha256'] = digest
            result_text = v.canonical(result)
            forged = v.ValidationAssertion(command_text, result_text, digest, v.sha256(result_text.encode()))
            with self.assertRaises(v.ValidationError):
                forged.result

    def test_duplicate_evidence_and_invalid_types_fail_validation(self):
        item = retained(phase_document())
        for evidence in ((item, item), ('not evidence',)):
            with self.assertRaises(v.ValidationError):
                self.phase(evidence)
        with self.assertRaises(v.ValidationError):
            v.PhasePolicy(IDENTITY, ('not a grant',))
        with self.assertRaises(v.ValidationError):
            self.phase(at=NOW.replace(tzinfo=None))


if __name__ == '__main__':
    unittest.main()
