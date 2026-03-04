import asyncio
import json
import os
import time
from typing import TypedDict, List, Dict, Optional, Callable
from dotenv import load_dotenv
from groq import Groq
from browse import Browser

load_dotenv()

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")
MODEL        = "llama-3.3-70b-versatile"

web_browser = None


class State(TypedDict):
    plan: List[Dict]
    page_url: str
    current_step: Dict
    history: List[Dict]
    status: str
    user_context: Dict
    last_user_answer: str
    last_dom: List[Dict]
    filled_fields: List[str]   # track what we already filled


def load_user_identity(folder_path: str) -> Dict:
    config_path = os.path.join(folder_path, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found: {folder_path}")
    with open(config_path) as f:
        config = json.load(f)
    files = [f for f in os.listdir(folder_path)
             if not f.startswith(".") and f != "config.json"]
    return {
        "bio":         config.get("bio", config.get("vault", {}).get("identity", {})),
        "secrets":     config.get("secrets", {}),
        "files":       files,
        "folder_path": folder_path,
    }


def llm_node(state: State, json_data: str):
    print("\n[INFO] Planning...")
    time.sleep(1)

    if len(json_data) > 20000:
        json_data = json_data[:20000] + "...(truncated)"

    user            = state["user_context"]
    history_context = json.dumps(state["history"][-5:], indent=2)
    filled          = state.get("filled_fields", [])

    answer_hint = ""
    if state.get("last_user_answer"):
        answer_hint = f'\n⚡ USER JUST PROVIDED: "{state["last_user_answer"]}" — use it immediately.'
        state["last_user_answer"] = ""

    prompt = f"""
You are A.R.C — an AI agent that fills out forms completely on behalf of a user.

USER PROFILE:
{json.dumps(user.get("bio", {}), indent=2)}

SECRETS (passwords, usernames — use only when needed):
{json.dumps(user.get("secrets", {}), indent=2)}

RECENT HISTORY:
{history_context}
{answer_hint}

ALREADY FILLED (do NOT re-fill these):
{json.dumps(filled)}

CURRENT PAGE ELEMENTS:
{json_data}

ELEMENT TYPE GUIDE:
- Standard inputs:    tag=input/textarea, label/name/id available
- Radio/checkbox:     tag=radio-group or checkbox-group, question="...", options=[...]
- Google dropdown:    role=listbox, label="question text", options=[...]
- Buttons/nav:        role=button, label="Next"/"Submit"

TOOLS (return a JSON array of ALL steps needed):
1. type    args={{"label":"exact question text"}},  value="answer"
2. check   args={{"question":"question text", "value":"option to pick"}}
3. select  args={{"label":"question text"}},  value="option to pick"
4. click   args={{"label":"Next"}}   or   args={{"label":"Submit"}}
5. ask_user  value="what to ask"   — ONLY if value truly unknown from profile
6. upload  args={{"label":"..."}},  value="filename"
7. screenshot  value="done.png"

CRITICAL RULES:
- Return ONLY a valid JSON array. No markdown, no explanation.
- Plan EVERY visible field in ONE response — do not plan just 1 step.
- Fill ALL fields first, then click Next or Submit at the end.
- NEVER re-fill fields listed in ALREADY FILLED above.
- If you see fields you already filled and a Next button, just click Next.
- For radio/checkbox the chosen option goes in "value".
- Google Forms: use exact question label text in args.label.
- If the page only has a Submit/Next button (all fields done), just click it.
- Do NOT add a screenshot step unless all fields are filled and submitted.
"""

    client = Groq(api_key=os.getenv("GROQ_API"))

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw      = response.choices[0].message.content
            parsed   = json.loads(raw)

            # Unwrap if LLM returns {"steps": [...]} or {"actions": [...]}
            if isinstance(parsed, dict):
                for key in ["steps", "plan", "actions", "tasks"]:
                    if key in parsed and isinstance(parsed[key], list):
                        parsed = parsed[key]
                        break
                else:
                    parsed = []

            # Safety: if still just 1 step and it's a type we already did → break loop
            if len(parsed) == 1:
                only = parsed[0]
                label_val = only.get("args", {}).get("label", "")
                if label_val in filled and only.get("action") == "type":
                    print("[WARN] LLM wants to re-fill already-filled field — injecting Next click.")
                    parsed = [{"action": "click", "args": {"label": "Next"}, "value": ""}]

            # Normalize: LLM sometimes uses "type" key instead of "action"
            for s in parsed:
                if "action" not in s and "type" in s:
                    s["action"] = s.pop("type")
                # Also strip \n and whitespace from label args
                if "args" in s and isinstance(s["args"], dict):
                    s["args"] = {k: v.strip() if isinstance(v, str) else v
                                 for k, v in s["args"].items()}

            state["plan"] = parsed
            print(f"[INFO] {len(parsed)} steps planned:")
            for i, s in enumerate(parsed):
                print(f"  [{i}] {s.get('action')} | args={s.get('args')} | value={s.get('value')}")
            return state

        except Exception as e:
            err = str(e)
            if "429" in err or "rate" in err.lower():
                wait = (attempt + 1) * 10
                print(f"[WARN] Rate limited — waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"[ERROR] Planning failed: {e}")
                state["plan"] = []
                return state

    print("[ERROR] All retries failed.")
    state["plan"] = []
    return state


def review_history(state: State):
    step = state["current_step"]
    if step.get("status") != "fail":
        return state

    args          = step.get("args", {})
    priority_keys = ["text", "label", "name", "placeholder", "class", "id"]
    removed       = False

    for key in priority_keys:
        if key in args:
            print(f"[REVIEW] Dropping failed selector: '{key}'")
            del args[key]
            removed = True
            break

    if removed and args:
        step["status"] = "pending"
    else:
        user_input = input(">> Manual selector (#id/.class/label) or 'skip': ")
        if user_input.lower() == "skip":
            step["status"] = "dead"
        else:
            if user_input.startswith("#"):   step["args"] = {"id": user_input[1:]}
            elif user_input.startswith("."): step["args"] = {"class": user_input[1:]}
            else:                            step["args"] = {"text": user_input}
            step["status"] = "pending"

    return state


async def execute_tool_call(state: State, step_callback: Optional[Callable] = None):
    global web_browser
    step   = state["current_step"]
    action = step.get("action") or "unknown"
    args   = step.get("args", {})
    value  = step.get("value", "")

    def _cb(status, detail=""):
        if step_callback:
            step_callback(action, detail, status)

    print(f"\n[EXEC] {action} | args={args} | value={value}")
    _cb("run", str(args))

    success = False
    try:
        if action == "ask_user":
            print(f"\n❓ {value}")
            user_answer = await asyncio.to_thread(input, ">> ")
            state["history"].append({"role": "user", "question": value, "answer": user_answer})
            state["last_user_answer"] = user_answer
            success = True

        elif action == "click":
            dom_after, success = await web_browser.click_button(args)
            if success:
                new_url = web_browser.page.url
                state["plan"] = []
                # After a click — clear filled_fields only on real page navigation
                if new_url != state["page_url"]:
                    print(f"[NAV] → {new_url}")
                    state["page_url"]     = new_url
                    state["filled_fields"] = []   # new page — reset
                if dom_after:
                    state["last_dom"] = dom_after

        elif action == "type":
            success = await web_browser.fill_input(args, value)
            if success:
                # Track filled field so LLM won't re-plan it
                label_key = args.get("label") or args.get("name") or args.get("id","")
                if label_key and label_key not in state["filled_fields"]:
                    state["filled_fields"].append(label_key)

        elif action == "check":
            if value and "value" not in args:
                args["value"] = value
            success = await web_browser.click_checkbox(args, "check")
            if success:
                q = args.get("question") or args.get("label","")
                if q and q not in state["filled_fields"]:
                    state["filled_fields"].append(q)

        elif action == "select":
            args["answer"] = value
            success = await web_browser.select_option(args)
            if success:
                q = args.get("label") or args.get("question","")
                if q and q not in state["filled_fields"]:
                    state["filled_fields"].append(q)

        elif action == "upload":
            web_browser.data_folder = state["user_context"]["folder_path"]
            success = await web_browser.file_upload(args, value)

        elif action == "save_session":
            success = await web_browser.save_session(value)

        elif action == "screenshot":
            success = await web_browser.save_screenshot(value)

        elif action == "wait":
            await asyncio.sleep(int(value) if value else 2)
            success = True

        else:
            print(f"[ERROR] Unknown action: {action}")

    except Exception as e:
        print(f"[ERROR] {e}")
        success = False

    if success:
        step["status"] = "success"
        state["history"].append({"action": action, "status": "success", "value": value})
        _cb("ok")
        if action == "ask_user":
            state["plan"]   = []
            state["last_dom"] = []
    else:
        print(f"[FAIL] {action} failed.")
        step["status"] = "fail"
        state["history"].append({"action": action, "status": "fail", "args": args})
        _cb("fail")

    return state


async def run_agent(
    start_url:         str,
    user_folder:       str,
    headless:          bool = False,
    timeout:           int  = 120000,
    identity_override: Optional[Dict] = None,
    step_callback:     Optional[Callable] = None,
    session_name:      str  = "",
    record_video:      bool = False,
):
    global web_browser

    identity = identity_override or None
    if not identity:
        print(f"[INFO] Loading identity from: {user_folder}")
        try:
            identity = load_user_identity(user_folder)
        except Exception as e:
            print(f"[ERROR] {e}"); return

    web_browser = Browser(timeout=timeout, dir_path=user_folder, headless=headless)
    await web_browser.start(record_video=record_video)

    if session_name:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        session_file = os.path.join(SESSIONS_DIR, f"{session_name}.json")
        if os.path.exists(session_file):
            print(f"[INFO] Loading saved session: {session_name}")
            await web_browser.reuse_session(session_file)
        else:
            print(f"[WARN] Session '{session_name}' not found — continuing without it.")

    if not start_url.startswith("http"):
        start_url = "https://" + start_url

    state: State = {
        "plan":             [],
        "page_url":         start_url,
        "current_step":     {},
        "history":          [],
        "status":           "running",
        "user_context":     identity,
        "last_user_answer": "",
        "last_dom":         [],
        "filled_fields":    [],
    }

    # Safety: max re-plan cycles to prevent infinite loops
    replan_count = 0
    MAX_REPLANS  = 20

    while True:
        if not state["plan"]:
            replan_count += 1
            if replan_count > MAX_REPLANS:
                print("[ERROR] Too many re-plans — possible infinite loop. Stopping.")
                break

            if state.get("last_dom"):
                print("[INFO] Re-planning with cached DOM")
                dom_data = state["last_dom"]
                state["last_dom"] = []
            else:
                print(f"[INFO] Observing: {state['page_url']}")
                dom_data = await web_browser.open_url(state["page_url"])

            state = llm_node(state, json.dumps(dom_data))

            if not state["plan"]:
                print("[DONE] No more steps. Task complete.")
                break

        step_status = state.get("current_step", {}).get("status")
        if not state.get("current_step") or step_status in ["success", "dead"]:
            if state["plan"]:
                state["current_step"]           = state["plan"].pop(0)
                state["current_step"]["status"] = "pending"
                print(f"\n[NEXT] {state['current_step']}")
            else:
                continue

        status = state["current_step"]["status"]
        if status == "pending":
            state = await execute_tool_call(state, step_callback)
        elif status == "fail":
            state = review_history(state)
        elif status == "dead":
            print("[SKIP] Dead step.")
            state["current_step"] = {}

    # Final screenshot
    try:
        import time as t
        shot = f"final_{int(t.time())}.png"
        await web_browser.save_screenshot(shot)
        print(f"[INFO] Screenshot saved: {shot}")
    except: pass

    await web_browser.browser.close()
    print("\n[INFO] Agent finished.")