#!/usr/bin/env python3
"""Automate reward account connections through a GenLogin profile."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable, Optional, Sequence, Tuple

import requests
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


REWARD_URL = "https://rewards.dtelecom.org/reward"
AUTHORIZE_XPATH = '//span[normalize-space(.)="Authorize app"]'
X_OAUTH_CONSENT_XPATH = '//button[@data-testid="OAuth_Consent_Button"]'
DISCORD_ACCOUNT_PICKER_XPATH = '(//*[contains(@class,"lineClamp1__4bd52")])[2]'
PROFILE_CONNECT_KEYS = (
    "cdpUrl",
    "cdpHttpUrl",
    "remotePortUrl",
    "debuggerAddress",
    "remoteDebuggingAddress",
    "remoteDebuggingUrl",
    "debuggingAddress",
    "debuggingUrl",
    "wsEndpoint",
    "webSocketDebuggerUrl",
    "browserWSEndpoint",
    "browserWsEndpoint",
    "ws",
    "websocket",
    "cdpWebSocket",
    "puppeteerUrl",
    "devtoolsFrontendUrl",
)
ACTION_STEPS: Sequence[Tuple[str, str]] = (
    (
        "Connect Discord",
        '//div[normalize-space(.)="Join dTelecom Discord"]/ancestor::*['
        'self::div or self::section or self::article][1]//button[normalize-space(.)="Claim"]',
    ),
    ("Connect X #5", '(//button[normalize-space(.)="Connect X"])[5]'),
    ("Connect X #4", '(//button[normalize-space(.)="Connect X"])[4]'),
)
DEFAULT_BASE_URL = "http://localhost:55550"
ENV_FILE = Path(__file__).resolve().with_name(".env")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Attach Playwright to a GenLogin profile and automate reward connections."
    )
    parser.add_argument(
        "--profile-id",
        default=os.getenv("GENLOGIN_PROFILE_ID"),
        help="GenLogin profile ID to start/attach. Defaults to GENLOGIN_PROFILE_ID.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GENLOGIN_TOKEN"),
        help="GenLogin Bearer token. Defaults to GENLOGIN_TOKEN.",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("GENLOGIN_EMAIL"),
        help="GenLogin email. Defaults to GENLOGIN_EMAIL.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("GENLOGIN_PASSWORD"),
        help="GenLogin password. Defaults to GENLOGIN_PASSWORD.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("GENLOGIN_BASE_URL", DEFAULT_BASE_URL),
        help="GenLogin API base URL. Defaults to GENLOGIN_BASE_URL or http://localhost:55550.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=int,
        default=90,
        help="Seconds to wait for the profile debugging endpoint to become available.",
    )
    parser.add_argument(
        "--action-timeout",
        type=int,
        default=30,
        help="Seconds to wait for page selectors and popup events.",
    )
    parser.add_argument(
        "--screenshot-on-error",
        default="genlogin_reward_error.png",
        help="Path for the error screenshot if automation fails.",
    )
    return parser.parse_args()


def load_dotenv_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        logging.info("No .env file found at %s. Using existing environment variables.", dotenv_path)
        return

    logging.info("Loading environment variables from %s", dotenv_path)
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class GenLoginClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            }
        )
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str) -> Any:
        url = self._url(path)
        logging.info("Calling GenLogin API: %s %s", method, url)
        response = self.session.request(method, url, timeout=self.timeout)
        response.raise_for_status()
        if not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text

    def get_profile_details(self, profile_id: str) -> Any:
        return self._request("GET", f"/backend/profiles/{profile_id}")

    def get_running_profiles(self) -> Any:
        return self._request("GET", "/backend/profiles/running")

    def start_profile(self, profile_id: str) -> Any:
        return self._request("PUT", f"/backend/profiles/{profile_id}/start")


def login_and_get_token(base_url: str, email: str, password: str, timeout: int = 30) -> str:
    login_url = f"{base_url.rstrip('/')}/backend/auth/login"
    logging.info("Logging into GenLogin API with email: %s", email)
    response = requests.post(
        login_url,
        json={"username": email, "password": password},
        headers={"Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    token = extract_token_from_login_payload(payload)
    if not token:
        top_level_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        data_keys: list[str] = []
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            data_keys = sorted(payload["data"].keys())
        raise RuntimeError(
            "GenLogin login succeeded but response did not include access_token. "
            f"top_level_keys={top_level_keys} data_keys={data_keys}"
        )
    return token


def extract_token_from_login_payload(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    candidate_objects = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        candidate_objects.insert(0, data)

    for item in candidate_objects:
        for key in ("access_token", "accessToken", "token", "jwt", "bearerToken"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def walk_values(payload: Any) -> Iterable[Any]:
    yield payload
    if isinstance(payload, dict):
        for value in payload.values():
            yield from walk_values(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from walk_values(item)


def extract_connect_endpoint(payload: Any) -> Optional[str]:
    for item in walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in PROFILE_CONNECT_KEYS:
            if key not in item:
                continue
            value = item[key]
            if isinstance(value, str) and value.strip():
                return normalize_endpoint(value.strip())
    return None


def normalize_endpoint(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        if value.endswith("/json/version"):
            return value[: -len("/json/version")]
        return value
    if value.startswith("ws://") or value.startswith("wss://"):
        return value
    if ":" in value and " " not in value and "/" not in value:
        return f"http://{value}"
    return value


def collect_profile_payloads(
    details_payload: Any,
    start_payload: Any,
    running_payload: Any,
    profile_id: str,
) -> Iterable[Any]:
    yield start_payload
    yield details_payload
    yield running_payload

    if isinstance(running_payload, list):
        for item in running_payload:
            if str(find_profile_id(item)) == str(profile_id):
                yield item
    elif isinstance(running_payload, dict):
        for item in walk_values(running_payload):
            if isinstance(item, dict) and str(find_profile_id(item)) == str(profile_id):
                yield item


def find_profile_id(payload: Any) -> Optional[Any]:
    if not isinstance(payload, dict):
        return None
    for key in ("id", "profile_id", "profileId"):
        if key in payload:
            return payload[key]
    return None


def ensure_profile_started(
    client: GenLoginClient,
    profile_id: str,
    startup_timeout: int,
) -> Tuple[str, Any, Any, Any]:
    details_payload = client.get_profile_details(profile_id)
    endpoint = extract_connect_endpoint(details_payload)
    start_payload: Any = None
    running_payload: Any = None

    if endpoint:
        logging.info("Found browser endpoint directly from profile details.")
        return endpoint, details_payload, start_payload, running_payload

    logging.info("No browser endpoint in profile details. Starting profile %s.", profile_id)
    start_payload = client.start_profile(profile_id)
    endpoint = extract_connect_endpoint(start_payload)
    if endpoint:
        logging.info("Found browser endpoint in start response.")
        return endpoint, details_payload, start_payload, running_payload

    deadline = time.time() + startup_timeout
    while time.time() < deadline:
        logging.info("Polling running profiles for browser endpoint...")
        running_payload = client.get_running_profiles()
        for payload in collect_profile_payloads(details_payload, start_payload, running_payload, profile_id):
            endpoint = extract_connect_endpoint(payload)
            if endpoint:
                logging.info("Found browser endpoint while polling running profiles.")
                return endpoint, details_payload, start_payload, running_payload
        time.sleep(2)

    available_keys = sorted(discover_keys(details_payload) | discover_keys(start_payload) | discover_keys(running_payload))
    raise RuntimeError(
        "Could not find a GenLogin browser endpoint after starting the profile. "
        f"Available response keys: {available_keys}"
    )


def discover_keys(payload: Any) -> set[str]:
    keys: set[str] = set()
    for item in walk_values(payload):
        if isinstance(item, dict):
            keys.update(item.keys())
    return keys


def attach_browser(playwright: Playwright, endpoint: str) -> Browser:
    logging.info("Attaching Playwright to GenLogin browser: %s", endpoint)
    cdp_endpoint = endpoint
    if endpoint.startswith(("ws://", "wss://")) and "/devtools/browser/" in endpoint:
        cdp_endpoint = websocket_endpoint_to_http(endpoint)
        logging.info("Using CDP over HTTP endpoint derived from websocket: %s", cdp_endpoint)
    return playwright.chromium.connect_over_cdp(cdp_endpoint)


def websocket_endpoint_to_http(endpoint: str) -> str:
    if endpoint.startswith("ws://"):
        remainder = endpoint[len("ws://") :]
        scheme = "http://"
    elif endpoint.startswith("wss://"):
        remainder = endpoint[len("wss://") :]
        scheme = "https://"
    else:
        return endpoint

    host_port = remainder.split("/", 1)[0]
    return f"{scheme}{host_port}"


def pick_context(browser: Browser) -> BrowserContext:
    contexts = browser.contexts
    if contexts:
        logging.info("Using existing browser context.")
        return contexts[0]
    logging.info("No existing context found. Creating a new one.")
    return browser.new_context()


def pick_page(context: BrowserContext) -> Page:
    pages = [page for page in context.pages if not page.is_closed()]
    if pages:
        logging.info("Found %s open page(s) in the profile context; creating a fresh page for automation.", len(pages))
    else:
        logging.info("No open page found. Creating a new page.")
    return context.new_page()


def wait_for_popup_after_click(
    page: Page, context: BrowserContext, trigger_xpath: str, timeout_ms: int
) -> Page:
    known_pages = list(context.pages)
    if not click_xpath(page, trigger_xpath, timeout_ms):
        raise LookupError(f"Could not find trigger selector: {trigger_xpath}")
    logging.info("Clicked trigger selector. Waiting for a new popup/tab to appear.")
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        current_pages = list(context.pages)
        if len(current_pages) > len(known_pages):
            popup = next((p for p in current_pages if p not in known_pages), current_pages[-1])
            popup.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            return popup
        time.sleep(0.2)
    raise RuntimeError(f"Clicked selector but no popup/tab was detected: {trigger_xpath}")


def click_x_oauth_consent_on_same_tab(page: Page, trigger_xpath: str, timeout_ms: int) -> None:
    if not click_xpath(page, trigger_xpath, timeout_ms):
        raise LookupError(f"Could not find trigger selector: {trigger_xpath}")
    logging.info("Clicked X trigger selector. Waiting 10 seconds before clicking OAuth consent button.")
    page.wait_for_timeout(10_000)
    if not click_xpath(page, X_OAUTH_CONSENT_XPATH, timeout_ms):
        raise RuntimeError(
            f"Clicked X selector but OAuth consent button was not detected: {X_OAUTH_CONSENT_XPATH}"
        )
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logging.info("X authorize page did not reach networkidle after consent; continuing.")


def click_xpath(page: Page, xpath: str, timeout_ms: int) -> bool:
    logging.info("Waiting for selector: %s", xpath)
    locator = page.locator(f"xpath={xpath}")
    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logging.warning("Selector not found or not visible within timeout: %s", xpath)
        return False
    logging.info("Clicking selector: %s", xpath)
    locator.click(timeout=timeout_ms)
    return True


def click_authorize_in_popup(popup: Page, timeout_ms: int) -> None:
    popup.bring_to_front()
    logging.info("Switched focus to popup/tab: %s", popup.url)
    popup.wait_for_timeout(10_000)
    logging.info("Waiting 10 seconds before clicking Authorize app.")
    click_xpath(popup, AUTHORIZE_XPATH, timeout_ms)
    try:
        popup.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logging.info("Popup did not reach networkidle after authorization; continuing.")


def select_discord_account_in_popup(popup: Page, timeout_ms: int) -> None:
    popup.bring_to_front()
    logging.info("Switched focus to Discord popup/tab: %s", popup.url)
    popup.wait_for_timeout(10_000)
    logging.info("Waiting 10 seconds before selecting the Discord account.")
    locator = popup.locator(f"xpath={DISCORD_ACCOUNT_PICKER_XPATH}")
    logging.info("Waiting for Discord account selector: %s", DISCORD_ACCOUNT_PICKER_XPATH)
    locator.wait_for(state="visible", timeout=timeout_ms)
    logging.info("Scrolling Discord account selector into view.")
    locator.scroll_into_view_if_needed(timeout=timeout_ms)
    logging.info("Clicking Discord account selector: %s", DISCORD_ACCOUNT_PICKER_XPATH)
    locator.click(timeout=timeout_ms)
    popup.wait_for_timeout(1_000)


def handle_discord_popup(popup: Page, timeout_ms: int) -> None:
    select_discord_account_in_popup(popup, timeout_ms)
    click_xpath(popup, AUTHORIZE_XPATH, timeout_ms)
    try:
        popup.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logging.info("Discord popup did not reach networkidle after authorization; continuing.")


def perform_connect_action(
    page: Page,
    context: BrowserContext,
    action_name: str,
    trigger_xpath: str,
    timeout_ms: int,
) -> None:
    logging.info("Starting action: %s", action_name)
    page.bring_to_front()
    try:
        if action_name.startswith("Connect X"):
            click_x_oauth_consent_on_same_tab(page, trigger_xpath, timeout_ms)
            logging.info("Completed action: %s", action_name)
            return

        popup = wait_for_popup_after_click(page, context, trigger_xpath, timeout_ms)
    except LookupError:
        logging.warning("Skipped action because trigger selector was not found: %s (%s)", action_name, trigger_xpath)
        return
    if action_name == "Connect Discord":
        handle_discord_popup(popup, timeout_ms)
    else:
        click_authorize_in_popup(popup, timeout_ms)
    try:
        popup.wait_for_event("close", timeout=5_000)
        logging.info("Popup closed after authorization.")
    except PlaywrightTimeoutError:
        logging.info("Popup stayed open after authorization; returning focus to the main page.")
    page.bring_to_front()
    logging.info("Completed action: %s", action_name)


def save_error_screenshot(page: Optional[Page], path: str) -> None:
    if page is None or page.is_closed():
        return
    try:
        page.screenshot(path=path, full_page=True)
        logging.info("Saved error screenshot to %s", path)
    except PlaywrightError as exc:
        logging.warning("Could not save error screenshot: %s", exc)


def validate_args(args: argparse.Namespace) -> None:
    if not args.profile_id:
        raise ValueError("Missing GenLogin profile ID. Set GENLOGIN_PROFILE_ID in .env or pass --profile-id.")
    has_token = bool(args.token)
    has_email_password = bool(args.email and args.password)
    if not has_token and not has_email_password:
        raise ValueError(
            "Missing GenLogin authentication. Set GENLOGIN_TOKEN, or set both "
            "GENLOGIN_EMAIL and GENLOGIN_PASSWORD in .env."
        )


def main() -> int:
    configure_logging()
    load_dotenv_file(ENV_FILE)
    args = parse_args()

    browser: Optional[Browser] = None
    page: Optional[Page] = None
    playwright: Optional[Playwright] = None

    try:
        validate_args(args)

        token = args.token
        if not token:
            token = login_and_get_token(args.base_url, args.email, args.password)

        client = GenLoginClient(args.base_url, token)
        endpoint, details_payload, start_payload, running_payload = ensure_profile_started(
            client,
            args.profile_id,
            args.startup_timeout,
        )
        logging.info(
            "Resolved GenLogin browser endpoint. details_keys=%s start_keys=%s running_keys=%s",
            sorted(discover_keys(details_payload)),
            sorted(discover_keys(start_payload)),
            sorted(discover_keys(running_payload)),
        )

        playwright = sync_playwright().start()
        browser = attach_browser(playwright, endpoint)
        context = pick_context(browser)
        page = pick_page(context)

        logging.info("Opening reward page: %s", REWARD_URL)
        page.goto(REWARD_URL, wait_until="domcontentloaded", timeout=args.action_timeout * 1000)
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeoutError:
            logging.info("Main page did not reach networkidle quickly; continuing.")

        for action_name, trigger_xpath in ACTION_STEPS:
            perform_connect_action(
                page=page,
                context=context,
                action_name=action_name,
                trigger_xpath=trigger_xpath,
                timeout_ms=args.action_timeout * 1000,
            )

        logging.info("All reward connection steps completed successfully.")
        return 0
    except Exception as exc:
        logging.exception("Automation failed: %s", exc)
        save_error_screenshot(page, args.screenshot_on_error)
        return 1
    finally:
        if browser is not None:
            try:
                browser.close()
                logging.info("Closed Playwright browser connection.")
            except PlaywrightError as exc:
                logging.warning("Could not close Playwright browser connection cleanly: %s", exc)
        if playwright is not None:
            try:
                playwright.stop()
            except PlaywrightError as exc:
                logging.warning("Could not stop Playwright cleanly: %s", exc)


if __name__ == "__main__":
    sys.exit(main())
