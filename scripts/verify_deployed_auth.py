"""Check the deployed authentication boundary over the public HTTPS URL.

Usage: DEPLOY_ORIGIN=https://host DEMO_PARTICIPANT_PASSWORD=... python scripts/verify_deployed_auth.py
Passwords are read from the environment only and never printed.
"""

import os
import sys

import httpx

PARTICIPANT = "participant-01"


def check(results, name, passed):
    results.append((name, bool(passed)))


def cookie_attributes(response, name):
    for value in response.headers.get_list("set-cookie"):
        if value.startswith(name + "="):
            return value
    return ""


def main():
    origin = os.environ["DEPLOY_ORIGIN"].rstrip("/")
    password = os.environ["DEMO_PARTICIPANT_PASSWORD"]
    if not origin.startswith("https://"):
        sys.exit("DEPLOY_ORIGIN must be an https:// origin")
    results = []
    plain = httpx.get("http://" + origin.removeprefix("https://") + "/api/health")
    check(results, "http_redirects_to_https", plain.status_code in (301, 308))

    with httpx.Client(base_url=origin, timeout=15) as browser:
        check(results, "anonymous_me_401", browser.get("/api/auth/me").status_code == 401)
        bootstrap = browser.get("/api/auth/csrf")
        check(results, "csrf_bootstrap_200", bootstrap.status_code == 200)
        nonce = cookie_attributes(bootstrap, "__Host-serentable_csrf")
        check(
            results,
            "csrf_cookie_host_secure_httponly_lax",
            all(part in nonce for part in ("Secure", "HttpOnly", "SameSite=lax", "Path=/"))
            and "Domain=" not in nonce,
        )
        token = bootstrap.json().get("csrf_token", "")
        foreign = browser.post(
            "/api/auth/login",
            headers={"Origin": "https://attacker.example", "X-CSRF-Token": token},
            json={"login_id": PARTICIPANT, "password": password},
        )
        check(results, "foreign_origin_login_403", foreign.status_code == 403)
        login = browser.post(
            "/api/auth/login",
            headers={"Origin": origin, "X-CSRF-Token": token},
            json={"login_id": PARTICIPANT, "password": password},
        )
        check(results, "participant_login_200", login.status_code == 200)
        session = cookie_attributes(login, "__Host-serentable_session")
        check(
            results,
            "session_cookie_host_secure_httponly",
            all(part in session for part in ("Secure", "HttpOnly", "SameSite=lax")),
        )
        check(results, "private_no_store", login.headers.get("cache-control") == "no-store")
        me = browser.get("/api/auth/me")
        check(results, "session_me_200", me.status_code == 200)
        check(
            results,
            "admin_denied_403",
            browser.get("/api/admin/participants").status_code == 403,
        )
        check(results, "own_profile_200", browser.get("/api/me/profile").status_code == 200)
        token = browser.get("/api/auth/csrf").json().get("csrf_token", "")
        logout = browser.post(
            "/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": token}
        )
        check(results, "logout_200", logout.status_code == 200)
        check(results, "after_logout_401", browser.get("/api/auth/me").status_code == 401)

    for name, passed in results:
        print(("PASS " if passed else "FAIL ") + name)
    sys.exit(0 if all(passed for _, passed in results) else 1)


if __name__ == "__main__":
    main()
