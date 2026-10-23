"""The UI renderer must not expose execution or render submitted HTML as code."""
import unittest
from unittest.mock import patch
from app import create_app


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.client=create_app().test_client()
    def test_templates_and_fragments_render(self):
        for path in ('/','/view/prompt','/view/progress','/view/progress?scenario=approval','/view/progress?scenario=blocked'):
            with self.subTest(path=path): self.assertEqual(200,self.client.get(path).status_code)
    def test_execution_endpoints_do_not_exist(self):
        for path in ('/api/tasks','/api/worker/turns','/exec','/run'):
            self.assertEqual(404,self.client.post(path,headers={'Origin':'http://localhost'}).status_code)
    def test_demo_input_is_escaped(self):
        r=self.client.post('/demo/message',data={'prompt':'<img src=x onerror=alert(1)>','channel':'analysis'},headers={'Origin':'http://localhost'})
        self.assertEqual(200,r.status_code);self.assertNotIn(b'<img',r.data);self.assertIn(b'&lt;img',r.data)
    def test_external_origin_and_host_refused(self):
        self.assertEqual(403,self.client.post('/demo/message',data={'prompt':'hi'},headers={'Origin':'https://external.invalid'}).status_code)
        self.assertEqual(403,self.client.get('/',headers={'Host':'external.invalid'}).status_code)
    def test_unknown_paths_and_oversize_inputs_refused(self):
        self.assertEqual(404,self.client.get('/view/unknown').status_code)
        self.assertEqual(400,self.client.get('/view/progress?scenario=unknown').status_code)
        self.assertEqual(404,self.client.get('/avatars/unknown.mp4').status_code)
        self.assertEqual(400,self.client.post('/demo/message',data={'prompt':'x'*20001},headers={'Origin':'http://localhost'}).status_code)
    def test_local_assets_and_preview_identity(self):
        with self.client.get('/static/vendor/htmx.min.js') as response:
            self.assertEqual(200,response.status_code)
        with patch('execution.capability',return_value={'enabled':False}):
            health=self.client.get('/preview-health').json
        self.assertTrue(health['ui_only'])
        self.assertEqual(health['owner'],'BGV.SceneControl.UI.v1')


if __name__=='__main__':unittest.main()
