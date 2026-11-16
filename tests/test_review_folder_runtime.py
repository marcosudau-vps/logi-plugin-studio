"""Native folder semantic/runtime checks against actual generated C# and installed SDK."""
import copy
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
import struct
import zlib
from xml.etree import ElementTree
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from adapters.logitech.folder_runtime import initial_layout, validate_layout, project_virtual_folders, FolderRuntimeError
from adapters.logitech.folder_host import FolderRuntimeHost
from adapters.logitech.product import generate_product, build_product, provision_connection
from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.naming import identifier
from runtime.wire import ConnectionSettings, LocalClient, HostError
from probe_helpers import ProcessProbe

def sample():
    raw=json.loads((ROOT/'examples/project_logitech_native_v1.json').read_text(encoding='utf-8'))
    raw['folders'][0]['entries'][0]['action_parameter']='first'
    return raw

def navigation_layout(raw, revision=1):
    layout,_=initial_layout(raw)
    def page(identity,entries):return dict(id=identity,entries=entries)
    def link(identity,target):return dict(id=identity,kind='link',label=target,target_id=target)
    layout['revision']=revision
    layout['folders'][0].update(start='folder.b',nodes=[
        dict(id='folder.b',label='B',pages=[page('page.b',[link('placement.link','folder.a.leaf')]),page('page.b.second',[])]),
        dict(id='folder.a',label='A',pages=[page('page.a',[link('placement.parent','folder.a.leaf')])]),
        dict(id='folder.a.leaf',label='A leaf',pages=[page('page.leaf',[dict(id='placement.shared',kind='action',label='Shared',action_id='action.command',action_parameter='second')])])])
    return validate_layout(layout,raw)

class FolderProjectionTests(unittest.TestCase):
    def test_native_initial_layout_blocks_editor_and_preserves_parameter(self):
        layout,diags=initial_layout(sample());entries=layout['folders'][0]['nodes'][0]['pages'][0]['entries']
        self.assertEqual(entries[0]['action_parameter'],'first');self.assertEqual(entries[3]['kind'],'unavailable')
        self.assertEqual(diags[0]['code'],'FOLDER_ACTION_EDITOR_UNSUPPORTED')
    def test_unknown_action_parameter_folder_target_and_editor_fail_closed(self):
        raw=sample();layout,_=initial_layout(raw)
        for edit in (lambda d:d.update(version='bad'),lambda d:d.update(plugin_id='foreign.plugin'),lambda d:d.update(revision=True),
                     lambda d:d['folders'][0]['nodes'][0]['pages'][0]['entries'][0].update(action_id='action.missing'),
                     lambda d:d['folders'][0]['nodes'][0]['pages'][0]['entries'][0].update(action_parameter='missing'),
                     lambda d:d['folders'][0]['nodes'][0]['pages'][0]['entries'][0].update(action_id='action.editor',action_parameter=None),
                     lambda d:d['folders'][0].update(start='folder.missing')):
            d=copy.deepcopy(layout);edit(d)
            with self.assertRaises(FolderRuntimeError):validate_layout(d,raw)
    def test_encoder_area_conflict_is_explicit(self):
        raw=sample();raw['folders'][0]['navigation']='EncoderArea'
        with self.assertRaisesRegex(FolderRuntimeError,'ENCODER_NAVIGATION_CONFLICT'):initial_layout(raw)
    def test_host_dynamic_allowlist_revision_and_snapshot(self):
        raw=sample();settings=ConnectionSettings(raw['plugin']['id'],__import__('runtime.wire',fromlist=['project_digest']).project_digest(raw),0,secrets.token_hex(32))
        host=FolderRuntimeHost(raw,settings);self.addCleanup(host.close)
        d=host.snapshot()['folder_runtime'];d['revision']=1
        d['folders'][0]['nodes'][0]['pages'][0]['entries'].pop(0)
        self.assertTrue(host.replace_folder_layout(d));self.assertFalse(host.replace_folder_layout(d))
        old=copy.deepcopy(d);old['revision']=0
        with self.assertRaises(HostError):host.replace_folder_layout(old)
        self.assertEqual(host.snapshot()['folder_runtime'],d)
        self.assertFalse(any(p['id']=='placement.command' for v in host._raw['views'] for p in v['placements']))
    def test_multiple_native_folders_and_virtual_projection(self):
        from studio.virtual_folders.sample import demo_document
        from dataclasses import asdict
        raw=sample();other=copy.deepcopy(raw['folders'][0]);other['id']='folder.second'
        for p in other['entries']:p['id']+='.second'
        raw['folders'].append(other)
        doc=demo_document(raw,'project.review')
        projected=project_virtual_folders(raw,asdict(doc),entrypoints={f['id']:doc.root_id for f in raw['folders']},revision=1)
        self.assertEqual(len(projected['folders']),2)
        self.assertTrue(any(e['kind']=='unavailable' for n in projected['folders'][0]['nodes'] for p in n['pages'] for e in p['entries']))
    def test_virtual_projection_rejects_malformed_authoring_graph(self):
        from studio.virtual_folders.sample import demo_document
        from dataclasses import asdict
        raw=sample();document=asdict(demo_document(raw,'project.review'))
        document['placements'][0]['kind']='invented'
        with self.assertRaises(FolderRuntimeError):
            project_virtual_folders(raw,document,entrypoints={'folder.main':document['root_id']},revision=1)
    def test_explicit_extension_generator_cli_produces_native_sources(self):
        from studio.virtual_folders.sample import demo_document
        from studio.virtual_folders.codec import encode
        raw=sample();doc=demo_document(raw,'project.review')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=root/'project.json';project.write_text(json.dumps(raw))
            extension=root/'project.vfolders.json';extension.write_bytes(encode(doc))
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_folder_runtime.py'),str(project),str(extension),'--entrypoint',f'folder.main={doc.root_id}','--out',str(root/'generated'),'--assembly','FolderCli'],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['folder_runtime'],'sdk-folders-1')
            self.assertIn('NativeFolderBase',(root/'generated/src/NativeFolders.cs').read_text())
            self.assertFalse((root/'generated/studio.connection.json').exists())

