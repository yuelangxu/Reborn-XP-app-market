#!/usr/bin/env python3
from pathlib import Path
import json,re,sys
p=Path(sys.argv[1])
text=p.read_text(errors='replace') if p.exists() else ''
patterns={
 'pthread': r'pthread|USE_PTHREADS|SharedArrayBuffer|shared memory',
 'thread': r'std::thread|salhelper::Thread|osl::Thread|pthread_create',
 'link': r'wasm-ld: error|undefined symbol|linker command failed',
 'compile': r'(^|\s)(fatal )?error:',
 'disk': r'No space left on device',
 'memory': r'out of memory|Cannot allocate memory|Killed',
 'configure': r'configure: error|autogen.*error',
}
counts={k:len(re.findall(v,text,re.I|re.M)) for k,v in patterns.items()}
lines=[]
for i,line in enumerate(text.splitlines(),1):
    if any(re.search(pattern,line,re.I) for pattern in patterns.values()):
        lines.append({'line':i,'text':line[:1000]})
        if len(lines)>=120: break
print(json.dumps({'counts':counts,'firstSignals':lines,'lines':len(text.splitlines())},indent=2))
