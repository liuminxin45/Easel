import json
from pathlib import Path
import tempfile
import unittest

from easel_health_control.cli import report
from easel_health_control.state import StateStore
from easel_health_control.usage import project


class UsageReportTests(unittest.TestCase):
    def test_only_aggregate_enums_numbers_leave_projection(self):
        value = {'status': 'available', 'enabled': True, 'credential': 'PRIVATE',
            'totals': {'view': 8, 'sql': 'PRIVATE'},
            'screens': [{'id': 'skills', 'count': 8, 'body': 'PRIVATE'}],
            'actions': [{'id': 'work.open', 'activate': 3, 'accepted': -1, 'label': 'PRIVATE'}],
            'paths': [{'from': '<script>PRIVATE</script>', 'to': 'skills', 'count': 5}]}
        result = project(value)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('accepted', result['actions'][0])
        self.assertEqual(result['paths'], [])

    def test_report_displays_current_and_retired_records_and_missing_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = StateStore(temporary)
            report(store)
            self.assertIn('当前使用数据不可用', (Path(temporary)/'report.html').read_text(encoding='utf-8'))
            store.write('status.json', {'observation': {'usage': {'status': 'available', 'enabled': False,
                'actions': [{'id': 'work.open', 'activate': 3}],
                'screens': [{'id': 'settings.usage', 'count': 2, 'retired': True}],
                'paths': [{'from': 'skills', 'to': 'works.list', 'count': 4}]}}})
            report(store)
            body = (Path(temporary)/'report.html').read_text(encoding='utf-8')
            for text in ('使用与路径', '已暂停记录', '当前页面与操作', '已退役页面与操作的历史记录', 'work.open', 'settings.usage', 'works.list'):
                self.assertIn(text, body)
            self.assertNotIn('<script', body)
