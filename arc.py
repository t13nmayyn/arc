#!/usr/bin/env python3
"""
A.R.C — Autonomous Registration Companion
arc.ai
"""
import asyncio, os, sys, json, time

# ── Palette: deep space + neon ────────────────────────────────────────────────
RST  = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"

# snake body colours  (warm → cool gradient)
S1   = "\033[38;2;255;80;120m"    # #FF5078  hot pink
S2   = "\033[38;2;200;60;255m"    # #C83CFF  violet
S3   = "\033[38;2;100;60;240m"    # #643CF0  indigo
S4   = "\033[38;2;60;120;255m"    # #3C78FF  royal blue
S5   = "\033[38;2;0;200;255m"     # #00C8FF  electric cyan

# UI colours
PRP  = "\033[38;2;180;80;255m"    # #B450FF  bright purple
IND  = "\033[38;2;100;80;220m"    # #6450DC  indigo
BLU  = "\033[38;2;100;160;255m"   # #64A0FF  blue
CYN  = "\033[38;2;0;210;255m"     # #00D2FF  cyan
MGT  = "\033[38;2;255;60;180m"    # #FF3CB4  magenta
GRN  = "\033[38;2;60;230;140m"    # #3CE68C  green
YLW  = "\033[38;2;255;200;60m"    # #FFC83C  gold
RED  = "\033[38;2;255;70;90m"     # #FF465A  red
WHT  = "\033[38;2;230;220;255m"   # #E6DCFF  lavender white
DIM2 = "\033[38;2;80;70;110m"     # #50466E  muted purple

def rc(col,t):  return f"{col}{t}{RST}"
def b(t):       return f"{BOLD}{t}{RST}"
def d(t):       return f"{DIM}{t}{RST}"
def hi(t):      return rc(PRP, b(t))

# ── arc.ai logo ───────────────────────────────────────────────────────────────
LOGO = f"""
  {rc(S1,b(' █████╗ '))} {rc(S3,b('██████╗  ██████╗'))}      {rc(MGT,b('·'))} {rc(WHT,b('arc.ai'))}
  {rc(S1,b('██╔══██╗'))} {rc(S3,b('██╔══██╗██╔════╝'))}    {rc(DIM2,'autonomous')}
  {rc(S2,b('███████║'))} {rc(S4,b('██████╔╝██║     '))}    {rc(DIM2,'registration')}
  {rc(S2,b('██╔══██║'))} {rc(S4,b('██╔══██╗██║     '))}    {rc(DIM2,'companion')}
  {rc(S3,b('██║  ██║'))} {rc(S5,b('██║  ██║╚██████╗'))}
  {rc(S3,b('╚═╝  ╚═╝'))} {rc(S5,b('╚═╝  ╚═╝ ╚═════╝'))}
"""

# ── Snake animation ───────────────────────────────────────────────────────────
def snake_intro():
    """Multi-colour snake crawls in, then resolves to arc.ai"""
    width = 44
    head  = f"{rc(GRN,b('◉'))}"
    trail = [S1,S2,S3,S4,S5,S4,S3,S2]

    for pos in range(0, width, 2):
        body = ""
        for i, col in enumerate(trail):
            bpos = pos - i * 2
            if bpos >= 0:
                body = rc(col,"━") + body
        pad  = " " * (width - pos)
        line = f"\r  {body}{head}{pad}"
        sys.stdout.write(line)
        sys.stdout.flush()
        time.sleep(0.045)

    # snake reaches logo — flash
    for col in [S1, S2, S5, WHT]:
        sys.stdout.write(f"\r  {rc(col,b('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'))}")
        sys.stdout.flush()
        time.sleep(0.07)

    sys.stdout.write(f"\r  {rc(GRN,b('◉'))} {rc(WHT,b('arc.ai'))}  {d('ready')}{'           '}\n")
    sys.stdout.flush()
    time.sleep(0.2)


def show_banner():
    os.system("clear" if os.name != "nt" else "cls")
    print(LOGO)
    snake_intro()
    print()


# ── Dividers ──────────────────────────────────────────────────────────────────
DIV  = f"  {rc(DIM2,'─'*50)}"
DIV2 = f"  {rc(IND,'·'*50)}"

# ── UI helpers ────────────────────────────────────────────────────────────────
def sec(t):
    print(); print(f"  {rc(MGT,'◆')} {b(rc(WHT,t))}"); print(DIV)

def ask(text, default=""):
    hint = f" {d(f'[{default}]')}" if default else ""
    sys.stdout.write(f"\n  {rc(PRP,'▸')} {rc(WHT,text)}{hint}  ")
    sys.stdout.flush()
    v = input().strip()
    return v if v else default

