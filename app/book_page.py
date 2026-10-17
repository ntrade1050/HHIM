"""The public booking page served at /book (self-contained HTML, no external scripts)."""
import html

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Book a free consultation | __BIZ__</title>
<style>
:root{--bg:#f3f4f1;--panel:#fff;--ink:#1b2420;--muted:#5f6b66;--line:#dde2de;--accent:#1f5c4a;--on:#fff;--err:#a33a2a}
@media (prefers-color-scheme:dark){:root{--bg:#121815;--panel:#1a221e;--ink:#e6ece9;--muted:#9aa8a1;--line:#2c3833;--accent:#6cc3a1;--on:#0d1411;--err:#f09a8a;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:640px;margin:0 auto;padding:24px 16px 40px;display:flex;flex-direction:column;gap:16px}
h1{font-size:24px;margin:0}p{margin:0}.muted{color:var(--muted)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:12px}
.row{display:flex;flex-wrap:wrap;gap:8px}
button.chip{border:1px solid var(--line);background:var(--panel);color:var(--ink);font:500 14px system-ui;padding:8px 12px;border-radius:10px;cursor:pointer;font-variant-numeric:tabular-nums}
button.chip[aria-pressed=true]{background:var(--accent);color:var(--on);border-color:var(--accent)}
label{display:flex;flex-direction:column;gap:4px;font-size:14px;font-weight:600}
input,textarea{font:16px system-ui;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.go{border:0;background:var(--accent);color:var(--on);font:600 16px system-ui;padding:12px;border-radius:10px;cursor:pointer}
.go:disabled{opacity:.5}.err{color:var(--err)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style></head><body><main>
<div><h1>Book a free consultation</h1><p class="muted">__BIZ__ &middot; __MIN__-minute call &middot; UK time</p></div>
<section class="card" id="pick"><p><b>1. Choose a day</b></p><div class="row" id="days"><span class="muted">Loading times&hellip;</span></div>
<p><b>2. Choose a time</b></p><div class="row" id="times"></div></section>
<form class="card" id="form">
<label>Your name<input id="name" required autocomplete="name"></label>
<label>Email (for your confirmation)<input id="email" type="email" required autocomplete="email"></label>
<label>Phone<input id="phone" type="tel" required autocomplete="tel"></label>
<label>What would you like help with? (optional)<textarea id="note" rows="3"></textarea></label>
<p class="err" id="err" hidden></p>
<button class="go" id="go" type="submit" disabled>Choose a time first</button></form>
<section class="card" id="done" hidden><h1>You're booked in</h1><p id="doneText"></p>
<p class="muted">A confirmation with a calendar invite has been emailed to you.</p></section>
</main><script>
let slots=[],day=null,start=null;const $=id=>document.getElementById(id);
function draw(){const days=[...new Set(slots.map(s=>s.day))];if(!day)day=days[0];
$("days").replaceChildren(...days.map(d=>{const b=document.createElement("button");b.type="button";b.className="chip";b.textContent=d;b.setAttribute("aria-pressed",d===day);b.onclick=()=>{day=d;start=null;draw()};return b}));
$("times").replaceChildren(...slots.filter(s=>s.day===day).map(s=>{const b=document.createElement("button");b.type="button";b.className="chip";b.textContent=s.time;b.setAttribute("aria-pressed",s.start===start);b.onclick=()=>{start=s.start;draw()};return b}));
if(!days.length)$("days").textContent="No times are free at the moment. Please email us instead.";
$("go").disabled=!start;$("go").textContent=start?"Book "+day+" at "+slots.find(s=>s.start===start).time:"Choose a time first"}
async function load(){const r=await fetch("api/slots");slots=(await r.json()).slots;if(start&&!slots.some(s=>s.start===start))start=null;draw()}
$("form").onsubmit=async e=>{e.preventDefault();$("err").hidden=true;$("go").disabled=true;
const r=await fetch("api/book",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({start,name:$("name").value,email:$("email").value,phone:$("phone").value,note:$("note").value})});
const j=await r.json();if(r.ok){$("pick").hidden=$("form").hidden=true;$("done").hidden=false;$("doneText").textContent=j.when+" (UK time)."}
else{$("err").textContent=j.error||"Something went wrong. Please try again.";$("err").hidden=false;await load()}};
load();
</script></body></html>"""


def render(business: str, minutes: int) -> str:
    return PAGE.replace("__BIZ__", html.escape(business)).replace("__MIN__", str(int(minutes)))
