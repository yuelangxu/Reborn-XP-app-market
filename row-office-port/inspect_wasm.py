#!/usr/bin/env python3
from pathlib import Path
import json,sys
class R:
 def __init__(self,b): self.b=b; self.i=0
 def u8(self):
  if self.i>=len(self.b): raise ValueError('truncated')
  x=self.b[self.i]; self.i+=1; return x
 def u32(self):
  x=0; sh=0
  for _ in range(5):
   c=self.u8(); x|=(c&127)<<sh
   if not c&128: return x
   sh+=7
  raise ValueError('bad leb128')
 def take(self,n):
  if self.i+n>len(self.b): raise ValueError('truncated')
  x=self.b[self.i:self.i+n]; self.i+=n; return x
 def name(self): return self.take(self.u32()).decode('utf8','replace')
def limits(r):
 f=r.u32(); mn=r.u32(); mx=r.u32() if f&1 else None
 return {'flags':f,'min':mn,'max':mx,'shared':bool(f&2),'memory64':bool(f&4)}
def inspect(path):
 b=Path(path).read_bytes(); r=R(b)
 if r.take(8)!=b'\0asm\x01\0\0\0': raise ValueError('not wasm v1')
 im=[]; mem=[]
 while r.i<len(b):
  sid=r.u8(); size=r.u32(); s=R(r.take(size))
  if sid==2:
   for _ in range(s.u32()):
    mod,name,kind=s.name(),s.name(),s.u8(); x={'module':mod,'name':name,'kind':kind}
    if kind==0: x['type']=s.u32()
    elif kind==1: x['reftype']=s.u8(); x['limits']=limits(s)
    elif kind==2: x['memory']=limits(s); mem.append({'source':'import',**x['memory']})
    elif kind==3: x['valtype']=s.u8(); x['mutable']=s.u8()
    elif kind==4: x['tag']=s.u8(); x['type']=s.u32()
    im.append(x)
  elif sid==5:
   for i in range(s.u32()): mem.append({'source':'defined','index':i,**limits(s)})
 shared=any(m['shared'] for m in mem)
 return {'file':str(path),'bytes':len(b),'importCount':len(im),'imports':im,'memories':mem,'sharedMemory':shared,'noSharedMemory':not shared}
if __name__=='__main__': print(json.dumps(inspect(sys.argv[1]),indent=2))
