from types import SimpleNamespace

import pytest

from apis.xhs_pc_login_apis import XHSLoginApi


class FakeQrHttp:
    def __init__(self, poll_payload, exchange_payload, exchange_cookies=None):
        self.poll_payload = poll_payload
        self.exchange_payload = exchange_payload
        self.exchange_cookies = exchange_cookies or {}
        self.exchange_calls = 0
        self.user_info_calls = 0
        self.user_info_failures = 0
        self.closed = 0
        self.poll_http_status = 200
        self.exchange_http_status = 200
        self.user_info_http_status = 200

    def close(self):
        self.closed += 1

    def post(self, url, **kwargs):
        return SimpleNamespace(
            url=url, status_code=self.poll_http_status, ok=self.poll_http_status < 400,
            cookies={}, json=lambda: self.poll_payload,
        )

    def get(self, url, **kwargs):
        if url.endswith('/api/sns/web/v2/user/me'):
            self.user_info_calls += 1
            if self.user_info_calls <= self.user_info_failures:
                raise ConnectionError('test user info unavailable')
            return SimpleNamespace(
                url=url, status_code=self.user_info_http_status, ok=self.user_info_http_status < 400,
                cookies={}, json=lambda: {'success': True, 'data': {
                    'user_id': 'test-user', 'nickname': 'test-account', 'guest': False,
                }},
            )
        self.exchange_calls += 1
        return SimpleNamespace(
            url=url, status_code=self.exchange_http_status, ok=self.exchange_http_status < 400,
            cookies=self.exchange_cookies, json=lambda: self.exchange_payload,
        )


@pytest.fixture
def sdk(monkeypatch):
    # Keep the actual SDK response/cookie parsing; isolate signing and HTTP only.
    monkeypatch.setattr(
        XHSLoginApi, '_signed_request_params',
        lambda self, *args, **kwargs: ({}, ''),
    )
    monkeypatch.setattr(
        'apis.xhs_pc_login_apis.build_pc_login_headers',
        lambda headers, cookies, **kwargs: headers,
    )

    def make(exchange, *, poll=None, exchange_cookies=None):
        http = FakeQrHttp(
            poll if poll is not None else {'success': True, 'data': {'codeStatus': 2}},
            exchange, exchange_cookies,
        )
        return XHSLoginApi(http_client=http), http

    return make


@pytest.mark.parametrize('envelope', [{'success': True}, {'code': 0}, {'code': '0'}])
@pytest.mark.parametrize('status_key', ['code_status', 'codeStatus'])
@pytest.mark.parametrize('status', [2, '2'])
def test_exchange_accepts_structured_success_and_status_variants(sdk, envelope, status_key, status):
    api, http = sdk({
        **envelope, 'msg': '成功',
        'data': {status_key: status, 'login_info': {'session': 'authenticated-session'}},
    })
    cookies = {'a1': 'test-a1', 'web_session': 'visitor-session'}

    success, message, result = api.check_qrcode_status('test-qr', 'test-code', cookies)

    assert success is True
    assert message == '验证成功'
    assert result['web_session'] == 'authenticated-session'
    assert api.profile.cookie_map['web_session'] == 'authenticated-session'
    assert http.exchange_calls == 1


@pytest.mark.parametrize('info_key', ['login_info', 'loginInfo'])
@pytest.mark.parametrize('status_fields', [{}, {'code_status': 0}])
def test_new_login_session_completes_exchange_without_redundant_status(sdk, info_key, status_fields):
    api, _ = sdk({
        'success': True, 'msg': '成功',
        'data': {**status_fields, info_key: {'session': 'authenticated-session'}},
    })
    cookies = {'a1': 'test-a1', 'web_session': 'visitor-session'}

    success, _, result = api.check_qrcode_status('test-qr', 'test-code', cookies)

    assert success is True
    assert result['web_session'] == 'authenticated-session'


def test_confirmed_exchange_accepts_new_session_from_response_cookie(sdk):
    api, _ = sdk(
        {'code': 0, 'msg': '成功', 'data': {'codeStatus': '2'}},
        exchange_cookies={'web_session': 'authenticated-session'},
    )

    success, _, cookies = api.check_qrcode_status(
        'test-qr', 'test-code', {'a1': 'test-a1', 'web_session': 'visitor-session'},
    )

    assert success is True
    assert cookies['web_session'] == 'authenticated-session'


