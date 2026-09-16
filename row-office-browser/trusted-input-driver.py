#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, sys, time, urllib.request, urllib.error

BASE = 'http://127.0.0.1:9515'
ELEMENT_KEY = 'element-6066-11e4-a52e-4f735466cecf'

def req(method: str, path: str, body=None, timeout=20):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header('content-type', 'application/json;charset=UTF-8')
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        payload = resp.read()
    return json.loads(payload or b'{}')

def wait_http(path='/status', seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        try:
            return req('GET', path)
        except Exception:
            time.sleep(.1)
    raise RuntimeError('chromedriver did not become ready')

def execute(sid, script, args=None):
    return req('POST', f'/session/{sid}/execute/sync', {'script': script, 'args': args or []}).get('value')

def execute_async(sid, script, args=None):
    return req('POST', f'/session/{sid}/execute/async', {'script': script, 'args': args or []}, timeout=30).get('value')

def wait_js(sid, script, expected=True, seconds=20):
    end = time.time() + seconds
    last = None
    while time.time() < end:
        try:
            last = execute(sid, script)
            if last == expected:
                return last
        except Exception:
            pass
        time.sleep(.1)
    raise RuntimeError(f'JS condition timed out: {script}; last={last!r}')

def find(sid, selector):
    value = req('POST', f'/session/{sid}/element', {'using':'css selector','value':selector}).get('value') or {}
    if ELEMENT_KEY not in value:
        raise RuntimeError(f'element not found: {selector}: {value!r}')
    return value

def switch_frame(sid, element):
    req('POST', f'/session/{sid}/frame', {'id': element})

def parent_frame(sid):
    req('POST', f'/session/{sid}/frame/parent', {})

def key_actions(sid, text: str):
    actions=[]
    for ch in text:
        actions.append({'type':'keyDown','value':ch})
        actions.append({'type':'keyUp','value':ch})
    req('POST', f'/session/{sid}/actions', {'actions':[{'type':'key','id':'kbd','actions':actions}]}, timeout=30)
    req('DELETE', f'/session/{sid}/actions', {})

def model_text(sid):
    return execute_async(sid, "var done=arguments[arguments.length-1]; parent.__rowClient.readText().then(x=>done(x.text),e=>done('ERR:'+String(e)));" )

def wait_text(sid, expected, seconds=15):
    end=time.time()+seconds
    last=''
    while time.time()<end:
        last=model_text(sid)
        if last == expected:
            return last
        time.sleep(.1)
    raise RuntimeError(f'model text mismatch after trusted typing; expected={expected!r} last={last!r}')

def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: trusted-input-driver.py <url>')
    url=sys.argv[1]
    chromedriver=os.environ.get('CHROMEDRIVER') or 'chromedriver'
    proc=subprocess.Popen([chromedriver,'--port=9515','--log-level=WARNING'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    sid=None
    try:
        wait_http()
        caps={
            'capabilities':{
                'alwaysMatch':{
                    'browserName':'chrome',
                    'pageLoadStrategy':'normal',
                    'goog:chromeOptions':{'args':['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage']}
                }
            }
        }
        created=req('POST','/session',caps)
        value=created.get('value') or {}
        sid=value.get('sessionId') or created.get('sessionId')
        if not sid:
            raise RuntimeError(f'could not create WebDriver session: {created!r}')
        req('POST',f'/session/{sid}/url',{'url':url})
        wait_js(sid,'return window.__rowTrustedReady===true || !!window.__rowTrustedError;',True,30)
        err=execute(sid,'return window.__rowTrustedError||null;')
        if err:
            raise RuntimeError('trusted page init failed: '+err)

        frame=find(sid,'.row-office-input-frame')
        switch_frame(sid,frame)
        wait_js(sid,"return !!document.getElementById('row-office-ime');",True,10)
        execute(sid,"document.getElementById('row-office-ime').focus(); return document.activeElement.id;")

        # Two waves without re-focusing: this is the failure mode seen in Reborn XP.
        wave1='abcde'
        key_actions(sid,wave1)
        wait_text(sid,wave1)
        wave2='fghijklmnopqrstuvwxyz0123456789abcdefghijklmno'
        key_actions(sid,wave2)
        expected=wave1+wave2
        wait_text(sid,expected)

        # Leave the input idle, then continue typing without touching the element.
        time.sleep(.8)
        wave3='secondwave1234567890'
        key_actions(sid,wave3)
        expected+=wave3
        wait_text(sid,expected)

        # Steal focus in the parent; the watchdog must restore the child editor.
        parent_frame(sid)
        execute(sid,"document.getElementById('focus-sink').focus(); return document.activeElement.id;")
        wait_js(sid,"return document.activeElement===window.__rowView.inputFrame && window.__rowView.inputFrame.contentDocument.activeElement===window.__rowView.ime;",True,5)
        switch_frame(sid,find(sid,'.row-office-input-frame'))
        key_actions(sid,'z')
        expected+='z'
        wait_text(sid,expected)

        # Unicode sent through WebDriver is still a trusted browser text event.
        key_actions(sid,'你好连续输入')
        expected+='你好连续输入'
        wait_text(sid,expected)

        parent_frame(sid)
        stats=execute(sid,'return window.__rowTrustedStats;') or {}
        if int(stats.get('trustedKeydown',0)) < 10:
            raise RuntimeError(f'too few trusted keydown events: {stats!r}')
        if int(stats.get('trustedInput',0)) < 10:
            raise RuntimeError(f'too few trusted input events: {stats!r}')
        print(json.dumps({'status':'pass','textLength':len(expected),'tail':expected[-24:],'stats':stats},ensure_ascii=False))
    finally:
        if sid:
            try:req('DELETE',f'/session/{sid}')
            except Exception:pass
        proc.terminate()
        try:proc.wait(timeout=5)
        except Exception:proc.kill()
        if proc.stdout:
            log=proc.stdout.read()
            if log.strip():
                print(log,file=sys.stderr)

if __name__=='__main__':
    main()
