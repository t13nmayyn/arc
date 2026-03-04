from browse import Browser
import asyncio


async def main():
    b = Browser(12000, 'sessions')
    await b.start()
    await b.reuse_session('google_form_1.json')
    x =  await b.open_url('https://docs.google.com/forms/d/e/1FAIpQLSeuC0srpuef_3F2OZiyxqhFEniB0KuOXXHJES3ok_PFtrsGAQ/viewform')
    print(x)


asyncio.run(main())