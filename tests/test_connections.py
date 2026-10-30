import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from ui import integrations as host,max_connection
class ConnectionTests(unittest.TestCase):
 def test_missing_target_never_falls_back(self):
  self.assertIsNone(host.preferred_session([{'directory':'other','protocol':2}],'closed'))
 def test_windows_include_unconnected(self):
  with patch.object(max_connection,'windows',return_value=[{'pid':1,'birth':'a'},{'pid':2,'birth':'b'}]),patch.object(host,'sessions',return_value=[{'pid':1,'birth':'a','directory':'one'}]):
   result=host.available_windows();self.assertEqual(result[0]['session']['directory'],'one');self.assertIsNone(result[1]['session'])
 def test_reused_pid_is_rejected(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);folder=root/'one';folder.mkdir();(folder/'info.json').write_text(json.dumps({'pid':123,'birth':'old'}))
   with patch.object(host,'session_root',return_value=root),patch.object(max_connection,'process_identity',return_value={'birth':'new'}):
    self.assertEqual(host.sessions(),[])
    with self.assertRaises(ValueError):host.request({'directory':str(folder),'pid':123,'birth':'old'},'inspect')
    self.assertFalse(list(folder.glob('*.request.json')))
 def test_install_is_user_scoped_and_idempotent(self):
  with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',{'APPDATA':temp}):
   script=Path(temp)/'bridge.ms';script.write_text('-- test')
   first=max_connection.install('test',script);before=(first/'PackageContents.xml').read_bytes()
   self.assertEqual(max_connection.install('test',script),first)
   self.assertEqual(before,(first/'PackageContents.xml').read_bytes())
   self.assertIn(str(script),(first/'loader.ms').read_text('utf-8-sig'))
if __name__=='__main__':unittest.main()
