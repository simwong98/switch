"""claude_source 的回归用例：用合成的对话记录重放各种状态。运行：python3 test_claude_source.py"""
import calendar
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'tb')]
import claude_source as cs  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)


def ts(sec):
    return (NOW - dt.timedelta(seconds=600 - sec)).isoformat().replace('+00:00', 'Z')


def user(sec, content, **kw):
    return {'type': 'user', 'sessionId': 'S', 'entrypoint': 'cli', 'cwd': '/w/proj', 'timestamp': ts(sec),
            'message': {'role': 'user', 'content': content}, **kw}


def asst(sec, stop, content):
    return {'type': 'assistant', 'sessionId': 'S', 'entrypoint': 'cli', 'cwd': '/w/proj', 'timestamp': ts(sec),
            'message': {'role': 'assistant', 'stop_reason': stop, 'content': content}}


PROMPT = user(1, '做这件事')
TOOL = asst(2, 'tool_use', [{'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {}}])
RESULT = user(3, [{'type': 'tool_result', 'tool_use_id': 't1'}])
FINAL = asst(4, 'end_turn', [{'type': 'text', 'text': '**做完了**'}])
ASK = asst(5, 'tool_use', [{'type': 'tool_use', 'id': 'q1', 'name': 'AskUserQuestion',
                            'input': {'questions': [{'question': '选哪个'}]}}])
ANSWER = user(6, [{'type': 'tool_result', 'tool_use_id': 'q1'}])
PROMPT2 = user(7, '再写一段')
INTERRUPT = user(8, [{'type': 'text', 'text': '[Request interrupted by user]'}])


def command(name, args=''):
    return f'<command-name>/{name}</command-name>\n<command-message>{name}</command-message>\n<command-args>{args}</command-args>'


class Derive(unittest.TestCase):
    def states(self, rows, hook=None, live=None):
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as fh:
            fh.write('\n'.join(json.dumps(r) for r in rows))
        try:
            return cs.derive(fh.name, cs.scan(fh.name), NOW, hook, live)['states']
        finally:
            os.unlink(fh.name)

    def test_transcript_only(self):
        self.assertEqual(self.states([PROMPT]), ['running'])
        self.assertEqual(self.states([PROMPT, TOOL]), ['running'])
        self.assertEqual(self.states([PROMPT, TOOL, RESULT]), ['running'])
        self.assertEqual(self.states([PROMPT, TOOL, RESULT, FINAL]), ['reply'])
        self.assertEqual(self.states([PROMPT, FINAL, ASK]), ['running', 'question'])
        self.assertEqual(self.states([PROMPT, FINAL, ASK, ANSWER]), ['running'])
        self.assertEqual(self.states([PROMPT, FINAL, PROMPT2, INTERRUPT]), ['aborted'])

    def test_injected_blocks_are_dropped_per_block(self):
        reminder = {'type': 'text', 'text': '<system-reminder>\n环境说明\n</system-reminder>'}
        # Desktop 无文件夹会话：第一条消息前插了一个 system-reminder 块，后面才是你写的
        first = user(1, [reminder, {'type': 'text', 'text': '真正的问题'}])
        self.assertEqual(self.states([first]), ['running'])
        self.assertEqual(self.states([first, FINAL]), ['reply'])
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as fh:
            fh.write(json.dumps(first))
        try:
            self.assertEqual(cs.scan(fh.name)['first_user'], '真正的问题')
        finally:
            os.unlink(fh.name)
        # 只有注入内容的消息不算你说的话；工具结果附带提醒时仍算工具结果
        self.assertEqual(self.states([PROMPT, FINAL, user(5, [reminder])]), ['reply'])
        result_with_reminder = user(3, [{'type': 'tool_result', 'tool_use_id': 't1'}, reminder])
        self.assertEqual(self.states([PROMPT, TOOL, result_with_reminder]), ['running'])

    def test_session_started_by_a_slash_command(self):
        def command(sec, name, args=''):
            return user(sec, f'<command-name>/{name}</command-name>\n<command-message>{name}</command-message>\n'
                             f'<command-args>{args}</command-args>')

        def scanned(rows):
            with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as fh:
                fh.write('\n'.join(json.dumps(r) for r in rows))
            try:
                return cs.scan(fh.name)
            finally:
                os.unlink(fh.name)
        # 本地设置命令不算消息，提交给模型的 human 命令立即算作用户输入。
        effort, goal = command(1, 'effort', 'xhigh'), command(2, 'goal', '修复登录')
        goal['turnOrigin'] = 'human'
        expansion = user(2.5, '命令展开后的说明', isMeta=True)
        f = scanned([effort, goal, expansion, TOOL, RESULT, FINAL])
        self.assertEqual((f['first_user'], f['first_user_ts'], f['last_user']), ('/goal 修复登录', ts(2), ts(2)))
        self.assertEqual(self.states([effort, goal, expansion, TOOL]), ['running'])
        self.assertEqual(self.states([effort, goal, expansion, TOOL, RESULT, FINAL]), ['reply'])
        # 只执行了 /login 的会话没有回复，仍然不收
        self.assertEqual(scanned([command(1, 'login')])['first_user'], '')
        # 本地命令后直接打字：以打字的那句为准，命令不会把这一轮的开始时间提前
        f = scanned([effort, PROMPT2, FINAL])
        self.assertEqual((f['first_user'], f['last_user']), ('再写一段', ts(7)))

    def test_hooks(self):
        stop = {'event': 'Stop', 'ts': ts(5)}
        self.assertEqual(self.states([PROMPT, TOOL], hook=stop), [])
        submit = {'event': 'UserPromptSubmit', 'ts': ts(6)}
        self.assertEqual(self.states([PROMPT, FINAL], hook=submit), ['running'])
        # 中断不触发 Stop：最后一条 hook 是被中断那一轮的提交，不能把它当成还在运行
        late_submit = {'event': 'UserPromptSubmit', 'ts': ts(7.5)}
        self.assertEqual(self.states([PROMPT, FINAL, PROMPT2, INTERRUPT], hook=late_submit), ['aborted'])

    def test_human_command_starts_a_turn_after_a_reply(self):
        goal = user(7, command('goal', 'Finish the task'), turnOrigin='human')
        self.assertEqual(self.states([PROMPT, FINAL, goal]), ['running'])

    def test_command_metadata_is_not_a_user_prompt(self):
        wrapped = command('goal', 'Finish the task')
        rows = [
            user(1, command('effort', 'high')),
            user(2, wrapped),
            user(3, wrapped, turnOrigin='agent'),
            user(4, wrapped, turnOrigin='human', isMeta=True),
            user(5, wrapped, turnOrigin='human', isSidechain=True),
            user(6, wrapped.removesuffix('</command-args>'), turnOrigin='human'),
            user(7, wrapped + ' extra text', turnOrigin='human'),
        ]
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as fh:
            fh.write('\n'.join(json.dumps(r) for r in rows))
        try:
            f = cs.scan(fh.name)
            self.assertEqual(f['first_user'], '')
            self.assertIsNone(f['last_user'])
        finally:
            os.unlink(fh.name)

    def test_live_registry_wins(self):
        self.assertEqual(self.states([PROMPT, FINAL], live={'status': 'busy'}), ['running'])
        self.assertEqual(self.states([PROMPT, TOOL], live={'status': 'idle'}), [])
        self.assertEqual(self.states([PROMPT, TOOL], live={'status': 'waiting', 'since': ts(3)}), ['running', 'approval'])
        # 提问框也会让进程报告 waiting，这时只算待回答
        self.assertEqual(self.states([PROMPT, FINAL, ASK], live={'status': 'waiting'}), ['running', 'question'])


class Collect(unittest.TestCase):
    """终端和 Desktop 的会话分开标出；程序调用的、在 Desktop 里归档的不收。"""

    def test_origins(self):
        def session(sid, entry):
            return [dict(r, sessionId=sid, entrypoint=entry) for r in (PROMPT, FINAL)]
        with tempfile.TemporaryDirectory() as root:
            proj, desk, desk3p, reg = (os.path.join(root, x) for x in
                                       ('projects/-w-proj', 'desktop/acct/org', 'desktop-3p/acct/org', 'registry'))
            for d in (proj, desk, desk3p, reg):
                os.makedirs(d)
            for sid, entry in (('C', 'cli'), ('D', 'claude-desktop'), ('A', 'claude-desktop'), ('P', 'sdk-cli'),
                               ('T', 'claude-desktop-3p')):
                with open(os.path.join(proj, sid + '.jsonl'), 'w') as fh:
                    fh.write('\n'.join(json.dumps(r) for r in session(sid, entry)))
            # 接第三方模型网关的 Desktop 把索引放在另一个目录
            for sid, archived, where in (('D', False, desk), ('A', True, desk), ('T', False, desk3p)):
                with open(os.path.join(where, f'local_{sid.lower()}1.json'), 'w') as fh:
                    json.dump({'sessionId': f'local_{sid.lower()}1', 'cliSessionId': sid, 'title': 'Desktop 里的标题',
                               'isArchived': archived, 'lastFocusedAt': 1791880000000}, fh)
            saved = cs.PROJECTS, cs.DESKTOPS, cs.REGISTRY
            cs.PROJECTS, cs.REGISTRY = os.path.join(root, 'projects'), reg
            cs.DESKTOPS = (os.path.join(root, 'desktop'), os.path.join(root, 'desktop-3p'))
            cs._CACHE.clear()
            try:
                tasks = {t['id']: t for t in cs.collect(30, NOW, {})}
            finally:
                cs.PROJECTS, cs.DESKTOPS, cs.REGISTRY = saved
                cs._CACHE.clear()
        self.assertEqual(set(tasks), {'C', 'D', 'T'})
        self.assertEqual((tasks['C']['origin'], tasks['C']['open_url']), ('cli', None))
        d = tasks['D']
        self.assertEqual((d['origin'], d['title'], d['open_url']), ('desktop', 'Desktop 里的标题', 'claude://code/continue?session=local_d1'))
        self.assertTrue(d['focused_at'].startswith('2026-10-13'))
        t = tasks['T']
        self.assertEqual((t['origin'], t['title'], t['open_url']), ('desktop', 'Desktop 里的标题', 'claude://claude.ai/epitaxy/local_t1'))
        self.assertTrue(t['focused_at'].startswith('2026-10-13'))

    def test_human_command_session_is_collected_without_importing_gateway_sessions(self):
        with tempfile.TemporaryDirectory() as root:
            proj = os.path.join(root, 'projects', 'example')
            os.makedirs(proj)
            for sid, entry, args in (
                ('desktop-goal', 'claude-desktop-3p', 'Finish the task\nCheck the result'),
                ('cli-goal', 'cli', ''),
                ('gateway-worker', 'sdk-cli', 'Finish the task'),
            ):
                rows = [
                    user(1, command('effort', 'high')),
                    user(2, command('goal', args), turnOrigin='human',
                         turnPosition={'promptIndex': 1, 'turnIndex': 1}),
                    user(3, 'Expanded command instructions', isMeta=True),
                    TOOL, RESULT,
                ]
                with open(os.path.join(proj, sid + '.jsonl'), 'w') as fh:
                    fh.write('\n'.join(json.dumps(dict(r, sessionId=sid, entrypoint=entry)) for r in rows))
            cs._CACHE.clear()
            try:
                with patch.multiple(cs, PROJECTS=os.path.join(root, 'projects'),
                                    DESKTOPS=(os.path.join(root, 'desktop'),), REGISTRY=os.path.join(root, 'registry')):
                    tasks = {t['id']: t for t in cs.collect(30, NOW, {})}
            finally:
                cs._CACHE.clear()
        self.assertEqual(set(tasks), {'desktop-goal', 'cli-goal'})
        self.assertEqual(tasks['desktop-goal']['title'], '/goal Finish the task\nCheck the result')
        self.assertEqual(tasks['desktop-goal']['origin'], 'desktop')
        self.assertEqual(tasks['cli-goal']['title'], '/goal')
        for task in tasks.values():
            self.assertEqual(task['started'], ts(2))
            self.assertEqual(task['states'], ['running'])

    def test_forked_session_keeps_its_own_identity(self):
        # 分叉出的会话（如 /btw 旁路对话）复制了原会话的记录，记录里的 sessionId 仍是原会话的；
        # 它不能冒充原会话：归档了就不收，没归档就是另一张卡片
        side_reply = dict(asst(9, 'end_turn', [{'type': 'text', 'text': '旁路回答'}]), sessionId='F')
        parent = [dict(r, sessionId='P', entrypoint='claude-desktop-3p') for r in (PROMPT, FINAL)]
        fork = parent + [dict(r, sessionId='F', entrypoint='claude-desktop-3p') for r in (PROMPT2, side_reply)]
        for archived, expected in ((True, {'P'}), (False, {'P', 'F'})):
            with tempfile.TemporaryDirectory() as root:
                proj, desk = os.path.join(root, 'projects', 'w'), os.path.join(root, 'desktop-3p', 'acct', 'org')
                os.makedirs(proj)
                os.makedirs(desk)
                for sid, rows in (('P', parent), ('F', fork)):
                    with open(os.path.join(proj, sid + '.jsonl'), 'w') as fh:
                        fh.write('\n'.join(json.dumps(r) for r in rows))
                with open(os.path.join(desk, 'local_f1.json'), 'w') as fh:
                    json.dump({'sessionId': 'local_f1', 'cliSessionId': 'F', 'forkedFromSessionId': 'local_p1',
                               'isArchived': archived}, fh)
                cs._CACHE.clear()
                try:
                    with patch.multiple(cs, PROJECTS=os.path.join(root, 'projects'), REGISTRY=os.path.join(root, 'r'),
                                        DESKTOPS=(os.path.join(root, 'desktop-3p'),)):
                        tasks = cs.collect(30, NOW, {})
                finally:
                    cs._CACHE.clear()
            self.assertEqual(sorted(t['id'] for t in tasks), sorted(expected), f'archived={archived}')
            by_id = {t['id']: t for t in tasks}
            self.assertEqual(by_id['P']['last_reply'], ts(4), 'The parent card keeps its own latest reply')
            if 'F' in by_id:
                self.assertEqual(by_id['F']['last_reply'], ts(9))

    def test_unarchive_is_not_seen(self):
        # 取消归档时 Desktop 把 lastFocusedAt 和 resumedAt 设成同一个值，那一刻不一定显示过，不算看过
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as fh:
            fh.write('\n'.join(json.dumps(dict(r, entrypoint='claude-desktop')) for r in (PROMPT, FINAL)))
        try:
            f = cs.scan(fh.name)
            seen = cs.derive(fh.name, f, NOW, desk={'sessionId': 'local_x', 'lastFocusedAt': 1791880000000})
            unarchived = cs.derive(fh.name, f, NOW, desk={'sessionId': 'local_x', 'lastFocusedAt': 1791880000000,
                                                          'resumedAt': 1791880000000})
        finally:
            os.unlink(fh.name)
        self.assertIsNotNone(seen['focused_at'])
        self.assertIsNone(unarchived['focused_at'])


class Registry(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX process identity check requires ps; Windows Claude testing is separate')
    def test_reused_pid_is_ignored(self):
        lstart = subprocess.run(['ps', '-o', 'lstart=', '-p', str(os.getpid())], capture_output=True, text=True).stdout.strip()
        utc = time.strftime('%a %b %d %H:%M:%S %Y', time.gmtime(time.mktime(time.strptime(lstart, '%a %b %d %H:%M:%S %Y'))))
        with tempfile.TemporaryDirectory() as d:
            for name, start in (('real', utc), ('reused', 'Mon Jan 01 00:00:00 2024')):
                with open(os.path.join(d, name + '.json'), 'w') as fh:
                    json.dump({'pid': os.getpid(), 'sessionId': name, 'procStart': start, 'status': 'busy',
                               'statusUpdatedAt': calendar.timegm(time.gmtime()) * 1000}, fh)
            old, cs.REGISTRY = cs.REGISTRY, d
            try:
                self.assertEqual(set(cs.live_status()), {'real'})
            finally:
                cs.REGISTRY = old


if __name__ == '__main__':
    unittest.main(verbosity=1)
