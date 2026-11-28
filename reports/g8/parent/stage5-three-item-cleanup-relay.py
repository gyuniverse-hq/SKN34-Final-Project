import os,signal
from pathlib import Path
target=str(Path(__file__).with_name('stage5-three-item-relay.py')).encode()
stopped=0
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():continue
    try:
        args=(entry/'cmdline').read_bytes().split(bytes([0]))
        if target in args:
            os.kill(int(entry.name),signal.SIGTERM);stopped+=1
    except (FileNotFoundError,ProcessLookupError,PermissionError):pass
print('Stopped scoped temporary relay:',stopped)
