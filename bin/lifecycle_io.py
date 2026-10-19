"""Atomic bounded-document persistence, independent of execution modules."""
import json,pathlib,uuid

def save(path,value):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 tmp=path.with_name("."+path.name+"-"+uuid.uuid4().hex+".tmp");tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(path)
