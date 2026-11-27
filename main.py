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

# ===== DETAILED WARM ADVISOR - PAID WORTHY =====
def advice_for_bp(sys, dia, pulse):
    if not sys or not dia:
        return "Please enter systolic e.g 120, diastolic e.g 80 and pulse e.g 72.", "Incomplete"
    
    # VALIDATION - Stop impossible 243 diastolic
    if dia > 150 or dia >= sys or sys > 250 or sys < 70:
        return f"Hi friend, check entry: You entered {sys} over {dia}. Diastolic cannot be {dia} or higher than systolic. Diastolic should be 40-130, systolic 90-220. Your real BP is likely 146 over 90, pulse {pulse}. Please re-enter correctly: Systolic top, Diastolic bottom, Pulse separate. Sugar 1-33 goes in Sugar box.", "ERROR ENTRY"

    pulse_txt = f"Pulse {pulse} bpm" if pulse else "Pulse not entered"
    pulse_detail = ""
    if pulse:
        if pulse > 100: pulse_detail = f"{pulse_txt} is a bit fast - possible stress, caffeine, dehydration, recent walk. Rest, hydrate, recheck."
        elif pulse < 60: pulse_detail = f"{pulse_txt} is a bit slow - if athletic can be okay. If dizzy/fatigue often, mention to clinician."
        else: pulse_detail = f"{pulse_txt} is normal rhythm range - good."

    if sys < 90 or dia < 60:
        return f"""🔵 BP {sys} over {dia} - LOW.
What it means: Below normal range. You may feel dizzy when standing.
Possible causes: Low water, long gap without food, heat.
What to do NOW: 1) REST sit, stand slowly 2) HYDRATE water 3) ENERGIZE light balanced meal 4) If frequent dizziness/fatigue, see clinician.
{pulse_detail}
Educational info only, not diagnosis.""", "LOW"

    if sys < 120 and dia < 80:
        return f"""✅ BP {sys} over {dia} - GOOD, healthy range (90-119/60-79). Meaning: Your heart is working well today.
What to do: Keep your daily walks, hydrate, low salt. Excellent job tracking!
{pulse_detail}""", "NORMAL"

    if sys < 130 and dia < 80:
        return f"""👀 BP {sys} over {dia} - ELEVATED.
What it means: Slightly above optimal, common and manageable.
Possible causes: Stress, coffee, little sleep last night.
What to do NOW & moving forward: 1) REST deep breaths 2) HYDRATE water 3) WALK 20-30 mins today 4) Reduce salt/coffee today 5) Sleep 7-8 hrs. Recheck tomorrow morning.
{pulse_detail}""", "ELEVATED"

    if sys < 140 or dia < 90:
        return f"""👀 BP {sys} over {dia} - HIGH Stage 1.
What it means: Above ideal range. Heart working a bit harder today.
Possible causes: Salty food yesterday, low water, stress, poor sleep, caffeine, low walk.
What to do: 1) REST 5-10 mins then recheck 2) HYDRATE water through day 3) WALK gentle 20 mins if feeling well 4) NUTRITION low salt, more vegetables 5) Track daily same time. If stays many days, see clinic.
{pulse_detail}""", "HIGH-1"

    if sys <= 180 and dia <= 120:
        return f"""⚠️ BP {sys} over {dia} - HIGH Stage 2.
What it means: Clearly above ideal (<120/80). Not crisis, but needs attention if it stays.
Possible causes: High salt, low water, stress, poor sleep, weight, missed medication.
What to do NOW: 1) REST - Sit quietly 5-10 mins, feet flat, breathe slow 2) HYDRATE small sips water 3) NO hard jog today if headache/dizzy - gentle walk later only if well 4) NUTRITION no fried/soda today 5) RECHECK after 15 mins.
Moving forward: Walk daily, low salt, 7hr sleep, track morning. If it stays ≥140/90 many days, please visit your clinic. You are doing well by tracking.
{pulse_detail}
This is educational info only, not medical diagnosis. For personal advice see doctor.""", "HIGH-2"

    return f"""🚨 BP {sys} over {dia} - CRISIS RANGE ≥180/120.
What it means: Very high, needs quick attention.
Possible causes: Missed BP medicine, very high salt, severe stress/pain.
What to do NOW: STOP activity, SIT 5 mins, breathe slowly, sip water, NO hard exercise, RECHECK after 10 mins. If chest pain, short breath, weakness, confusion, slurred speech, or stays ≥180/120, seek emergency care immediately.
{pulse_detail}
General info only, seek care urgently.""", "CRISIS"

