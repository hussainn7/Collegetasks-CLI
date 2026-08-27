from playwright.sync_api import sync_playwright
from config import settings

settings.ensure_data_dir()
profile_path = str(settings.browser_profile_path)

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=profile_path,
        headless=True
    )
    cookies = context.cookies()
    for c in cookies:
        print(c['name'], c.get('expires', 'session'))
    context.close()
