"""
Flask inference server for ConvNeXt-Large-MLP / iNat21.
Scans the working directory for *.safetensors and *.onnx files and exposes
them as selectable backends through the UI.
"""

import io, json, os, time, threading
import numpy as np
import torch
import torch.nn.functional as F
import timm
from safetensors.torch import load_file
from torchvision import transforms
from PIL import Image
from flask import Flask, request, jsonify, render_template_string

# ── Config ────────────────────────────────────────────────────────────────────
BASE        = os.path.dirname(os.path.abspath(__file__))
DEVICE      = "cuda" if torch.cuda.is_available() else "cpu"

with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
    cfg = json.load(f)

ARCH, NUM_CLASSES = cfg["architecture"], cfg["num_classes"]
LABEL_NAMES = cfg["label_names"]
LABEL_MAP   = cfg.get("label_map", {})
pc          = cfg["pretrained_cfg"]
H = W       = pc["input_size"][1]
MEAN, STD   = pc["mean"], pc["std"]
RESIZE_TO   = int(H / pc["crop_pct"])

TRANSFORM = transforms.Compose([
    transforms.Resize(RESIZE_TO, interpolation=transforms.InterpolationMode.BICUBIC),
    transforms.CenterCrop((H, W)),
    transforms.ToTensor(),
    transforms.Normalize(mean=MEAN, std=STD),
])

# ── Dynamic backend discovery ─────────────────────────────────────────────────
_SKIP = {"model_prep", "model_prep-inferred"}   # intermediate files to hide

def _label(fname):
    n = fname.replace(".safetensors", "").replace(".onnx", "")
    mapping = {
        "model":          "PyTorch FP32",
        "model_fp32":     "ONNX FP32",
        "model_fp16":     "ONNX FP16",
        "model_int8":     "ONNX INT8",
    }
    return mapping.get(n, n)

def _type(fname):
    return "pytorch" if fname.endswith(".safetensors") else "onnx"

def discover_backends():
    out = {}
    for fname in sorted(os.listdir(BASE)):
        stem = fname.rsplit(".", 1)[0]
        if stem in _SKIP:
            continue
        if fname.endswith(".safetensors") or fname.endswith(".onnx"):
            key = stem
            out[key] = {
                "key":   key,
                "label": _label(fname),
                "path":  os.path.join(BASE, fname),
                "type":  _type(fname),
            }
    return out

BACKENDS = discover_backends()

# ── Model state ───────────────────────────────────────────────────────────────
_lock         = threading.Lock()
_active_key   = None
_active_model = None
_active_type  = None

def _load(key):
    global _active_key, _active_model, _active_type
    if key == _active_key:
        return
    b = BACKENDS[key]
    print(f"[switch] unloading '{_active_key}', loading '{key}' ...")
    _active_model = None
    if DEVICE == "cuda":
        torch.cuda.empty_cache()
    t0 = time.time()
    if b["type"] == "pytorch":
        m = timm.create_model(ARCH, pretrained=False, num_classes=NUM_CLASSES)
        m.load_state_dict(load_file(b["path"], device=DEVICE), strict=False)
        m.to(DEVICE).eval()
        _active_model = m
        _active_type  = "pytorch"
    else:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = ["CUDAExecutionProvider","CPUExecutionProvider"] \
                    if DEVICE=="cuda" else ["CPUExecutionProvider"]
        _active_model = ort.InferenceSession(b["path"], sess_options=so, providers=providers)
        _active_type  = "onnx"
    _active_key = key
    print(f"[switch] '{key}' ready in {time.time()-t0:.1f}s")

def _infer(img, top_k):
    x = TRANSFORM(img).unsqueeze(0).numpy()
    t0 = time.perf_counter()
    if _active_type == "pytorch":
        with torch.inference_mode():
            probs = F.softmax(_active_model(torch.from_numpy(x).to(DEVICE)), dim=-1)[0].cpu()
        vals, idxs = torch.topk(probs, top_k)
        vals, idxs = vals.tolist(), idxs.tolist()
    else:
        lg = _active_model.run(["logits"], {"image": x})[0][0]
        idxs = np.argsort(lg)[::-1][:top_k].tolist()
        e = np.exp(lg - lg.max()); p = e / e.sum()
        vals = [float(p[i]) for i in idxs]
    ms = (time.perf_counter() - t0) * 1000
    return [{"rank": r+1, "label": LABEL_NAMES[i],
              "common_name": LABEL_MAP.get(LABEL_NAMES[i], ""),
              "class_index": i, "confidence": round(v, 6)}
            for r,(i,v) in enumerate(zip(idxs,vals))], ms

