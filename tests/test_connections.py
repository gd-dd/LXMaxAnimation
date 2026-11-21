import base64,hashlib,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
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
   self.assertIn(max_connection.mxs_string(script),(first/'loader.ms').read_text('utf-8-sig'))
 def test_installed_xml_preserves_name_and_loader(self):
  import xml.etree.ElementTree as ET
  with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',{'APPDATA':temp}):
   script=Path(temp)/'bridge.ms';script.write_text('-- test')
   folder=max_connection.install("test&'name",script)
   root=ET.parse(folder/'PackageContents.xml').getroot()
   self.assertEqual(root.attrib['Name'],"LX test&'name connection")
   self.assertEqual(root.find('Components/ComponentEntry').attrib['ModuleName'],'./loader.ms')
   self.assertEqual(root.attrib['ProductCode'],root.attrib['UpgradeCode'])
 def test_registration_uses_a_validated_package_path_and_is_idempotent(self):
  with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',{'APPDATA':temp,'LOCALAPPDATA':temp}):
   package=Path(__file__).resolve().parents[1]
   context=SimpleNamespace(package_root=package,resource=lambda relative:package/relative)
   installed=max_connection.register('max-animation',context)
   descriptor=Path(temp)/'LXMaxTools/auto-connect/max-animation.txt'
   lines=descriptor.read_text('ascii').splitlines()
   self.assertEqual(Path(base64.b64decode(lines[0]).decode()),package)
   self.assertEqual(lines[2],hashlib.sha256((package/'max/bridge.py').read_bytes()).hexdigest())
   timestamp=descriptor.stat().st_mtime_ns
   self.assertEqual(max_connection.register('max-animation',context),installed)
   self.assertEqual(descriptor.stat().st_mtime_ns,timestamp)
   self.assertIn('auto_connect.ms',(installed/'loader.ms').read_text('utf-8-sig'))

 def test_attach_skips_ready_and_unsupported_processes(self):
  with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',{'LOCALAPPDATA':temp}):
   package=Path(__file__).resolve().parents[1]
   context=SimpleNamespace(resource=lambda relative:package/relative)
   controller=max_connection.AutoAttach('max-animation',context)
   windows=[dict(pid=1251,birth='ready',title='Autodesk 3ds Max 2026'),
            dict(pid=1252,birth='unsupported',title='Autodesk 3ds Max 2023'),
            dict(pid=1253,birth='waiting',title='Autodesk 3ds Max 2026')]
   try:
    with patch.object(max_connection,'windows',return_value=windows),patch.object(max_connection,'attach_window',return_value=True) as attach:
     controller.poll({(1251,'ready')})
     controller.job.join(timeout=3)
     self.assertFalse(controller.job.is_alive())
    self.assertEqual(controller.windows_count,2)
    self.assertEqual(attach.call_args.args[0],windows[-1])
   finally:
    controller.close()
if __name__=='__main__':unittest.main()
