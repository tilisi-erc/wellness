from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from gtts import gTTS
import os

app = FastAPI(title="Tilisi Wellness Coach API")

# --- MODELS ---
class UserRegister(BaseModel):
    name: str
    phone: str
    password: str
    weight: float = None
    height: float = None

class Reading(BaseModel):
    user_phone: str
    type: str  # pulse, balance, weight, walk
    systolic: int = None
    diastolic: int = None
    glucose: float = None
    weight: float = None
    target_miles: float = None

# In-memory DB for Pydroid 3 (use Postgres on Render later)
users_db = {}
readings_db = []

# Ensure static folder exists for gTTS
os.makedirs("static", exist_ok=True)

# --- AUDIO HELPER ---
def create_audio(text, filename):
    try:
        tts = gTTS(text=text, lang='en', slow=False)
        path = f"static/{filename}.mp3"
        tts.save(path)
        return f"/static/{filename}.mp3"
    except:
        return None

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
def home():
    # If UI file exists, serve it, else serve API welcome
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    else:
        text = "Welcome to Tilisi Wellness Coaching services. Please select a feature. Say Check Pulse, Check Balance, Check Weight, Walk with me, My Nutrition, or My Progress."
        return f"<h3>{text}</h3><p>Go to <a href='/docs'>/docs</a> to test API</p>"

@app.get("/welcome")
def welcome():
    text = "Welcome to Tilisi Wellness Coaching services. Please select a feature. Say Check Pulse, Check Balance, Check Weight, Walk with me, My Nutrition, or My Progress."
    return {"message": text, "audio_text": text, "features": ["pulse", "balance", "weight", "walk", "nutrition", "progress"]}

@app.post("/register")
def register(user: UserRegister):
    users_db[user.phone] = user.model_dump()
    audio = f"Welcome {user.name} to Tilisi Wellness Coach. Your mindful journey begins. How are you feeling today?"
    return {"status": "registered", "audio": audio, "next": "Select feature: Pulse, Balance, Weight, Walk, Nutrition"}

@app.post("/login")
def login(phone: str, password: str):
    if phone not in users_db:
        raise HTTPException(status_code=400, detail="User not found")
    return {"status": "logged_in", "audio": "Welcome back. What would you like to do today? Check Pulse, Balance, Weight, Walk, Nutrition or Progress?", "user": users_db[phone]}

@app.post("/reading")
def add_reading(r: Reading):
    readings_db.append(r.model_dump())
    
    audio_response = ""
    if r.type == "weight":
        if r.weight and r.weight > 0:
            dist_km = 250 / (r.weight * 0.78)
            miles = dist_km * 0.621
            audio_response = f"Asante. At {r.weight} kilos, a {int(dist_km*12)} minute walk of {miles:.1f} miles will burn about 250 calories. How many miles do you intend to cover today? Say 1, 2 or 3 miles."
        else:
            audio_response = "Please enter your weight to calculate your walk."
    
    elif r.type == "pulse":
        sys = r.systolic or 0
        if sys < 120:
            audio_response = "Beautiful flow today, calm wave. Keep hydrating and take a light walk."
        elif sys < 140:
            audio_response = "Your pulse is asking for a little ease. Let's breathe for 2 minutes, less salt today, recheck in 30 minutes. If headache or blurry vision, consider clinic today."
        else:
            audio_response = "Your body needs attention soon. Please sit and rest. If chest pain or severe headache, go to hospital now. I have prepared a summary for your doctor."
    
    elif r.type == "balance":
        glu = r.glucose or 0
        if glu < 100:
            audio_response = "Balanced morning, well done."
        elif glu < 126:
            audio_response = "Slightly elevated. Let's look at last night's plate and take a gentle walk."
        else:
            audio_response = "Needs clinical review soon. Avoid sugary drinks today. If vomiting or confusion, go to facility immediately."
    
    elif r.type == "walk":
        calories = r.weight * (r.target_miles * 1.6) * 0.78 if r.weight else (r.target_miles or 1)*150
        audio_response = f"Perfect, {r.target_miles} miles it is. I will walk with you. Starting now. I will update every half mile. Estimated burn {int(calories)} calories."

    return {"saved": True, "audio_advice": audio_response, "next_step": "walk or progress"}

@app.get("/nutrition/{day}")
def nutrition(day: str):
    weekly = {
        "monday": "Breakfast millet porridge and boiled egg. Lunch ndengu, brown ugali, sukuma. Supper grilled tilapia and matoke. Avoid mandazi and soda.",
        "tuesday": "Breakfast oats and avocado. Lunch githeri with greens. Supper chicken stew with traditional veg. Avoid chips and white bread.",
        "wednesday": "Breakfast sweet potato + tea no sugar. Lunch beans + brown rice. Supper lean beef + kales.",
        "thursday": "Breakfast fermented porridge + groundnuts. Lunch fish + ugali. Supper vegetable soup.",
        "friday": "Breakfast arrow roots + egg. Lunch green grams + chapati. Supper tilapia + greens.",
        "saturday": "Breakfast oats + banana. Lunch traditional veg + ugali. Supper chicken stew.",
        "sunday": "Breakfast millet + milk. Lunch pilau with lots veg. Supper light soup + fruit."
    }
    text = weekly.get(day.lower(), "Balanced plate: Half vegetables, quarter protein, quarter whole grain, plus water.")
    return {"day": day, "plan": text, "audio": text, "avoid": "Sugary drinks, deep fried foods, excess salt"}

@app.post("/walk/complete")
def walk_complete(phone: str, miles: float, steps: int, duration: int):
    calories = steps * 0.04
    audio = f"Hongera! You did it! {miles} miles completed, {steps} steps, {int(calories)} calories in {duration} minutes! You walked more than yesterday! I am proud of you!"
    return {"celebration_audio": audio, "steps": steps, "calories": int(calories)}

@app.post("/logout")
def logout(phone: str):
    return {"status": "logged_out", "audio": "Thank you for taking care of yourself today with Tilisi Wellness Coach. See you tomorrow. Kwaheri."}

# For Render deployment
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)