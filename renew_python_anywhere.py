import os
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.pythonanywhere.com"
LOG_FILE = ".github/logs/workflow_runs.log"
ACCOUNT_PATTERN = re.compile(r"^ACCOUNT_(\d+)_(USERNAME|PASSWORD)$")

STATUS_SUCCESS = "SUCCESS"
STATUS_SKIPPED = "SKIPPED"
STATUS_FAILED = "FAILED"


def log(message):
    """Encoding-safe console output.

    Emoji and other non-ASCII markers must not crash a run on a console
    whose encoding cannot represent them (e.g. Windows GBK); unencodable
    characters are replaced instead.
    """
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = message.encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        )
        print(safe)


def get_accounts_from_env():
    """Return configured accounts, incomplete pairs, and duplicate warnings."""
    accounts = []
    incomplete = []
    warnings = []
    seen_credentials = set()
    numbered = {}

    credentials_json = os.environ.get("ACCOUNT_CREDENTIALS_JSON", "").strip()
    if credentials_json:
        try:
            configured = json.loads(credentials_json)
        except json.JSONDecodeError:
            incomplete.append("ACCOUNT_CREDENTIALS_JSON (invalid JSON)")
            configured = []
        if isinstance(configured, dict):
            configured = [
                {"username": username, "password": password}
                for username, password in configured.items()
            ]
        if not isinstance(configured, list):
            incomplete.append("ACCOUNT_CREDENTIALS_JSON (expected a list or object)")
            configured = []
        for index, account in enumerate(configured, 1):
            if not isinstance(account, dict):
                incomplete.append(f"ACCOUNT_CREDENTIALS_JSON item {index}")
                continue
            username = account.get("username", "")
            password = account.get("password", "")
            username = username.strip() if isinstance(username, str) else ""
            password = password.strip() if isinstance(password, str) else ""
            label = f"ACCOUNT_CREDENTIALS_JSON item {index}"
            if not username or not password:
                incomplete.append(label)
                continue
            if (username, password) in seen_credentials:
                warnings.append(f"{label} (duplicate credentials, skipped)")
                continue
            seen_credentials.add((username, password))
            accounts.append((label, username, password))

    legacy_username = os.environ.get("PA_USERNAME", "").strip()
    legacy_password = os.environ.get("PA_PASSWORD", "").strip()
    if legacy_username or legacy_password:
        if legacy_username and legacy_password:
            if (legacy_username, legacy_password) in seen_credentials:
                warnings.append("PA_USERNAME/PA_PASSWORD (duplicate credentials, skipped)")
            else:
                seen_credentials.add((legacy_username, legacy_password))
                accounts.append(("PA", legacy_username, legacy_password))
        else:
            incomplete.append("PA_USERNAME/PA_PASSWORD")

    for name, value in os.environ.items():
        match = ACCOUNT_PATTERN.match(name)
        if match:
            index, field = match.groups()
            numbered.setdefault(index, {})[field] = value.strip()

    for index in sorted(numbered, key=int):
        username = numbered[index].get("USERNAME", "")
        password = numbered[index].get("PASSWORD", "")
        if not username and not password:
            continue
        label = f"ACCOUNT_{index}_USERNAME/ACCOUNT_{index}_PASSWORD"
        if not username or not password:
            incomplete.append(label)
            continue
        if (username, password) in seen_credentials:
            warnings.append(f"{label} (duplicate credentials, skipped)")
            continue
        seen_credentials.add((username, password))
        accounts.append((f"ACCOUNT_{index}", username, password))

    return accounts, incomplete, warnings


def login(session, username, password):
    login_url = f"{BASE_URL}/login/"
    log(f"🔐 Logging in as {username}...")
    login_page = session.get(login_url, timeout=10)
    login_page.raise_for_status()
    soup = BeautifulSoup(login_page.content, "html.parser")
    csrf_token = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf_token:
        log("❌ Could not find CSRF token on login page")
        return False

    response = session.post(
        login_url,
        data={
            "csrfmiddlewaretoken": csrf_token["value"],
            "auth-username": username,
            "auth-password": password,
            "login_view-current_step": "auth",
        },
        headers={"Referer": login_url},
        timeout=10,
        allow_redirects=True,
    )
    response.raise_for_status()
    if "log out" not in response.text.lower() or "login" in response.url.lower():
        log("❌ Login failed")
        return False

    log("✅ Login successful")
    return True


