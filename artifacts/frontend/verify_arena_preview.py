"""作用：在原隔离SQLite预览库上启动竞技新版；只补缺失SQLite字段和冻结版本，保留账号/成长/棋盘。
该脚本不读取业务MySQL配置，不执行生产Flyway。--port默认8006。
"""
import argparse
from pathlib import Path
import sqlite3
import sys
import threading
import time
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root));sys.path.insert(0,str(root/'artifacts/frontend'))
from verify_sudoku import environment
import verify_ranking as qa
from backend.app.services.pk_runtime import runtime
from backend.app.services.pk_service import maintenance

def main():
    """固定工作区内的预览库；按现有模型补表，已有字段不覆盖。"""
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8006);args=parser.parse_args()
    database=(root/'artifacts/frontend/sudoku-preview.sqlite3').resolve()
    assert database.is_relative_to((root/'artifacts/frontend').resolve())
    if database.exists():
        with sqlite3.connect(database) as connection:
            for table,column,definition in [('pk_rooms','host_id','INTEGER'),('pk_rooms','source',"VARCHAR(16) NOT NULL DEFAULT 'friend'"),('pk_participants','board','JSON')]:
                columns=[row[1] for row in connection.execute(f'PRAGMA table_info({table})')]
                if columns and column not in columns:connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    engine,sessions=environment(database)
    settings=qa.get_settings();settings.pk_rooms_enabled=settings.matchmaking_enabled=True
    maintenance(sessions,restart=True)
    stopped=threading.Event()
    def maintain():
        """单个预览调度线程使用同一隔离库，每次仅处理有界活跃集合。"""
        while not stopped.wait(.25):
            try:maintenance(sessions)
            except Exception as error:print('Preview maintenance retry:',type(error).__name__,flush=True)
    thread=threading.Thread(target=maintain,daemon=True);thread.start()
    print(f'Arena preview: http://127.0.0.1:{args.port}/pk.html',flush=True)
    try:qa.uvicorn.run(qa.api.app,host='127.0.0.1',port=args.port,log_level='error',lifespan='off')
    finally:stopped.set();thread.join(3);runtime.reset();engine.dispose()
if __name__=='__main__':main()
