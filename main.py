from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os, sqlite3, datetime, re, json
from datetime import timedelta

app = FastAPI(title="Tilisi V3 - Calibrated + Till 6899566 + PDF")

# --- SETUP DB (SQLite so data doesn't disappear) ---
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
    cur.execute("""CREATE TABLE IF NOT EXISTS users
        (name TEXT PRIMARY KEY, name_key TEXT, phone TEXT, password TEXT, weight REAL, height REAL, trial_count INTEGER DEFAULT 0, paid_until TEXT, plan TEXT, last_mpesa_code TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS readings
        (id INTEGER PRIMARY KEY AUTOINCREMENT, user_key TEXT, type TEXT, systolic INTEGER, diastolic INTEGER, pulse INTEGER, weight REAL, glucose REAL, miles REAL, steps INTEGER, duration_min INTEGER, advice TEXT, created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS payments
        (id INTEGER PRIMARY KEY AUTOINCREMENT, user_key TEXT, mpesa_code TEXT UNIQUE, amount INTEGER, plan TEXT, created_at TEXT)""")
    conn.commit()
    conn.close()

init_db()

# --- MODELS ---
class UserRegister(BaseModel):
    name: str
    phone: str
    password: str
    weight: float = 70
    height: float = 165

class Login(BaseModel):
    name: str
    password: str

class MpesaVerify(BaseModel):
    name: str
    mpesa_code: str  # e.g QGH7X8Y9Z0
    amount: int = 100
    plan: str = "weekly"  # weekly or monthly

class Reading(BaseModel):
    user_name: str
    type: str  # bp, sugar, weight
    systolic: int = None
    diastolic: int = None
    pulse: int = None
    weight: float = None
    glucose: float = None  # NOW IN mmol/L 1-33

class WalkComplete(BaseModel):
    user_name: str
    miles: float
    steps: int
    duration_min: int

# --- CALIBRATED HELPERS ---
def advice_for_bp(sys, dia, pulse):
    if not sys or not dia:
        return "Please enter systolic, diastolic and pulse.", "Incomplete"
    if sys < 90 or dia < 60:
        return f"LOW BP: {sys} over {dia}, pulse {pulse}. Sit now, hydrate water + ORS, eat little salted soup. If dizzy or fainting → Clinic NOW.", "LOW"
    if sys < 120 and dia < 80:
        return f"NORMAL: {sys} over {dia}, pulse {pulse} - Beautiful flow! Excellent. Keep 2L water, 15 min walk daily.", "NORMAL"
    if sys < 130 and dia < 80:
        return f"ELEVATED: {sys} over {dia}. Slightly raised. Rest 10 min, breathe 4-2-4, less salt/tea today. Recheck 30 min. If headache/blurry → clinic today.", "ELEVATED"
    if sys < 140 or dia < 90:
        return f"HIGH Stage 1: {sys} over {dia}. Body asks for ease. No heavy work today, low salt, recheck 2h. If headache → clinic.", "HIGH-1"
    if sys <= 180 and dia <= 120:
        return f"HIGH Stage 2: {sys} over {dia} - Attention needed. SIT NOW & REST. No salt, no exertion. If chest pain, severe headache, blurred vision → HOSPITAL NOW.", "HIGH-2"
    return f"CRISIS: {sys} over {dia} >180/120 - EMERGENCY. Go to hospital immediately!", "CRISIS"

