"""Installed, opt-in rotation acceptance; SAME identity, only PostgreSQL secret changes."""
import json
from pathlib import Path

from run_scm_acceptance import Harness, main, digest, require, wait_for
from credential_rotation import Rotation, qualification_request, frozen, verify_result


class RotationHarness(Harness):
    report_format = 'corner.credential-rotation-acceptance/1'
    scope = 'disposable execution service; stop/drain PostgreSQL secret rotation; explicit session revocation'
    work_kinds = ['qualify']

    def rejected_start(self, request):
        # One expected startup failure, no restart storm while the vault is stale.
        self.service.disable_recovery()
        before = self.fixture.execution(request)['claim_count']
        self.fixture.conn.commit()
        self.offset = len(self.events())
        self.mode('normal')
        self.service.start()
        wait_for(lambda: any(e.get('event') == 'host_adapter_error' for e in self.events()[self.offset:]), 30)
        wait_for(lambda: self.service.status()['state'] == 1, 20)
        require(not any(e.get('event') == 'ready' for e in self.events()[self.offset:]), 'revoked vault credential passed readiness')
        require(not (self.stage / 'runtime/instance.json').exists(), 'failed startup retained runtime identity')
        after = self.fixture.execution(request)['claim_count']
        self.fixture.conn.commit()
        require(before == after, 'failed readiness claimed work')
        self.report['scm_states'].append(dict(self.service.status(), event='expected_stale_credential_readiness_failure'))
        self.report['checks']['stale_vault_fails_readiness_without_claiming'] = 'passed'

    def run(self):
        rotation = Rotation(self.fixture, self.report)
        self.extra_secrets.extend([rotation.old_secret, rotation.new_secret])
        config_path, approval_path = self.stage / 'app/config.json', self.stage / 'app/approval.json'
        unchanged_files = (digest(config_path), digest(approval_path))
        self.report['configuration_sha256'], self.report['target_approval_sha256'] = unchanged_files
        self.report['postgres_login'] = rotation.login
        authority = json.loads(config_path.read_text())['authority']
        try:
            self.report['phase'] = 'baseline_credential_readiness'
            self.start('normal'); self.stop('graceful_exit')
            self.report['checks']['initial_vault_credential_passes_readiness'] = 'passed'

            self.report['phase'] = 'freeze_qualification_before_rotation'
            request = qualification_request(self.fixture)
            self.start('stop_prepared'); self.event('acceptance_checkpoint')
            original = frozen(self.fixture, request)
            rotation.open_old_session()
            self.stop('graceful_exit')
            require(self.service.status()['state'] == 1, 'service must be stopped before rotating')
            self.report['checks']['service_stopped_with_frozen_command_preserved'] = 'passed'

            self.report['phase'] = 'rotate_and_verify_connection_revocation'
            rotation.rotate()
            self.extra_secrets.append(rotation.verifier)
            rotation.reject_old()
            rotation.revoke_old_session()

            self.report['phase'] = 'stale_vault_readiness_rejection'
            self.rejected_start(request)
            rotation.require_no_sessions()

            self.report['phase'] = 'replace_same_user_vault_secret'
            self.account.load_profile()
            try: self.account.credential(rotation.login, rotation.new_secret)
            finally: self.account.unload_profile()
            require((digest(config_path), digest(approval_path)) == unchanged_files, 'rotation changed config or authority manifest')
            self.report['checks']['same_config_authority_and_vault_target'] = 'passed'

            self.report['phase'] = 'restart_with_new_secret_and_original_command'
            self.start('normal')
            self.report['checks']['new_vault_credential_passes_readiness'] = 'passed'
            result = verify_result(self.fixture, request, original, authority)
            require(result['claim_count'] >= 2, 'original frozen work was not reclaimed')
            self.report['work'].append(result)
            self.stop('graceful_exit')
            rotation.require_no_sessions()
            require(rotation.role_fingerprint() == rotation.before_role, 'role changed during restart')
            self.report['checks']['frozen_command_and_domain_identity_preserved'] = 'passed'
        finally:
            rotation.close()


if __name__ == '__main__':
    raise SystemExit(main(harness_class=RotationHarness))