def yn(text):
    sys.stdout.write(f"\n  {rc(YLW,'▸')} {rc(WHT,text)} {d('[y/N]')}  ")
    sys.stdout.flush()
    return input().strip().lower() == 'y'

def ok(t):   print(f"  {rc(GRN,'◉')}  {t}")
def info(t): print(f"  {rc(BLU,'·')}  {t}")
def warn(t): print(f"  {rc(YLW,'!')}  {rc(YLW,t)}")
def err(t):  print(f"  {rc(RED,'✕')}  {rc(RED,t)}")
def sp():    print()

def step_cb(action, detail, status):
    icons  = {"run": rc(YLW,"◌"), "ok": rc(GRN,"◉"), "fail": rc(RED,"✕")}
    icon   = icons.get(status, " ")
    action = str(action) if action else "unknown"
    detail = str(detail) if detail else ""
    print(f"    {icon}  {rc(BLU,action):<22} {d(detail[:55])}")

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE         = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(HERE, "sessions")
PROFILE_FILE = os.path.expanduser("~/.arc/profile.json")
WORK_DIR     = os.path.join(HERE, "workspace")

def load_profile():
    if os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE) as f: return json.load(f)
    return {}

def save_profile(data):
    os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
    with open(PROFILE_FILE,"w") as f: json.dump(data, f, indent=2)

def list_sessions():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return [f.replace(".json","") for f in os.listdir(SESSIONS_DIR)
            if f.endswith(".json") and not f.endswith("_meta.json")]

def find_google_session():
    for name in list_sessions():
        if any(k in name.lower() for k in ["google","gmail","form","gform"]):
            return name
    return None

# ── Session warning block ─────────────────────────────────────────────────────
def session_risks_warning(url: str):
    """Tell the user what to expect when no session exists."""
    sp()
    print(DIV2)
    print(f"  {rc(YLW,b('  No saved session found'))}")
    print(DIV2)
    sp()
    info(f"A.R.C will try to open {rc(CYN, url[:60])}")
    info("and attempt to log in automatically.")
    sp()
    print(f"  {rc(YLW,'!')}  {b('Things that may block automatic login:')}")
    print()
    lines = [
        (RED,  "OTP / 2FA via SMS or email  →  A.R.C cannot read your inbox"),
        (YLW,  "Google / Apple login popup  →  May show bot-detection page"),
        (YLW,  "CAPTCHA                     →  Will pause and ask you to solve"),
        (BLU,  "Email verification link     →  You must click it manually"),
        (BLU,  "Password-only login         →  A.R.C will fill it for you"),
    ]
    for col, line in lines:
        print(f"    {rc(col,'›')}  {d(line)}")
    sp()
    print(f"  {rc(GRN,b('Tip:'))} Save your session once with option {b('2')} and")
    print(f"  A.R.C will skip login entirely on every future run.")
    sp()
    print(DIV2)
    sp()


# ── Status bar ────────────────────────────────────────────────────────────────
def status_bar():
    profile  = load_profile()
    sessions = list_sessions()
    name     = profile.get("bio",{}).get("full_name","")
    sp()
    print(DIV)
    left  = f"  {rc(DIM2,'user')} {rc(WHT, b(name)) if name else rc(YLW,'not set')}"
    right = f"{rc(GRN,str(len(sessions))+ ' session(s)')} " if sessions else f"{rc(YLW,'0 sessions')} "
    print(f"{left}{'':>10}{right}")
    print(DIV)
    sp()


# ── Menu ──────────────────────────────────────────────────────────────────────
def show_menu():
    sec("What do you want to do?")
    sp()
    items = [
        ("1", PRP,  "Run on a URL",           "open any site · fill form · auto login"),
        ("2", S2,   "Save a session",          "log in once, reuse forever"),
        ("3", BLU,  "View / edit profile",     "name, email, credentials, API key"),
        ("q", DIM2, "Quit",                    ""),
    ]
    for key, col, label_, desc in items:
        extra = f"  {d(desc)}" if desc else ""
        print(f"   {rc(col,b(key))}  {rc(WHT,label_)}{extra}")
    sp()


# ── Commands ──────────────────────────────────────────────────────────────────

