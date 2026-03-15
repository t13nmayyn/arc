from playwright.async_api import Page, async_playwright
import asyncio
import os
import re
import shutil
from custom_collections import PageList


ANTI_BOT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
    const _origPerms = window.navigator.permissions.query.bind(navigator.permissions);
    window.navigator.permissions.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : _origPerms(p);
"""

def get_chrome_path():
    paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")


def get_firefox_path():
    paths = [
        "/usr/bin/firefox",
        "/Applications/Firefox.app/Contents/MacOS/firefox",
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return shutil.which("firefox")


def _is_gform(url: str) -> bool:
    return "docs.google.com/forms" in url


class Browser:
    def __init__(self, timeout: float, dir_path: str, headless: bool = False):
        self.timeout     = timeout
        self.headless    = headless
        self.playwright  = None
        self.browser     = None
        self.context     = None
        self.page        = None
        self.data_folder = dir_path
        self.page_list   = PageList()
        self._video_dir  = None
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
            print(f"Created data folder: {self.data_folder}/")

    async def start(self, record_video: bool = False, browser: str = 'chromium'):
        self.playwright = await async_playwright().start()
        launch_opts     = {"headless": self.headless}

        if browser == 'chrome':
            path = get_chrome_path()
            if path:
                launch_opts["executable_path"] = path
                print(f"  Using Chrome: {path}")
            self.browser = await self.playwright.chromium.launch(**launch_opts)
        elif browser == 'firefox':
            path = get_firefox_path()
            if path:
                launch_opts["executable_path"] = path
                print(f"  Using Firefox: {path}")
            self.browser = await self.playwright.firefox.launch(**launch_opts)
        else:
            self.browser = await self.playwright.chromium.launch(**launch_opts)

        ctx_opts = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        if record_video:
            video_dir = os.path.join(self.data_folder, "recordings")
            os.makedirs(video_dir, exist_ok=True)
            ctx_opts["record_video_dir"]  = video_dir
            ctx_opts["record_video_size"] = {"width": 1280, "height": 720}
            self._video_dir = video_dir
            print(f"[REC] Recording to: {video_dir}")

        self.context = await self.browser.new_context(**ctx_opts)
        await self.context.add_init_script(ANTI_BOT_SCRIPT)
        self.page = await self.context.new_page()
        self.page_list.add_page(self.page)
        self.page.set_default_timeout(self.timeout)
        self.context.on("page", self._on_new_page)
        return self

    async def _on_new_page(self, new_page: Page):
        print(f"Popup: {new_page.url}")
        await new_page.wait_for_load_state("domcontentloaded")
        new_page.set_default_timeout(self.timeout)
        self.page_list.add_page(new_page)
        self.page = self.page_list.current_page()
        new_page.on("close", lambda _: self._restore_main_page())

    def _restore_main_page(self):
        self.page_list.go_back()
        self.page = self.page_list.current_page()

    async def open_url(self, url: str):
        print(f"Navigating to {url}...")
        await self.page.goto(url)
        await self.page.wait_for_load_state("domcontentloaded")
        await self.page.wait_for_timeout(2000)
        return await self.extract_dom()

    async def ask_human(self, message: str, expect_input: bool = False):
        print(f"\n{'='*50}")
        print(f"🧑 HUMAN NEEDED: {message}")
        print(f"{'='*50}")

        await self.page.evaluate(f"""() => {{
            const existing = document.getElementById('__arc_human_notice');
            if (existing) existing.remove();
            const div = document.createElement('div');
            div.id = '__arc_human_notice';
            div.style.cssText = [
                'position:fixed','top:0','left:0','right:0',
                'background:#c0392b','color:#fff',
                'padding:14px 20px','font-size:17px','font-weight:bold',
                'z-index:2147483647','text-align:center','font-family:monospace',
                'box-shadow:0 2px 8px rgba(0,0,0,.4)'
            ].join(';');
            div.innerText = '⚠️  ARC needs you — check your terminal!';
            document.body.prepend(div);
        }}""")

        if expect_input:
            response = await asyncio.to_thread(input, "  >> Your input: ")
        else:
            await asyncio.to_thread(input, "  Press Enter when done in browser... ")
            response = None

        await self.page.evaluate("""() => {
            const el = document.getElementById('__arc_human_notice');
            if (el) el.remove();
        }""")
        return response

  
    async def detect_captcha(self) -> bool:
        return await self.page.evaluate("""() => {
            const body = document.body ? document.body.innerText.toLowerCase() : '';
            const html = document.documentElement.innerHTML.toLowerCase();
            return [
                body.includes('captcha'),
                body.includes('i am not a robot'),
                body.includes('verify you are human'),
                body.includes('security check'),
                body.includes('prove you are human'),
                html.includes('recaptcha'),
                html.includes('hcaptcha'),
                !!document.querySelector('iframe[src*="recaptcha"]'),
                !!document.querySelector('iframe[src*="hcaptcha"]'),
                !!document.querySelector('.g-recaptcha'),
                !!document.querySelector('.h-captcha'),
                !!document.querySelector('[data-sitekey]'),
                !!document.querySelector('#captchaImg'),
                !!document.querySelector('input[name*="captcha" i]'),
                !!document.querySelector('input[id*="captcha" i]'),
                !!document.querySelector('img[id*="captcha" i]'),
                !!document.querySelector('img[src*="captcha" i]'),
            ].some(Boolean);
        }""")



    async def extract_dom(self):
        if await self.detect_captcha():
            print("\n🔒 CAPTCHA detected!")
            await self.ask_human("Solve the captcha in the browser, then press Enter")

        if _is_gform(self.page.url):
            return await self._extract_google_form()
        return await self._extract_standard()

    async def _extract_standard(self):
        return await self.page.evaluate("""() => {
            function isVisible(el) {
                try {
                    const r = el.getBoundingClientRect(), s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && s.opacity !== '0';
                } catch(e) { return false; }
            }
            function getLabel(el) {
                const lby = el.getAttribute('aria-labelledby');
                if (lby) { const l = document.getElementById(lby); if (l) return l.innerText.trim(); }
                const al = el.getAttribute('aria-label');
                if (al) return al.trim();
                if (el.id) {
                    const lf = document.querySelector('label[for="' + el.id + '"]');
                    if (lf) return lf.innerText.trim();
                }
                const pl = el.closest('label');
                if (pl) return pl.innerText.trim();
                const prev = el.previousElementSibling;
                if (prev && !['input','select','textarea','button']
                        .includes(prev.tagName.toLowerCase()))
                    return prev.innerText.trim();
                return '';
            }
            const SEL = "input,select,textarea,button,[role='button'],[type='submit']";
            const important = ['next','continue','submit','verify','confirm','proceed',
                               'register','login','sign in','sign up','finish','send'];
            const results = [], counter = {};
            for (const el of document.querySelectorAll(SEL)) {
                if (!isVisible(el)) continue;
                const tag  = el.tagName.toLowerCase();
                const type = (el.getAttribute('type') || '').toLowerCase();
                const role = el.getAttribute('role') || '';
                const id   = el.id || '', name = el.name || '';
                const ph   = el.placeholder || '', cls = el.className || '';
                const val  = el.value || '', href = el.href || '';
                const lbl  = getLabel(el);
                const text = [el.innerText||'', el.getAttribute('aria-label')||'', val]
                             .join(' ').trim().toLowerCase();
                const isBtn = tag==='button' || role==='button' || type==='submit';
                if (isBtn && !important.some(w => text.includes(w))
                          && !el.closest('form')) continue;
                const key = tag + '|' + id + '|' + name + '|' + cls;
                if (!counter[key]) counter[key] = 0;
                results.push({ tag, role, type, text, label: lbl,
                               id, name, class: cls, placeholder: ph,
                               value: val, href, index: counter[key]++,
                               insideForm: !!el.closest('form') });
            }
            return results;
        }""")

    async def _extract_google_form(self):
        print("Google Form detected.")
        items = await self.page.evaluate("""() => {
            const results = [];
            const blocks = document.querySelectorAll(
                '[data-params],.freebirdFormviewerViewItemsItemItem,.Qr7Oae');
            for (const block of blocks) {
                const titleEl = block.querySelector(
                    '.freebirdFormviewerViewItemsItemItemTitle,.M7eMe,.z12JJ,[role="heading"]');
                const question = titleEl ? titleEl.innerText.trim() : '';
                if (!question) continue;
                const required = !!block.querySelector('[aria-required="true"],.vnumgf');
                const base = { question, label: question,
                               text: question.toLowerCase(),
                               insideForm: true, required,
                               href: '', placeholder: '', value: '' };
                const inp = block.querySelector('input[type="text"],textarea');
                if (inp) {
                    results.push({...base, tag: inp.tagName.toLowerCase(),
                        type: inp.tagName === 'TEXTAREA' ? 'textarea' : 'text',
                        role: '', name: inp.name||'', id: inp.id||'',
                        class: inp.className||'', index: 0 });
                    continue;
                }
                const radios = [...block.querySelectorAll('[role="radio"],input[type="radio"]')];
                if (radios.length) {
                    const opts = radios.map(r => {
                        const p = r.closest('[data-value]') || r.closest('label') || r.parentElement;
                        return p ? (p.innerText.trim() || r.getAttribute('data-value') || r.value) : r.value;
                    }).filter(Boolean);
                    results.push({...base, tag: 'radio-group', type: 'radio',
                        role: 'radiogroup', options: opts,
                        name: radios[0].name||'', id: '', class: '', index: 0 });
                    continue;
                }
                const cbs = [...block.querySelectorAll('[role="checkbox"],input[type="checkbox"]')];
                if (cbs.length) {
                    const opts = cbs.map(c =>
                        (c.closest('label') || c.parentElement || c).innerText.trim()
                    ).filter(Boolean);
                    results.push({...base, tag: 'checkbox-group', type: 'checkbox',
                        role: 'group', options: opts,
                        name: cbs[0].name||'', id: '', class: '', index: 0 });
                    continue;
                }
                const dd = block.querySelector('select,[role="listbox"]');
                if (dd) {
                    const opts = [...dd.querySelectorAll('option,[role="option"]')]
                        .map(o => o.innerText.trim()).filter(Boolean);
                    results.push({...base, tag: dd.tagName.toLowerCase(),
                        type: 'select', role: 'listbox', options: opts,
                        name: dd.name||'', id: dd.id||'',
                        class: dd.className||'', index: 0 });
                    continue;
                }
                const fi = block.querySelector('input[type="file"],[aria-label="Add File"]');
                if (fi) {
                    results.push({...base, tag: 'input', type: 'file', role: '',
                        name: fi.name||'', id: fi.id||'',
                        class: fi.className||'', index: 0 });
                }
            }
            document.querySelectorAll('[role="button"][jsname]').forEach(btn => {
                const txt = btn.innerText.trim(); if (!txt) return;
                results.push({ tag: 'div', type: '', role: 'button',
                    label: txt, question: '', text: txt.toLowerCase(),
                    name: '', id: btn.id||'', class: btn.className||'',
                    placeholder: '', value: '', href: '',
                    index: 0, insideForm: true, required: false });
            });
            return results;
        }""")
        print(f"Extracted {len(items)} Google Form fields.")
        return items

    def _gform_block(self, question: str):
        """
        Return a Playwright locator for the question container block
        whose title text matches `question`.
        Tries both modern and legacy Google Forms class names.
        """
        q = question.strip()
        block_sel = (
            ".freebirdFormviewerViewItemsItemItem, "
            ".Qr7Oae, "
            "[data-params]"
        )
        title_sel = (
            ".freebirdFormviewerViewItemsItemItemTitle, "
            ".M7eMe, .z12JJ, [role='heading']"
        )
        
        return (
            self.page
            .locator(block_sel)
            .filter(has=self.page.locator(title_sel).filter(has_text=q))
        )

    async def _gform_fill_text(self, question: str, value: str) -> bool:
        """Fill a text/textarea input inside the matching question block."""
        try:
            block = self._gform_block(question)
            inp   = block.locator("input[type='text'], textarea").first
            await inp.wait_for(state="visible", timeout=5000)
            await inp.click()
            await inp.fill(value)
            print(f"   gform_text ✓")
            return True
        except Exception as e:
            print(f"   gform_text failed: {e}")
            return False

    async def _gform_select(self, question: str, value: str) -> bool:
        """
        Handle Google Forms custom dropdown (not a real <select>).
        Clicks the dropdown trigger inside the block, waits for the
        options list, then clicks the matching option.
        """
        try:
            block = self._gform_block(question)

            # The visible trigger element (various possible selectors)
            trigger = block.locator(
                "[role='listbox'], "
                ".quantumWizMenuPaperselectEl, "
                ".exportSelectPopup, "
                "div[jscontroller][jsaction*='click']"
            ).first
            await trigger.wait_for(state="visible", timeout=5000)
            await trigger.click()
            await self.page.wait_for_timeout(400)

            # Options appear in a global overlay — search the whole page
            option = self.page.locator(
                f"[role='option']:has-text('{value}'), "
                f"li:has-text('{value}'), "
                f"[data-value='{value}']"
            ).first
            await option.wait_for(state="visible", timeout=4000)
            await option.click()
            print(f"   gform_select ✓")
            return True
        except Exception as e:
            print(f"   gform_select failed: {e}")
            return False

    async def _gform_radio(self, question: str, value: str) -> bool:
        """Click a radio option whose label text matches `value`."""
        try:
            block = self._gform_block(question)

            # Try [data-value] first (most reliable in Google Forms)
            radio = block.locator(f"[data-value='{value}']").first
            if await radio.count() > 0:
                await radio.click()
                print(f"   gform_radio data-value ✓")
                return True

            # Fall back: find any radio container whose text matches
            radio = block.locator("[role='radio']").filter(has_text=value).first
            if await radio.count() > 0:
                await radio.click()
                print(f"   gform_radio role ✓")
                return True

            print(f"   gform_radio: no match for '{value}'")
            return False
        except Exception as e:
            print(f"   gform_radio failed: {e}")
            return False

    async def _gform_checkbox(self, question: str, value: str) -> bool:
        """Click a checkbox option whose label text matches `value`."""
        try:
            block = self._gform_block(question)
            cb    = block.locator("[role='checkbox']").filter(has_text=value).first
            if await cb.count() > 0:
                checked = await cb.get_attribute("aria-checked")
                if checked != "true":
                    await cb.click()
                print(f"   gform_checkbox ✓")
                return True
            # data-value fallback
            cb = block.locator(f"[data-value='{value}']").first
            if await cb.count() > 0:
                await cb.click()
                print(f"   gform_checkbox data-value ✓")
                return True
            return False
        except Exception as e:
            print(f"   gform_checkbox failed: {e}")
            return False

    async def _gform_submit(self) -> tuple:
        """Click the Google Forms Submit button."""
        try:
            btn = self.page.locator(
                "[role='button']:has-text('Submit'), "
                "div[jsname='M2UYVd'], "
                "span:has-text('Submit')"
            ).first
            await btn.wait_for(state="visible", timeout=5000)
            await btn.click()
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass
            await self.page.wait_for_timeout(1500)
            return await self.extract_dom(), True
        except Exception as e:
            print(f"   gform_submit failed: {e}")
            return None, False



    async def get_locators(self, element, element_type='input'):
        tag      = element.get('tag', element_type)
        locators = []

        if element.get('label'):
            locators.append(('label',      self.page.get_by_label(element['label'], exact=False)))
            locators.append(('aria_label', self.page.locator(f"[aria-label='{element['label']}']")))
            if element_type == 'button':
                locators.append(('role_button', self.page.get_by_role("button", name=element['label'])))
                locators.append(('label_text',  self.page.get_by_text(element['label'], exact=True)))

        if element.get('role') and element.get('label'):
            locators.append(('role', self.page.get_by_role(
                element['role'], name=element['label'])))

        if element.get('id'):
            locators.append(('id', self.page.locator(f"#{element['id']}")))

        if element.get('name'):
            locators.append(('name', self.page.locator(f"[name='{element['name']}']")))

        if element.get('placeholder'):
            locators.append(('placeholder', self.page.get_by_placeholder(
                re.compile(element['placeholder'], re.IGNORECASE))))

        if element.get('text') and element_type == 'button':
            locators.append(('text', self.page.get_by_role(
                "button", name=re.compile(element['text'], re.IGNORECASE))))

        if element.get('value') and element_type in ['checkbox', 'radio']:
            locators.append(('data_value', self.page.locator(
                f"[data-value='{element['value']}']")))

        if element.get('class'):
            clean = "." + ".".join(element['class'].split())
            locators.append(('class', self.page.locator(f"{tag}{clean}")))

        if element_type == 'checkbox' and element.get('name') and element.get('value'):
            locators.append(('name_value', self.page.locator(
                f"input[name='{element['name']}'][value='{element['value']}']")))

        if element_type == 'select' and element.get('name'):
            locators.append(('select_name', self.page.locator(
                f"select[name='{element['name']}']")))

        if element_type == 'file':
            locators.append(('file_input', self.page.locator("input[type='file']")))

        return locators


    async def button_click_helper(self, button):
        try:
            await button.click()
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass
            await self.page.wait_for_timeout(1500)
            print(f"URL: {self.page.url}")
            return await self.extract_dom(), True
        except Exception as e:
            print(f"Click failed: {e}")
            return None, False

    async def click_button(self, element):
        label = element.get('label') or element.get('text') or ''

        # ── Google Forms Submit ───────────────────────────────────────────────
        if _is_gform(self.page.url) and label.lower() in ('submit', 'next'):
            dom, ok = await self._gform_submit()
            if ok:
                return dom, True
            # fall through to standard locators if gform submit failed

        locators = await self.get_locators(element, 'button')
        for name, locator in locators:
            try:
                count = await locator.count()
                if count == 0:
                    continue
                if count == 1:
                    result = await self.button_click_helper(locator)
                    if result[1]:
                        return result
                    continue
                print(f"\n{count} matches via '{name}' — choose:")
                for i in range(count):
                    try:    txt = await locator.nth(i).inner_text()
                    except: txt = f"element {i}"
                    print(f"  [{i}] {txt.strip()}")
                choice = await asyncio.to_thread(input, "  Number (or q): ")
                if choice.lower() == 'q':
                    return None, False
                try:
                    idx = int(choice)
                    if 0 <= idx < count:
                        return await self.button_click_helper(locator.nth(idx))
                except ValueError:
                    pass
            except Exception as e:
                print(f"  {name} failed: {e}")
                continue

        # human fallback
        await self.ask_human(f"Please click '{label}' manually in browser")
        return await self.extract_dom(), True



    async def fill_input(self, element, data: str):
        label = element.get('label') or element.get('question') or element.get('name') or '?'
        print(f"Filling '{label}' -> '{data}'")

        if _is_gform(self.page.url):
            question = element.get('question') or element.get('label') or ''
            if question:
                if await self._gform_fill_text(question, data):
                    return True

        # ── Standard: entry.XXXXXXX name attribute ────────────────────────────
        if element.get('name') and element['name'].startswith('entry.'):
            try:
                loc = self.page.locator(f"[name='{element['name']}']")
                if await loc.count() > 0:
                    await loc.first.fill(data)
                    print(f"   entry_name ✓")
                    return True
            except Exception as e:
                print(f"   entry_name: {e}")

        # ── Generic locators ──────────────────────────────────────────────────
        for name, locator in await self.get_locators(element, 'input'):
            try:
                if await locator.count() == 0:
                    continue
                await locator.first.fill(data)
                print(f"   {name} ✓")
                return True
            except Exception as e:
                print(f"   {name}: {e}")

        # human fallback
        await self.ask_human(f"Please type '{data}' into '{label}' manually")
        return True

    # ── Checkbox ──────────────────────────────────────────────────────────────

    async def check_box_helper(self, locator, action):
        try:
            checked = await locator.is_checked()
            if action == "check" and not checked:
                await locator.check()
                print("CHECKED!")
                return True
            elif action == "uncheck" and checked:
                await locator.uncheck()
                print("UNCHECKED")
                return True
            else:
                print(f"Already {'checked' if checked else 'unchecked'}.")
                return True
        except Exception as e:
            print(f"check_box_helper: {e}")
            return False

    async def click_checkbox(self, element, action: str = 'check'):
        question = element.get('question') or element.get('label') or ''
        value    = element.get('value') or ''

        if _is_gform(self.page.url) and question:
            el_type = element.get('type', '')
            if el_type in ('radio', '') or element.get('tag') == 'radio-group':
                if await self._gform_radio(question, value):
                    return True
            if el_type == 'checkbox' or element.get('tag') == 'checkbox-group':
                if await self._gform_checkbox(question, value):
                    return True

        for name, locator in await self.get_locators(element, 'checkbox'):
            try:
                if await locator.count() == 0:
                    continue
                return await self.check_box_helper(locator.first, action)
            except Exception as e:
                print(f"  {name} failed: {e}")

        # human fallback
        label = question or value or '?'
        await self.ask_human(f"Please {action} '{label}' manually")
        return True



    async def select_option(self, element):
        answer   = element.get('answer') or element.get('value', '')
        question = element.get('label') or element.get('question') or ''
        if not answer:
            return False

        
        if _is_gform(self.page.url) and question:
            if await self._gform_select(question, answer):
                return True

        for name, locator in await self.get_locators(element, 'select'):
            try:
                if await locator.count() == 0:
                    continue
                await locator.first.select_option(answer)
                print(f"   {name} ✓")
                return True
            except Exception as e:
                print(f"   {name}: {e}")

        # human fallback
        await self.ask_human(f"Please select '{answer}' from '{question}' manually")
        return True


    async def file_upload(self, element, file_name: str):
        fp = self.get_filepath(file_name)
        if not os.path.exists(fp):
            print(f"NOT FOUND: {fp}")
            return False

        for name, locator in await self.get_locators(element, 'file'):
            try:
                if await locator.count() == 0:
                    continue
                async with self.page.expect_file_chooser(timeout=5000) as fc:
                    await locator.first.click()
                chooser = await fc.value
                await chooser.set_files(fp)
                print(f"   uploaded via {name} ✓")
                return True
            except Exception as e:
                print(f"   {name}: {e}")

        label = element.get('label') or element.get('name') or '?'
        await self.ask_human(
            f"Please upload '{file_name}' into '{label}' manually "
            f"(file is at: {fp})"
        )
        return True


    async def reuse_session(self, file_name: str):
        fp = file_name if os.path.isabs(file_name) else self.get_filepath(file_name)
        if not os.path.exists(fp):
            print(f"Session not found: {fp}")
            return False
        if self.context:
            await self.context.close()
        ctx_opts = {"storage_state": fp}
        if self._video_dir:
            ctx_opts["record_video_dir"]  = self._video_dir
            ctx_opts["record_video_size"] = {"width": 1280, "height": 720}
        self.context = await self.browser.new_context(**ctx_opts)
        await self.context.add_init_script(ANTI_BOT_SCRIPT)
        self.page = await self.context.new_page()
        self.page_list.add_page(self.page)
        self.page.set_default_timeout(self.timeout)
        self.context.on("page", self._on_new_page)
        print("Session restored.")
        return True

    async def save_session(self, file_name: str):
        try:
            await self.page.context.storage_state(path=self.get_filepath(file_name))
            print("Session saved.")
            return True
        except Exception as e:
            print(f"Save session failed: {e}")
            return False


    def get_filepath(self, file_path: str):
        return os.path.join(self.data_folder, file_path)

    async def save_screenshot(self, filename: str):
        if not os.path.splitext(filename)[1]:
            filename += ".png"
        fp = self.get_filepath(filename)
        if os.path.exists(fp):
            from datetime import datetime
            b, e = os.path.splitext(filename)
            fp = self.get_filepath(f"{b}_{datetime.now().strftime('%H%M%S')}{e}")
        try:
            await self.page.screenshot(path=fp)
            print(f"Screenshot: {os.path.basename(fp)}")
            return True
        except Exception as e:
            print(f"Screenshot failed: {e}")
            return False