_load(next(iter(BACKENDS)))

# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__)

UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>iNat21 Classifier</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--sur:#161b22;--card:#1c2330;--bdr:#30363d;
      --g:#3fb950;--b:#58a6ff;--txt:#e6edf3;--mut:#8b949e;
      --red:#f85149;--ylw:#d29922;--r:14px}
body{font-family:Inter,sans-serif;background:var(--bg);color:var(--txt);
     min-height:100vh;display:flex;flex-direction:column;align-items:center}

/* header */
header{width:100%;padding:.9rem 2rem;background:var(--sur);
       border-bottom:1px solid var(--bdr);display:flex;align-items:center;gap:.7rem}
header h1{font-size:1rem;font-weight:600}
.pill{margin-left:auto;font-size:.72rem;font-weight:500;padding:.22rem .7rem;
      border-radius:999px;background:rgba(63,185,80,.15);color:var(--g);
      border:1px solid rgba(63,185,80,.3);transition:all .3s}
.pill.busy{background:rgba(210,153,34,.15);color:var(--ylw);
           border-color:rgba(210,153,34,.3);animation:pulse .9s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* main */
main{width:100%;max-width:780px;padding:1.8rem 1.4rem;
     display:flex;flex-direction:column;gap:1.3rem}

/* weights panel */
.wp{background:var(--sur);border:1px solid var(--bdr);border-radius:var(--r);padding:1.1rem}
.wp-hdr{font-size:.78rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
        color:var(--mut);margin-bottom:.85rem;display:flex;align-items:center;gap:.5rem}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(162px,1fr));gap:.6rem}

/* tiles */
.tile{position:relative;border:2px solid var(--bdr);border-radius:10px;
      padding:.8rem .85rem;cursor:pointer;background:var(--card);
      transition:border-color .15s,background .15s;user-select:none}