def get_webapp_expiry(soup, domain):
    pane = soup.find(id=f"id_{domain.replace('.', '_')}")
    if pane:
        expiry = pane.find("p", class_="webapp_expiry")
        if expiry and expiry.find("strong"):
            return expiry.find("strong").text.strip()
    return "Unknown Date"


def _item(kind, name, ok, status, detail):
    """Build one checkable per-item outcome.

    kind:   "Web App" or "Task"
    name:   domain (web apps) or command / task list label (tasks)
    ok:     whether the item counts toward account success
    status: STATUS_SUCCESS / STATUS_SKIPPED / STATUS_FAILED
    detail: human-readable reason or old -> new expiry
    """
    return {
        "kind": kind,
        "name": name,
        "ok": ok,
        "status": status,
        "detail": detail,
    }


def render_item(item):
    return f"{item['kind']}: {item['name']} — {item['status']}: {item['detail']}"


def renew_webapps(session, username):
    """Renew every web app form, recording one outcome per domain.

    A failure on one form (missing CSRF, bad POST status, unexpected
    redirect, refresh error) never stops the remaining forms from being
    attempted. Returns (all_ok, per_item_results).
    """
    dashboard_url = f"{BASE_URL}/user/{username}/webapps/"
    log("📊 Checking web apps...")
    time.sleep(1)
    try:
        dashboard = session.get(dashboard_url, timeout=10)
    except requests.RequestException as error:
        return False, [
            _item(
                "Web App",
                "(dashboard)",
                False,
                STATUS_FAILED,
                f"dashboard request failed: {error}",
            )
        ]
    if dashboard.status_code != 200:
        return False, [
            _item(
                "Web App",
                "(dashboard)",
                False,
                STATUS_FAILED,
                f"dashboard request failed, HTTP {dashboard.status_code}",
            )
        ]

    soup = BeautifulSoup(dashboard.content, "html.parser")
    forms = [
        form
        for form in soup.find_all("form", action=True)
        if "/extend" in form["action"].lower()
    ]
    if not forms:
        log("ℹ️ No web apps found on this account.")
        return True, []

    results = []
    for form in forms:
        action = urljoin(BASE_URL, form["action"])
        domain = action.rstrip("/").split("/webapps/")[-1].replace("/extend", "")
        csrf = form.find("input", {"name": "csrfmiddlewaretoken"})
        if not csrf:
            log(f"❌ Missing CSRF token for web app: {domain}")
            results.append(
                _item(
                    "Web App",
                    domain,
                    False,
                    STATUS_FAILED,
                    "missing CSRF token in extend form",
                )
            )
            continue

        old_expiry = get_webapp_expiry(soup, domain)
        try:
            response = session.post(
                action,
                data={"csrfmiddlewaretoken": csrf["value"]},
                headers={"Referer": dashboard_url},
                timeout=10,
            )
        except requests.RequestException as error:
            results.append(
                _item(
                    "Web App",
                    domain,
                    False,
                    STATUS_FAILED,
                    f"extend request failed: {error}",
                )
            )
            continue

        if response.status_code != 200:
            results.append(
                _item(
                    "Web App",
                    domain,
                    False,
                    STATUS_FAILED,
                    f"extend POST returned HTTP {response.status_code}",
                )
            )
            continue
        if "webapps" not in response.url.lower():
            results.append(
                _item(
                    "Web App",
                    domain,
                    False,
                    STATUS_FAILED,
                    f"unexpected redirect after extend: {response.url}",
                )
            )
            continue

        time.sleep(1)
        try:
            refreshed = session.get(dashboard_url, timeout=10)
        except requests.RequestException as error:
            results.append(
                _item(
                    "Web App",
                    domain,
                    False,
                    STATUS_FAILED,
                    f"renewed but dashboard refresh failed: {error}",
                )
            )
            continue
        if refreshed.status_code != 200:
            results.append(
                _item(
                    "Web App",
                    domain,
                    False,
                    STATUS_FAILED,
                    "renewed but dashboard refresh failed, "
                    f"HTTP {refreshed.status_code}",
                )
            )
            continue

        new_expiry = get_webapp_expiry(
            BeautifulSoup(refreshed.content, "html.parser"), domain
        )
        results.append(
            _item(
                "Web App",
                domain,
                True,
                STATUS_SUCCESS,
                f"{old_expiry} → {new_expiry}",
            )
        )
        log(f"✅ Renewed web app: {domain} ({old_expiry} → {new_expiry})")

    return not any(not item["ok"] for item in results), results