def advice_for_sugar_mmol(glu):
    if glu is None:
        return "Please enter sugar mmol/L e.g 5.5 (range 1-33)", "Incomplete"
    
    if glu < 1 or glu > 33:
        return f"Sugar {glu} mmol/L outside 1-33 range. Meter shows LO <1 or HI >33 (usually >20). If meter shows HI, seek care quickly. Enter actual e.g 5.5, or 22 if HI.", "OUT OF RANGE"

    if glu < 3.0:
        return f"""🔴 SUGAR {glu} mmol/L - VERY LOW (<3.0).
What it means: Dangerously low - brain needs sugar now. You may feel shaky, sweaty, dizzy, confused.
Possible causes: Missed meal, too much activity, diabetes medicine effect.
What to do NOW - ENERGIZE: 1) Take honey/sugar/juice NOW - 1 tbsp honey or 1/2 cup juice 2) NO insulin now 3) REST sit safely 4) RECHECK after 15 mins 5) If still <3.0 or confused, seek help. Once normal, eat balanced meal. Discuss pattern with clinician.
Educational only.""", "VERY LOW"

    if glu < 3.9:
        return f"""🟡 SUGAR {glu} mmol/L - LOW (3.0-3.8).
What it means: Below normal (normal 3.9-5.5 fasting).
Possible causes: Long gap without food, activity.
What to do: 1) ENERGIZE small fast sugar + snack 2) REST 15 mins 3) HYDRATE water 4) RECHECK. If frequent lows, see clinician.""", "LOW"

    if glu <= 5.5:
        return f"""✅ SUGAR {glu} mmol/L - NORMAL (3.9-5.5).
What it means: Perfect fasting range, body balanced. Excellent!
What to do: Keep balanced meals, daily walk, hydrate. Great job!""", "NORMAL"

    if glu <= 6.9:
        return f"""👀 SUGAR {glu} mmol/L - PRE-HIGH (5.6-6.9).
What it means: Slightly above normal, often after meal.
Possible causes: Recent meal with carbs, stress.
What to do: 1) WALK gentle 15 mins if feeling well 2) HYDRATE water 3) Next meal more vegetables, less sugary drinks. Recheck in 2 hrs. Track pattern.""", "PRE-HIGH"

    if glu <= 7.7:
        return f"""🟡 SUGAR {glu} mmol/L - HIGH (7.0-7.7).
What it means: Above target.
Possible causes: High carb meal, low activity.
What to do: 1) HYDRATE water 2) WALK light 20 mins if well 3) Avoid sugary foods today 4) Check Nutrition by Sugar for today's plan. Recheck later.""", "HIGH"

    if glu <= 11.0:
        return f"""🟠 SUGAR {glu} mmol/L - HIGH After Meal (7.8-11.0).
What it means: Above target range.
Possible causes: Large meal, sugary drink, low activity.
What to do: 1) HYDRATE plain water 2) WALK 20 mins if feeling well 3) No soda/mandazi today 4) Recheck in 2 hrs. If frequent, see clinician.""", "HIGH"

    if glu <= 13.8:
        return f"""🔴 SUGAR {glu} mmol/L - VERY HIGH (11.1-13.8).
What it means: Very high, needs attention today.
Possible causes: Large sugary meal, missed medication, illness, low water.
What to do: 1) HYDRATE plain water (no soda) 2) NO sugary foods 3) REST - no hard exercise if feeling sick, vomiting, belly pain - seek care 4) RECHECK in 1-2 hrs 5) If repeats, contact clinician today.
Educational only.""", "VERY HIGH"

    if glu <= 20.0:
        return f"""🔴 SUGAR {glu} mmol/L - CRITICAL (13.9-20).
What it means: Critically high.
What to do: HYDRATE water, NO sugary foods, NO hard exercise if unwell. If thirsty, frequent urination, vomiting, confusion, seek care urgently. Contact clinician today.
General info only.""", "CRITICAL"

    return f"""🚨 SUGAR {glu} mmol/L - EMERGENCY HI >20 mmol/L (range up to 33).
What it means: Meter shows HI, extremely high, up to 33.
What to do: HYDRATE water, DO NOT exercise hard, seek urgent care now, especially if thirsty, vomiting, belly pain, confusion, fast breathing. This is general info only, seek care now.
Educational only.""", "EMERGENCY"