def advice_for_sugar_mmol(glu):
    if glu is None:
        return "Please enter sugar in mmol/L e.g 5.5", "Incomplete"
    # mmol/L scale 1-33
    if glu < 3.0:
        return f"VERY LOW {glu} mmol/L (<54 mg/dL) - DANGER! Take 1 tbsp honey/juice NOW, sit down. DO NOT give insulin - sugar needed! If confused/fainting → Hospital NOW. Recheck 15 min.", "VERY LOW"
    if glu < 3.9:
        return f"LOW {glu} mmol/L (54-69 mg/dL). Take honey/juice, rest, recheck 15 min. If sweating/shaky → seek help.", "LOW"
    if glu <= 5.5:
        return f"NORMAL Fasting {glu} mmol/L (70-99 mg/dL) - Balanced! Perfect. Keep half-veg plate + walk.", "NORMAL"
    if glu <= 6.9:
        return f"SLIGHTLY HIGH {glu} mmol/L (100-125) - Pre-diabetes range. Avoid soda, mandazi, white bread today. Drink water, walk 20 min after meals.", "PRE-HIGH"
    if glu <= 7.7:
        return f"HIGH Fasting {glu} mmol/L (126-139). No sugar/soda today, water only, clinic within 24h if thirsty.", "HIGH"
    if glu <= 11.0:
        return f"HIGH After Meal {glu} mmol/L (140-199). Very high after eating. Avoid all starch/sugar, walk gently 15 min, hydrate.", "HIGH"
    if glu <= 13.8:
        return f"VERY HIGH {glu} mmol/L (200-250). Take your prescribed meds/insulin ONLY if doctor already prescribed. Water only. See clinic TODAY.", "VERY HIGH"
    if glu <= 20.0:
        return f"CRITICAL {glu} mmol/L (250-360). CRITICAL! If you have prescribed insulin, take as doctor instructed. Drink water. If vomiting, fruity breath, confusion, no urine → HOSPITAL NOW.", "CRITICAL"
    return f"EMERGENCY HI >20 mmol/L ({glu} mmol/L = >360 mg/dL). Meter shows HI. Go to HOSPITAL NOW! Do NOT walk, do NOT eat. Emergency!", "EMERGENCY"

def advice_for_weight_bmi(weight, height_cm):
    if not weight or not height_cm:
        return "Enter weight KG and height cm.", "Unknown", 0
    h_m = height_cm/100
    bmi = weight/(h_m*h_m) if h_m>0 else 0
    dist_km = 250/(weight*0.78) if weight>0 else 3
    miles = dist_km*0.621
    if bmi < 18.5:
        msg = f"Underweight: {weight}KG, Height {height_cm}cm, BMI {bmi:.1f} (<18.5). Need more protein: eggs, ndengu, groundnuts, milk. Check for illness if losing weight."
        status="LOW"
    elif bmi < 25:
        msg = f"Normal: {weight}KG, BMI {bmi:.1f} (18.5-24.9). Great! Maintenance walk {miles:.1f} miles burns ~250 cal. 30 min walk + water keeps you strong."
        status="NORMAL"
    elif bmi < 30:
        msg = f"Overweight: {weight}KG, BMI {bmi:.1f} (25-29.9). To support heart, {int(dist_km*12)} min walk of {miles:.1f} miles burns ~250 cal. Let's start 1.5 miles today. I walk with you."
        status="HIGH"
    else:
        msg = f"Obese: {weight}KG, BMI {bmi:.1f} (30+). Asante for checking. Strongly encouraged: start with 1 mile walk daily, small steps = victory. Burns {miles:.1f} miles ~250 cal. Hydrate, less fried food."
        status="VERY HIGH"
    return msg, status, bmi

def nutrition_for_sugar_mmol(glu, day):
    low_plan = {
        "breakfast": "Sweet potato + 1 boiled egg + black tea no sugar (need energy)",
        "lunch": "Githeri + sukuma + avocado + 1 banana",
        "supper": "Fish + brown ugali small + managu + juice if low",
        "avoid": "AVOID skipping meals. Carry honey/juice always"
    }
    balanced = {
        "breakfast": "Millet porridge no sugar + groundnuts + egg",
        "lunch": "Ndengu + brown ugali + kales + tomato",
        "supper": "Chicken stew + traditional veg + clear soup",
        "avoid": "Avoid soda, mandazi, deep fried"
    }
    high_plan = {
        "breakfast": "Oats + unsweetened milk + 1 small green apple",
        "lunch": "Beans + brown rice small + cabbage + lots greens",
        "supper": "Grilled tilapia + matoke small + greens",
        "avoid": "NO soda, mandazi, chapati, white rice, added sugar, fruit juice"
    }
    very_high = {
        "breakfast": "Fermented porridge no sugar + boiled egg only",
        "lunch": "Green grams + 1 chapati brown + sukuma",
        "supper": "Vegetable soup + 1 small brown ugali + fish",
        "avoid": "STRICT: No sugar, no soda, no white flour, no rice. Water 2-3L. Take meds as prescribed"
    }
    if glu is None:
        plan=balanced
    elif glu < 3.9:
        plan=low_plan
    elif glu <= 7.7:
        plan=balanced
    elif glu <= 11.0:
        plan=high_plan
    else:
        plan=very_high
    return {"day":day,"sugar":glu,"plan":plan}

