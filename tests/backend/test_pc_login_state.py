import json
from types import SimpleNamespace

from apis.xhs_pc_login_apis import XHSLoginApi
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter


def test_qr_preparation_and_state_survive_new_clients_for_each_request(monkeypatch):
    actions = []
    signed_states = []
    clients = []

    class Transport:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

        def post(self, url, **kwargs):
            actions.append('poll')
            # The first poll is performed before the QR is shown to the user.
            status = 0 if actions.count('poll') == 1 else 2
            return SimpleNamespace(
                url=url, ok=True, status_code=200, cookies={},
                json=lambda: {'success': True, 'data': {'codeStatus': status}},
            )

        def get(self, url, **kwargs):
            if url.endswith('/api/sns/web/v2/user/me'):
                actions.append('user-info')
                payload = {'success': True, 'data': {'guest': False, 'user_id': 'test-user', 'nickname': 'test'}}
            else:
                actions.append('exchange')
                payload = {'success': True, 'data': {'code_status': 2, 'login_info': {'session': 'formal-session'}}}
            return SimpleNamespace(url=url, ok=True, status_code=200, cookies={}, json=lambda: payload)

    def new_client():
        client = XHSLoginApi(http_client=Transport())
        clients.append(client)
        return client

    def initialize(self):
        actions.append('initialize')
        cookies = {'a1': 'test-a1', 'web_session': 'visitor', 'loadts': '1000', 'ets': '1000'}
        profile = self._ensure_profile(cookies)
        profile.session.last_tiga_update_time = 1234
        profile.session.dsllt = 1234
        self._cookie_store.update(self.base_url, {'acw_tc': 'api-only-cookie'})
        self._cookie_store.update(self.as_url, {'acw_tc': 'security-only-cookie'})
        return cookies

    def create_qr(self, cookies):
        actions.append('create-qr')
        return True, '成功', {'cookies': cookies, 'qr_id': 'test-qr', 'code': 'test-code', 'qr_url': 'https://example.test/qr'}

    def prepare(self, cookies):
        actions.append('prepare')
        self._webprofile_reported = True
        self._login_b1 = 'existing-login-report'
        self.profile_data = 'existing-profile-data'
        cookies['gid'] = 'test-gid'
        self.profile.update_cookies(cookies)
        self.profile.mark_profile_reported()
        return 'test-gid'

    def signed(self, cookies, api, *args, **kwargs):
        profile = self._ensure_profile(cookies)
        signed_states.append((
            profile.session.next_seq(), self._webprofile_reported,
            profile.session.last_tiga_update_time, self._login_b1,
        ))
        return {}, ''

    monkeypatch.setattr('apis.xhs_pc_login_apis.XHSLoginApi', new_client)
    monkeypatch.setattr(XHSLoginApi, 'generate_init_cookies', initialize)
    monkeypatch.setattr(XHSLoginApi, 'generate_qrcode', create_qr)
    monkeypatch.setattr(XHSLoginApi, 'ensure_webprofile', prepare)
    monkeypatch.setattr(XHSLoginApi, '_signed_request_params', signed)
    monkeypatch.setattr('apis.xhs_pc_login_apis.build_pc_login_headers', lambda headers, cookies, **kwargs: headers)

    created = XhsPcLoginAdapter().create_qrcode()
    assert actions == ['initialize', 'create-qr', 'poll', 'prepare']
    # JSON round trips simulate encrypted temporary state storage between calls.
    checkpoint = json.loads(json.dumps(created['login_state']))
    result = XhsPcLoginAdapter().check_qrcode_status(
        created['qr_id'], created['code'], created['cookies'], login_state=checkpoint,
    )
    assert result['status'] == 'confirmed'
    checkpoint = json.loads(json.dumps(result['login_state']))
    user = XhsPcLoginAdapter().get_user_info(result['cookies'], login_state=checkpoint)
    assert user['external_user_id'] == 'test-user'
    assert len(clients) == 3
    assert len({id(client) for client in clients}) == 3
    assert all(client.http.closed == 1 for client in clients)
    assert [state[0] for state in signed_states] == [1, 2, 3, 4]
    assert signed_states[0][1] is False
    assert all(state[1] is True for state in signed_states[1:])
    assert all(state[2] == 1234 for state in signed_states)
    assert all(state[3] == 'existing-login-report' for state in signed_states[1:])
    assert clients[-1].host_cookies_snapshot() == clients[0].host_cookies_snapshot()
    assert clients[-1].profile_data == 'existing-profile-data'
    assert user['login_state']['session']['mns_seq'] == 4

    # A different login must not inherit this user's host cookies or state.
    isolated = XHSLoginApi(http_client=Transport())
    assert isolated.host_cookies_snapshot() == {}
    assert isolated._webprofile_reported is False
    assert isolated.profile is None


def test_exported_state_is_a_detached_copy():
    client = XHSLoginApi(http_client=SimpleNamespace(close=lambda: None))
    client._ensure_profile({'a1': 'test-a1', 'loadts': '1000', 'ets': '1000'})
    client.local_storage['nested'] = {'counter': 1}
    snapshot = client.export_login_state()
    snapshot['options']['local_storage']['nested']['counter'] = 999
    snapshot['session']['mns_seq'] = 999
    assert client.local_storage['nested']['counter'] == 1
    assert client.profile.session.mns_seq == 0