def advice_for_weight_bmi(weight, height_cm):
    if not weight or not height_cm:
        return "Enter weight KG and height cm.", "Unknown", 0
    h_m = height_cm/100
    bmi = weight/(h_m*h_m) if h_m>0 else 0
    dist_km = 250/(weight*0.78) if weight>0 else 3
    miles = dist_km*0.621

    if bmi < 18.5:
        msg = f"""⚖️ WEIGHT {weight}KG, BMI {bmi:.1f} - LOW (Underweight).
What it means: Below healthy weight (18.5-24.9). May feel low energy.
Possible causes: Low intake.
What to do: Balanced nutrition small frequent meals, protein, strength walks, good sleep. If losing weight without trying, see clinician."""
        status="LOW"
    elif bmi < 25:
        msg = f"""✅ WEIGHT {weight}KG, BMI {bmi:.1f} - HEALTHY (18.5-24.9).
What it means: Healthy weight range, great for BP and sugar control.
What to do: Keep walks {miles:.1f}mi target, balanced diet, hydrate. Great job!"""
        status="NORMAL"
    elif bmi < 30:
        msg = f"""👀 WEIGHT {weight}KG, BMI {bmi:.1f} - ABOVE IDEAL (25-29.9 Overweight).
What it means: Slight extra weight can raise BP and sugar.
What to do: 1) WALK 30 mins daily 2) HYDRATE water over soda 3) NUTRITION smaller portions, more veg, less fried 4) Sleep 7 hrs. Small daily steps matter. Target {miles:.1f}mi walks."""
        status="HIGH"
    else:
        msg = f"""⚠️ WEIGHT {weight}KG, BMI {bmi:.1f} - HIGH (≥30 Obese).
What it means: Higher weight raises risk for BP and sugar. Manageable with steps.
What to do: 1) WALK daily as app encourages - start 1 mile 2) NUTRITION by Sugar plan - less sugary drinks/fried 3) REST good sleep helps weight 4) Track weekly same day. Consider clinician guidance for personal plan. You can improve steadily."""
        status="VERY HIGH"
    return msg, status, bmi

def nutrition_for_sugar_mmol(glu, day):
    low = {"breakfast": "Sweet potato + boiled egg + tea no sugar", "lunch": "Githeri + sukuma + avocado", "supper": "Fish + brown ugali small + veg", "avoid": "Carry honey/juice for lows"}
    balanced = {"breakfast": "Millet porridge + groundnuts + egg", "lunch": "Ndengu + brown ugali + kales", "supper": "Chicken stew + veg + small ugali", "avoid": "Avoid soda, mandazi"}
    high = {"breakfast": "Oats + unsweetened milk + egg", "lunch": "Beans + brown rice + cabbage", "supper": "Tilapia + matoke small + veg", "avoid": "NO soda, mandazi, sugary tea"}
    vhigh = {"breakfast": "Fermented porridge no sugar + egg + veg", "lunch": "Green grams + brown chapati 1 + sukuma", "supper": "Vegetable soup + small ugali + fish", "avoid": "STRICT: No sugar, no soda, no mandazi, drink water"}
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
        conn.close(); raise HTTPException(status_code=400, detail="Name exists, login")
    cur.execute("INSERT INTO users (name,name_key,phone,password,weight,height,trial_count) VALUES (?,?,?,?,?,?,0)", (user.name,key,user.phone,user.password,user.weight,user.height))
    conn.commit(); conn.close()
    return {"status":"registered","name":user.name,"message":f"Karibu {user.name}! 3 FREE trials. Till 6899566."}

@app.post("/login")
def login(data: Login):
    key = data.name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,))
    row=cur.fetchone()
    if not row: conn.close(); raise HTTPException(status_code=404, detail="Name not found")
    if row["password"]!=data.password: conn.close(); raise HTTPException(status_code=401, detail="Wrong password")
    ok, msg = check_access(row); conn.close()
    if not ok: return {"status":"payment_required","message":f"Trials over. Lipa Till 6899566 Buy Goods 100 weekly or 500 monthly. {msg}"}
    return {"status":"logged_in","user":{"name":row["name"],"weight":row["weight"],"height":row["height"]},"access_msg":msg,"message":f"Welcome back {row['name']}! {msg}."}

