"""Recoverable account deletion. Owned by Bridge's single business executor.

Native ledgers stay in place. This business file is included by copy_business;
an unreadable index fails closed rather than silently reactivating accounts.
"""
from copy import deepcopy
import json
import re
from pathlib import Path
from simulator_core import write_json

GROUPS = {'original', 'top5', 'seven', 'nasdaq', 'hangseng', 'hangtech'}


class AccountTrash:
    def __init__(self, folder):
        self.path = Path(folder) / '账户回收站.json'

    @staticmethod
    def key(group, identity):
        if group not in GROUPS or not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identity):
            raise ValueError('账户参数无效')
        return group + ':' + identity

    def read(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text('utf8'))
            if data['version'] != 1 or not isinstance(data['accounts'], dict):
                raise ValueError('索引格式无效')
            for key, row in data['accounts'].items():
                if (key != self.key(row['group'], row['id']) or not isinstance(row['summary'], dict)
                        or row['summary']['id'] != row['id'] or not isinstance(row['deleted_at'], str)):
                    raise ValueError('索引条目无效')
            return data['accounts']
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise ValueError('已删除账户索引无法读取，已停止账户操作，请先恢复有效备份。') from exc

    def contains(self, group, identity):
        return self.key(group, identity) in self.read()

    def entries(self, group):
        if group not in GROUPS:
            raise ValueError('账户组无效')
        return sorted((deepcopy(r) for r in self.read().values() if r['group'] == group),
                      key=lambda r: r['deleted_at'], reverse=True)

    def delete(self, group, identity, summary, deleted_at):
        key = self.key(group, identity); rows = self.read()
        if key not in rows:
            rows[key] = dict(group=group, id=identity, summary=deepcopy(summary), deleted_at=deleted_at)
            write_json(self.path, dict(version=1, accounts=rows))
        return deepcopy(rows[key])

    def restore(self, group, identity):
        key = self.key(group, identity); rows = self.read()
        if key in rows:
            del rows[key]
            write_json(self.path, dict(version=1, accounts=rows))
