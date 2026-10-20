"""Avatar input/HTTP boundaries fail on modified, absent or oversized media."""
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from researchops import dashboard_bundle as b
from researchops.dashboard_server import LocalServer, resources


class AvatarMediaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.assets = Path(tmp.name)
        self.data = b"\x00\x00\x00\x18ftypisom avatar test clip"
        self.pins = {name:b.digest(self.data) for name in b.AVATAR_VIDEOS}
        patcher = patch.object(b, 'AVATAR_VIDEOS', self.pins)
        patcher.start(); self.addCleanup(patcher.stop)
        for name in self.pins: (self.assets/name).write_bytes(self.data)
        for name in b.AVATARS: (self.assets/name).write_bytes(b'poster fixture')

    def test_exact_local_clips_accepted(self):
        self.assertEqual({name:self.data for name in self.pins}, b.video_assets(self.assets))

    def test_modified_clip_rejected(self):
        (self.assets/'lucy.mp4').write_bytes(self.data+b'changed')
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_AVATAR_VIDEO'): b.video_assets(self.assets)

    def test_missing_clip_rejected(self):
        (self.assets/'david.mp4').unlink()
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_AVATAR_VIDEO'): b.video_assets(self.assets)

    def test_oversized_clip_rejected_even_if_rehashed(self):
        value=b'\x00\x00\x00\x18ftyp'+b'x'*(2*1024*1024)
        (self.assets/'david.mp4').write_bytes(value); self.pins['david.mp4']=b.digest(value)
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_AVATAR_VIDEO'): b.video_assets(self.assets)

    def test_disguised_non_video_rejected_even_if_rehashed(self):
        value=b'not an mp4 file'+b'x'*20
        (self.assets/'lucy.mp4').write_bytes(value); self.pins['lucy.mp4']=b.digest(value)
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_AVATAR_VIDEO'): b.video_assets(self.assets)

    def test_http_exact_media_mime_csp_and_no_extra_file_routes(self):
        server=LocalServer(('127.0.0.1',0),None,resources(self.assets))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for name in self.pins:
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                c.request('GET','/assets/'+name);r=c.getresponse()
                self.assertEqual(200,r.status);self.assertEqual('video/mp4',r.getheader('Content-Type'))
                self.assertIn("media-src 'self'",r.getheader('Content-Security-Policy'))
                self.assertEqual(self.data,r.read());c.close()
            for path in ('/assets/unknown.mp4','/assets/../machine.json','/assets/lucy.mp4?path=elsewhere'):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                c.request('GET',path);r=c.getresponse();self.assertEqual(404,r.status);r.read();c.close()
        finally:
            server.shutdown();server.server_close();thread.join(3)
