from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from gtts import gTTS
import os, time, random

app = FastAPI(title="Tilisi Wellness Coach V2 - Name Based")

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

class MpesaPay(BaseModel):
    name: str
    phone: str  # For STK push
    amount: int = 299

class Reading(BaseModel):
    user_name: str
    type: str  # bp, sugar, weight
    systolic: int = None
    diastolic: int = None
    pulse: int = None
    weight: float = None
    glucose: float = None

class WalkComplete(BaseModel):
    user_name: str
    miles: float
    steps: int
    duration_min: int

# In-memory DB
users_db = {}  # keyed by name lowercased
mpesa_paid = {} # name -> True/False
readings_db = []

os.makedirs("static", exist_ok=True)

# Mount static for audio
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- HELPERS ---
def advice_for_bp(sys, dia, pulse):
    if not sys or not dia:
        return "Please enter systolic, diastolic and pulse."
    if sys < 90 or dia < 60:
        return f"Your BP {sys} over {dia} is low today with pulse {pulse}. Please sit, hydrate with water and ORS, eat a little salted soup. If dizzy or fainting, go to clinic now."
    if sys < 120 and dia < 80:
        return f"Beautiful flow today! {sys} over {dia}, pulse {pulse} is excellent. Keep hydrating 2L water, light walk 15 min."
    if sys < 140 and dia < 90:
        return f"Your BP {sys} over {dia} is slightly raised. Your body asks for ease. Rest 10 minutes, breathe slowly 4-2-4, less salt and tea today. Recheck after 30 min. If headache or blurred vision, go to clinic today."
    else:
        return f"Attention needed: BP {sys} over {dia} is high. Please SIT NOW and REST. Avoid salt and exertion. If chest pain, severe headache, or blurry vision, go to HOSPITAL NOW. I have logged this for your doctor."

def advice_for_sugar(glu):
    if not glu:
        return "Please enter your sugar level."
    if glu < 70:
        return f"Sugar {glu} mg/dL is LOW. Take 1 tablespoon honey or juice quickly, sit down, recheck after 15 min. If sweating or confusion, seek help immediately."
    if glu < 100:
        return f"Balanced! Sugar {glu} is excellent. Keep your half-veg plate and walk after meals."
    if glu < 140:
        return f"Sugar {glu} is slightly high. Avoid sugary drinks, mandazi and white bread today. Drink water and walk 20 minutes after eating. Recheck in 2 hours."
    if glu < 200:
        return f"Sugar {glu} is high. Please avoid all sugar, soda, chapati, rice today. Walk gently 15 min, hydrate. If you feel thirsty often or tired, see clinic within 24 hours."
    else:
        return f"CRITICAL: Sugar {glu} is very high. Drink water ONLY, no food with sugar. DO NOT exert. If vomiting, fruity breath, confusion, or no urine, go to HOSPITAL NOW."

def advice_for_weight(weight):
    if not weight:
        return "Please enter your current weight."
    bmi_proxy = weight # simplified
    dist_km = 250 / (weight * 0.78) if weight>0 else 3
    miles = dist_km * 0.621
    if weight >= 90:
        return f"Asante at {weight} KG. To support your heart, a {int(dist_km*12)} min walk of {miles:.1f} miles burns ~250 cal. Let's start with 1 mile today. I will walk with you and count steps. Small steps daily is victory."
    elif weight >= 80:
        return f"At {weight} KG, a {int(dist_km*12)} min walk of {miles:.1f} miles burns ~250 cal. You are doing well. Let's target 1.5 miles to stay fit. Shall we start?"
    else:
        return f"Great weight {weight} KG! Maintenance walk {miles:.1f} miles burns ~250 cal. 30 min walk + water keeps you strong. Ready?"

def nutrition_for_sugar(glu, day):
    # Base plans
    low_sugar_plan = {
        "breakfast": "Sweet potato + 1 boiled egg + black tea no sugar",
        "lunch": "Githeri (maize+beans) + sukuma + avocado",
        "supper": "Grilled fish + brown ugali small + managu",
        "avoid": "Avoid honey, juice, soda, white bread today"
    }
    high_sugar_plan = {
        "breakfast": "Millet porridge no sugar + groundnuts + 1 egg",
        "lunch": "Ndengu + brown ugali + kales with tomato",
        "supper": "Chicken stew (no skin) + traditional veg + clear soup",
        "avoid": "NO soda, mandazi, chapati, white rice, added sugar, fruit juice"
    }
    balanced_plan = {
        "breakfast": "Oats + milk + 1 banana",
        "lunch": "Beans + brown rice + cabbage",
        "supper": "Tilapia + matoke + greens",
        "avoid": "Avoid fried chips, soda, excess salt"
    }
    if glu is None:
        plan = balanced_plan
    elif glu < 80:
        plan = low_sugar_plan
    elif glu > 140:
        plan = high_sugar_plan
    else:
        plan = balanced_plan
    
    return {
        "day": day,
        "sugar_level": glu,
        "plan": plan,
        "audio": f"For sugar {glu}, today eat: {plan['breakfast']}. Lunch {plan['lunch']}. Supper {plan['supper']}. {plan['avoid']}"
    }

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Tilisi Live - Go to /docs</h3>"

