"""Real Edge, isolated HTTPS server and TEMP settings; no model or platform calls."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('browser_fixture', ROOT / 'tests/workbench_native_browser.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    from easel import harnesses
    from playwright.sync_api import sync_playwright, expect
    report = {'passed': False, 'real_model_calls': 0, 'production_data_access': False,
              'native': args.native.name, 'checks': []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
            headless=True, args=['--ignore-certificate-errors'])
        with fixture.isolated(args.native.resolve(), b'TEMP unused image') as data, patch.object(harnesses, 'describe',
            lambda runtime: {'id': runtime, 'label': runtime, 'installed': True, 'protocol': 'TEMP', 'install_hint': 'TEMP'}):
            for name, width in [('desktop', 1280), ('mobile', 390)]:
                context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 900},
                    is_mobile=width < 500, has_touch=width < 500)
                context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': data['origin'],
                    'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(data['origin'] + '/native/?path=%2Fsettings%3Fpanel%3Dmodel', wait_until='domcontentloaded')
                toggle = page.get_by_role('switch', name='永久通过授权', exact=True)
                sandbox = page.get_by_role('button', name='Codex 沙箱', exact=True)
                save = page.get_by_role('button', name='保存底座', exact=True)
                expect(toggle).to_have_attribute('aria-checked', 'false')
                expect(sandbox).to_be_enabled()
                toggle.click()
                expect(toggle).to_have_attribute('aria-checked', 'true')
                expect(sandbox).to_be_disabled()
                expect(page.locator('#codex-auto-approve-help')).to_contain_text('不再请求人工执行审批')
                save.click()
                expect(page.get_by_text('已保存，请新建对话；旧对话仍保留在原底座，不迁移历史。', exact=True)).to_be_visible()
                page.reload(wait_until='domcontentloaded')
                expect(toggle).to_have_attribute('aria-checked', 'true')
                expect(sandbox).to_be_disabled()
                toggle.scroll_into_view_if_needed()
                page.screenshot(path=str(args.out / (name + '-full-access.png')))
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                toggle.click()
                expect(sandbox).to_be_enabled()
                save.click()
                expect(page.get_by_text('已保存，请新建对话；旧对话仍保留在原底座，不迁移历史。', exact=True)).to_be_visible()
                page.reload(wait_until='domcontentloaded')
                expect(toggle).to_have_attribute('aria-checked', 'false')
                assert not errors, errors
                report['checks'].append({'viewport': name, 'save_reload_enable_disable': True, 'no_horizontal_overflow': True})
                context.close()
        browser.close()
    report['passed'] = True
    (args.out / 'browser.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