def renew_scheduled_tasks(session, username):
    """Renew every scheduled task, recording one outcome per task.

    List-level problems (request failure, non-JSON payload, missing/
    non-list ``results``) become a single task-level FAILED record instead
    of aborting the account. Per-task problems (missing extend URL, extend
    POST failure, refresh failure/invalid payload) only affect that task.
    Returns (all_ok, per_item_results).
    """
    tasks_page_url = f"{BASE_URL}/user/{username}/tasks_tab/"
    tasks_api_url = f"{BASE_URL}/api/v0/user/{username}/schedule/"
    log("🗓️ Checking scheduled tasks...")
    time.sleep(1)

    try:
        response = session.get(
            tasks_api_url, headers={"Referer": tasks_page_url}, timeout=10
        )
    except requests.RequestException as error:
        return False, [
            _item(
                "Task",
                "task list",
                False,
                STATUS_FAILED,
                f"list request failed: {error}",
            )
        ]

    if response.status_code != 200:
        return False, [
            _item(
                "Task",
                "task list",
                False,
                STATUS_FAILED,
                f"list request failed, HTTP {response.status_code}",
            )
        ]

    try:
        payload = response.json()
    except ValueError as error:
        reason = str(error) or "response was not valid JSON"
        return False, [
            _item(
                "Task",
                "task list",
                False,
                STATUS_FAILED,
                f"list response was not valid JSON ({reason})",
            )
        ]

    tasks = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        return False, [
            _item(
                "Task",
                "task list",
                False,
                STATUS_FAILED,
                "list response did not contain a results list",
            )
        ]

    if not tasks:
        log("ℹ️ No scheduled tasks found on this account.")
        return True, []

    csrf_token = session.cookies.get("csrftoken")
    if not csrf_token:
        return False, [
            _item(
                "Task",
                "task list",
                False,
                STATUS_FAILED,
                "missing CSRF token for task extension",
            )
        ]

    results = []
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            results.append(
                _item(
                    "Task",
                    f"task entry {index}",
                    False,
                    STATUS_FAILED,
                    "task entry was not a JSON object",
                )
            )
            continue

        description = (
            task.get("command")
            or (f"task {task.get('id')}" if task.get("id") is not None else None)
            or f"task entry {index}"
        )
        old_expiry = task.get("expiry")
        extend_url = task.get("extend_url")
        if not extend_url:
            log(f"⏭️ Skipping task without extend URL: {description}")
            results.append(
                _item(
                    "Task",
                    description,
                    True,
                    STATUS_SKIPPED,
                    "no extend URL available",
                )
            )
            continue

        try:
            result = session.post(
                urljoin(BASE_URL, extend_url),
                headers={"X-CSRFToken": csrf_token, "Referer": tasks_page_url},
                timeout=10,
            )
        except requests.RequestException as error:
            results.append(
                _item(
                    "Task",
                    description,
                    False,
                    STATUS_FAILED,
                    f"extend request failed: {error}",
                )
            )
            continue
        if result.status_code != 200:
            results.append(
                _item(
                    "Task",
                    description,
                    False,
                    STATUS_FAILED,
                    f"extend POST returned HTTP {result.status_code}",
                )
            )
            continue

        time.sleep(1)
        try:
            refreshed = session.get(
                tasks_api_url, headers={"Referer": tasks_page_url}, timeout=10
            )
        except requests.RequestException as error:
            results.append(
                _item(
                    "Task",
                    description,
                    False,
                    STATUS_FAILED,
                    f"renewed but list refresh failed: {error}",
                )
            )
            continue
        if refreshed.status_code != 200:
            results.append(
                _item(
                    "Task",
                    description,
                    False,
                    STATUS_FAILED,
                    f"renewed but list refresh failed, HTTP {refreshed.status_code}",
                )
            )
            continue

        try:
            refreshed_payload = refreshed.json()
        except ValueError:
            results.append(
                _item(
                    "Task",
                    description,
                    False,
                    STATUS_FAILED,
                    "renewed but refresh response was not valid JSON",
                )
            )
            continue
        tasks_after = (
            refreshed_payload.get("results")
            if isinstance(refreshed_payload, dict)
            else refreshed_payload
        )
        if not isinstance(tasks_after, list):
            results.append(
                _item(
                    "Task",
                    description,
                    False,
                    STATUS_FAILED,
                    "renewed but refresh response did not contain a results list",
                )
            )
            continue

        new_expiry = next(
            (
                task_after.get("expiry")
                for task_after in tasks_after
                if isinstance(task_after, dict)
                and task_after.get("id") == task.get("id")
            ),
            old_expiry,
        )

        if new_expiry == old_expiry:
            results.append(
                _item(
                    "Task",
                    description,
                    True,
                    STATUS_SUCCESS,
                    f"Already maxed out at: {old_expiry}",
                )
            )
            log(f"✅ Task already maxed out: {description} ({old_expiry})")
        else:
            results.append(
                _item(
                    "Task",
                    description,
                    True,
                    STATUS_SUCCESS,
                    f"{old_expiry} → {new_expiry}",
                )
            )
            log(f"✅ Renewed task: {description} ({old_expiry} → {new_expiry})")

    return not any(not item["ok"] for item in results), results


