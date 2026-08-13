from flask import Flask, render_template, request, jsonify, redirect, session
import ssl, json, time, re, base64, urllib.request, urllib.error, os
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

    # Step 1: GET main page to get XSRF token + session cookies
    req = urllib.request.Request(base)
    for k, v in BROWSER_HEADERS.items():
        req.add_header(k, v)
    resp = opener.open(req, timeout=30)
    html = resp.read().decode('utf-8', 'ignore')

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

    # Cricash24/SpinMatch99/SpinJeet365: CSRF meta is on /mobile page, not homepage
    if not csrf_meta and site_key in ("cricash24.com", "spinmatch99.com", "spinjeet365.com"):
        try:
            mob_req = urllib.request.Request(f"{base}/mobile")
            for k, v in BROWSER_HEADERS.items():
                mob_req.add_header(k, v)
            mob_resp = opener.open(mob_req, timeout=30)
            mob_html = mob_resp.read().decode('utf-8', 'ignore')
            mob_m = re.search(r'meta\s+name="csrf-token"\s+content="([^"]+)"', mob_html)
            if mob_m:
                csrf_meta = mob_m.group(1)
        except:
            pass

    if not xsrf:
        raise Exception("Could not get XSRF token from site")

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

    elif site_key in ("playinhorse.com", "betinexchange88.com"):
        login_data = json.dumps({"username": username, "password": password}).encode()
        login_req = urllib.request.Request(f"{base}/api2/v2/login",
            data=login_data,
            headers=make_xhr_headers("application/json"),
            method="POST")

    elif site_key in ("cricash24.com", "spinmatch99.com", "spinjeet365.com"):
        login_data = urlencode({
            "email": username, "password": password,
        }).encode()
        login_req = urllib.request.Request(f"{base}/api2/v2/login",
            data=login_data,
            headers=make_xhr_headers("application/x-www-form-urlencoded",
                {"X-CSRF-Token": csrf_meta or xsrf}),
            method="POST")

    elif site_key == "khelo24match99.com":
        login_data = json.dumps({"username": username, "email": username, "password": password}).encode()
        login_req = urllib.request.Request(f"{base}/api2/login",
            data=login_data,
            headers=make_xhr_headers("application/json",
                {"X-CSRF-TOKEN": csrf_meta or xsrf}),
            method="POST")

    else:
        raise Exception(f"No login handler for {site_key}")

    # Step 3: Execute login
    try:
        resp = opener.open(login_req, timeout=30)
        body = resp.read().decode('utf-8', 'ignore')
        status = resp.status
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
        elif resp_status not in (200, True) and not resp_json.get("success"):
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
    return re.search(r'token=([^&]+)', gu).group(1)


def get_sid(token):
    url = f"{GAME_BASE}/cwstartgamev2.do?bankId=winmatch&gameId=30239&mode=real&token={token}&lang=en"
    req = urllib.request.Request(url, headers={
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
        raise Exception("Could not get game session")
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


def get_state(key):
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
        return render_template('nan_login.html', sites=SITES)
    return render_template('nan_dashboard.html',
        site_name=session.get('site_name', ''),
        balance=session.get('balance', 0),
        username=session.get('username', ''),
    )


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
        session['logged_in'] = True
        session['site'] = site_key
        session['site_name'] = site['name']
        session['cookies'] = cookies
        session['balance'] = balance
        session['username'] = username
        session['sid'] = sid  # Game session ID — unique per player

        st = get_state(username)
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
    """Wipe all in-memory state and sessions."""
    global sessions_state
    sessions_state = {}
    session.clear()
    return jsonify({"success": True, "message": "All cache and session data cleared"})


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

        st = get_state(session.get('username', 'default'))
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
        st = get_state(session.get('username', 'default'))
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
