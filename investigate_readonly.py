"""Bounded read-only evidence collection; never prints raw responses."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import time

os.umask(0o077)
out = Path('PRIVATE_INVESTIGATION')
out.mkdir(mode=0o700, exist_ok=True)
base = ['docker', 'run', '--rm', '--network', 'host', 'fullstorydev/grpcurl:v1.9.3', '-plaintext', '-connect-timeout', '3', '-max-time', '8']
ns = 'SpaceX.API.Device.'

def query(label, endpoint, tail):
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        p = subprocess.run(base + tail, capture_output=True, text=True, timeout=15)
        rec = dict(start=start, end=datetime.datetime.now(datetime.timezone.utc).isoformat(), endpoint=endpoint, tail=tail, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except subprocess.TimeoutExpired:
        rec = dict(start=start, end=datetime.datetime.now(datetime.timezone.utc).isoformat(), endpoint=endpoint, tail=tail, returncode=-1, stdout='', stderr='LOCAL_TIMEOUT')
    (out / (label + '.json')).write_text(json.dumps(rec, indent=2))
    return rec

if __name__ == '__main__':
    start = time.monotonic()
    for i in range(9):
        time.sleep(max(0, start + 15*i - time.monotonic()))
        ep = '192.168.1.1:9000'
        r = query('presence-%02d' % i, ep, ['-d', '{"wifi_get_clients":{}}', ep, ns+'Device/Handle'])
        print('Presence sample %d/9: transport %s' % (i+1, 'OK' if r['returncode']==0 else 'FAILED'), flush=True)