.tile:hover{border-color:var(--b);background:#1b2840}
.tile.on{border-color:var(--b);background:linear-gradient(135deg,#1a2840,#162035);
         box-shadow:0 0 0 3px rgba(88,166,255,.1)}
.tile.busy2{pointer-events:none;opacity:.65}
.chk{position:absolute;top:.5rem;right:.5rem;width:15px;height:15px;
     border-radius:50%;border:2px solid var(--bdr);background:var(--bg);
     display:flex;align-items:center;justify-content:center;font-size:.58rem;transition:all .2s}
.tile.on .chk{background:var(--b);border-color:var(--b);color:#fff}
.tname{font-size:.81rem;font-weight:600;padding-right:1.1rem;margin-bottom:.28rem}
.tbadges{display:flex;gap:.3rem;flex-wrap:wrap;margin-bottom:.35rem}
.bx{font-size:.6rem;font-weight:600;padding:.08rem .34rem;border-radius:4px;
    text-transform:uppercase;letter-spacing:.04em}
.b-pt{background:rgba(238,76,44,.18);color:#f0784a;border:1px solid rgba(238,76,44,.3)}
.b-ox{background:rgba(88,166,255,.15);color:var(--b);border:1px solid rgba(88,166,255,.3)}
.b-f32{background:rgba(63,185,80,.12);color:var(--g);border:1px solid rgba(63,185,80,.25)}
.b-f16{background:rgba(163,113,247,.15);color:#a371f7;border:1px solid rgba(163,113,247,.3)}
.b-i8{background:rgba(210,153,34,.12);color:var(--ylw);border:1px solid rgba(210,153,34,.25)}
.tsz{font-size:.69rem;color:var(--mut)}
.spin-wrap{display:none;position:absolute;inset:0;align-items:center;
           justify-content:center;border-radius:9px;background:rgba(13,17,23,.5)}
.tile.busy2 .spin-wrap{display:flex}
.spin{width:17px;height:17px;border:2px solid var(--bdr);border-top-color:var(--b);
      border-radius:50%;animation:rot .7s linear infinite}
@keyframes rot{to{transform:rotate(360deg)}}

/* chips */
#chips{display:flex;gap:.45rem;flex-wrap:wrap}
.chip{background:var(--card);border:1px solid var(--bdr);border-radius:8px;
      padding:.3rem .75rem;font-size:.77rem;display:flex;align-items:center;gap:.35rem}
.cl{color:var(--mut)}.cv{font-weight:600;color:var(--b)}

/* upload */
.sec-lbl{font-size:.69rem;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
         color:var(--mut);margin-bottom:.55rem}
.drop{background:var(--card);border:2px dashed var(--bdr);border-radius:var(--r);
      padding:2.4rem 2rem;text-align:center;cursor:pointer;position:relative;
      transition:border-color .2s,background .2s}
.drop:hover,.drop.drag{border-color:var(--b);background:#1b2840}
.drop input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.drop .ico{font-size:2.3rem;margin-bottom:.4rem}
.drop p{color:var(--mut);font-size:.86rem;margin-top:.28rem}
.drop strong{color:var(--b)}
#pw{display:none;background:var(--card);border:1px solid var(--bdr);
    border-radius:var(--r);overflow:hidden}
#pw img{width:100%;max-height:310px;object-fit:contain;background:#000;display:block}
.pbar{padding:.6rem 1.1rem;font-size:.81rem;color:var(--mut);
      display:flex;justify-content:space-between;align-items:center}
#xbtn{background:none;border:1px solid var(--bdr);color:var(--mut);
      padding:.25rem .7rem;border-radius:6px;cursor:pointer;font-size:.77rem;transition:all .15s}
#xbtn:hover{border-color:var(--red);color:var(--red)}

/* controls */
.ctrl{display:flex;gap:.9rem;align-items:center}
.topk-lbl{color:var(--mut);font-size:.84rem;display:flex;align-items:center;gap:.45rem;white-space:nowrap}
.topk-lbl input{accent-color:var(--b);width:86px}
.topk-lbl span{color:var(--txt);font-weight:600;min-width:1.4ch}
#go{flex:1;padding:.78rem 1.4rem;background:linear-gradient(135deg,#238636,#2ea043);
    color:#fff;border:none;border-radius:var(--r);font-size:.97rem;font-weight:600;
    cursor:pointer;transition:opacity .2s,transform .1s}
#go:disabled{opacity:.4;cursor:not-allowed}
#go:not(:disabled):hover{opacity:.85}
#go:not(:disabled):active{transform:scale(.97)}

/* status + results */
#st{font-size:.83rem;color:var(--mut);text-align:center;min-height:1.1em}
#st.err{color:var(--red)}
#res{display:flex;flex-direction:column;gap:.65rem}
.rc{background:var(--card);border:1px solid var(--bdr);border-radius:var(--r);
    padding:.95rem 1.1rem;display:flex;flex-direction:column;gap:.42rem;
    animation:up .2s ease both}
.rc.top{border-color:rgba(88,166,255,.35);background:#1a2840}
@keyframes up{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.rh{display:flex;justify-content:space-between;align-items:baseline;gap:.45rem}
.rk{font-size:.73rem;color:var(--mut);font-weight:500}
.rn{font-style:italic;font-weight:600;font-size:.96rem;flex:1}
.rp{font-weight:700;font-size:.96rem;color:var(--g);white-space:nowrap}
.rc.top .rp{color:var(--b)}
.rcm{font-size:.79rem;color:var(--mut)}
.bar{width:100%;height:4px;background:var(--bdr);border-radius:99px;overflow:hidden}
.bf{height:100%;border-radius:99px;background:var(--g);transition:width .4s}
.rc.top .bf{background:var(--b)}

footer{margin-top:auto;padding:1.4rem;font-size:.73rem;color:var(--mut);text-align:center}
</style>
</head>
<body>
<header>
  <span>🌿</span>
  <h1>iNat21 Species Classifier</h1>
  <span class="pill" id="pill">Ready</span>
</header>
<main>

  <div class="wp">
    <div class="wp-hdr">⚖️&nbsp; Model Weights</div>
    <div id="grid"></div>
  </div>

  <div id="chips">
    <div class="chip"><span class="cl">Active</span><span class="cv" id="ca">—</span></div>
    <div class="chip"><span class="cl">Architecture</span><span class="cv">{{ arch }}</span></div>
    <div class="chip"><span class="cl">Classes</span><span class="cv">{{ num_classes }}</span></div>
    <div class="chip"><span class="cl">Device</span><span class="cv">{{ device }}</span></div>
  </div>

  <div>
    <div class="sec-lbl">Image</div>
    <div class="drop" id="dz">
      <input type="file" id="fi" accept="image/*"/>
      <div class="ico">📷</div>
      <p>Drag &amp; drop an image, or <strong>click to browse</strong></p>
      <p>JPEG &nbsp;·&nbsp; PNG &nbsp;·&nbsp; WEBP</p>
    </div>
    <div id="pw">
      <img id="pi" src="" alt=""/>
      <div class="pbar"><span id="fn"></span><button id="xbtn">✕ Clear</button></div>
    </div>
  </div>

  <div class="ctrl">
    <label class="topk-lbl">Top-K &nbsp;
      <input type="range" id="tk" min="1" max="20" value="5"/>
      <span id="tv">5</span>
    </label>
    <button id="go" disabled>Classify</button>
  </div>

  <p id="st"></p>
  <div id="res"></div>
</main>
<footer><em>{{ arch }}</em> &nbsp;·&nbsp; {{ num_classes }} species &nbsp;·&nbsp; {{ device }}</footer>

<script>
const pill=document.getElementById('pill'),grid=document.getElementById('grid'),
      ca=document.getElementById('ca'),go=document.getElementById('go'),
      st=document.getElementById('st'),res=document.getElementById('res'),
      dz=document.getElementById('dz'),fi=document.getElementById('fi'),
      pw=document.getElementById('pw'),pi=document.getElementById('pi'),
      fn=document.getElementById('fn'),xbtn=document.getElementById('xbtn'),
      tk=document.getElementById('tk'),tv=document.getElementById('tv');

let file=null,active=null,busy=false;

function badges(key,label){
  const rt=label.toLowerCase().includes('pytorch')?
    '<span class="bx b-pt">PyTorch</span>':'<span class="bx b-ox">ONNX</span>';
  const ft=key==='pytorch'||key==='model_fp32'||key==='fp32'?'<span class="bx b-f32">FP32</span>':
           key==='fp16'||key==='model_fp16'?'<span class="bx b-f16">FP16</span>':
           key==='int8'||key==='model_int8'?'<span class="bx b-i8">INT8</span>':'';
  return rt+ft;
}

function buildGrid(backends,act){
  active=act; grid.innerHTML='';
  backends.forEach(b=>{
    const on=b.key===act;
    const t=document.createElement('div');
    t.className='tile'+(on?' on':''); t.id='t-'+b.key; t.dataset.key=b.key;
    t.innerHTML=`<div class="chk">${on?'✓':''}</div>
      <div class="tname">${b.label}</div>
      <div class="tbadges">${badges(b.key,b.label)}</div>
      <div class="tsz">${b.size_mb?b.size_mb+' MB':''}</div>
      <div class="spin-wrap"><div class="spin"></div></div>`;
    t.onclick=()=>switchTo(b.key);
    grid.appendChild(t);
  });
  ca.textContent=backends.find(b=>b.key===act)?.label??act;
  pill.textContent='Ready'; pill.className='pill';
}

async function loadModels(){
  const d=await fetch('/models').then(r=>r.json());
  buildGrid(d.backends,d.active);
}

async function switchTo(key){
  if(key===active||busy) return;
  busy=true;
  const prev=document.getElementById('t-'+active);
  const next=document.getElementById('t-'+key);
  if(prev){prev.classList.remove('on');prev.querySelector('.chk').textContent='';}
  if(next) next.classList.add('busy2');
  pill.textContent='Loading…'; pill.className='pill busy';
  go.disabled=true;
  try{
    const r=await fetch('/switch',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({backend:key})});
    const d=await r.json();
    if(!r.ok) throw new Error(d.error||'failed');
    await loadModels();
    res.innerHTML=''; st.textContent=''; st.className='';
  }catch(e){
    st.className='err'; st.textContent='Switch failed: '+e.message;
    if(next) next.classList.remove('busy2');
    if(prev){prev.classList.add('on');prev.querySelector('.chk').textContent='✓';}
    pill.textContent='Ready'; pill.className='pill';
  }finally{
    busy=false; if(file) go.disabled=false;
  }
}

tk.oninput=()=>tv.textContent=tk.value;
['dragover','dragenter'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.add('drag')}));
['dragleave','drop'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.remove('drag')}));
dz.addEventListener('drop',ev=>{const f=ev.dataTransfer.files[0];if(f)setFile(f);});
fi.onchange=()=>{if(fi.files[0])setFile(fi.files[0]);};
xbtn.onclick=clear;

