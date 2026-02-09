from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import bcrypt
from bson.objectid import ObjectId

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# MongoDB
client = MongoClient(os.getenv("MONGO_URI"))
db = client.fitness_db
users = db.users

# Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.username = user_data["username"]
        self.profile = user_data.get("profile", {})

@login_manager.user_loader
def load_user(user_id):
    user_data = users.find_one({"_id": ObjectId(user_id)})
    return User(user_data) if user_data else None

# Kerala/India specific data
KERALA_LOW_BUDGET_PROTEIN = [
    "Lentils (Dal - Moong, Toor, Urad)", "Chickpeas (Kadala)", "Black-eyed peas",
    "Soya chunks", "Eggs (if non-veg)", "Fish (Sardine/Mackerel - cheap & common in Kerala)",
    "Peanuts", "Curd/Yogurt", "Paneer (small amounts)"
]

MIDDLE_BUDGET = KERALA_LOW_BUDGET_PROTEIN + [
    "Whey protein (MuscleBlaze / AS-IT-IS / Optimum Nutrition)", "Greek yogurt", "Chicken breast"
]

ADVANCED_SUPPS = MIDDLE_BUDGET + [
    "Whey protein isolate", "Creatine monohydrate (Nutrabay / MuscleBlaze)", "BCAAs", "Multivitamin"
]

WORKOUT_PLAN = {
    "Monday": {"Gym": ["Bench Press 4×8-10", "Incline DB Press 3×10", "Chest Fly 3×12", "Dips 3×max"],
               "Home": ["Push-ups 4×max", "Incline Push-ups (feet elevated) 3×10", "Dumbbell Floor Press (if dumbbells) 3×12", "Pike Push-ups"]},
    "Tuesday": {"Gym": ["Deadlift 4×6", "Pull-ups/Lat Pulldown 4×8", "Barbell Row 3×10"],
               "Home": ["Dumbbell Rows (or inverted rows) 4×10", "Superman holds 3×20s", "Bodyweight Inverted Row (table)"]},
    # ... add other days similarly
    "Wednesday": {"Gym": ["Overhead Press 4×8", "Lateral Raises 3×12", "Rear Delt Fly"],
                  "Home": ["Pike Push-ups / Handstand holds", "Dumbbell Lateral Raises", "Reverse Fly (light DB)"]},
    "Thursday": {"Gym": ["Squats 4×8", "Leg Press 3×10", "Lunges 3×12"],
                 "Home": ["Bodyweight Squats 4×20", "Bulgarian Split Squats 3×10", "Walking Lunges"]},
    "Friday": {"Gym": ["Bicep Curls 3×12", "Tricep Dips/Extensions 3×12", "Hammer Curls"],
               "Home": ["Dumbbell Curls (or water bottles)", "Chair Dips", "Close-grip Push-ups"]},
    "Saturday": {"Gym/Home": ["Rest or Light Cardio"]},
    "Sunday": {"Gym/Home": ["Rest or Active Recovery"]},
}

@app.route('/')
@login_required
def index():
    today = datetime.now().strftime("%A")
    day_plan = WORKOUT_PLAN.get(today, {"Gym/Home": ["Rest Day"]})
    equipment = current_user.profile.get("equipment", "none")
    location = current_user.profile.get("location", "Gym")
    plan_type = "Home" if location == "Home" else "Gym"
    if equipment == "none" and plan_type == "Home":
        plan_type = "Home"  # fallback to bodyweight

    workouts = day_plan.get(plan_type, day_plan.get("Gym/Home", ["No plan"]))

    # Protein tracking (last 7 days score)
    protein_logs = list(db.protein_logs.find({"user_id": current_user.id}))
    weekly_protein = sum(log["amount"] for log in protein_logs if log["date"] >= datetime.now() - timedelta(days=7))
    target_week = current_user.profile.get("protein_target", 120) * 7
    score = min(100, int((weekly_protein / target_week) * 100)) if target_week > 0 else 0

    return render_template('index.html', 
                           user=current_user, 
                           today=today, 
                           workouts=workouts, 
                           score=score,
                           protein_target=current_user.profile.get("protein_target"),
                           suggestions=current_user.profile.get("food_suggestions", []))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        user_data = users.find_one({"username": username})
        if user_data and bcrypt.checkpw(password, user_data['password'].encode('utf-8')):
            user = User(user_data)
            login_user(user)
            if "profile" not in user_data or not user_data["profile"]:
                return redirect(url_for('profile_setup'))
            return redirect(url_for('index'))
        flash("Invalid credentials")
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        if users.find_one({"username": username}):
            flash("Username exists")
            return redirect(url_for('signup'))
        password = bcrypt.hashpw(request.form['password'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user_id = users.insert_one({
            "username": username,
            "password": password,
            "profile": {}
        }).inserted_id
        user = User(users.find_one({"_id": user_id}))
        login_user(user)
        return redirect(url_for('profile_setup'))
    return render_template('signup.html')

@app.route('/profile_setup', methods=['GET', 'POST'])
@login_required
def profile_setup():
    if request.method == 'POST':
        age = int(request.form.get('age', 0))
        name = request.form['name']
        height = float(request.form.get('height', 0))  # cm
        weight = float(request.form.get('weight', 0))  # kg
        country = request.form['country']
        state = request.form['state']
        budget = request.form['budget']
        location = request.form['location']
        equipment = request.form.get('equipment', 'none')

        protein_g_per_kg = 1.6
        protein_target = round(weight * protein_g_per_kg)

        suggestions = KERALA_LOW_BUDGET_PROTEIN
        if budget == "middle":
            suggestions = MIDDLE_BUDGET
        elif budget == "advanced":
            suggestions = ADVANCED_SUPPS

        if state.lower() != "kerala" or country.lower() != "india":
            suggestions = ["Generic high-protein: Eggs, Chicken, Lentils, Paneer, Whey"]  # fallback

        users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {
                "profile": {
                    "name": name,
                    "age": age,
                    "height": height,
                    "weight": weight,
                    "protein_target": protein_target,
                    "budget": budget,
                    "location": location,
                    "equipment": equipment,
                    "food_suggestions": suggestions[:8]  # limit display
                }
            }}
        )
        return redirect(url_for('index'))
    return render_template('profile_setup.html')

@app.route('/log_food', methods=['GET', 'POST'])
@login_required
def log_food():
    if request.method == 'POST':
        food = request.form['food']
        amount = float(request.form.get('amount', 0))  # grams protein
        db.protein_logs.insert_one({
            "user_id": current_user.id,
            "food": food,
            "amount": amount,
            "date": datetime.now()
        })
        flash("Food logged!")
    return render_template('log_food.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
