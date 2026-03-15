import asyncio
import json
import os
import time
from typing import TypedDict, List, Dict, Optional, Callable
from dotenv import load_dotenv
from groq import Groq
from browser import Browser
from custom_collections import PlanQueue

load_dotenv()

MODEL           = "llama-3.3-70b-versatile"
client          = Groq(api_key=os.getenv("GROQ_API"))

MAX_RETRIES     = 3    # retries per step before skipping
MAX_REPLANS     = 10   # total replan cycles before hard stop
RATE_LIMIT_WAIT = 15

HERE         = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(HERE, "sessions")


class State(TypedDict):
    url:              str
    user_data:        Dict
    last_dom:         List[Dict]
    history:          List[Dict]
    already_filled:   List[str]
    user_assistance:  List[str]
    last_user_answer: str


def _resolve_session(session_name: str) -> Optional[str]:
    """Return absolute path for a session name, or None if not found."""
    if not session_name:
        return None
    # already absolute
    if os.path.isabs(session_name) and os.path.exists(session_name):
        return session_name

    for candidate in [
        os.path.join(SESSIONS_DIR, session_name),
        os.path.join(SESSIONS_DIR, session_name + ".json"),
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


def llm_node(state: State, dom: List[Dict]) -> State:
    print("\n[INFO] Planning...")

    answer_hint = ""
    if state.get("last_user_answer"):
        answer_hint = (
            f'\n⚡ USER JUST PROVIDED: "{state["last_user_answer"]}"'
            f' — use this immediately.'
        )
        state["last_user_answer"] = ""

    prompt = f"""
You are A.R.C — an AI agent that fills out web forms completely on behalf of a user.

USER PROFILE:
{json.dumps(state["user_data"].get("bio", {}), indent=2)}

SECRETS (use only when needed):
{json.dumps(state["user_data"].get("secrets", {}), indent=2)}

RECENT HISTORY (last 5 actions):
{json.dumps(state["history"][-5:], indent=2)}
{answer_hint}

ALREADY FILLED (do NOT re-fill these):
{json.dumps(state["already_filled"])}

CURRENT PAGE ELEMENTS:
{json.dumps(dom, indent=2)}

ELEMENT TYPE GUIDE:
- input / textarea         → action: "type"
- radio-group / radiogroup → action: "check"   (NEVER "select")
- checkbox-group           → action: "check"   (NEVER "select")
- tag=select / role=listbox → action: "select"
- role=button / tag=button → action: "click"
- file input               → action: "upload"
- unknown from profile     → action: "human_node"

TOOLS — return a JSON array of steps:
1. type       args={{"label":"exact question"}}          value="answer"
2. check      args={{"question":"question", "value":"option to pick"}}
3. select     args={{"label":"question"}}                value="option"
4. click      args={{"label":"Next"}} or {{"label":"Submit"}}
5. upload     args={{"label":"question"}}                value="filename"
6. human_node args={{}}                                  value="what to ask user"

RULES:
- Return ONLY a valid JSON array. No markdown, no explanation.
- Plan EVERY visible unfilled field in ONE response.
- Fill ALL fields first, THEN click Next/Submit last.
- NEVER re-fill anything in ALREADY FILLED.
- radio-group → ALWAYS "check", NEVER "select".
- Copy label/question text EXACTLY from PAGE ELEMENTS.
- If only Next/Submit remains, just return that one click.
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw    = response.choices[0].message.content
        parsed = json.loads(raw)

        if isinstance(parsed, dict):
            for key in ["steps", "plan", "actions", "tasks"]:
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
            else:
                parsed = []

        for s in parsed:
            if "action" not in s and "type" in s:
                s["action"] = s.pop("type")
            if "args" in s and isinstance(s["args"], dict):
                s["args"] = {
                    k: v.strip() if isinstance(v, str) else v
                    for k, v in s["args"].items()
                }

        # Degenerate case: LLM only planned one already-filled type step
        if len(parsed) == 1:
            only  = parsed[0]
            label = only.get("args", {}).get("label", "")
            if label in state["already_filled"] and only.get("action") == "type":
                parsed = [{"action": "click", "args": {"label": "Next"}, "value": ""}]

        state["plan_queue"] = parsed
        print(f"[INFO] {len(parsed)} steps planned:")
        for i, s in enumerate(parsed):
            print(f"  [{i}] {s.get('action')} | args={s.get('args')} | value={s.get('value')}")

    except Exception as e:
        print(f"[ERROR] Planning failed: {e}")
        state["plan_queue"] = []

    return state


async def execute_step(
    step: Dict,
    state: State,
    browser: Browser,
    callback: Optional[Callable] = None,
) -> tuple[bool, List[Dict]]:

    action = step.get("action", "")
    args   = step.get("args") or {}
    value  = step.get("value") or ""

    # pull value out if nested inside args
    if isinstance(args.get("value"), str) and not value:
        value = args.pop("value")

    label = args.get("label") or args.get("question") or ""

    if callback:
        callback(action, label, "run")

    print(f"\n[EXEC] {action} | label='{label}' | value='{value}'")

    dom = None

    try:
        if action == "type":
            success = await browser.fill_input(args, value)
            if success and label:
                state["already_filled"].append(label)
            dom = await browser.extract_dom()

        elif action == "check":
            element = {
                "type":     "radio",
                "question": args.get("question", ""),
                "label":    args.get("question", ""),
                "value":    value,
                "name":     args.get("name", ""),
                "id":       args.get("id", ""),
                "class":    args.get("class", ""),
            }
            success = await browser.click_checkbox(element, action="check")
            if success and label:
                state["already_filled"].append(args.get("question", label))
            dom = await browser.extract_dom()

        elif action == "select":
            element = {**args, "answer": value, "value": value}
            success = await browser.select_option(element)
            if success and label:
                state["already_filled"].append(label)
            dom = await browser.extract_dom()

        elif action == "click":
            dom, success = await browser.click_button(args)
            dom = dom or []

        elif action == "upload":
            success = await browser.file_upload(args, value)
            dom = await browser.extract_dom()

        elif action == "human_node":
            question = value or "Please provide input"
            answer   = await browser.ask_human(question, expect_input=True)
            state["user_assistance"].append(answer or "")
            state["last_user_answer"] = answer or ""
            dom = await browser.extract_dom()
            success = True

        else:
            print(f"[ERROR] Unknown action: {action}")
            success = False
            dom = await browser.extract_dom()

    except Exception as e:
        print(f"[ERROR] execute_step crashed: {e}")
        success = False
        dom = await browser.extract_dom()

    if callback:
        callback(action, label, "ok" if success else "fail")

    return success, dom

def is_done(url: str, dom: List[Dict]) -> bool:
    done_sigs = [
        "formresponse", "viewform?usp=pp_url",
        "thank", "success", "submitted",
        "alreadyresponded", "confirmation",
    ]
    if any(sig in url.lower() for sig in done_sigs):
        return True

    all_text = " ".join(
        (el.get("text") or "") + (el.get("label") or "")
        for el in dom
    ).lower()
    done_phrases = [
        "thank you", "response recorded", "already responded",
        "successfully submitted", "form submitted", "your response",
    ]
    return any(p in all_text for p in done_phrases)


async def run_agent(
    start_url:         str,
    user_folder:       str,
    headless:          bool              = False,
    timeout:           int               = 120_000,
    identity_override: Optional[Dict]    = None,
    session_name:      str               = "",
    step_callback:     Optional[Callable]= None,
    record_video:      bool              = False,
    browser_type:      str               = "chromium",
):
    """
    Entry point called by arc.py.

    Parameters
    ----------
    start_url         : page to open
    user_folder       : workspace / data directory (passed to Browser)
    headless          : run browser without UI
    timeout           : Playwright default timeout (ms)
    identity_override : dict with keys bio, secrets, files, folder_path
                        (built by arc.py from profile.json)
    session_name      : basename (or full path) of a saved session file
    step_callback     : callable(action, detail, status) for UI feedback
    record_video      : save a video of the run
    browser_type      : "chromium" | "chrome" | "firefox"
    """


    if identity_override:
        user_data = identity_override
    else:
        # fall back: look for config.json in user_folder
        config_path = os.path.join(user_folder, "config.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
            files = [
                fn for fn in os.listdir(user_folder)
                if not fn.startswith(".") and fn != "config.json"
            ]
            user_data = {
                "bio":         cfg.get("bio", cfg.get("vault", {}).get("identity", {})),
                "secrets":     cfg.get("secrets", {}),
                "files":       files,
                "folder_path": user_folder,
            }
        else:
            user_data = {"bio": {}, "secrets": {}, "files": [], "folder_path": user_folder}

   
    session_file = _resolve_session(session_name)
    if session_name and not session_file:
        print(f"[WARN] Session '{session_name}' not found — continuing without it.")


    browser = Browser(timeout=timeout, dir_path=user_folder, headless=headless)
    await browser.start(record_video=record_video, browser=browser_type)

    try:
        
        if session_file:
            print(f"[INFO] Loading saved session: {session_file}")
            ok = await browser.reuse_session(session_file)
            if not ok:
                print("[WARN] Session load failed — continuing without session.")

        # navigate
        dom = await browser.open_url(start_url)

        state: State = {
            "url":              start_url,
            "user_data":        user_data,
            "last_dom":         dom,
            "history":          [],
            "already_filled":   [],
            "user_assistance":  [],
            "last_user_answer": "",
            "plan_queue":       [],
        }

        queue        = PlanQueue()
        replan_count = 0

    
        while replan_count < MAX_REPLANS:

            current_url = browser.page.url
            if is_done(current_url, state["last_dom"]):
                print("\n✅ Form completed successfully!")
                break

            if queue.is_empty():
                if replan_count > 0:
                    print(f"\n[INFO] Re-observing: {current_url}")
                    state["last_dom"] = await browser.open_url(current_url)

                state     = llm_node(state, state["last_dom"])
                new_steps = state.pop("plan_queue", [])

                if not new_steps:
                    print("[WARN] LLM returned no steps — stopping.")
                    break

                queue.add_steps(new_steps)
                replan_count += 1

            step = queue.pop()
            if not step:
                continue

            print(f"\n[NEXT] {step}")

            success = False
            dom     = state["last_dom"]

            for attempt in range(MAX_RETRIES):
                success, dom = await execute_step(step, state, browser, step_callback)
                if success:
                    break
                print(f"[RETRY] attempt {attempt + 1}/{MAX_RETRIES} failed.")
                await asyncio.sleep(1)

            state["history"].append({
                "action":  step.get("action"),
                "args":    step.get("args"),
                "value":   step.get("value"),
                "success": success,
            })

            if dom:
                state["last_dom"] = dom

            if not success:
                print(
                    f"[SKIP] '{step.get('action')}' failed after "
                    f"{MAX_RETRIES} attempts — skipping."
                )
                queue.clear()

        else:
            print(f"\n[STOP] Hit max replan limit ({MAX_REPLANS}).")

    finally:
        # always close browser cleanly so video is flushed
        await browser.context.close()
        await browser.browser.close()
        await browser.playwright.stop()

    print("\n[INFO] Agent finished.")