@pytest.mark.parametrize('data', [
    {'code_status': 2},
    {'code_status': 2, 'login_info': {'session': 'visitor-session'}},
    {'code_status': 1},
    {},
    [],
])
def test_success_message_never_suffices_without_formal_session(sdk, data):
    api, _ = sdk({'success': True, 'code': 0, 'msg': '成功', 'data': data})

    with pytest.raises(RuntimeError) as caught:
        api.check_qrcode_status(
            'test-qr', 'test-code', {'a1': 'test-a1', 'web_session': 'visitor-session'},
        )

    detail = str(caught.value)
    assert detail != '成功'
    assert '凭证' in detail
    assert 'code=' in detail
    assert 'code_status=' in detail
    assert 'visitor-session' not in detail
    assert 'test-code' not in detail


def test_explicit_rejection_overrides_code_zero_and_session(sdk):
    api, _ = sdk({
        'success': False, 'code': 0, 'msg': '成功',
        'data': {'code_status': 2, 'login_info': {'session': 'must-not-accept'}},
    })

    with pytest.raises(RuntimeError, match='success=false') as caught:
        api.check_qrcode_status(
            'test-qr', 'test-code', {'a1': 'test-a1', 'web_session': 'visitor-session'},
        )

    assert 'must-not-accept' not in str(caught.value)


@pytest.mark.parametrize('status, expected', [('0', '请扫描二维码'), ('1', '请确认登录'), ('3', '二维码已过期')])
def test_poll_normalizes_status_without_exchanging_pending_qr(sdk, status, expected):
    api, http = sdk({}, poll={'code': 0, 'data': {'code_status': status}})

    success, message, _ = api.check_qrcode_status('test-qr', 'test-code', {'a1': 'test-a1'})

    assert success is False
    assert message == expected
    assert http.exchange_calls == 0


@pytest.mark.parametrize('poll', [
    {'success': False, 'msg': '成功', 'data': {'codeStatus': 2}},
    {'success': True, 'msg': '成功', 'data': {}},
    {'success': True, 'msg': '成功', 'data': {'codeStatus': True}},
    {'success': True, 'msg': '成功', 'data': {'codeStatus': 42}},
    [],
])
def test_invalid_poll_is_diagnostic_and_never_exchanges(sdk, poll):
    api, http = sdk({}, poll=poll)

    with pytest.raises(RuntimeError) as caught:
        api.check_qrcode_status('test-qr', 'test-code', {'a1': 'test-a1'})

    assert str(caught.value) != '成功'
    assert '二维码状态' in str(caught.value)
    assert http.exchange_calls == 0


