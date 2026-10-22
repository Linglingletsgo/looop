"""Shared test isolation: never read the operator's real data/ directory."""
import pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import product_research

def setUpModule():
 """Point the opt-in lookup at an empty temp root so the pack stays disabled."""
 runtime=tempfile.TemporaryDirectory()
 unittest.addModuleCleanup(runtime.cleanup)
 patcher=patch.object(product_research,'ROOT',pathlib.Path(runtime.name))
 patcher.start()
 unittest.addModuleCleanup(patcher.stop)