function setFile(f){
  file=f; pi.src=URL.createObjectURL(f); fn.textContent=f.name;
  pw.style.display='block'; dz.style.display='none';
  go.disabled=busy; res.innerHTML=''; st.textContent=''; st.className='';
}
function clear(){
  file=null; pi.src=''; pw.style.display='none'; dz.style.display='block';
  go.disabled=true; res.innerHTML=''; st.textContent=''; st.className=''; fi.value='';
}

go.onclick=async()=>{
  if(!file) return;
  go.disabled=true; st.className=''; st.textContent='Running inference…'; res.innerHTML='';
  const form=new FormData();
  form.append('image',file); form.append('top_k',tk.value);
  try{
    const t0=performance.now();
    const r=await fetch('/predict',{method:'POST',body:form});
    const d=await r.json();
    if(!r.ok) throw new Error(d.error||'error');
    st.textContent=`Done in ${(performance.now()-t0).toFixed(0)} ms  ·  ${d.backend_label}`;
    d.predictions.forEach((p,i)=>{
      const pct=(p.confidence*100).toFixed(2);
      const c=document.createElement('div');
      c.className='rc'+(i===0?' top':'');
      c.style.animationDelay=i*38+'ms';
      c.innerHTML=`<div class="rh"><span class="rk">#${p.rank}</span>
        <span class="rn">${p.label}</span><span class="rp">${pct}%</span></div>
        ${p.common_name?`<div class="rcm">${p.common_name}</div>`:''}
        <div class="bar"><div class="bf" style="width:${pct}%"></div></div>`;
      res.appendChild(c);
    });
  }catch(e){st.className='err';st.textContent='Error: '+e.message;}
  finally{go.disabled=false;}
};