@app.get("/welcome")
def welcome():
    return {"message": "Welcome to Tilisi. Sign up with your name, pay via M-Pesa, then choose: Check BP, Sugar, or Weight. I walk with you."}

@app.post("/register")
def register(user: UserRegister):
    key = user.name.strip().lower()
    if key in users_db:
        raise HTTPException(status_code=400, detail="Name already exists. Please login.")
    users_db[key] = user.model_dump()
    mpesa_paid[key] = False
    return {"status": "registered", "name": user.name, "next": "pay_mpesa", "message": f"Karibu {user.name}! Please pay KES 299 via M-Pesa to activate your wellness journey."}

@app.post("/mpesa/pay")
def mpesa_pay(p: MpesaPay):
    key = p.name.strip().lower()
    if key not in users_db:
        raise HTTPException(status_code=404, detail="Register first with your name")
    # MOCK STK Push - In real Daraja you call safaricom API here
    # For now auto-approve after 2 sec simulation
    mpesa_paid[key] = True
    return {"status": "stk_sent", "to": p.phone, "amount": p.amount, "message": f"STK Push sent to {p.phone}. Enter M-Pesa PIN to pay KES {p.amount}. (Demo auto-approved)", "paid": True}

@app.get("/mpesa/status/{name}")
def mpesa_status(name: str):
    key = name.strip().lower()
    return {"paid": mpesa_paid.get(key, False)}

@app.post("/login")
def login(data: Login):
    key = data.name.strip().lower()
    if key not in users_db:
        raise HTTPException(status_code=404, detail="Name not found. Please Sign Up.")
    if users_db[key]["password"] != data.password:
        raise HTTPException(status_code=401, detail="Wrong password")
    if not mpesa_paid.get(key, False):
        return {"status": "payment_required", "message": "Please complete M-Pesa payment KES 299 to continue"}
    return {"status": "logged_in", "user": users_db[key], "message": f"Welcome back {data.name}! What would you like to do today? Assess BP, Sugar levels, or Weight?"}

@app.post("/reading")
def add_reading(r: Reading):
    key = r.user_name.strip().lower()
    if key not in users_db or not mpesa_paid.get(key, False):
        raise HTTPException(status_code=403, detail="Login and pay first")
    
    readings_db.append(r.model_dump())
    user_weight = r.weight or users_db[key].get("weight", 70)

    if r.type == "bp":
        msg = advice_for_bp(r.systolic, r.diastolic, r.pulse)
    elif r.type == "sugar":
        msg = advice_for_sugar(r.glucose)
    elif r.type == "weight":
        msg = advice_for_weight(r.weight)
    else:
        msg = "Please select BP, Sugar, or Weight."

    return {"saved": True, "advice": msg, "next": "Choose Walk or My Nutrition"}

@app.get("/nutrition/{name}/{day}")
def get_nutrition(name: str, day: str):
    key = name.strip().lower()
    # Find last sugar reading for this user
    last_glu = None
    for rec in reversed(readings_db):
        if rec["user_name"].lower() == key and rec.get("glucose"):
            last_glu = rec["glucose"]
            break
    return nutrition_for_sugar(last_glu or 95, day)

@app.post("/walk/complete")
def walk_complete(data: WalkComplete):
    key = data.user_name.strip().lower()
    user = users_db.get(key, {})
    weight = user.get("weight", data.user_name and 70) or 70
    # Engine: calories = MET * weight * hours. Approx walking 0.78 factor + steps 0.04
    calories_steps = data.steps * 0.04
    calories_time = weight * (data.miles * 1.6) * 0.78 * (data.duration_min / 60) * 2
    calories = int((calories_steps + calories_time)/2)
    if calories < 50:
        calories = int(data.miles * 90)

    if data.miles >= 2:
        praise = f"HONGERA SANA {data.user_name}! You conquered {data.miles} miles, {data.steps} steps in {data.duration_min} min! You burned {calories} calories! You are stronger than yesterday. I am very proud of you! Rest, drink water."
    else:
        praise = f"Excellent {data.user_name}! {data.miles} miles done, {data.steps} steps, {calories} calories burned in {data.duration_min} minutes! Every step counts. See you tomorrow for more!"

    return {"celebration": praise, "steps": data.steps, "calories": calories, "miles": data.miles}

@app.get("/progress/{name}")
def progress(name: str):
    key = name.strip().lower()
    my = [r for r in readings_db if r["user_name"].lower() == key]
    return {"name": name, "total_readings": len(my), "readings": my[-10:]}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
