from playwright.async_api import async_playwright, Page
import asyncio
import re
import os


class Browser:
    def __init__(self, timeout: float, dir_path: str, headless: bool = False):
        self.timeout     = timeout
        self.headless    = headless
        self.playwright  = None
        self.browser     = None
        self.context     = None
        self.page        = None
        self._main_page  = None
        self.data_folder = dir_path
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
            print(f"Created data folder: {self.data_folder}/")

    async def start(self, record_video: bool = False):
        self.playwright  = await async_playwright().start()
        self.browser     = await self.playwright.chromium.launch(headless=self.headless)
        ctx_opts = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        if record_video:
            import os
            video_dir = os.path.join(self.data_folder, "recordings")
            os.makedirs(video_dir, exist_ok=True)
            ctx_opts["record_video_dir"]  = video_dir
            ctx_opts["record_video_size"] = {"width": 1280, "height": 720}
            self._video_dir = video_dir
            print(f"[REC] Recording to: {video_dir}")
        else:
            self._video_dir = None
        self.context    = await self.browser.new_context(**ctx_opts)
        self.page       = await self.context.new_page()
        self._main_page = self.page
        self.page.set_default_timeout(self.timeout)
        self.context.on("page", self._on_new_page)
        return self

    async def _on_new_page(self, new_page: Page):
        print(f"Popup: {new_page.url}")
        await new_page.wait_for_load_state("domcontentloaded")
        new_page.set_default_timeout(self.timeout)
        self.page = new_page
        new_page.on("close", lambda _: self._restore_main_page())

    def _restore_main_page(self):
        self.page = self._main_page

    async def open_url(self, url: str):
        print(f"Navigating to {url}...")
        await self.page.goto(url)
        await self.page.wait_for_load_state("domcontentloaded")
        await self.page.wait_for_timeout(2000)
        return await self.extract_dom()

    async def extract_dom(self):
        if "docs.google.com/forms" in self.page.url:
            return await self._extract_google_form()
        return await self._extract_standard()

    async def _extract_standard(self):
        return await self.page.evaluate("""() => {
            function getAllElements(root, sel) {
                const found = [];
                function walk(node) {
                    try {
                        found.push(...node.querySelectorAll(sel));
                        node.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
                    } catch(e) {}
                }
                walk(root); return found;
            }
            function isVisible(el) {
                try {
                    const r=el.getBoundingClientRect(), s=window.getComputedStyle(el);
                    return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0';
                } catch(e) { return false; }
            }
            function getLabel(el) {
                const lby=el.getAttribute('aria-labelledby');
                if(lby){const l=document.getElementById(lby); if(l) return l.innerText.trim();}
                const al=el.getAttribute('aria-label'); if(al) return al.trim();
                if(el.id){const lf=document.querySelector('label[for="'+el.id+'"]'); if(lf) return lf.innerText.trim();}
                const pl=el.closest('label'); if(pl) return pl.innerText.trim();
                const prev=el.previousElementSibling;
                if(prev && !['input','select','textarea','button'].includes(prev.tagName.toLowerCase())) return prev.innerText.trim();
                return '';
            }
            const SEL = "input,select,textarea,button,a,[role='button'],[role='option'],[type='submit'],[type='button']";
            const important = ['next','continue','submit','verify','confirm','proceed','register','login','log in','sign in','sign up','finish','search','done','send'];
            const results=[]; const counter={};
            for(const el of getAllElements(document, SEL)) {
                if(!isVisible(el)) continue;
                const tag=el.tagName.toLowerCase(), type=(el.getAttribute('type')||"").toLowerCase(), role=el.getAttribute('role')||"";
                const id=el.id||"", name=el.name||"", ph=el.placeholder||"", cls=el.className||"", val=el.value||"", href=el.href||"";
                const lbl=getLabel(el);
                const text=([el.innerText||"",el.getAttribute('aria-label')||"",el.getAttribute('title')||"",val].join(" ")).trim().toLowerCase();
                const isBtn=tag==='button'||role==='button'||type==='submit'||type==='button';
                const isLink=tag==='a';
                if(isLink){if(!href||href.startsWith('#')||href.startsWith('javascript:')) continue; if(!important.some(w=>text.includes(w))) continue;}
                if(isBtn&&!['input','select','textarea'].includes(tag)){if(!important.some(w=>text.includes(w))&&!el.closest('form')) continue;}
                const key=tag+'|'+id+'|'+name+'|'+cls; if(!counter[key]) counter[key]=0;
                results.push({tag,role,type,text,label:lbl,id,name,class:cls,placeholder:ph,value:val,href,index:counter[key]++,insideForm:!!el.closest('form')});
            }
            return results;
        }""")

    async def _extract_google_form(self):
        print("Google Form detected.")
        items = await self.page.evaluate("""() => {
            const results=[];
            const blocks=document.querySelectorAll('[data-params],.freebirdFormviewerViewItemsItemItem,.Qr7Oae');
            for(const block of blocks){
                const titleEl=block.querySelector('.freebirdFormviewerViewItemsItemItemTitle,.M7eMe,.z12JJ,[role="heading"]');
                const question=titleEl?titleEl.innerText.trim():''; if(!question) continue;
                const required=!!block.querySelector('[aria-required="true"],.vnumgf');
                const base={question,label:question,text:question.toLowerCase(),insideForm:true,required,href:'',placeholder:'',value:''};
                const inp=block.querySelector('input[type="text"],textarea');
                if(inp){results.push({...base,tag:inp.tagName.toLowerCase(),type:inp.tagName==='TEXTAREA'?'textarea':'text',role:'',name:inp.name||'',id:inp.id||'',class:inp.className||'',index:0});continue;}
                const radios=[...block.querySelectorAll('[role="radio"],input[type="radio"]')];
                if(radios.length){
                    const opts=radios.map(r=>{const p=r.closest('[data-value]')||r.closest('label')||r.parentElement;return p?(p.innerText.trim()||r.getAttribute('data-value')||r.value):r.value;}).filter(Boolean);
                    results.push({...base,tag:'radio-group',type:'radio',role:'radiogroup',options:opts,name:radios[0].name||'',id:'',class:'',index:0});continue;
                }
                const cbs=[...block.querySelectorAll('[role="checkbox"],input[type="checkbox"]')];
                if(cbs.length){
                    const opts=cbs.map(c=>(c.closest('label')||c.parentElement||c).innerText.trim()).filter(Boolean);
                    results.push({...base,tag:'checkbox-group',type:'checkbox',role:'group',options:opts,name:cbs[0].name||'',id:'',class:'',index:0});continue;
                }
                const dd=block.querySelector('select,[role="listbox"]');
                if(dd){
                    const opts=[...dd.querySelectorAll('option,[role="option"]')].map(o=>o.innerText.trim()).filter(Boolean);
                    results.push({...base,tag:dd.tagName.toLowerCase(),type:'select',role:'listbox',options:opts,name:dd.name||'',id:dd.id||'',class:dd.className||'',index:0});continue;
                }
                const dt=block.querySelector('input[type="date"]');
                if(dt){results.push({...base,tag:'input',type:'date',role:'',name:dt.name||'',id:dt.id||'',class:dt.className||'',placeholder:'YYYY-MM-DD',index:0});continue;}
                const fi=block.querySelector('input[type="file"]');
                if(fi){results.push({...base,tag:'input',type:'file',role:'',name:fi.name||'',id:fi.id||'',class:fi.className||'',index:0});}
            }
            document.querySelectorAll('[role="button"][jsname],.appsMaterialWizButtonPaperbuttonContent').forEach(btn=>{
                const txt=btn.innerText.trim(); if(!txt) return;
                results.push({tag:'div',type:'',role:'button',label:txt,question:'',text:txt.toLowerCase(),name:'',id:btn.id||'',class:btn.className||'',placeholder:'',value:'',href:'',index:0,insideForm:true,required:false});
            });
            return results;
        }""")
        print(f"Extracted {len(items)} Google Form fields.")
        return items

    async def button_click_helper(self, button):
        try:
            await button.click()
            try: await self.page.wait_for_load_state("domcontentloaded", timeout=6000)
            except: pass
            await self.page.wait_for_timeout(1500)
            print(f"URL: {self.page.url}")
            return await self.extract_dom(), True
        except Exception as e:
            print(f"Click failed: {e}"); return None, False

    async def click_button(self, element):
        tag = element.get('tag', 'div')
        try:
            btn = None
            if element.get('label'):
                btn = self.page.get_by_role("button", name=element['label'], exact=True)
                if await btn.count() == 0:
                    btn = self.page.locator(f"[aria-label='{element['label']}']")
            elif element.get('text'):
                btn = self.page.get_by_role("button", name=re.compile(element['text'], re.IGNORECASE))
            elif element.get('name'):
                btn = self.page.locator(f"[name='{element['name']}']")
            elif element.get('id'):
                btn = self.page.locator(f"#{element['id']}")
            elif element.get('class'):
                clean = "." + ".".join(element['class'].split())
                btn = self.page.locator(f"{tag}{clean}")
            else:
                print("Insufficient element info."); return None, False

            count = await btn.count()
            if count == 0: print("No match."); return None, False
            if count == 1: return await self.button_click_helper(btn)

            print(f"\n{count} matches — choose:")
            for i in range(count):
                try: txt = await btn.nth(i).inner_text()
                except: txt = f"element {i}"
                print(f"  [{i}] {txt.strip()}")
            choice = await asyncio.to_thread(input, "Number (or q): ")
            if choice.lower() == 'q': return None, False
            try:
                idx = int(choice)
                if 0 <= idx < count: return await self.button_click_helper(btn.nth(idx))
            except ValueError: pass
            return None, False
        except Exception as e:
            print(f"click_button error: {e}"); return None, False

    async def fill_input(self, element, data: str):
        print(f"Filling '{element.get('label') or element.get('name')}' -> '{data}'")
        if element.get('label') and "docs.google.com/forms" in self.page.url:
            try:
                await self.page.get_by_label(element['label'], exact=False).fill(data)
                return True
            except Exception as e: print(f"  Google label fill failed: {e}")
        strategies = []
        if element.get('name'):        strategies.append(('name',        lambda: self.page.locator(f"[name='{element['name']}']")))
        if element.get('label'):       strategies.append(('label',       lambda: self.page.get_by_label(element['label'], exact=False)))
        if element.get('placeholder'): strategies.append(('placeholder', lambda: self.page.get_by_placeholder(re.compile(re.escape(element['placeholder']), re.IGNORECASE))))
        if element.get('id'):          strategies.append(('id',          lambda: self.page.locator(f"#{element['id']}")))
        if element.get('class'):
            c = "." + ".".join(element['class'].split())
            strategies.append(('class', lambda c=c: self.page.locator(f"input{c}")))
        for sname, fn in strategies:
            try: await fn().fill(data); print(f"  Filled by {sname}"); return True
            except Exception as e: print(f"  {sname} failed: {e}")
        print("  All fill strategies failed."); return False

    async def check_box_helper(self, locator, action):
        try:
            checked = await locator.is_checked()
            if action == "check" and not checked: await locator.check(); print("CHECKED!")
            elif action == "uncheck" and checked: await locator.uncheck(); print("UNCHECKED")
            else: print(f"Already {'checked' if checked else 'unchecked'}.")
            return True
        except Exception as e: print(f"check_box_helper: {e}"); return False

    async def click_checkbox(self, element, action: str = 'check'):
        if element.get('question') and element.get('value'):
            try:
                loc = self.page.locator(f"[data-value='{element['value']}'],"
                                        f"[aria-label='{element['value']}']")
                if await loc.count(): await loc.first.click(); return True
            except Exception as e: print(f"  Google option failed: {e}")
        et = element.get('type', '')
        if et not in ['radio', 'checkbox']: return False
        try:
            if element.get('label'):   loc = self.page.get_by_label(element['label'], exact=False)
            elif element.get('id'):    loc = self.page.locator(f"#{element['id']}")
            elif element.get('name') and element.get('value'): loc = self.page.locator(f'input[name="{element["name"]}"][value="{element["value"]}"]')
            elif element.get('class'):
                clean = '.' + '.'.join(element['class'].split())
                loc = self.page.locator(f"input{clean}")
            else: return False
            return await self.check_box_helper(loc, action)
        except Exception as e: print(f"  click_checkbox error: {e}"); return False

    async def select_option(self, element):
        answer = element.get('answer') or element.get('value', '')
        if not answer: return False
        if element.get('role') == 'listbox' or (element.get('question') and "docs.google.com/forms" in self.page.url):
            try:
                await self.page.get_by_label(element.get('label', ''), exact=False).click()
                await self.page.wait_for_timeout(500)
                await self.page.get_by_role("option", name=re.compile(answer, re.IGNORECASE)).first.click()
                print(f"  Google dropdown: {answer}"); return True
            except Exception as e: print(f"  Google dropdown failed: {e}")
        try:
            loc = None
            if element.get('label'):  loc = self.page.get_by_label(element['label'])
            elif element.get('name'): loc = self.page.locator(f'select[name="{element["name"]}"]')
            elif element.get('id'):   loc = self.page.locator(f"#{element['id']}")
            if loc and await loc.count(): await loc.select_option(answer); return True
        except Exception as e: print(f"  select_option: {e}")
        return False

    async def file_upload(self, element, file_name: str):
        fp = self.get_filepath(file_name)
        if not os.path.exists(fp): print(f"NOT FOUND: {fp}"); return False
        try:
            async with self.page.expect_file_chooser(timeout=8000) as fc_info:
                trigger = None
                if element.get('label'): trigger = self.page.get_by_label(element['label'], exact=False)
                elif element.get('text'): trigger = self.page.get_by_text(re.compile(element['text'], re.IGNORECASE))
                if trigger and await trigger.count(): await trigger.first.click()
                else: await self.page.locator("input[type='file'],[aria-label*='upload']").first.click()
            fc = await fc_info.value; await fc.set_files(fp)
            print(f"  File uploaded: {file_name}"); return True
        except Exception as e: print(f"  File chooser failed: {e}")
        try:
            loc = None
            if element.get('label'):  loc = self.page.get_by_label(element['label'])
            elif element.get('id'):   loc = self.page.locator(f"#{element['id']}")
            elif element.get('name'): loc = self.page.locator(f"input[name='{element['name']}']")
            else: loc = self.page.locator("input[type='file']").first
            if loc: await loc.set_input_files(fp); print(f"  File set: {file_name}"); return True
        except Exception as e: print(f"  file_upload: {e}")
        return False

    def get_filepath(self, file_path: str):
        return os.path.join(self.data_folder, file_path)

    async def reuse_session(self, file_name: str):
        # Accept both absolute paths and plain filenames
        fp = file_name if os.path.isabs(file_name) else self.get_filepath(file_name)
        if not os.path.exists(fp): print(f"Session not found: {fp}"); return False
        if self.context: await self.context.close()
        self.context = await self.browser.new_context(storage_state=fp)
        self.page    = await self.context.new_page()
        self._main_page = self.page
        self.page.set_default_timeout(self.timeout)
        self.context.on("page", self._on_new_page)
        print("Session restored."); return True

    async def save_session(self, file_name: str):
        try:
            await self.page.context.storage_state(path=self.get_filepath(file_name))
            print("Session saved."); return True
        except Exception as e: print(f"Save session failed: {e}"); return False

    async def save_screenshot(self, filename: str):
        if not os.path.splitext(filename)[1]: filename += ".png"
        fp = self.get_filepath(filename)
        if os.path.exists(fp):
            from datetime import datetime
            b, e = os.path.splitext(filename)
            fp = self.get_filepath(f"{b}_{datetime.now().strftime('%H%M%S')}{e}")
        try:
            await self.page.screenshot(path=fp); print(f"Screenshot: {os.path.basename(fp)}"); return True
        except Exception as e: print(f"Screenshot: {e}"); return False