"""Clone a Lutris launch configuration without changing its source entry."""
import copy
from contextlib import closing
import fcntl
from pathlib import Path
import re
import sqlite3
import uuid
import yaml
from .runtime import LUTRIS,library_path
from .registration import STATE


def create_variant(source_id,name,identity,environment=None,dll_overrides=None,lutris=None,state=STATE):
    if not str(source_id).isascii() or not str(source_id).isdigit():raise ValueError('Select a valid source Lutris entry.')
    if not name.strip() or not re.fullmatch(r'[A-Za-z0-9_.-]+',identity):raise ValueError('Invalid variant name or identity.')
    root=Path(lutris) if lutris else library_path(LUTRIS)
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    with (state/'registration.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        with closing(sqlite3.connect(root/'pga.db',timeout=10)) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
            source=db.execute('SELECT * FROM games WHERE id=?',(int(source_id),)).fetchone()
            if source is None or source['runner']!='wine' or not source['installed']:raise ValueError('Select an installed Wine game in Lutris.')
            configuration=root/'games'/(source['configpath']+'.yml')
            if configuration.is_symlink() or configuration.resolve().parent!=(root/'games').resolve():raise ValueError('Unsafe Lutris configuration path.')
            original=yaml.safe_load(configuration.read_text())
            key=f'{source_id}:{identity}'
            # Only entries created for this exact source and plugin are reused.
            for candidate in db.execute('SELECT id,configpath FROM games WHERE id != ?',(int(source_id),)):
                path=root/'games'/(str(candidate['configpath'])+'.yml')
                if path.is_symlink() or path.resolve().parent!=(root/'games').resolve() or not path.is_file():continue
                saved=yaml.safe_load(path.read_text()) or {}
                if saved.get('playlite_variant')==key:return {'id':candidate['id'],'reused':True}
            config=copy.deepcopy(original)
            config['playlite_variant']=key
            game=config.setdefault('game',{})
            executable=Path(game.get('exe') or source['executable'])
            if not executable.is_absolute():raise ValueError('The source executable must use an absolute path.')
            game['working_dir']=str(executable.parent)
            config.setdefault('system',{}).setdefault('env',{}).update(environment or {})
            config.setdefault('wine',{}).setdefault('overrides',{}).update(dll_overrides or {})
            slug=(re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-') or 'modded')+'-'+uuid.uuid4().hex[:8]
            config_name=slug+'-playlite'
            target=root/'games'/(config_name+'.yml')
            backup=state/('lutris-before-variant-'+uuid.uuid4().hex+'.db')
            with closing(sqlite3.connect(root/'pga.db')) as src,closing(sqlite3.connect(backup)) as dst:src.backup(dst)
            try:
                with target.open('x') as stream:yaml.safe_dump(config,stream)
                values=dict(source);values.pop('id',None)
                values.update(name=name,sortname=name,slug=slug,configpath=config_name)
                columns=list(values)
                query='INSERT INTO games ('+','.join('"'+column+'"' for column in columns)+') VALUES ('+','.join('?' for _ in columns)+')'
                identity=db.execute(query,[values[column] for column in columns]).lastrowid
                db.commit()
            except Exception:
                db.rollback();target.unlink(missing_ok=True);raise
            return {'id':identity,'reused':False}


def launch_configuration(source_id,lutris=None):
    root=Path(lutris) if lutris else library_path(LUTRIS)
    with closing(sqlite3.connect((root/'pga.db').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM games WHERE id=?',(source_id,)).fetchone()
    if row is None or row['runner']!='wine':raise ValueError('Select a Wine game in Lutris.')
    path=root/'games'/(row['configpath']+'.yml')
    if path.is_symlink() or path.resolve().parent!=(root/'games').resolve():raise ValueError('Unsafe Lutris configuration path.')
    return yaml.safe_load(path.read_text())