loadModels();
</script>
</body></html>"""

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return render_template_string(UI, arch=ARCH, num_classes=NUM_CLASSES, device=DEVICE)

@app.get("/models")
def list_models():
    rows = []
    for key, b in BACKENDS.items():
        rows.append({"key": key, "label": b["label"],
                     "size_mb": round(os.path.getsize(b["path"]) / 1e6),
                     "active": key == _active_key})
    return jsonify({"backends": rows, "active": _active_key})

@app.post("/switch")
def switch():
    key = (request.get_json(force=True) or {}).get("backend", "").strip()
    if not key:
        return jsonify({"error": "Missing 'backend'."}), 400
    if key not in BACKENDS:
        return jsonify({"error": f"Unknown backend '{key}'."}), 404
    with _lock:
        try: _load(key)
        except Exception as e: return jsonify({"error": str(e)}), 500
    return jsonify({"active": _active_key, "label": BACKENDS[_active_key]["label"]})

@app.post("/predict")
def predict():
    if "image" not in request.files:
        return jsonify({"error": "No image field."}), 400
    top_k = max(1, min(int(request.form.get("top_k", 5)), NUM_CLASSES))
    try:
        img = Image.open(io.BytesIO(request.files["image"].read())).convert("RGB")
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    with _lock:
        if _active_model is None:
            return jsonify({"error": "No model loaded."}), 503
        try: preds, ms = _infer(img, top_k)
        except Exception as e: return jsonify({"error": str(e)}), 500
    return jsonify({"predictions": preds, "inference_ms": round(ms, 2),
                    "backend": _active_key,
                    "backend_label": BACKENDS[_active_key]["label"],
                    "device": DEVICE})

@app.get("/health")
def health():
    return jsonify({"status": "ok", "active": _active_key,
                    "available": list(BACKENDS.keys()), "device": DEVICE})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
