"""Shared runtime location; independent of scheduling backend."""
import os,pathlib
CODE_ROOT=pathlib.Path(__file__).resolve().parent.parent
ROOT=pathlib.Path(os.environ.get('AGENT_RUNTIME_ROOT',str(pathlib.Path(__file__).resolve().parent.parent))).expanduser().resolve()