@pytest.fixture
def login_route(sdk, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
    from backend.app.api import login_sessions
    from backend.app.core.database import Base, get_db
    from backend.app.core.security import create_access_token, encrypt_text
    from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount, User

    _, http = sdk({
        'code': 0, 'msg': '成功',
        'data': {'codeStatus': '2', 'loginInfo': {'session': 'authenticated-session'}},
    })
    clients = []

    def new_sdk():
        api = XHSLoginApi(http_client=http)
        clients.append(api)
        return api

    # Recreate SDK clients as production does; state must survive in the DB.
    monkeypatch.setattr('apis.xhs_pc_login_apis.XHSLoginApi', new_sdk)

    def no_extra_profile(*args, **kwargs):
        raise RuntimeError('optional profile enrichment disabled in offline test')

    monkeypatch.setattr(XhsPcApiAdapter, 'get_self_info', no_extra_profile)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'qr-response.db'}", connect_args={'check_same_thread': False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username='qr-parser-owner', password_hash='unused-in-test')
        db.add(user)
        db.flush()
        pending = LoginSession(
            user_id=user.id, platform='xhs', sub_type='pc', status='scanned',
            qr_id='test-qr', code='test-code', qr_url='https://example.test/qr',
            encrypted_temp_cookies=encrypt_text(login_sessions._dump_temp_state({
                'a1': 'test-a1', 'web_session': 'visitor-session',
            })),
        )
        db.add(pending)
        db.commit()
        token = create_access_token(user.id)
        session_id = pending.id

    def test_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(login_sessions.router, prefix='/api')
    app.dependency_overrides[get_db] = test_db
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client, headers={'Authorization': f'Bearer {token}'},
                url=f'/api/xhs/login-sessions/{session_id}', session_id=session_id,
                sessions=sessions, http=http, clients=clients,
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.parametrize('user_info_failures', [0, 1])
def test_sdk_response_reaches_account_binding_and_completed_polls_are_repeatable(login_route, user_info_failures):
    from sqlalchemy import select
    from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount

    route = login_route
    route.http.user_info_failures = user_info_failures
    response = route.client.get(route.url, headers=route.headers)
    if user_info_failures:
        assert response.status_code == 502
        with route.sessions() as db:
            assert db.get(LoginSession, route.session_id).status == 'scanned'
        response = route.client.get(route.url, headers=route.headers)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'confirmed'
    account = response.json()['account']
    assert account['nickname'] == 'test-account'
    assert 'login_state' not in response.json()

    # Simulate losing the first successful response, then polling again.
    repeated = route.client.get(route.url, headers=route.headers)
    assert repeated.status_code == 200
    assert repeated.json()['status'] == 'confirmed'
    assert repeated.json()['account']['id'] == account['id']
    assert route.http.exchange_calls == 1
    assert route.http.user_info_calls == 1 + user_info_failures
    assert len(route.clients) == 2 + user_info_failures
    assert route.http.closed == len(route.clients)
    with route.sessions() as db:
        assert len(db.scalars(select(PlatformAccount)).all()) == 1
        assert len(db.scalars(select(AccountCookieVersion)).all()) == 1


@pytest.mark.parametrize('stage', ['poll', 'exchange', 'user_info'])
def test_http_471_overrides_success_json_and_remains_terminal(login_route, stage):
    import json
    from sqlalchemy import select
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount

    route = login_route
    setattr(route.http, f'{stage}_http_status', 471)
    response = route.client.get(route.url, headers=route.headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'blocked'
    assert result['upstream_status'] == 471
    assert result['retryable'] is False
    assert result['error_code'] == 'xhs_login_blocked'
    assert '官方' in result['message']
    assert result['account'] is None
    assert 'authenticated-session' not in response.text
    assert 'login_state' not in result
    exchange_calls = route.http.exchange_calls
    user_info_calls = route.http.user_info_calls
    client_count = len(route.clients)

    # A refresh, another worker, or a later poll must not call the SDK again.
    repeated = route.client.get(route.url, headers=route.headers)
    assert repeated.status_code == 200
    assert repeated.json() == result
    assert route.http.exchange_calls == exchange_calls
    assert route.http.user_info_calls == user_info_calls
    assert len(route.clients) == client_count
    assert route.http.closed == client_count
    with route.sessions() as db:
        stored = db.get(LoginSession, route.session_id)
        assert stored.status == 'blocked'
        state = json.loads(decrypt_text(stored.encrypted_temp_cookies))
        assert state['cookies'] == {}
        assert state['login_error']['upstream_status'] == 471
        assert db.scalars(select(PlatformAccount)).all() == []
        assert db.scalars(select(AccountCookieVersion)).all() == []


@pytest.mark.parametrize('operation', ['check_qrcode_status', 'get_user_info'])
def test_http_471_is_identified_before_parsing_an_html_body(sdk, operation):
    from xhs_utils.xhs_core.errors import XhsLoginBlockedError

    api, http = sdk({})
    original = http.post if operation == 'check_qrcode_status' else http.get

    def blocked_response(*args, **kwargs):
        response = original(*args, **kwargs)
        response.status_code = 471
        response.ok = False

        def no_json():
            raise AssertionError('HTTP 471 must be handled without parsing its HTML body')

        response.json = no_json
        return response

    if operation == 'check_qrcode_status':
        http.post = blocked_response
        call = lambda: api.check_qrcode_status('test-qr', 'test-code', {'a1': 'test-a1'})
    else:
        http.get = blocked_response
        call = lambda: api.get_user_info({'a1': 'test-a1'})
    with pytest.raises(XhsLoginBlockedError, match='HTTP 471'):
        call()