@unittest.skipUnless(DEFAULT_SDK_DLL.is_file(),'installed Logitech SDK required')
class NativeFolderSdkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='native-folder-sdk-');cls.root=Path(cls.tmp.name)
        cls.raw=sample()
        cls.raw['folders'][0]['entries'].append(dict(id='placement.plain',action='action.command',position=4))
        other=copy.deepcopy(cls.raw['folders'][0]);other['id']='folder.second'
        for entry in other['entries']:entry['id']+='.second'
        cls.raw['folders'].append(other)
        def png(size):
            def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
            return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0\xff'*size)*size))+chunk(b'IEND',b'')
        for index,state in enumerate(cls.raw['actions'][1]['states']):
            state['image']=f'state{index}.png';(cls.root/state['image']).write_bytes(png(index+2))
        p=cls.root/'project.json';p.write_text(json.dumps(cls.raw),encoding='utf-8')
        product=cls.root/'plugin';cls.plan=generate_product(p,output_dir=product,assembly_name='ReviewFolders')
        build_product(cls.plan,product,log_path=cls.root/'build.log')
        cls.connection=provision_connection(cls.plan,product)
        folder=identifier('Folder',cls.raw['folders'][0]['id'])
        names={a.component_id:a.type_name for a in cls.plan.actions}
        source=(ROOT/'tests/process_probe/NativeFolderProbe.cs.in').read_text()
        for key,value in {'NAMESPACE':cls.plan.namespace,'PLUGIN_TYPE':cls.plan.plugin_class,'FOLDER_TYPE':folder,'OTHER_FOLDER_TYPE':identifier('Folder','folder.second'),'COMMAND_TYPE':names['action.command'],
                          'MULTISTATE_TYPE':names['action.multistate'],'ADJUSTMENT_TYPE':names['action.adjustment']}.items():
            source=source.replace('$'+key+'$',value)
        probe=cls.root/'probe';probe.mkdir();(probe/'Program.cs').write_text(source,encoding='utf-8')
        includes=''.join(f'<Compile Include="{escape(str(product/name))}" />' for name in cls.plan.files if name.endswith('.cs'))
        tree=ElementTree.fromstring(cls.plan.files[cls.plan.csproj_relative_path])
        for resource in tree.iter('EmbeddedResource'):
            includes+=f'<EmbeddedResource Include="{escape(str(product/resource.attrib["Include"]))}"><LogicalName>{resource.findtext("LogicalName")}</LogicalName></EmbeddedResource>'
        (probe/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><ImportDirectoryBuildProps>false</ImportDirectoryBuildProps><ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup><ItemGroup>'+includes+'<Reference Include="PluginApi"><HintPath>'+escape(str(DEFAULT_SDK_DLL))+'</HintPath></Reference></ItemGroup></Project>')
        (probe/'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
        result=subprocess.run(['dotnet','build',str(probe/'Probe.csproj'),'--nologo','-v:q'],capture_output=True,text=True,timeout=120)
        if result.returncode:raise AssertionError(result.stdout+result.stderr)
        cls.dll=probe/'bin/Debug/net10.0/Probe.dll'
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def setUp(self):
        self.seen=[]
        self.host=FolderRuntimeHost(self.raw,ConnectionSettings.load(self.connection))
        self.host.register_handler('handler.main','invoke',lambda payload,c:self.seen.append(dict(component=c.component_id,placement=c.placement_id,parameter=c.action_parameter,operation=c.operation,diff=c.adjustment_diff)) or {})
        self.host.start();self.addCleanup(self.host.close)
        self.probe=ProcessProbe(self.dll,self.connection,self.root/'process.log',sdk_dll=DEFAULT_SDK_DLL);self.addCleanup(self.probe.close)
        try:
            def ready(s):
                self.assertNotIn('error',s,s)
                return s['ready']
            self.probe.wait(ready)
        except Exception as exc:
            raise AssertionError((self.root/'process.log').read_text(encoding='utf-8')) from exc
    def rpc(self,command):
        value=self.probe.rpc(command);self.assertNotIn('error',value,value);return value
    def wait_calls(self,n):
        # A callback precedes the HTTP acknowledgement. Wait for its completed
        # journal roundtrip before driving the next explicit SDK operation.
        until=time.monotonic()+6
        while time.monotonic()<until:
            view=self.rpc('inspect')
            if len(self.seen)>=n and view['ready'] and view['transport']['seq']>=n:break
            time.sleep(.02)
        self.assertEqual(len(self.seen),n,dict(seen=self.seen,view=self.probe.rpc('inspect'),log=(self.root/'process.log').read_text(encoding='utf-8')))
    def test_direct_and_folder_command_parameter_state_and_adjustment(self):
        view=self.rpc('inspect');command=next(x for x in view['buttons'] if 'placement.command' in x)
        self.assertTrue(self.rpc('direct|action.command|first')['ok']);self.wait_calls(1)
        self.rpc('run|'+command);self.wait_calls(2)
        self.assertEqual(self.seen[0]['parameter'],self.seen[1]['parameter']);self.assertIsNone(self.seen[0]['placement'])
        self.assertEqual(self.seen[1]['placement'],'placement.command')
        self.rpc('direct|action.multistate');self.wait_calls(3)
        self.assertEqual(self.rpc('state')['name'],'on')
        multi=next(x for x in view['buttons'] if 'placement.multistate' in x)
        self.rpc('run|'+multi);self.wait_calls(4);self.assertEqual(self.rpc('state')['name'],'off')
        self.assertEqual(self.rpc('text|'+multi)['text'],'Aus')
        adjust=view['encoders'][0];self.assertTrue(self.rpc('direct-adjust|2')['ok']);self.wait_calls(5)
        self.rpc('adjust|'+adjust+'|3');self.wait_calls(6)
        self.assertEqual(self.seen[-1],dict(component='action.adjustment',placement='placement.adjustment',parameter=None,operation='adjustment',diff=3))
        self.assertIn('55',self.rpc('value|'+adjust)['value'])
        self.rpc('run|'+view['resets'][0]);self.wait_calls(7)
        self.assertIn('50',self.rpc('value|'+adjust)['value'])
        plain=next(x for x in view['buttons'] if 'placement.plain' in x)
        self.rpc('direct|action.command');self.wait_calls(8);self.rpc('run|'+plain);self.wait_calls(9)
        self.assertIsNone(self.seen[-1]['parameter']);self.assertIsNone(self.seen[-2]['parameter'])
        self.assertEqual(self.seen[-1]['placement'],'placement.plain')
    def test_native_state_images_match_direct_sdk_action_and_repaint_without_membership(self):
        before=self.rpc('inspect');multi=next(x for x in before['buttons'] if 'placement.multistate' in x)
        self.assertEqual(self.rpc('image|'+multi),self.rpc('direct-image'))
        self.assertEqual(self.rpc('image|'+multi)['width'],2)
        self.rpc('direct|action.multistate');self.wait_calls(1)
        self.assertEqual(self.rpc('image|'+multi),self.rpc('direct-image'))
        self.assertEqual(self.rpc('image|'+multi)['width'],3)
        after=self.rpc('inspect');self.assertEqual(after['membership'],before['membership']);self.assertGreater(after['images'],before['images'])
    def test_bad_ids_and_action_editor_do_not_invoke(self):
        view=self.rpc('inspect');editor=next(x for x in view['buttons'] if 'placement.editor' in x)
        self.rpc('run|unknown');self.rpc('run|foreign/'+editor);self.rpc('run|'+editor)
        time.sleep(.2);self.assertEqual(self.seen,[])
        self.assertEqual(self.rpc('inspect')['diagnostic'],'FOLDER_ACTION_EDITOR_UNSUPPORTED')
    def test_signed_dynamic_membership_link_back_page_and_stale_callbacks(self):
        before=self.rpc('inspect');old=before['buttons'][0]
        layout=navigation_layout(self.raw)
        self.host.replace_folder_layout(layout)
        until=time.monotonic()+4
        while time.monotonic()<until:
            view=self.rpc('inspect')
            if view['node']=='folder.b':break
            time.sleep(.03)
        self.assertEqual(view['node'],'folder.b');self.assertGreater(view['membership'],before['membership'])
        self.assertEqual(view['other_node'],'folder.second');self.assertTrue(view['other_buttons'])
        self.assertTrue(view['notifications'])
        self.rpc('run|'+old);self.assertEqual(self.seen,[])
        next_page=next(x for x in view['buttons'] if ':next' in x)
        self.rpc('run|'+next_page);second=self.rpc('inspect')
        self.assertEqual((second['page'],second['back']),(1,0))
        self.rpc('run|'+next(x for x in second['buttons'] if ':previous' in x))
        view=self.rpc('inspect');self.rpc('run|'+next(x for x in view['buttons'] if 'placement.link' in x))
        leaf=self.rpc('inspect');self.assertEqual((leaf['node'],leaf['back']),('folder.a.leaf',1))
        command=next(x for x in leaf['buttons'] if 'placement.shared' in x)
        self.rpc('run|'+command);self.wait_calls(1)
        self.assertEqual((self.seen[0]['placement'],self.seen[0]['parameter']),('placement.shared','second'))
        self.rpc('run|'+next(x for x in leaf['buttons'] if ':back' in x))
        returned=self.rpc('inspect');self.assertEqual((returned['node'],returned['page'],returned['back']),('folder.b',0,0))
        self.rpc('run|'+command);time.sleep(.1);self.assertEqual(len(self.seen),1)
    def test_label_update_repaints_without_membership_change_and_bad_data_preserves_view(self):
        before=self.rpc('inspect');layout=self.host.snapshot()['folder_runtime'];layout['revision']=1
        layout['folders'][0]['nodes'][0]['pages'][0]['entries'][3]['label']='Unavailable editor changed'
        self.host.replace_folder_layout(layout)
        until=time.monotonic()+4
        while time.monotonic()<until:
            after=self.rpc('inspect')
            if after['images']>before['images']:break
            time.sleep(.03)
        self.assertEqual(before['membership'],after['membership']);self.assertEqual(before['buttons'],after['buttons'])
        broken=copy.deepcopy(layout);broken['revision']=2;broken['folders'][0]['start']='unknown'
        rejected=self.probe.rpc('replace|'+json.dumps(broken,separators=(',',':')))
        self.assertIn('error',rejected);self.assertEqual(self.rpc('inspect')['buttons'],after['buttons'])
        self.rpc('run|arbitrary/placement.multistate');self.assertEqual(self.seen,[])
    def test_host_restart_resends_layout_without_replaying_commands(self):
        view=self.rpc('inspect');command=next(x for x in view['buttons'] if 'placement.command' in x)
        self.rpc('run|'+command);self.wait_calls(1)
        self.host.close()
        self.probe.wait(lambda s:not s['ready'])
        self.host=FolderRuntimeHost(self.raw,ConnectionSettings.load(self.connection))
        self.host.register_handler('handler.main','invoke',lambda p,c:self.seen.append(dict(component=c.component_id,placement=c.placement_id)) or {})
        self.host.start();self.addCleanup(self.host.close)
        self.probe.wait(lambda s:s['ready']);time.sleep(.2)
        self.assertEqual(len(self.seen),1)
    def test_csharp_rejects_stale_duplicate_missing_fields_and_invalid_ids(self):
        layout=self.host.snapshot()['folder_runtime'];layout['revision']=2
        self.rpc('replace|'+json.dumps(layout,separators=(',',':')))
        before=self.rpc('inspect')
        invalids=[]
        for edit in (lambda d:d.update(revision=1), lambda d:d.pop('revision'),lambda d:d.update(extra=True),
                     lambda d:d['folders'][0]['nodes'][0]['pages'][0]['entries'][0].update(action_id='action.unknown'),
                     lambda d:d['folders'][0]['nodes'][0]['pages'][0]['entries'][0].update(action_parameter='unknown'),
                     lambda d:d['folders'][0]['nodes'][0]['pages'][0]['entries'][0].update(id='INVALID ID')):
            d=copy.deepcopy(layout);d['revision']=3;edit(d);invalids.append(json.dumps(d,separators=(',',':')))
        invalids.append('{"version":"sdk-folders-1","version":"sdk-folders-1"}')
        for data in invalids:
            with self.subTest(data=data[:100]):
                self.assertIn('error',self.probe.rpc('replace|'+data))
                self.assertEqual(self.rpc('inspect')['buttons'],before['buttons'])
