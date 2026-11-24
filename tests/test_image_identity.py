import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('ship',Path(__file__).resolve().parents[1]/'scripts/ship.py')
ship=importlib.util.module_from_spec(spec);spec.loader.exec_module(ship)

class ImageIdentityTests(unittest.TestCase):
    def test_only_the_exported_manifest_for_the_exact_config_is_accepted(self):
        config='sha256:'+'a'*64
        body=json.dumps({'config':{'digest':config},'layers':[]}).encode()
        manifest='sha256:'+hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'image.tar.gz'
            with tarfile.open(target,'w:gz') as archive:
                for name,value in [('index.json',json.dumps({'manifests':[{'digest':manifest}]}).encode()),('blobs/sha256/'+manifest[7:],body)]:
                    info=tarfile.TarInfo(name);info.size=len(value);archive.addfile(info,io.BytesIO(value))
            self.assertEqual(ship.exported_image_ids(target,config),{config,manifest})
            other='sha256:'+'b'*64
            self.assertEqual(ship.exported_image_ids(target,other),{other})

if __name__=='__main__':unittest.main()
