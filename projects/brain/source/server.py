#!/usr/bin/env python3
"""server.py — Localhost chat UI for "the brain" (Flask + Anthropic + web search)."""
import json
import os
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
MODEL = "claude-opus-4-6"

SYSTEM = """You are "the brain": a sharp, honest research and reasoning engine with live web access.

PURPOSE: Help a researcher examine hypotheses, identify missing evidence and
record conclusions. Do not assume that a forecasting or trading strategy works.
Personal background context was removed for this public source snapshot.

HOW TO REASON: Search for current facts when needed rather than relying on training knowledge. Distinguish what you know vs found vs inferred. If a question's premise is flawed, say so. Be concise, concrete, and calibrated. Be sharp, honest, and useful — he'll respect you for it."""

conversation = []


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/chat", methods=["POST"])
def chat():
    from anthropic import Anthropic
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    use_search = data.get("search", True)
    if not user_msg:
        return jsonify({"error": "empty message"}), 400
    conversation.append({"role": "user", "content": user_msg})
    client = Anthropic()
    kwargs = {
        "model": MODEL, "max_tokens": 2000, "system": SYSTEM,
        "messages": conversation,
    }
    if use_search:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:
        conversation.pop()
        return jsonify({"error": str(e)}), 500
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    n_search = sum(1 for b in resp.content if getattr(b, "type", None) == "server_tool_use")
    conversation.append({"role": "assistant", "content": text})
    return jsonify({"reply": text, "searches": n_search})


@app.route("/reset", methods=["POST"])
def reset():
    conversation.clear()
    return jsonify({"ok": True})


PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>the brain</title>
<style>
  body{font-family:-apple-system,system-ui,sans-serif;max-width:780px;margin:0 auto;
       background:#0e0f13;color:#e6e7ea;display:flex;flex-direction:column;height:100vh}
  header{padding:14px 18px;border-bottom:1px solid #23252b;display:flex;align-items:center;gap:12px}
  header h1{font-size:16px;margin:0;font-weight:600}
  .dot{width:8px;height:8px;border-radius:50%;background:#4ade80}
  #log{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:14px}
  .msg{padding:11px 14px;border-radius:12px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word}
  .user{background:#2563eb;align-self:flex-end;max-width:78%}
  .brain{background:#1a1c22;align-self:flex-start;max-width:88%;border:1px solid #23252b}
  .meta{font-size:11px;color:#7c7f87;margin-top:6px}
  form{display:flex;gap:8px;padding:14px 18px;border-top:1px solid #23252b}
  #q{flex:1;background:#1a1c22;border:1px solid #2c2f37;color:#e6e7ea;border-radius:10px;
     padding:11px 13px;font-size:14px;resize:none;font-family:inherit}
  button{background:#2563eb;color:#fff;border:0;border-radius:10px;padding:0 18px;
         font-size:14px;cursor:pointer;font-weight:500}
  button:disabled{opacity:.5;cursor:default}
  .toggle{display:flex;align-items:center;gap:6px;font-size:12px;color:#9ca0a8;padding:0 18px 10px}
  .thinking{color:#7c7f87;font-style:italic}
</style></head>
<body>
<header><span class="dot"></span><h1>the brain</h1>
  <span style="font-size:12px;color:#7c7f87">opus + live search</span>
  <button onclick="resetChat()" style="margin-left:auto;background:#23252b;padding:6px 12px">reset</button>
</header>
<div id="log"></div>
<label class="toggle"><input type="checkbox" id="search" checked> web search on</label>
<form id="f">
  <textarea id="q" rows="1" placeholder="ask the brain..." autofocus></textarea>
  <button type="submit" id="send">send</button>
</form>
<script>
const log=document.getElementById('log'),q=document.getElementById('q'),
      f=document.getElementById('f'),send=document.getElementById('send'),
      searchBox=document.getElementById('search');
function add(text,cls,meta){const d=document.createElement('div');d.className='msg '+cls;
  d.textContent=text;if(meta){const m=document.createElement('div');m.className='meta';
  m.textContent=meta;d.appendChild(m);}log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
q.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();f.requestSubmit();}});
f.onsubmit=async e=>{e.preventDefault();const msg=q.value.trim();if(!msg)return;
  add(msg,'user');q.value='';send.disabled=true;
  const th=add('thinking...','brain thinking');
  try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message:msg,search:searchBox.checked})});
    const data=await r.json();th.remove();
    if(data.error){add('Error: '+data.error,'brain');}
    else{add(data.reply,'brain',data.searches?(data.searches+' web searches'):'');}}
  catch(err){th.remove();add('Error: '+err,'brain');}
  send.disabled=false;q.focus();};
async function resetChat(){await fetch('/reset',{method:'POST'});log.innerHTML='';}
</script>
</body></html>"""


if __name__ == "__main__":
    print("the brain running at http://localhost:5000")
    app.run(port=5000, debug=False)