async def do_run():
    from agent import run_agent

    sec("Run Agent")
    url = ask("Enter URL")
    if not url: warn("No URL."); return
    if not url.startswith("http"): url = "https://" + url

    sessions = list_sessions()
    google   = find_google_session()
    session  = ""

    # Auto-match Google session for Google URLs
    if google and ("google" in url or "docs.google" in url):
        ok(f"Google session found: {rc(GRN,b(google))} — using it automatically.")
        session = google

    # Ask for session if others exist
    elif sessions:
        sp()
        info(f"Saved sessions: {', '.join(rc(GRN,s) for s in sessions)}")
        entered = ask("Session to use? (Enter to skip)", "")
        if entered in sessions:
            session = entered
        elif entered:
            warn(f"'{entered}' not found — continuing without session.")

    # No sessions at all — explain risks
    else:
        session_risks_warning(url)
        if not yn("Continue anyway? (A.R.C will try to log in)"):
            return

    sp()
    record = yn("Record browser video?")

    os.makedirs(WORK_DIR, exist_ok=True)
    profile  = load_profile()
    identity = {
        "bio":         profile.get("bio", {}),
        "secrets":     profile.get("secrets", {}),
        "files":       [],
        "folder_path": WORK_DIR,
    } if profile else {"bio":{},"secrets":{},"files":[],"folder_path":WORK_DIR}

    sp()
    print(DIV2)
    info(f"URL      {rc(CYN, url)}")
    info(f"Session  {rc(GRN, session) if session else d('none — will try live login')}")
    print(DIV2)
    sp()

    await run_agent(
        start_url=url,
        user_folder=WORK_DIR,
        headless=False,
        timeout=120000,
        identity_override=identity,
        session_name=session,
        step_callback=step_cb,
        record_video=record,
    )

    # Screenshot at end
    sp(); print(DIV2)
    shot = os.path.join(WORK_DIR, f"screenshot_{int(time.time())}.png")
    try:
        from browse import Browser
        # agent already closed browser, so we note path only
        ok(f"Run complete.")
        info(f"Workspace: {rc(CYN, WORK_DIR)}")
    except: pass
    sp()


async def do_session():
    from save_session import main as sm
    await sm()


def do_profile():
    sec("Profile")
    profile = load_profile()
    bio     = profile.get("bio", {})
    secrets = profile.get("secrets", {})

    sp()
    fields = [
        ("full_name",     "Full name"),
        ("email",         "Email"),
        ("phone",         "Phone (+country code)"),
        ("date_of_birth", "Date of birth (YYYY-MM-DD)"),
        ("college",       "College / University"),
        ("degree",        "Degree"),
        ("address",       "City / Address"),
    ]
    for key, lbl in fields:
        bio[key] = ask(lbl, bio.get(key,""))

    sp()
    sec("Groq API Key")
    info(f"Free key at {rc(CYN,'https://console.groq.com')}")
    env_path = os.path.join(HERE, ".env")
    existing = ""
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("GROQ_API="):
                existing = line.split("=",1)[1].strip()
    if existing:
        info(f"Current: {d(existing[:12]+'...')}")
        if not yn("Keep this key?"): existing = ""
    if not existing:
        k = ask("Paste Groq API key")
        if k:
            lines = [l for l in open(env_path) if not l.startswith("GROQ_API=")] if os.path.exists(env_path) else []
            lines.append(f"GROQ_API={k}\n")
            open(env_path,"w").writelines(lines)
            ok("Key saved.")

    profile["bio"] = bio
    profile["secrets"] = secrets
    save_profile(profile)
    sp(); ok("Profile saved!")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    # Direct URL arg: python3 arc.py https://...
    if len(sys.argv) == 2 and sys.argv[1].startswith("http"):
        show_banner()
        asyncio.run(do_run_direct(sys.argv[1]))
        return

    show_banner()
    status_bar()

    while True:
        show_menu()
        sys.stdout.write(f"  {rc(PRP,'▸')} {rc(WHT,'Choose')}  ")
        sys.stdout.flush()
        choice = input().strip().lower()
        sp()

        if   choice in ("1","run"):     asyncio.run(do_run())
        elif choice in ("2","session"): asyncio.run(do_session())
        elif choice in ("3","profile"): do_profile()
        elif choice in ("q","quit"):
            sp()
            print(f"  {rc(GRN,'◉')} {d('goodbye.')}"); sp(); break
        else: warn("Type 1, 2, 3 or q.")


async def do_run_direct(url):
    from agent import run_agent
    profile = load_profile()
    os.makedirs(WORK_DIR, exist_ok=True)
    google  = find_google_session()
    session = google or ""
    if session: ok(f"Auto-using session: {rc(GRN,session)}")
    else:
        session_risks_warning(url)
    identity = {"bio": profile.get("bio",{}),"secrets": profile.get("secrets",{}),"files":[],"folder_path":WORK_DIR}
    await run_agent(
        start_url=url, user_folder=WORK_DIR, headless=False,
        timeout=120000, identity_override=identity,
        session_name=session, step_callback=step_cb,
    )


main()