#!/usr/bin/env python3
"""Interactive Claude Code using only the Command Code Flash route."""
import os,sys
from runtime import ROOT
from commandcode_claude import environment,MODEL
if __name__=='__main__':
 os.execvpe('claude',['claude','--model',MODEL,*sys.argv[1:]],environment(ROOT,os.environ))
