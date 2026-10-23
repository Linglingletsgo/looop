#!/usr/bin/env python3
"""Manage the standalone console owner password without printing secrets."""
import argparse,getpass,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import console_auth

def _stdin_password():
 line=sys.stdin.readline()
 if not line:raise SystemExit('未从标准输入读取到密码；未修改。')
 return line.rstrip('\r\n')

def main(argv=None):
 parser=argparse.ArgumentParser(description='looop console owner password')
 commands=parser.add_subparsers(dest='command',required=True)
 set_password=commands.add_parser('set-password',help='set or replace the owner password')
 set_password.add_argument('--stdin',action='store_true',help='read one password line from stdin (tests)')
 commands.add_parser('status',help='report whether a password is configured')
 args=parser.parse_args(argv)
 auth=console_auth.Auth(console_auth.default_root())
 if args.command=='status':
  print('password set' if auth.password_set() else 'password not set')
  return 0
 password=_stdin_password() if args.stdin else getpass.getpass('新密码（至少 12 个字符，不回显）: ')
 if not args.stdin and password!=getpass.getpass('再次输入新密码: '):
  print('两次输入不一致；未修改。',file=sys.stderr);return 2
 try:auth.set_password(password)
 except ValueError as exc:
  print(str(exc).rstrip('。')+'；未修改。',file=sys.stderr);return 2
 except OSError as exc:
  print(str(exc)+'；密码未修改（现有会话可能已失效）。',file=sys.stderr);return 2
 print('密码已设置；所有控制台会话已失效。')
 return 0

if __name__=='__main__':
 try:raise SystemExit(main())
 except KeyboardInterrupt:raise SystemExit(130)
