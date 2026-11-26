from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os, sqlite3, datetime, re, json
from datetime import timedelta

app = FastAPI(title="Tilisi V3 - PWA + Till 6899566")

DB = "tilisi.db"
os.makedirs("static", exist_ok=True)
if os.path.exists("static"):
    try:
        app.mount("/static", StaticFiles(directory="static"), name="static")
    except:
        pass

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, name_key TEXT, phone TEXT, password TEXT, weight REAL, height REAL, trial_count INTEGER DEFAULT 0, paid_until TEXT, plan TEXT, last_mpesa_code TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS readings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_key TEXT, type TEXT, systolic INTEGER, diastolic INTEGER, pulse INTEGER, weight REAL, glucose REAL, miles REAL, steps INTEGER, duration_min INTEGER, advice TEXT, created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_key TEXT, mpesa_code TEXT UNIQUE, amount INTEGER, plan TEXT, created_at TEXT)""")
    conn.commit()
    conn.close()
init_db()

class UserRegister(BaseModel):
    name: str; phone: str; password: str; weight: float = 70; height: float = 165
class Login(BaseModel):
    name: str; password: str
class MpesaVerify(BaseModel):
    name: str; mpesa_code: str; amount: int = 100; plan: str = "weekly"
class Reading(BaseModel):
    user_name: str; type: str; systolic: int = None; diastolic: int = None; pulse: int = None; weight: float = None; glucose: float = None
class WalkComplete(BaseModel):
    user_name: str; miles: float; steps: int; duration_min: int

def advice_for_bp(sys, dia, pulse):
    if not sys or not dia: return "Please enter systolic, diastolic and pulse.", "Incomplete"
    if sys < 90 or dia < 60: return f"LOW BP: {sys} over {dia}, pulse {pulse}. Sit now, hydrate.", "LOW"
    if sys < 120 and dia < 80: return f"NORMAL: {sys} over {dia}, pulse {pulse} - Excellent.", "NORMAL"
    if sys < 130 and dia < 80: return f"ELEVATED: {sys} over {dia}. Rest 10 min.", "ELEVATED"
    if sys < 140 or dia < 90: return f"HIGH Stage 1: {sys} over {dia}.", "HIGH-1"
    if sys <= 180 and dia <= 120: return f"HIGH Stage 2: {sys} over {dia} - SIT NOW.", "HIGH-2"
    return f"CRISIS: {sys} over {dia} >180/120 - EMERGENCY.", "CRISIS"

def advice_for_sugar_mmol(glu):
    if glu is None: return "Please enter sugar mmol/L e.g 5.5", "Incomplete"
    if glu < 3.0: return f"VERY LOW {glu} mmol/L - DANGER! Honey/juice NOW, NO insulin!", "VERY LOW"
    if glu < 3.9: return f"LOW {glu} mmol/L. Honey/juice, recheck 15 min.", "LOW"
    if glu <= 5.5: return f"NORMAL {glu} mmol/L - Balanced!", "NORMAL"
    if glu <= 6.9: return f"SLIGHTLY HIGH {glu} mmol/L - Pre-diabetes.", "PRE-HIGH"
    if glu <= 7.7: return f"HIGH {glu} mmol/L. No sugar/soda.", "HIGH"
    if glu <= 11.0: return f"HIGH After Meal {glu} mmol/L.", "HIGH"
    if glu <= 13.8: return f"VERY HIGH {glu} mmol/L. Clinic TODAY.", "VERY HIGH"
    if glu <= 20.0: return f"CRITICAL {glu} mmol/L. HOSPITAL if vomiting.", "CRITICAL"
    return f"EMERGENCY HI >20 mmol/L ({glu}) - HOSPITAL NOW!", "EMERGENCY"

def advice_for_weight_bmi(weight, height_cm):
    if not weight or not height_cm: return "Enter weight KG and height cm.", "Unknown", 0
    h_m = height_cm/100; bmi = weight/(h_m*h_m) if h_m>0 else 0
    dist_km = 250/(weight*0.78) if weight>0 else 3; miles = dist_km*0.621
    if bmi < 18.5: msg = f"Underweight: {weight}KG, BMI {bmi:.1f}"; status="LOW"
    elif bmi < 25: msg = f"Normal: {weight}KG, BMI {bmi:.1f}. Walk {miles:.1f}mi"; status="NORMAL"
    elif bmi < 30: msg = f"Overweight: {weight}KG, BMI {bmi:.1f}. Walk {miles:.1f}mi"; status="HIGH"
    else: msg = f"Obese: {weight}KG, BMI {bmi:.1f}. Start 1 mile walk"; status="VERY HIGH"
    return msg, status, bmi

def nutrition_for_sugar_mmol(glu, day):
    low = {"breakfast": "Sweet potato + boiled egg", "lunch": "Githeri + sukuma + avocado", "supper": "Fish + brown ugali small", "avoid": "Carry honey/juice"}
    balanced = {"breakfast": "Millet porridge + groundnuts + egg", "lunch": "Ndengu + brown ugali + kales", "supper": "Chicken stew + veg", "avoid": "Avoid soda"}
    high = {"breakfast": "Oats + unsweetened milk", "lunch": "Beans + brown rice + cabbage", "supper": "Tilapia + matoke small", "avoid": "NO soda, mandazi"}
    vhigh = {"breakfast": "Fermented porridge no sugar + egg", "lunch": "Green grams + brown chapati + sukuma", "supper": "Vegetable soup + small ugali + fish", "avoid": "STRICT: No sugar, no soda"}
    if glu is None: plan=balanced
    elif glu < 3.9: plan=low
    elif glu <= 7.7: plan=balanced
    elif glu <= 11.0: plan=high
    else: plan=vhigh
    return {"day":day,"sugar":glu,"plan":plan}

def check_access(user_row):
    if not user_row: return False, "User not found"
    paid_until_str = user_row["paid_until"]; trial = user_row["trial_count"] or 0
    if paid_until_str:
        try:
            paid_until = datetime.datetime.fromisoformat(paid_until_str)
            if datetime.datetime.now() < paid_until:
                return True, f"Paid until {paid_until_str[:10]}"
        except: pass
    if trial < 3: return True, f"Free trial {trial+1}/3"
    return False, "Payment required - Till 6899566"

@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html","r",encoding="utf-8") as f: return f.read()
    return "<h3>Tilisi V3 Live - Go to /docs</h3>"

@app.get("/manifest.json")
def manifest():
    if os.path.exists("manifest.json"):
        return FileResponse("manifest.json", media_type="application/manifest+json")
    return FileResponse("index.html")

@app.get("/sw.js")
def sw():
    if os.path.exists("sw.js"):
        return FileResponse("sw.js", media_type="application/javascript")
    return HTMLResponse("self.addEventListener('fetch', e=>e.respondWith(fetch(e.request)))", media_type="application/javascript")

@app.post("/register")
def register(user: UserRegister):
    key = user.name.strip().lower()
    conn = get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?", (key,))
    if cur.fetchone():
        conn.close(); raise HTTPException(400,"Name exists, login")
    cur.execute("INSERT INTO users (name,name_key,phone,password,weight,height,trial_count) VALUES (?,?,?,?,?,?,0)", (user.name,key,user.phone,user.password,user.weight,user.height))
    conn.commit(); conn.close()
    return {"status":"registered","name":user.name,"message":f"Karibu {user.name}! 3 FREE trials. Till 6899566."}

@app.post("/login")
def login(data: Login):
    key = data.name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,))
    row=cur.fetchone()
    if not row: conn.close(); raise HTTPException(404,"Name not found")
    if row["password"]!=data.password: conn.close(); raise HTTPException(401,"Wrong password")
    ok, msg = check_access(row); conn.close()
    if not ok: return {"status":"payment_required","message":f"Trials over. Lipa Till 6899566 Buy Goods 100 weekly or 500 monthly. {msg}"}
    return {"status":"logged_in","user":{"name":row["name"],"weight":row["weight"],"height":row["height"]},"access_msg":msg,"message":f"Welcome back {row['name']}! {msg}."}

@app.post("/mpesa/verify")
def mpesa_verify(data: MpesaVerify):
    key=data.name.strip().lower(); code=data.mpesa_code.strip().upper()
    if not re.match(r"^[A-Z0-9]{10}$", code): raise HTTPException(400,"Invalid code e.g QGH7X8Y9Z0")
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,)); user=cur.fetchone()
    if not user: conn.close(); raise HTTPException(404,"Register first")
    cur.execute("SELECT * FROM payments WHERE mpesa_code=?",(code,))
    if cur.fetchone(): conn.close(); raise HTTPException(400,"Code already used")
    now=datetime.datetime.now()
    paid_until=now+timedelta(days=30) if data.plan=="monthly" else now+timedelta(days=7)
    try:
        cur.execute("INSERT INTO payments (user_key,mpesa_code,amount,plan,created_at) VALUES (?,?,?,?,?)",(key,code,data.amount,data.plan,now.isoformat()))
        cur.execute("UPDATE users SET paid_until=?, plan=?, last_mpesa_code=?, trial_count=3 WHERE name_key=?",(paid_until.isoformat(),data.plan,code,key))
        conn.commit()
    except: conn.close(); raise HTTPException(400,"Code already used")
    conn.close()
    return {"status":"paid","plan":data.plan,"paid_until":paid_until.isoformat(),"message":f"Asante {data.name}! {code} verified. Till 6899566."}

@app.get("/mpesa/instructions")
def mpesa_instructions(): return {"till":"6899566","type":"Buy Goods","weekly":100,"monthly":500}

@app.post("/reading")
def add_reading(r: Reading):
    key=r.user_name.strip().lower(); conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,)); user=cur.fetchone()
    if not user: conn.close(); raise HTTPException(404,"User not found")
    ok, msg = check_access(user)
    if not ok: conn.close(); raise HTTPException(403,f"Trials finished. Lipa Till 6899566. {msg}")
    if not user["paid_until"] or datetime.datetime.fromisoformat(user["paid_until"]) < datetime.datetime.now():
        if (user["trial_count"] or 0) <3: cur.execute("UPDATE users SET trial_count=trial_count+1 WHERE name_key=?",(key,))
    advice_text=""; status_label=""
    if r.type=="bp": advice_text,status_label = advice_for_bp(r.systolic,r.diastolic,r.pulse)
    elif r.type=="sugar": advice_text,status_label = advice_for_sugar_mmol(r.glucose)
    elif r.type=="weight":
        h = user["height"] or 165; w = r.weight or user["weight"]
        advice_text,status_label,bmi = advice_for_weight_bmi(w,h)
        cur.execute("UPDATE users SET weight=? WHERE name_key=?",(w,key))
    else: advice_text="Choose BP, Sugar, Weight"
    cur.execute("INSERT INTO readings (user_key,type,systolic,diastolic,pulse,weight,glucose,advice,created_at) VALUES (?,?,?,?,?,?,?,?,?)",(key,r.type,r.systolic,r.diastolic,r.pulse,r.weight,r.glucose,advice_text,datetime.datetime.now().isoformat()))
    conn.commit(); conn.close()
    return {"saved":True,"advice":advice_text,"status":status_label,"access":msg}

@app.get("/nutrition/{name}/{day}")
def get_nutrition(name: str, day: str):
    key=name.strip().lower(); conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT glucose FROM readings WHERE user_key=? AND glucose IS NOT NULL ORDER BY id DESC LIMIT 1",(key,)); row=cur.fetchone(); glu = row["glucose"] if row else 5.5; conn.close()
    return nutrition_for_sugar_mmol(glu,day)

@app.post("/walk/complete")
def walk_complete(data: WalkComplete):
    key=data.user_name.strip().lower(); conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT weight FROM users WHERE name_key=?",(key,)); u=cur.fetchone(); weight = u["weight"] if u else 70
    calories = int((data.steps*0.04)+(weight*data.miles*1.036*0.6))
    if calories<8: calories=int(data.miles*90) if data.miles>0 else 10
    praise = f"HONGERA SANA {data.user_name}! {data.miles} miles, {data.steps} steps in {data.duration_min} min! Burned {calories} cal!"
    cur.execute("INSERT INTO readings (user_key,type,miles,steps,duration_min,advice,created_at) VALUES (?,?,?,?,?,?,?)",(key,"walk",data.miles,data.steps,data.duration_min,praise,datetime.datetime.now().isoformat()))
    conn.commit(); conn.close()
    return {"celebration":praise,"calories":calories,"miles":data.miles,"steps":data.steps}

@app.get("/progress/{name}")
def progress(name: str):
    key=name.strip().lower(); conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM readings WHERE user_key=? ORDER BY id DESC LIMIT 50",(key,)); rows=[dict(r) for r in cur.fetchall()]; conn.close()
    return {"name":name,"readings":rows}

@app.get("/report/pdf/{name}/{period}")
def report_pdf(name: str, period: str):
    key=name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,))
    user=cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(404,"User not found")
    now=datetime.datetime.now()
    since=now-timedelta(days=1) if period=="daily" else now-timedelta(days=7) if period=="weekly" else now-timedelta(days=30)
    cur.execute("SELECT * FROM readings WHERE user_key=? AND created_at>=? ORDER BY created_at ASC",(key,since.isoformat()))
    readings=[dict(r) for r in cur.fetchall()]
    conn.close()
    
    os.makedirs("static", exist_ok=True)
    pdf_path=f"static/Tilisi_Report_{name}_{period}_{now.date()}.pdf"
    
    # FORCE REAL PDF - no txt fallback
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    c=canvas.Canvas(pdf_path,pagesize=A4)
    c.setFont("Helvetica-Bold",16)
    c.drawString(20*mm,280*mm,f"Tilisi Wellness Report - {name}")
    c.setFont("Helvetica",10)
    c.drawString(20*mm,273*mm,f"Period: {period.upper()} | {since.date()} to {now.date()} | Till 6899566")
    c.drawString(20*mm,268*mm,f"Weight: {user['weight']}KG Height: {user['height']}cm Phone: {user['phone']}")
    c.drawString(20*mm,263*mm,f"Generated: {now.strftime('%Y-%m-%d %H:%M')}")
    y=250*mm
    c.setFont("Helvetica-Bold",10)
    c.drawString(12*mm,y,"Date Time | Type | Value | Advice")
    y-=6*mm
    c.setFont("Helvetica",8)
    if not readings:
        c.drawString(12*mm,y,"No readings in this period.")
        y-=5*mm
    else:
        for r in readings[-50:]:
            if y<20*mm:
                c.showPage()
                y=280*mm
                c.setFont("Helvetica",8)
            vals=f"{r['systolic']}/{r['diastolic']} P{r['pulse']}" if r['type']=="bp" else f"{r['glucose']} mmol/L" if r['type']=="sugar" else f"{r['weight']}KG" if r['type']=="weight" else f"{r['miles']}mi {r['steps']} steps"
            advice=(r['advice'] or "").replace("\n"," ")[:70]
            line=f"{r['created_at'][:16]} | {r['type']:6} | {vals:15} | {advice}"
            c.drawString(10*mm,y,line[:115])
            y-=4.8*mm
    c.setFont("Helvetica-Bold",7)
    c.drawString(10*mm,12*mm,"Calibrated: BP <90/60 LOW, 90-119/60-79 NORMAL, 120-139/80-89 HIGH-1, 140-180/90-120 HIGH-2, >180 CRISIS | Sugar <3.0 VERY LOW, 3.0-3.8 LOW, 3.9-5.5 NORMAL, 5.6-6.9 PRE-HIGH, 7-11 HIGH, >11 VERY HIGH, >20 EMERGENCY HI")
    c.showPage()
    c.save()
    return FileResponse(pdf_path, filename=os.path.basename(pdf_path), media_type="application/pdf")

if __name__=="__main__":
    import uvicorn
    port=int(os.environ.get("PORT",10000))
    uvicorn.run(app,host="0.0.0.0",port=port)