# --- PAYMENT LOGIC ---
def check_access(user_row):
    if not user_row:
        return False, "User not found"
    paid_until_str = user_row["paid_until"]
    trial = user_row["trial_count"] or 0
    if paid_until_str:
        try:
            paid_until = datetime.datetime.fromisoformat(paid_until_str)
            if datetime.datetime.now() < paid_until:
                return True, f"Paid until {paid_until_str}"
        except:
            pass
    if trial < 3:
        return True, f"Free trial {trial+1}/3"
    return False, "Payment required - Till 6899566"

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html","r",encoding="utf-8") as f:
            return f.read()
    return "<h3>Tilisi V3 Live - Go to /docs</h3>"

@app.post("/register")
def register(user: UserRegister):
    key = user.name.strip().lower()
    conn = get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?", (key,))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Name exists, login")
    cur.execute("INSERT INTO users (name,name_key,phone,password,weight,height,trial_count) VALUES (?,?,?,?,?,?,0)",
                (user.name,key,user.phone,user.password,user.weight,user.height))
    conn.commit(); conn.close()
    return {"status":"registered","name":user.name,"message":f"Karibu {user.name}! You have 3 FREE trials. Pay to Till 6899566 Buy Goods when trials end. KES 100/week or 500/month."}

@app.post("/login")
def login(data: Login):
    key = data.name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,))
    row=cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404,"Name not found. Sign Up")
    if row["password"]!=data.password:
        conn.close()
        raise HTTPException(401,"Wrong password")
    ok, msg = check_access(row)
    conn.close()
    if not ok:
        return {"status":"payment_required","message":f"Trials over. Lipa Till 6899566 Buy Goods KES 100 weekly or 500 monthly, then enter M-Pesa code. {msg}"}
    return {"status":"logged_in","user":{"name":row["name"],"weight":row["weight"],"height":row["height"]},"access_msg":msg,"message":f"Welcome back {row['name']}! {msg}. What would you like to assess? BP, Sugar, Weight?"}

@app.post("/mpesa/verify")
def mpesa_verify(data: MpesaVerify):
    key=data.name.strip().lower()
    code=data.mpesa_code.strip().upper()
    # Validate M-Pesa code format: 10 alphanumeric e.g QGH7X8Y9Z0
    if not re.match(r"^[A-Z0-9]{10}$", code):
        raise HTTPException(400,"Invalid M-Pesa code. Enter 10 letters/numbers from M-Pesa SMS, e.g QGH7X8Y9Z0")
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,))
    user=cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(404,"Register first")
    # Check duplicate code
    cur.execute("SELECT * FROM payments WHERE mpesa_code=?",(code,))
    if cur.fetchone():
        conn.close()
        raise HTTPException(400,"This M-Pesa code already used")
    # Check amount matches plan
    if data.plan=="weekly" and data.amount<100:
        conn.close()
        raise HTTPException(400,"Weekly is KES 100")
    if data.plan=="monthly" and data.amount<500:
        conn.close()
        raise HTTPException(400,"Monthly is KES 500")
    # Save payment
    now=datetime.datetime.now()
    if data.plan=="monthly":
        paid_until=now+timedelta(days=30)
    else:
        paid_until=now+timedelta(days=7)
    try:
        cur.execute("INSERT INTO payments (user_key,mpesa_code,amount,plan,created_at) VALUES (?,?,?,?,?)",
                    (key,code,data.amount,data.plan,now.isoformat()))
        cur.execute("UPDATE users SET paid_until=?, plan=?, last_mpesa_code=?, trial_count=3 WHERE name_key=?",
                    (paid_until.isoformat(),data.plan,code,key))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400,"Code already used")
    conn.close()
    return {"status":"paid","plan":data.plan,"paid_until":paid_until.isoformat(),"message":f"Asante {data.name}! Payment {code} verified. {data.plan} active until {paid_until.date()}. Till 6899566 confirmed."}