def renew_account(label, username, password):
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )

    try:
        logged_in = login(session, username, password)
    except requests.Timeout:
        return False, ["Login failed: request timed out"]
    except requests.RequestException as error:
        return False, [f"Login failed: network error: {error}"]
    except Exception as error:
        return False, [f"Login failed: unexpected error: {error}"]
    if not logged_in:
        return False, ["Login failed"]

    # Web apps and scheduled tasks are independent: a failure in one stage
    # must not prevent the other stage from being attempted.
    try:
        webapps_ok, webapp_results = renew_webapps(session, username)
    except Exception as error:
        webapps_ok = False
        webapp_results = [
            _item(
                "Web App",
                "(all web apps)",
                False,
                STATUS_FAILED,
                f"unexpected error: {error}",
            )
        ]

    try:
        tasks_ok, task_results = renew_scheduled_tasks(session, username)
    except Exception as error:
        tasks_ok = False
        task_results = [
            _item(
                "Task",
                "task list",
                False,
                STATUS_FAILED,
                f"unexpected error: {error}",
            )
        ]

    details = [render_item(item) for item in webapp_results + task_results]
    return webapps_ok and tasks_ok, details


def write_log(status, accounts, incomplete, warnings, results):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    lines = [
        "========================================",
        f"Workflow Run: {timestamp}",
        f"Status: {status}",
        f"Trigger: {os.environ.get('GITHUB_EVENT_NAME', 'local')}",
        f"Repository: {os.environ.get('GITHUB_REPOSITORY', 'local')}",
        f"Branch: {os.environ.get('GITHUB_REF_NAME', 'local')}",
        f"Run ID: {os.environ.get('GITHUB_RUN_ID', 'local')}",
        "Configured accounts:",
    ]
    if accounts:
        lines.extend(f"- {label}: {username}" for label, username, _ in accounts)
    else:
        lines.append("- None")
    if incomplete:
        lines.append("Incomplete or skipped credentials:")
        lines.extend(f"- {item}" for item in incomplete)
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings)
    lines.append("Renewal details:")
    if results:
        for label, success, details in results:
            lines.append(f"- {label}: {'SUCCESS' if success else 'FAILED'}")
            if details:
                lines.extend(f"  - {detail}" for detail in details)
            else:
                lines.append("  - No web apps or scheduled tasks found.")
    else:
        lines.append("- No complete accounts were configured.")
    lines.extend(["========================================", ""])
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write("\n".join(lines))


def run():
    accounts, incomplete, warnings = get_accounts_from_env()
    results = []
    for label, username, password in accounts:
        log(f"\n{'=' * 50}\nProcessing {label}: {username}\n{'=' * 50}")
        success, details = renew_account(label, username, password)
        results.append((label, success, details))

    any_failed = any(not success for _, success, _ in results)
    if any_failed:
        status = "FAILED"
    elif not accounts:
        status = "FAILED"
    elif incomplete:
        status = "PARTIAL"
    else:
        status = "SUCCESS"
    write_log(status, accounts, incomplete, warnings, results)
    return 1 if status == "FAILED" else 0


if __name__ == "__main__":
    sys.exit(run())
