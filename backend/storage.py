import json
import sqlite3
import threading
import time
from pathlib import Path
from . import config
from .domain import AlertArgs, NotifyArgs, ReportArgs

def dump(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))
def atomic_json(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)); tmp.replace(path)

class Store:
    def __init__(self, path=None):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path or config.DATA/'crowd.sqlite',check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tools(namespace TEXT,event_id TEXT,name TEXT,args TEXT,result TEXT,state TEXT,attempts INTEGER,updated REAL, PRIMARY KEY(namespace,event_id,name));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT,body TEXT);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT,version INTEGER);
        CREATE TABLE IF NOT EXISTS acknowledgements(event_id TEXT PRIMARY KEY,at REAL);
        CREATE TABLE IF NOT EXISTS tool_attempts(id INTEGER PRIMARY KEY,namespace TEXT,event_id TEXT,name TEXT,state TEXT,detail TEXT,at REAL);
        '''); self.db.commit()
        for row in self.db.execute('SELECT id,body FROM jobs').fetchall():
            job=json.loads(row['body'])
            if job.get('status') in ['running','queued']:
                job.update(status='interrupted',error='服务重启，任务已中断，可重试')
                self.db.execute('UPDATE jobs SET body=? WHERE id=?',(dump(job),row['id']))
        self.db.execute("UPDATE tools SET state='failed' WHERE state='running'");self.db.commit()
    def save_event(self, event):
        with self.lock,self.db: self.db.execute('INSERT INTO events VALUES(?,?,?)',(event['event_id'],dump(event),time.time()))
    def event(self, eid):
        with self.lock: r=self.db.execute('SELECT body FROM events WHERE id=?',(eid,)).fetchone()
        if not r: raise KeyError(eid)
        return json.loads(r[0])
    def events(self):
        with self.lock: rows=self.db.execute('SELECT body FROM events ORDER BY created DESC LIMIT 100').fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_job(self, job, kind):
        with self.lock,self.db: self.db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(job['id'],kind,dump(job)))
    def jobs(self,kind):
        with self.lock: rows=self.db.execute('SELECT body FROM jobs WHERE kind=? ORDER BY rowid DESC LIMIT 100',(kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def tool_rows(self,eid,namespace='production'):
        with self.lock: rows=self.db.execute('SELECT * FROM tools WHERE event_id=? AND namespace=? ORDER BY updated',(eid,namespace)).fetchall()
        return [{**dict(r),'args':json.loads(r['args']),'result':json.loads(r['result']) if r['result'] else None} for r in rows]
    def execute(self,name,args,event_id,namespace='production'):
        schemas={'create_alert':AlertArgs,'notify_operator':NotifyArgs,'save_report':ReportArgs}
        if name not in schemas: raise ValueError('工具不在白名单')
        validated=schemas[name].model_validate(args).model_dump()
        if validated['event_id']!=event_id: raise ValueError('工具 event_id 与冻结事件不一致')
        self.event(event_id)
        if not namespace or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in namespace): raise ValueError('非法命名空间')
        with self.lock:
            row=self.db.execute('SELECT * FROM tools WHERE namespace=? AND event_id=? AND name=?',(namespace,event_id,name)).fetchone()
            if row and row['state']=='completed': return json.loads(row['result'])
            attempts=(row['attempts'] if row else 0)+1
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO tools VALUES(?,?,?,?,?,?,?,?)',(namespace,event_id,name,dump(validated),None,'running',attempts,time.time()))
            try:
                if name=='save_report':
                    target=config.DATA/'reports'/namespace/f'{event_id}.md'
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.with_suffix('.tmp').write_text(validated['report_content'],encoding='utf-8')
                    target.with_suffix('.tmp').replace(target)
                result={'event_id':event_id,'tool':name,'status':'completed'}
                with self.db:
                    self.db.execute('UPDATE tools SET result=?,state=?,updated=? WHERE namespace=? AND event_id=? AND name=?',(dump(result),'completed',time.time(),namespace,event_id,name))
                    self.db.execute('INSERT INTO tool_attempts(namespace,event_id,name,state,detail,at) VALUES(?,?,?,?,?,?)',(namespace,event_id,name,'completed',dump(result),time.time()))
                return result
            except Exception as exc:
                with self.db:
                    self.db.execute('UPDATE tools SET state=?,result=?,updated=? WHERE namespace=? AND event_id=? AND name=?',('failed',dump({'error':str(exc)}),time.time(),namespace,event_id,name))
                    self.db.execute('INSERT INTO tool_attempts(namespace,event_id,name,state,detail,at) VALUES(?,?,?,?,?,?)',(namespace,event_id,name,'failed',str(exc),time.time()))
                raise
