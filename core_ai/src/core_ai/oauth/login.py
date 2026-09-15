from __future__ import annotations

import threading
import time
import webbrowser

import httpx

from core_ai.oauth import anthropic as anthropic_oauth
from core_ai.oauth import openai_codex as openai_oauth
from core_ai.oauth import xai as xai_oauth
from core_ai.oauth.callback import start_callback_server
from core_ai.oauth.types import LoginCancelled, LoginPrompt, OAuthToken, supports_oauth


class LoginFlow:
    """In-flight subscription login for one provider.

    `wait()` blocks until the browser/device flow finishes, the user pastes a
    callback, or `close()` cancels. Safe to call `complete_from_paste` from
    another thread (the TUI input handler).
    """

    def __init__(
        self,
        prompt: LoginPrompt,
        *,
        verifier: str = "",
        state: str = "",
        device: xai_oauth.DeviceCode | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.prompt = prompt
        self._verifier = verifier
        self._state = state
        self._device = device
        self._client = client
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._token: OAuthToken | None = None
        self._error: BaseException | None = None
        self._server = None
        self._server_thread: threading.Thread | None = None

    def start_loopback(self) -> bool:
        """Bind `localhost:1455` for the ChatGPT redirect. Returns False if busy."""
        if self.prompt.provider_id != "openai":
            return False
        try:
            server = start_callback_server(
                "127.0.0.1",
                openai_oauth.CALLBACK_PORT,
                openai_oauth.CALLBACK_PATH,
                self._on_loopback,
            )
        except OSError:
            return False
        self._server = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server_thread = thread
        return True

    def wait(self, timeout: float = 300.0) -> OAuthToken:
        if self.prompt.kind == "device" and self._device is not None:
            self._poll_device(timeout)
        elif not self._done.wait(timeout):
            self.close()
            raise TimeoutError("Login timed out")
        return self._result()

    def complete_from_paste(self, pasted: str) -> OAuthToken:
        provider = self.prompt.provider_id
        raw = pasted.strip()
        if provider == "anthropic" and anthropic_oauth.looks_like_setup_token(raw):
            token = anthropic_oauth.setup_token_from_paste(raw)
        elif provider == "openai":
            code, state = openai_oauth.parse_codex_callback(raw)
            token = openai_oauth.exchange_codex_code(
                code,
                verifier=self._verifier,
                state=state,
                expected_state=self._state,
                client=self._client,
            )
        elif provider == "anthropic":
            token = anthropic_oauth.exchange_anthropic_code(
                raw,
                verifier=self._verifier,
                expected_state=self._state,
                client=self._client,
            )
        else:
            raise ValueError("xAI login happens in the browser. Wait for it to finish, or Esc to cancel")
        self._succeed(token)
        return token

    def close(self) -> None:
        with self._lock:
            if not self._done.is_set():
                self._error = LoginCancelled()
                self._done.set()
        self._shutdown_server()

    def _poll_device(self, timeout: float) -> None:
        assert self._device is not None
        deadline = time.time() + timeout
        interval = float(self._device.interval)
        while not self._done.is_set() and time.time() < deadline:
            if self._done.wait(timeout=interval):
                return
            try:
                token = xai_oauth.poll_device_token(self._device, client=self._client)
            except xai_oauth.AuthorizationPending:
                continue
            except xai_oauth.SlowDown:
                interval += 5.0
                continue
            except Exception as exc:
                self._fail(exc)
                return
            self._succeed(token)
            return
        if not self._done.is_set():
            self._fail(TimeoutError("xAI login timed out"))

    def _on_loopback(self, code: str, state: str, error: str) -> None:
        if error:
            self._fail(ValueError(error))
            return
        if not code:
            self._fail(ValueError("Redirect did not include an authorization code"))
            return
        try:
            token = openai_oauth.exchange_codex_code(
                code,
                verifier=self._verifier,
                state=state,
                expected_state=self._state,
            )
        except Exception as exc:
            self._fail(exc)
            return
        self._succeed(token)

    def _succeed(self, token: OAuthToken) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self._token = token
            self._done.set()
        self._shutdown_server()

    def _fail(self, error: BaseException) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self._error = error
            self._done.set()
        self._shutdown_server()

    def _result(self) -> OAuthToken:
        if self._error is not None:
            raise self._error
        if self._token is None:
            raise LoginCancelled()
        return self._token

    def _shutdown_server(self) -> None:
        server = self._server
        if server is None:
            return
        self._server = None
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass


def start_login(
    provider_id: str,
    *,
    open_browser: bool = True,
    bind_loopback: bool = True,
    client: httpx.Client | None = None,
) -> LoginFlow:
    """Start a subscription login for OpenAI, Anthropic, or xAI."""
    if not supports_oauth(provider_id):
        raise ValueError(f"No subscription login for provider: {provider_id}")
    if provider_id == "openai":
        url, verifier, state = openai_oauth.start_codex_pkce()
        prompt = LoginPrompt(
            provider_id="openai",
            kind="browser",
            title="Sign in with ChatGPT",
            instructions="A browser window should open. After you approve, Symphony captures the redirect. If it does not bounce back, paste the localhost URL here.",
            url=url,
            paste_hint="http://localhost:1455/auth/callback?code=...",
        )
        flow = LoginFlow(prompt, verifier=verifier, state=state, client=client)
        if bind_loopback:
            flow.start_loopback()
        _maybe_open(url, enabled=open_browser)
        return flow
    if provider_id == "anthropic":
        url, verifier, state = anthropic_oauth.start_anthropic_pkce()
        prompt = LoginPrompt(
            provider_id="anthropic",
            kind="paste",
            title="Sign in with Claude",
            instructions="Preferred: run `claude setup-token` and paste the token. Alternative: open the URL, then paste the `code#state` from the redirect.",
            url=url,
            paste_hint="sk-ant-oat-...  or  code#state",
        )
        flow = LoginFlow(prompt, verifier=verifier, state=state, client=client)
        return flow
    device = xai_oauth.request_device_code(client=client)
    prompt = LoginPrompt(
        provider_id="grok",
        kind="device",
        title="Sign in with xAI",
        instructions=f"Open the URL and enter this code: {device.user_code}",
        url=device.verification_uri_complete or device.verification_uri,
        user_code=device.user_code,
        paste_hint="",
    )
    flow = LoginFlow(prompt, device=device, client=client)
    _maybe_open(prompt.url, enabled=open_browser)
    return flow


def _maybe_open(url: str, *, enabled: bool) -> None:
    if not enabled or not url:
        return
    try:
        webbrowser.open(url, new=2, autoraise=True)
    except Exception:
        return