@app.get("/mpesa/instructions")
def mpesa_instructions():
    return {
        "till": "6899566",
        "type": "Buy Goods",
        "weekly": 100,
        "monthly": 500,
        "steps": ["Go to M-Pesa -> Lipa na M-Pesa -> Buy Goods -> Till 6899566","Enter 100 for weekly or 500 monthly","Enter M-Pesa PIN","Copy M-Pesa code e.g QGH7... and paste in Tilisi to verify"]
    }

@app.post("/reading")
def add_reading(r: Reading):
    key=r.user_name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,))
    user=cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(404,"User not found")
    ok, msg = check_access(user)
    if not ok:
        conn.close()
        raise HTTPException(403,f"Trials finished. Lipa Till 6899566 then verify code. {msg}")
    # If still in free trial, increment
    if not user["paid_until"] or datetime.datetime.fromisoformat(user["paid_until"]) < datetime.datetime.now():
        if (user["trial_count"] or 0) <3:
            cur.execute("UPDATE users SET trial_count=trial_count+1 WHERE name_key=?",(key,))
    # Generate advice
    advice_text=""; status_label=""
    if r.type=="bp":
        advice_text,status_label = advice_for_bp(r.systolic,r.diastolic,r.pulse)
    elif r.type=="sugar":
        advice_text,status_label = advice_for_sugar_mmol(r.glucose)
    elif r.type=="weight":
        h = user["height"] or 165
        w = r.weight or user["weight"]
        advice_text,status_label,bmi = advice_for_weight_bmi(w,h)
        # Update user weight
        cur.execute("UPDATE users SET weight=? WHERE name_key=?",(w,key))
    else:
        advice_text="Choose BP, Sugar, Weight"
    
    cur.execute("INSERT INTO readings (user_key,type,systolic,diastolic,pulse,weight,glucose,advice,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (key,r.type,r.systolic,r.diastolic,r.pulse,r.weight,r.glucose,advice_text,datetime.datetime.now().isoformat()))
    conn.commit(); conn.close()
    return {"saved":True,"advice":advice_text,"status":status_label,"access":msg}

@app.get("/nutrition/{name}/{day}")
def get_nutrition(name: str, day: str):
    key=name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT glucose FROM readings WHERE user_key=? AND glucose IS NOT NULL ORDER BY id DESC LIMIT 1",(key,))
    row=cur.fetchone()
    glu = row["glucose"] if row else 5.5
    conn.close()
    return nutrition_for_sugar_mmol(glu,day)

@app.post("/walk/complete")
def walk_complete(data: WalkComplete):
    key=data.user_name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT weight FROM users WHERE name_key=?",(key,))
    u=cur.fetchone()
    weight = u["weight"] if u else 70
    # calories: steps*0.04 + weight*miles*1.036 approx
    cal_steps = data.steps*0.04
    cal_dist = weight*data.miles*1.036*0.6
    calories = int((cal_steps+cal_dist))
    if calories<8:
        calories=int(data.miles*90) if data.miles>0 else 10
    praise = f"HONGERA SANA {data.user_name}! {data.miles} miles, {data.steps} steps in {data.duration_min} min! Burned {calories} cal! Rest & drink water."
    cur.execute("INSERT INTO readings (user_key,type,miles,steps,duration_min,advice,created_at) VALUES (?,?,?,?,?,?,?)",
                (key,"walk",data.miles,data.steps,data.duration_min,praise,datetime.datetime.now().isoformat()))
    conn.commit(); conn.close()
    return {"celebration":praise,"calories":calories,"miles":data.miles,"steps":data.steps}

@app.get("/progress/{name}")
def progress(name: str):
    key=name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM readings WHERE user_key=? ORDER BY id DESC LIMIT 50",(key,))
    rows=[dict(r) for r in cur.fetchall()]
    conn.close()
    return {"name":name,"readings":rows}

# --- PDF REPORTS ---
@app.get("/report/pdf/{name}/{period}")
def report_pdf(name: str, period: str):
    # period: daily, weekly, monthly
    key=name.strip().lower()
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM users WHERE name_key=?",(key,))
    user=cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(404,"User not found")
    now=datetime.datetime.now()
    if period=="daily":
        since=now-timedelta(days=1)
    elif period=="weekly":
        since=now-timedelta(days=7)
    else:
        since=now-timedelta(days=30)
    cur.execute("SELECT * FROM readings WHERE user_key=? AND created_at>=? ORDER BY created_at ASC",(key,since.isoformat()))
    readings=[dict(r) for r in cur.fetchall()]
    conn.close()
    # Generate PDF with reportlab if available else simple text file
    pdf_path=f"static/Tilisi_Report_{name}_{period}_{now.date()}.pdf"
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        c=canvas.Canvas(pdf_path,pagesize=A4)
        c.setFont("Helvetica-Bold",16)
        c.drawString(20*mm,280*mm,f"Tilisi Wellness Report - {name}")
        c.setFont("Helvetica",10)
        c.drawString(20*mm,273*mm,f"Period: {period.upper()} | From {since.date()} to {now.date()} | Till: 6899566 | Generated {now}")
        c.drawString(20*mm,268*mm,f"Weight: {user['weight']}KG Height: {user['height']}cm Phone: {user['phone']}")
        y=260*mm
        c.setFont("Helvetica-Bold",11)
        c.drawString(20*mm,y,"Date | Type | Values | Advice/Status")
        y-=5*mm
        c.setFont("Helvetica",8)
        for r in readings[-60:]:  # max 60 rows
            if y<20*mm:
                c.showPage()
                y=280*mm
                c.setFont("Helvetica",8)
            typ=r['type']
            vals=""
            if typ=="bp":
                vals=f"{r['systolic']}/{r['diastolic']} P:{r['pulse']}"
            elif typ=="sugar":
                vals=f"{r['glucose']} mmol/L"
            elif typ=="weight":
                vals=f"{r['weight']}KG"
            elif typ=="walk":
                vals=f"{r['miles']}mi {r['steps']}steps"
            advice=(r['advice'] or "")[:110]
            line=f"{r['created_at'][:16]} | {typ} | {vals} | {advice}"
            c.drawString(15*mm,y,line[:150])
            y-=4.5*mm
        if not readings:
            c.drawString(20*mm,y,"No readings in this period.")
        c.setFont("Helvetica-Bold",10)
        y-=8*mm
        c.drawString(20*mm,y,"Calibration: BP <90/60 LOW, 90-119/60-79 NORMAL, 120-139/80-89 HIGH-1, 140-180/90-120 HIGH-2, >180/120 CRISIS")
        y-=5*mm
        c.drawString(20*mm,y,"Sugar mmol/L: <3.0 VERY LOW, 3.0-3.8 LOW, 3.9-5.5 NORMAL, 5.6-6.9 PRE-HIGH, 7.0-11.0 HIGH, 11.1-13.8 VERY HIGH, >13.9 CRITICAL, >20 EMERGENCY")
        y-=5*mm
        c.drawString(20*mm,y,"Weight: BMI <18.5 LOW, 18.5-24.9 NORMAL, 25-29.9 HIGH, 30+ VERY HIGH")
        c.showPage()
        c.save()
    except Exception as e:
        # Fallback: create simple text as PDF placeholder (HTML)
        with open(pdf_path.replace(".pdf",".txt"),"w") as f:
            f.write(f"Tilisi Report {name} {period}\n")
            json.dump(readings,f,indent=2)
        # create minimal pdf via fpdf if reportlab missing
        try:
            from fpdf import FPDF
            pdf=FPDF()
            pdf.add_page()
            pdf.set_font("Arial",size=12)
            pdf.cell(200,10,txt=f"Tilisi Report {name} {period}",ln=True)
            for r in readings:
                pdf.cell(200,6,txt=str(r)[:180],ln=True)
            pdf.output(pdf_path)
        except:
            # If no pdf lib, return txt as pdf
            pdf_path=pdf_path.replace(".pdf",".txt")
    if not os.path.exists(pdf_path):
        pdf_path=pdf_path.replace(".pdf",".txt")
    return FileResponse(pdf_path,filename=os.path.basename(pdf_path),media_type="application/pdf" if pdf_path.endswith("pdf") else "text/plain")
    @app.get("/manifest.json")
def get_manifest():
    return FileResponse("manifest.json")

@app.get("/sw.js")
def get_sw():
    return FileResponse("sw.js")

if __name__=="__main__":
    import uvicorn
    port=int(os.environ.get("PORT",10000))
    uvicorn.run(app,host="0.0.0.0",port=port)
