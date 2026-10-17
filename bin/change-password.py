#!/usr/bin/env python3
"""Interactive owner password change; run in the operator's SSH terminal."""
import getpass
import http.cookiejar
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
from board import BASE

def main():
    os.umask(0o077)
    if not sys.stdin.isatty():
        raise SystemExit('请通过 ssh -t 在交互终端运行。')
    credential = ROOT / 'data/owner-login.json'
    saved = json.loads(credential.read_text())
    password = getpass.getpass('新密码（8–128字符，不回显）: ')
    if not 8 <= len(password) <= 128:
        raise SystemExit('密码长度须为8–128字符；未修改。')
    if password != getpass.getpass('再次输入新密码: '):
        raise SystemExit('两次输入不一致；未修改。')
    jar = http.cookiejar.MozillaCookieJar(str(ROOT / 'data/board-cookies.txt'))
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    def call(path, body):
        request = urllib.request.Request(BASE + '/api/auth/' + path,
            json.dumps(body).encode(), {'Content-Type': 'application/json', 'Origin': BASE}, method='POST')
        with opener.open(request, timeout=30) as response:
            response.read()
    try:
        call('sign-in/email', saved)
    except Exception:
        raise SystemExit('当前保存的凭据登录失败；未修改密码。') from None
    pending = credential.with_name('owner-login.pending.json')
    if pending.exists():
        raise SystemExit('发现先前未完成的密码操作，请先核对 owner-login.pending.json；本次未修改。')
    updated = {**saved, 'password': password}
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(updated, f)
        f.flush()
        os.fsync(f.fileno())
    try:
        call('change-password', {'currentPassword': saved['password'],
            'newPassword': password, 'revokeOtherSessions': True})
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            pending.unlink()
            raise SystemExit(f'服务拒绝修改（HTTP {e.code}），原凭据保留。') from None
        raise SystemExit('服务响应不确定，已保留 owner-login.pending.json 供恢复；请勿重复操作。') from None
    except Exception:
        raise SystemExit('连接中断，修改结果不确定；已保留 owner-login.pending.json 供恢复，请勿重复操作。') from None
    pending.replace(credential)
    credential.chmod(0o600)
    jar.save(ignore_discard=True, ignore_expires=True)
    pathlib.Path(jar.filename).chmod(0o600)
    try:
        call('sign-in/email', updated)
        jar.save(ignore_discard=True, ignore_expires=True)
    except Exception:
        raise SystemExit('密码已更新且本地凭据已同步；自动登录验证失败，请在看板用新密码登录。') from None
    print('密码已修改并验证，新凭据已同步给调度器。请在浏览器重新登录。')

if __name__ == '__main__':
    main()
