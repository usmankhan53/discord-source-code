"""Regression coverage for uploads, deterministic calculations and streaming events."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient
import app as module


def chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class FakeStream:
    def __enter__(self):
        return iter([chunk('The total '), chunk('is 60.')])

    def __exit__(self, *args):
        pass


class AnalystTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(module.app)
        module.df = None
        self.data = pd.DataFrame({'Revenue': [10, 20, 30], 'Region': ['A', 'B', 'A'], '_value': ['keep', 'this', 'column']})

    def upload(self):
        buffer = io.BytesIO()
        self.data.to_excel(buffer, index=False)
        return self.client.post('/upload', files={'file': ('sample.xlsx', buffer.getvalue())})

    def test_upload_and_static_assets(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['rows'], 3)
        for route in ['/', '/static/app.js', '/static/styles.css']:
            self.assertEqual(self.client.get(route).status_code, 200)

    def test_invalid_upload_preserves_previous_data(self):
        self.upload()
        response = self.client.post('/upload', files={'file': ('bad.xlsx', b'broken')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(module.df), 3)

    def test_missing_upload_and_blank_question(self):
        self.assertEqual(self.client.post('/ask/stream', json={'question': 'Total?'}).status_code, 400)
        self.upload()
        self.assertEqual(self.client.post('/ask/stream', json={'question': '  '}).status_code, 400)
        self.assertEqual(self.client.post('/ask/stream', json={'question': ''}).status_code, 422)

    def test_calculations_and_original_columns(self):
        self.assertEqual(module.analyze({'operation': 'sum', 'column': 'Revenue'}, self.data), {'result': 60.0})
        self.assertEqual(module.analyze({'operation': 'group_sum', 'column': 'Revenue', 'group_by': 'Region'}, self.data), {'A': 40.0, 'B': 20.0})
        top = module.analyze({'operation': 'top', 'column': 'Revenue'}, self.data)
        self.assertEqual(top[0]['_value'], 'column')
        self.assertEqual(top[0]['Revenue'], 30)

    def test_stream_success(self):
        self.upload()
        with patch.object(module, 'choose_plan', return_value={'operation': 'sum', 'column': 'Revenue'}), patch.object(module.ai.chat.completions, 'create', return_value=FakeStream()) as create:
            response = self.client.post('/ask/stream', json={'question': 'Total revenue?'})
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertIn('application/x-ndjson', response.headers['content-type'])
        self.assertEqual(events[1]['answer'], {'result': 60.0})
        self.assertEqual(''.join(e['text'] for e in events if e['type'] == 'delta'), 'The total is 60.')
        self.assertEqual(events[-1]['type'], 'done')
        self.assertTrue(create.call_args.kwargs['stream'])

    def test_stream_error_after_result_retains_calculation(self):
        self.upload()
        with patch.object(module, 'choose_plan', return_value={'operation': 'sum', 'column': 'Revenue'}), patch.object(module.ai.chat.completions, 'create', side_effect=RuntimeError('provider down')):
            with self.assertLogs(module.logger, level='ERROR'):
                response = self.client.post('/ask/stream', json={'question': 'Total?'})
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertTrue(any(e['type'] == 'result' for e in events))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertNotIn('provider down', response.text)

    def test_unsupported_plan(self):
        self.upload()
        with patch.object(module, 'choose_plan', return_value={'operation': 'unsupported'}):
            response = self.client.post('/ask/stream', json={'question': 'Predict next year'})
        self.assertEqual(json.loads(response.text.splitlines()[-1])['type'], 'error')

    def test_legacy_json_endpoint(self):
        self.upload()
        with patch.object(module, 'choose_plan', return_value={'operation': 'count'}):
            response = self.client.post('/ask', json={'question': 'Row count?'})
        self.assertEqual(response.json()['answer'], {'rows': 3})


if __name__ == '__main__':
    unittest.main()
