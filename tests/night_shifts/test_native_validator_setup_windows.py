"""Ordinary native relative-create/flush/sharing characterization, NOT setup.

Only disposable compiler copies substitute the regular user SID for BA in the
TWO exact private descriptor policies. The production policies and host gate are
unchanged. No approved anchor, installer, claim, product Main or elevation.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_install_request as request
from tests.night_shifts.test_native_validator_guardian_entry import _profile
from tests.night_shifts.test_native_validator_setup import ROOT, powershell, quote

NATIVE = r'''
using System;
using System.Runtime.InteropServices;
using System.Text;
using AiAgent.NativeValidator;
namespace AiAgent.ValidatorSetup {
    public static class OrdinarySetupNativeFixture {
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern IntPtr CreateFileW(string path,uint access,uint share,IntPtr sd,uint disposition,uint flags,IntPtr template);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool GetHandleInformation(IntPtr handle,out uint flags);
        static void Check(bool ok) { if (!ok) throw new Exception("NATIVE_FIXTURE_ASSERTION"); }
        static void Denied(WindowsSetupFiles api,string path,uint access,bool directory) {
            IntPtr h=CreateFileW(path,access,7,IntPtr.Zero,3,directory?0x02000000u:0u,IntPtr.Zero);
            int error=Marshal.GetLastWin32Error();
            if (h!=IntPtr.Zero && h!=new IntPtr(-1)) { api.Close(h); throw new Exception("SHARING_NOT_ENFORCED"); }
            Check(error==32);
        }
        static void Collision(WindowsSetupFiles api,object parent,string leaf,bool directory) {
            bool refused=false;
            try { object unexpected=api.Create(parent,leaf,directory); api.Close(unexpected); }
            catch (SetupRefused e) { Check(e.Message=="create_collision_or_refused"); refused=true; }
            Check(refused);
        }
        public static void Run(string parent) {
            var api=new WindowsSetupFiles(); object root=null,dir=null,file=null,reader=null;
            bool closeUnknown=false;
            try {
                IntPtr h=CreateFileW(parent,0x1200a1,3,IntPtr.Zero,3,0x02200000,IntPtr.Zero);
                Check(h!=IntPtr.Zero && h!=new IntPtr(-1)); root=h;
                // This ordinary parent is deliberately NOT admitted by production
                // acquisition. Only direct native create methods are exercised.
                dir=api.Create(root,"ordinary-fixture",true); Stamp d=api.Observe(dir,true,false);
                Check(d.Links==1); Collision(api,root,"ordinary-fixture",true);
                file=api.Create(dir,"inert.bin",false); Stamp before=api.Observe(file,false,false);
                Check(before.Bytes==0 && before.Links==1);
                byte[] bytes=Encoding.ASCII.GetBytes("INERT NATIVE SETUP FIXTURE\n"); api.Write(file,bytes);
                Stamp after=api.Observe(file,false,false);
                Check(before.Same(after,true,true) && after.Bytes==bytes.Length);
                api.Rewind(file); byte[] got=new byte[bytes.Length]; Check(api.Read(file,got,got.Length)==got.Length);
                SetupPayload.Exact(got,bytes); Check(api.Read(file,new byte[1],1)==0);
                Collision(api,dir,"inert.bin",false);
                object old=file; file=null; api.Close(old); reader=api.Open(dir,"inert.bin",false);
                Stamp sealedInfo=api.Observe(reader,false,false); Check(after.Same(sealedInfo,false,false));
                uint flags; Check(GetHandleInformation((IntPtr)reader,out flags) && flags==0);
                Check(GetHandleInformation((IntPtr)dir,out flags) && flags==0);
                Denied(api,parent+"\\ordinary-fixture\\inert.bin",0x40000000,false);
                Denied(api,parent+"\\ordinary-fixture\\inert.bin",0x10000,false);
                Denied(api,parent+"\\ordinary-fixture",0x10000,true);
                Check(api.Names(dir).Length==1 && api.Names(dir)[0]=="inert.bin");
            } finally {
                foreach (object owned in new object[] {reader,file,dir,root}) {
                    if (owned==null) continue; try { api.Close(owned); } catch { closeUnknown=true; }
                }
                if (closeUnknown) throw new Exception("CLOSE_UNKNOWN_RETAIN_FIXTURE");
            }
            Console.WriteLine("ordinary_native_fixture|PASS");
        }
    }
}
'''


def test_native_relative_creation_explicit_private_descriptors_flush_and_share_locks():
    if os.name != 'nt':
        pytest.skip('requires ordinary Windows/NTFS; not production installation evidence')
    # Obtain test account only in an explicitly UNELEVATED process. These observed
    # values never enter a production profile or approved pin set.
    identity = powershell("$ErrorActionPreference='Stop'; $id=[Security.Principal.WindowsIdentity]::GetCurrent(); "
        "if((New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'UNELEVATED fixture required'}; $id.User.Value")
    assert identity.returncode == 0, identity.stdout + identity.stderr
    sid = identity.stdout.strip()
    assert sid.startswith('S-1-5-21-') and all(c in 'S-0123456789' for c in sid)
    folder = Path(tempfile.mkdtemp(prefix='native-setup-ordinary-'))
    paths = []
    for name in (*build.SOURCE_NAMES, 'native_validator_setup.cs', 'native_validator_setup_windows.cs'):
        path = ROOT / 'scripts' / name
        if name in ('native_validator_install_windows.cs', 'native_validator_setup_windows.cs'):
            source = path.read_text(encoding='utf-8')
            assert source.count('O:BAG:BA') == 1
            if name == 'native_validator_install_windows.cs':
                assert source.count('Admins="S-1-5-32-544"') == 1
                source = source.replace('Admins="S-1-5-32-544"', f'Admins="{sid}"')
            source = source.replace('O:BAG:BA', f'O:{sid}G:{sid}').replace(';;;BA)', f';;;{sid})')
            path = folder / name
            path.write_text(source, encoding='utf-8')
        paths.append(path)
    generated = folder / 'ReviewedGuardianProfile.g.cs'
    generated.write_bytes(request.build_validation_guardian_profile(_profile()))
    paths.append(generated)
    fixture = folder / 'ordinary-native.cs'
    fixture.write_text(NATIVE, encoding='utf-8')
    paths.append(fixture)
    script = ("$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll'); "
        f'[AiAgent.ValidatorSetup.OrdinarySetupNativeFixture]::Run({quote(folder)})')
    result = powershell(script)
    assert result.returncode == 0, result.stdout + result.stderr + '\nFixture retained: ' + str(folder)
    assert result.stdout.strip() == 'ordinary_native_fixture|PASS', result.stdout + result.stderr
    # Only this EXACT random tree after normal return AND checked native closes.
    # Timeout, assertion, unknown close or compiler failure retains it for review.
    shutil.rmtree(folder)
