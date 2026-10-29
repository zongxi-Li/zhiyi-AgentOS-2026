"""Fetch pinned user-local binaries; does not invoke MSI installation or services.

Memurai payload is read through Windows Installer's read-only database API and
CAB expansion. No product registration, PATH, firewall or service is changed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

PG_URL = 'https://get.enterprisedb.com/postgresql/postgresql-15.19-1-windows-x64-binaries.zip'
PG_SHA256 = 'cc54e2d349f48c7743ad0c509b755ea565ff04bb5c5e71745d114074cab0c453'
PG_BYTES = 330307933
MEMURAI_URL = 'https://dist.memurai.com/releases/Memurai-Developer/4.1.2/Memurai-Developer-v4.1.2.msi'
MEMURAI_SHA256 = '11d009c8e93912e1899b5263d0e7d78907903913e1672b30020612ada6d27446'


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def fetch(url, path, expected, length=None):
    if path.is_file() and digest(path) == expected: return
    if length:
        # Bounded range requests also work with local HTTPS proxies that stall
        # on a single large archive. Every byte is verified after assembly.
        parts = path.with_name(path.name+'.parts')
        parts.mkdir(exist_ok=True)
        size = 4*1024*1024
        def part(index):
            start, end = index*size, min(length-1,(index+1)*size-1)
            target = parts/str(index)
            if target.exists() and target.stat().st_size == end-start+1: return
            for attempt in range(3):
                try:
                    request = urllib.request.Request(url, headers={'Range':f'bytes={start}-{end}'})
                    with urllib.request.urlopen(request, timeout=60) as response: data = response.read()
                    if len(data) != end-start+1: raise RuntimeError('Download range mismatch')
                    target.write_bytes(data)
                    return
                except Exception:
                    if attempt == 2: raise
        count = (length+size-1)//size
        with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(part, range(count)))
        with path.open('wb') as file:
            for index in range(count): file.write((parts/str(index)).read_bytes())
    else:
        with urllib.request.urlopen(url, timeout=60) as response, path.open('wb') as file:
            shutil.copyfileobj(response, file)
    if digest(path) != expected: raise RuntimeError('Dependency SHA256 mismatch: '+path.name)


def extract_msi_readonly(package, destination):
    msi = ctypes.WinDLL('msi')
    msi.MsiOpenDatabaseW.argtypes = [w.LPCWSTR,w.LPCWSTR,ctypes.POINTER(w.UINT)]
    msi.MsiDatabaseOpenViewW.argtypes = [w.UINT,w.LPCWSTR,ctypes.POINTER(w.UINT)]
    msi.MsiRecordGetStringW.argtypes = [w.UINT,w.UINT,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    def check(code):
        if code: raise OSError(code,'Read-only MSI extraction failed')
    def text(record, field):
        size = w.DWORD(4096)
        buffer = ctypes.create_unicode_buffer(size.value)
        check(msi.MsiRecordGetStringW(record,field,buffer,ctypes.byref(size)))
        return buffer.value
    database = w.UINT()
    check(msi.MsiOpenDatabaseW(str(package),None,ctypes.byref(database)))
    def query(sql):
        view = w.UINT()
        check(msi.MsiDatabaseOpenViewW(database,sql,ctypes.byref(view)))
        check(msi.MsiViewExecute(view,0))
        return view
    try:
        view = query("SELECT `Data` FROM `_Streams` WHERE `Name`='cab1.cab'")
        record = w.UINT()
        check(msi.MsiViewFetch(view,ctypes.byref(record)))
        cabinet = destination/'payload.cab'
        with cabinet.open('wb') as file:
            while True:
                buffer = ctypes.create_string_buffer(65536)
                size = w.DWORD(len(buffer))
                check(msi.MsiRecordReadStream(record,1,buffer,ctypes.byref(size)))
                if not size.value: break
                file.write(buffer.raw[:size.value])
        msi.MsiCloseHandle(record)
        msi.MsiCloseHandle(view)
        subprocess.run(['expand.exe',str(cabinet),'-F:*',str(destination)],check=True,stdout=subprocess.DEVNULL)
        view = query('SELECT `File`,`FileName` FROM `File`')
        while True:
            record = w.UINT()
            code = msi.MsiViewFetch(view,ctypes.byref(record))
            if code == 259: break
            check(code)
            key, name = text(record,1), text(record,2).split('|')[-1]
            msi.MsiCloseHandle(record)
            if Path(name).name != name: raise RuntimeError('Invalid MSI filename')
            source = destination/key
            if source.exists() and (name != 'memurai.exe' or key == 'file_memurai.exe'):
                source.replace(destination/name)
        msi.MsiCloseHandle(view)
    finally:
        msi.MsiCloseHandle(database)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'ZhiyiNative/dependencies')
    args = parser.parse_args()
    root = args.destination.absolute()
    root.mkdir(parents=True,exist_ok=True)
    pg, memurai = root/PG_URL.rsplit('/',1)[-1], root/MEMURAI_URL.rsplit('/',1)[-1]
    fetch(PG_URL,pg,PG_SHA256,PG_BYTES)
    fetch(MEMURAI_URL,memurai,MEMURAI_SHA256)
    if not (root/'postgresql-15.19/pgsql/bin/postgres.exe').is_file():
        with zipfile.ZipFile(pg) as archive: archive.extractall(root/'postgresql-15.19')
    output = root/'memurai-4.1.2'
    if not (output/'memurai.exe').is_file():
        output.mkdir(exist_ok=True)
        extract_msi_readonly(memurai,output)
    result = {'status':'PASS','root':str(root),'postgresSha256':digest(pg),'memuraiSha256':digest(memurai),
              'systemInstallationPerformed':False,'servicesInstalled':False,
              'postgresHashOrigin':'Pinned after HTTPS vendor download; not an independent vendor signature',
              'memuraiHashOrigin':'microsoft/winget-pkgs Memurai.MemuraiDeveloper 4.1.2',
              'memuraiLicense':'Developer: development/testing only; 10-day uptime limit'}
    (root/'dependencies.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__': main()
