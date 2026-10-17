"""Local test chat at /chat (only when TEST_CHAT=true): talk to the real bot, real model, real bookings."""
import html

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test chat | __BIZ__</title>
<style>
:root{--bg:#f3f4f1;--panel:#fff;--ink:#1b2420;--muted:#5f6b66;--line:#dde2de;--accent:#1f5c4a;--on:#fff;--me:#d9ebe3;--warn:#9a5b00}
@media (prefers-color-scheme:dark){:root{--bg:#121815;--panel:#1a221e;--ink:#e6ece9;--muted:#9aa8a1;--line:#2c3833;--accent:#6cc3a1;--on:#0d1411;--me:#24453a;--warn:#f3c26b;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:720px;margin:0 auto;padding:20px 16px;display:flex;flex-direction:column;gap:12px}
h1{font-size:20px;margin:0}.muted{color:var(--muted);font-size:13px;margin:0}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
select,input,textarea{font:15px system-ui;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:7px 10px}
#log{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;min-height:360px;max-height:60vh;overflow-y:auto;display:flex;flex-direction:column;gap:8px}
.m{max-width:85%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid var(--line)}
.me{align-self:flex-end;background:var(--me);border-color:transparent}.bot{align-self:flex-start}
.tag{font-size:12px;color:var(--warn)}
form{display:flex;gap:8px}textarea{flex:1;min-width:0;resize:none}
button{border:0;background:var(--accent);color:var(--on);font:600 14px system-ui;padding:0 16px;border-radius:8px;cursor:pointer}
button.ghost{background:none;color:var(--muted);border:1px solid var(--line);padding:7px 12px}
button:disabled{opacity:.5}
</style></head><body><main>
<div><h1>Test chat &middot; __BIZ__</h1><p class="muted">Model: <b>__MODEL__</b>. Real AI and real bookings: confirmation emails really send unless DRY_RUN=true.</p></div>
<div class="bar"><label>Channel <select id="ch"><option value="whatsapp">WhatsApp style</option><option value="email">Email style</option></select></label>
<label>Your phone <input id="phone" value="07700 900000" size="14"></label>
<button class="ghost" id="reset" type="button">New client</button></div>
<div id="log"></div>
<form id="f"><textarea id="box" rows="2" placeholder="Write as a new client..."></textarea><button id="go">Send</button></form>
</main><script>
const $=id=>document.getElementById(id);let sid=Math.random().toString(36).slice(2);
function add(cls,t,tag){const d=document.createElement("div");d.className="m "+cls;d.textContent=t;if(tag){const s=document.createElement("div");s.className="tag";s.textContent=tag;d.append(s)}$("log").append(d);$("log").scrollTop=1e9;return d}
$("reset").onclick=()=>{sid=Math.random().toString(36).slice(2);$("log").replaceChildren()};
$("ch").onchange=$("reset").onclick;
$("box").onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();$("f").requestSubmit()}};
$("f").onsubmit=async e=>{e.preventDefault();const t=$("box").value.trim();if(!t)return;$("box").value="";add("me",t);
const p=add("bot","...");$("go").disabled=true;const t0=performance.now();
try{const r=await fetch("api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session:sid,channel:$("ch").value,phone:$("phone").value,message:t})});
const j=await r.json();p.remove();add("bot",j.reply||j.error,(j.needs_human?"Handed to a person · ":"")+((performance.now()-t0)/1000).toFixed(1)+"s")}
catch(err){p.textContent="Request failed: is the server running?"}finally{$("go").disabled=false;$("box").focus()}};
</script></body></html>"""


def render(business: str, model: str) -> str:
    return PAGE.replace("__BIZ__", html.escape(business)).replace("__MODEL__", html.escape(model))
