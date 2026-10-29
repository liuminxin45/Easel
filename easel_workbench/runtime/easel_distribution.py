"""Connection-only boundary; existing project delivery drivers stay independent."""


class EaselDistributionRuntime:
    def __init__(self, box, fallback):
        self.box, self.fallback = box, fallback

    def __getattr__(self, name):
        return getattr(self.fallback, name)

    def _accounts(self):
        from easel_workbench.runtime.easel_accounts import service
        return service(self.box)

    def capability(self, connection, action):
        supplied = self._accounts().capability(connection, action)
        return supplied if supplied is not None else self.fallback.capability(connection, action)

    def probe(self, connection):
        session = self._accounts().session_for(connection)
        if session:
            return {'account': session.get('account'), 'identity_status': session.get('identity_status'),
                    'logged_in': session.get('logged_in'), 'checked_at': session.get('checked_at')}
        return self.fallback.probe(connection)

    def send(self, claim, assets):
        if not self._accounts().session_for(claim['connection']):
            return self.fallback.send(claim, assets)
        from easel_workbench.runtime.distribution_runtime import BridgeError
        raise BridgeError('Easel 仅接入平台连接，未接入交付驱动')

    def verify(self, delivery, revision, connection, hints):
        if not self._accounts().session_for(connection):
            return self.fallback.verify(delivery, revision, connection, hints)
        return {'remote_state': 'unknown', 'verified': False, 'account': connection['account'],
                'reason': '仅保留原交付记录；平台连接不提供发布回执读取'}