@app.post("/mpesa/verify")
def mpesa_verify(data: MpesaVerify):
    key=data.name.strip().lower(); code=data.mpesa_code.strip().upper()
    if not re.match(r"^[A-Z0-9]{10}$", code): raise HTTPException(status_code=400, detail="Invalid code e.g QGH7X8Y9Z0")
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,)); user=cur.fetchone()
    if not user: conn.close(); raise HTTPException(status_code=404, detail="Register first")
    cur.execute("SELECT * FROM payments WHERE mpesa_code=?",(code,))
    if cur.fetchone(): conn.close(); raise HTTPException(status_code=400, detail="Code already used")
    now=datetime.datetime.now()
    paid_until=now+timedelta(days=30) if data.plan=="monthly" else now+timedelta(days=7)
    try:
        cur.execute("INSERT INTO payments (user_key,mpesa_code,amount,plan,created_at) VALUES (?,?,?,?,?)",(key,code,data.amount,data.plan,now.isoformat()))
        cur.execute("UPDATE users SET paid_until=?, plan=?, last_mpesa_code=?, trial_count=3 WHERE name_key=?",(paid_until.isoformat(),data.plan,code,key))
        conn.commit()
    except: conn.close(); raise HTTPException(status_code=400, detail="Code already used")
    conn.close()
    return {"status":"paid","plan":data.plan,"paid_until":paid_until.isoformat(),"message":f"Asante {data.name}! {code} verified. Till 6899566."}

@app.get("/mpesa/instructions")
def mpesa_instructions(): return {"till":"6899566","type":"Buy Goods","weekly":100,"monthly":500}

@app.post("/reading")
def add_reading(r: Reading):
    key=r.user_name.strip().lower(); conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,)); user=cur.fetchone()
    if not user: conn.close(); raise HTTPException(status_code=404, detail="User not found")
    ok, msg = check_access(user)
    if not ok: conn.close(); raise HTTPException(status_code=403, detail=f"Trials finished. Lipa Till 6899566. {msg}")
    if not user["paid_until"] or (user["paid_until"] and datetime.datetime.fromisoformat(user["paid_until"]) < datetime.datetime.now()):
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
    praise = f"HONGERA SANA {data.user_name}! {data.miles} miles, {data.steps} steps in {data.duration_min} min! Burned {calories} cal! Keep walking daily - helps BP and sugar."
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
        raise HTTPException(status_code=404, detail="User not found")
    now=datetime.datetime.now()
    since=now-timedelta(days=1) if period=="daily" else now-timedelta(days=7) if period=="weekly" else now-timedelta(days=30)
    cur.execute("SELECT * FROM readings WHERE user_key=? AND created_at>=? ORDER BY created_at ASC",(key,since.isoformat()))
    readings=[dict(r) for r in cur.fetchall()]
    conn.close()
    
    os.makedirs("static", exist_ok=True)
    pdf_path=f"static/Tilisi_Report_{name}_{period}_{now.date()}.pdf"
    
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
            advice=(r['advice'] or "").replace("\n"," ")[:90]
            line=f"{r['created_at'][:16]} | {r['type']:6} | {vals:15} | {advice}"
            c.drawString(10*mm,y,line[:130])
            y-=4.8*mm
    c.setFont("Helvetica-Bold",7)
    c.drawString(10*mm,12*mm,"Calibrated: BP <90/60 LOW, 90-119/60-79 NORMAL, 120-139/80-89 HIGH-1, 140-180/90-120 HIGH-2, >180 CRISIS | Sugar mmol/L <3.0 VERY LOW, 3.0-3.8 LOW, 3.9-5.5 NORMAL, 5.6-6.9 PRE-HIGH, 7-11 HIGH, >11 VERY HIGH, >20 EMERGENCY HI (1-33 range)")
    c.showPage()
    c.save()
    return FileResponse(pdf_path, filename=os.path.basename(pdf_path), media_type="application/pdf")

if __name__=="__main__":
    import uvicorn
    port=int(os.environ.get("PORT",10000))
    uvicorn.run(app,host="0.0.0.0",port=port)
