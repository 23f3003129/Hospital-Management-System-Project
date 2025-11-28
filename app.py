from flask import Flask, render_template, redirect, request, session, flash, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, date, timedelta, time
from sqlalchemy import or_, and_, func


# App and DB Setup


PREDEFINED_SLOTS = [
    time(9, 0),
    time(11, 0),
    time(13, 0),
    time(15, 0),
]


def create_app():
    app = Flask(__name__)
    app.config.from_pyfile("config.py")
    return app


app = create_app()

db = SQLAlchemy()
db.init_app(app)

migrate = Migrate(app, db)

# Models



class User(db.Model):
    __tablename__ = "User"
    uid = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(110), unique=True, nullable=False)
    password = db.Column(db.String(130), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    is_blacklisted = db.Column(db.Boolean, nullable=False, default=False)
    specialization = db.Column(db.String, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('Role.rid'), nullable=False)
    role = db.relationship('Role', backref='users')


class Role(db.Model):
    __tablename__ = "Role"
    rid = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))


class Appointment(db.Model):
    __tablename__ = "Appointment"
    aid = db.Column(db.Integer, primary_key=True, autoincrement=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('User.uid'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('User.uid'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('AvailableSlot.sid'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="booked")
    diagnosis = db.Column(db.Text, nullable=True)
    prescription = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    reason = db.Column(db.String(250), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    patient = db.relationship('User', foreign_keys=[patient_id], backref='appointments_as_patient')
    doctor = db.relationship('User', foreign_keys=[doctor_id], backref='appointment_as_doctor')
    slot = db.relationship('AvailableSlot', backref='appointment')

    def __repr__(self):
        return f"<Appointment doctor = {self.doctor_id} patient = {self.patient_id}, slot = {self.slot_id} status = {self.status}>"


class AvailableSlot(db.Model):
    __tablename__ = 'AvailableSlot'
    sid = db.Column(db.Integer, primary_key=True, autoincrement=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('User.uid'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    is_booked = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    doctor = db.relationship('User', backref='available_slots')
    __table_args__ = (db.UniqueConstraint('doctor_id', 'date', 'time', name='uix_doctor_slot'),)

    def __repr__(self):
        return f"<Slot {self.date} {self.time} doctor={self.doctor_id} booked={self.is_booked}>"



# Helper Functions 


def auto_mark_missed():
    now = datetime.now()
    today = now.date()
    current_time = now.time()

    q = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(Appointment.status == "booked")
        .filter(
            or_(
                AvailableSlot.date < today,
                and_(AvailableSlot.date == today, AvailableSlot.time < current_time)
            )
        )
    )

    updated = 0
    for appt in q.all():
        appt.status = "missed"
        updated += 1

    if updated:
        db.session.commit()
    return updated


def ensure_future_slots(doctor_id, days_ahead=7):
    today = date.today()
    created = 0

    for i in range(days_ahead):
        slot_date = today + timedelta(days=i)
        for slot_time in PREDEFINED_SLOTS:
            existing = AvailableSlot.query.filter_by(
                doctor_id=doctor_id,
                date=slot_date,
                time=slot_time
            ).first()
            if not existing:
                db.session.add(AvailableSlot(
                    doctor_id=doctor_id,
                    date=slot_date,
                    time=slot_time,
                    is_booked=False
                ))
                created += 1

    if created:
        db.session.commit()
    return created


def cleanup_old_slots(doctor_id=None):
    now = datetime.now()
    today = now.date()
    current_time = now.time()

    q = AvailableSlot.query
    if doctor_id is not None:
        q = q.filter(AvailableSlot.doctor_id == doctor_id)

    q = q.filter(
        or_(
            AvailableSlot.date < today,
            and_(AvailableSlot.date == today, AvailableSlot.time < current_time)
        ),
        AvailableSlot.is_booked == False
    )

    deleted = 0
    for slot in q.all():
        if not getattr(slot, 'appointment', None):
            db.session.delete(slot)
            deleted += 1

    if deleted:
        db.session.commit()
    return deleted



# (home, signup, login, logout)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/signup", methods=['GET', 'POST'])
def signup():
    if request.method == "GET":
        return render_template("signup.html")
    else:
        name = (request.form.get("name") or "").strip()
        age_str = (request.form.get("age") or "").strip()
        gender = (request.form.get("gender") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not name or not age_str or not gender or not email or not password:
            flash("All fields are required.")
            return redirect("/signup")

        try:
            age_val = int(age_str)
        except ValueError:
            flash("Age must be a number.")
            return redirect("/signup")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("User already exist. Please Login or use a different email")
            return redirect("/signup")

        patient_role = Role.query.filter_by(role_name="Patient").first()
        if not patient_role:
            flash("Default role not found in database. Please contact admin.")
            return redirect("/signup")

        new_user = User(
            name=name,
            age=age_val,
            gender=gender,
            email=email,
            password=password,
            role=patient_role
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Signup Successful. Please Login")
        return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    else:
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if not user:
            flash("User does not exist. Please signup first")
            return redirect("/signup")
        if user.password != password:
            flash("Incorrect Password. Please try again")
            return redirect("/login")
        if user.is_blacklisted:
            flash("Your account has been blocked. Please contact the admin.")
            return redirect("/login")

        session["uid"] = user.uid
        session["name"] = user.name

        if user.role.role_name == "Admin":
            return redirect("/admindashboard")
        elif user.role.role_name == "Doctor":
            return redirect("/doctordashboard")
        else:
            return redirect("/userdashboard")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect("/login")



# PATIENT ROUTES


@app.route("/userdashboard")
def userdashboard():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    auto_mark_missed()
    return render_template("userdashboard.html", name=user.name)


@app.route("/patient/profile")
def patient_profile():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    return render_template("patient_profile.html", patient=user)


@app.route("/patient/profile/edit", methods=["GET", "POST"])
def patient_profile_edit():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    patient = User.query.get(session["uid"])
    if not patient or patient.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    if request.method == "GET":
        return render_template("patient_profile_edit.html", patient=patient)

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    age = request.form.get("age")
    gender = (request.form.get("gender") or "").strip()

    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_new_password = request.form.get("confirm_new_password") or ""

    if not name or not email:
        flash("Name and Email are required.")
        return redirect("/patient/profile/edit")

    try:
        age_val = int(age) if age not in (None, "") else None
    except ValueError:
        flash("Age must be a number.")
        return redirect("/patient/profile/edit")

    existing = User.query.filter_by(email=email).first()
    if existing and existing.uid != patient.uid:
        flash("This email is already in use by another user.")
        return redirect("/patient/profile/edit")

    patient.name = name
    patient.email = email
    if age_val is not None:
        patient.age = age_val
    if gender:
        patient.gender = gender

    if any([current_password, new_password, confirm_new_password]):
        if not (current_password and new_password and confirm_new_password):
            flash("To change password, fill current, new, and confirm password.")
            return redirect("/patient/profile/edit")
        if patient.password != current_password:
            flash("Current password is incorrect.")
            return redirect("/patient/profile/edit")
        if new_password != confirm_new_password:
            flash("New password and confirmation do not match.")
            return redirect("/patient/profile/edit")
        patient.password = new_password

    db.session.commit()
    session["name"] = patient.name
    flash("Profile updated successfully.")
    return redirect("/patient/profile")


@app.route("/patient/departments")
def patient_departments():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    specs = (
        User.query.join(Role)
        .filter(
            Role.role_name == "Doctor",
            User.is_blacklisted == False,
            User.specialization.isnot(None)
        )
        .with_entities(User.specialization)
        .distinct()
        .all()
    )
    departments = [s[0] for s in specs if s[0]]

    return render_template("patient_departments.html", departments=departments)


@app.route("/patient/departments/<specialization>")
def patient_doctors_by_spec(specialization):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    doctors = (
        User.query.join(Role)
        .filter(
            Role.role_name == "Doctor",
            User.is_blacklisted == False,
            User.specialization == specialization
        )
        .order_by(User.name)
        .all()
    )

    return render_template(
        "patient_doctors_by_spec.html",
        specialization=specialization,
        doctors=doctors
    )


@app.route("/patient/doctor/<int:doctor_id>/profile")
def patient_doctor_profile(doctor_id):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    doctor = User.query.get_or_404(doctor_id)
    if doctor.role.role_name != "Doctor" or doctor.is_blacklisted:
        flash("Doctor not available.")
        return redirect("/patient/departments")

    today = date.today()

    total_appointments = Appointment.query.filter_by(doctor_id=doctor.uid).count()
    completed_appointments = Appointment.query.filter_by(
        doctor_id=doctor.uid, status="completed"
    ).count()

    upcoming_appointments = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(
            Appointment.doctor_id == doctor.uid,
            Appointment.status == "booked",
            AvailableSlot.date >= today
        )
        .count()
    )

    next_free_slots = (
        AvailableSlot.query
        .filter(
            AvailableSlot.doctor_id == doctor.uid,
            AvailableSlot.date >= today,
            AvailableSlot.is_booked == False
        )
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .limit(5)
        .all()
    )

    return render_template(
        "doctor_profile_public.html",
        doctor=doctor,
        total_appointments=total_appointments,
        completed_appointments=completed_appointments,
        upcoming_appointments=upcoming_appointments,
        next_free_slots=next_free_slots
    )


@app.route("/patient/doctor/<int:doctor_id>/slots")
def patient_doctor_slots(doctor_id):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    doctor = User.query.get_or_404(doctor_id)
    if doctor.role.role_name != "Doctor" or doctor.is_blacklisted:
        flash("Doctor not available.")
        return redirect("/patient/departments")

    cleanup_old_slots(doctor.uid)
    ensure_future_slots(doctor.uid, 7)

    now = datetime.now()
    start_date = now.date()
    end_date = start_date + timedelta(days=7)

    slots = (
        AvailableSlot.query
        .filter(
            AvailableSlot.doctor_id == doctor_id,
            AvailableSlot.is_booked == False,
            AvailableSlot.date < end_date,
            or_(
                AvailableSlot.date > start_date,
                and_(
                    AvailableSlot.date == start_date,
                    AvailableSlot.time >= now.time()
                )
            )
        )
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .all()
    )

    return render_template("patient_doctor_slots.html", doctor=doctor, slots=slots)


@app.post("/patient/book/<int:slot_id>")
def patient_book(slot_id):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    patient = User.query.get(session["uid"])
    if not patient or patient.role.role_name != "Patient":
        flash("Access denied. Only patients can book.")
        return redirect("/login")

    slot = AvailableSlot.query.get_or_404(slot_id)
    doctor = User.query.get(slot.doctor_id)

    if doctor.is_blacklisted:
        flash("This doctor is not available for booking.")
        return redirect(url_for('patient_doctor_slots', doctor_id=doctor.uid))

    existing_non_cancelled = (
        Appointment.query
        .filter(
            Appointment.slot_id == slot.sid,
            Appointment.status != "cancelled"
        )
        .first()
    )

    if slot.is_booked or existing_non_cancelled:
        flash("This slot has already been booked.")
        return redirect(url_for('patient_doctor_slots', doctor_id=doctor.uid))

    appt = Appointment(
        patient_id=patient.uid,
        doctor_id=doctor.uid,
        slot_id=slot.sid,
        status="booked"
    )
    slot.is_booked = True

    db.session.add(appt)
    db.session.commit()

    flash("Appointment booked successfully.")
    return redirect(url_for('patient_doctor_slots', doctor_id=doctor.uid))


@app.route("/patient/appointments")
def patient_appointments():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    auto_mark_missed()

    today = date.today()

    appts = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(
            Appointment.patient_id == user.uid,
            AvailableSlot.date >= today,
            Appointment.status == "booked"
        )
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .all()
    )

    return render_template("patient_appointments.html", appointments=appts)


@app.post("/patient/appointment/<int:aid>/cancel")
def patient_cancel_appointment(aid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied. Only patients can cancel.")
        return redirect("/login")

    appt = Appointment.query.get_or_404(aid)
    if appt.patient_id != user.uid:
        flash("You can cancel only your own appointments.")
        return redirect(url_for("patient_appointments"))

    if appt.status.lower() == "completed":
        flash("This appointment is already completed and cannot be cancelled.")
        return redirect(url_for("patient_appointments"))
    if appt.status.lower() == "cancelled":
        flash("This appointment is already cancelled.")
        return redirect(url_for("patient_appointments"))

    slot = appt.slot
    now = datetime.now()
    slot_dt = datetime.combine(slot.date, slot.time)
    if slot_dt < now:
        flash("Cannot cancel a past appointment.")
        return redirect(url_for("patient_appointments"))

    appt.status = "cancelled"
    slot.is_booked = False
    db.session.commit()

    flash("Appointment cancelled.")
    return redirect(url_for("patient_appointments"))


@app.route("/patient/history")
def patient_history():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    patient = User.query.get(session["uid"])
    if not patient or patient.role.role_name != "Patient":
        flash("Access denied. Only patients can access this page.")
        return redirect("/login")

    history = (
        Appointment.query
        .filter_by(patient_id=patient.uid, status="completed")
        .order_by(Appointment.created_at.desc())
        .all()
    )

    return render_template("patient_history.html", history=history, patient=patient)


@app.route("/patient/search")
def patient_search_doctors():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Patient":
        flash("Access denied.")
        return redirect("/login")

    q = (request.args.get("q") or "").strip()
    doctors = []
    if q:
        like = f"%{q.lower()}%"
        doctors = (
            User.query.join(Role)
            .filter(
                Role.role_name == "Doctor",
                User.is_blacklisted == False,
                or_(
                    func.lower(User.name).like(like),
                    func.lower(User.specialization).like(like),
                )
            )
            .order_by(User.name)
            .all()
        )

    return render_template("patient_search_doctors.html", q=q, doctors=doctors)


# DOCTOR ROUTES


@app.route("/doctordashboard")
def doctordashboard():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Doctor":
        flash("Access denied. Only doctors can access this page.")
        return redirect("/login")

    auto_mark_missed()

    ensure_future_slots(user.uid, 7)
    cleanup_old_slots(user.uid)

    now = datetime.now()
    today = now.date()
    week_end = today + timedelta(days=7)

    slots = (
        AvailableSlot.query
        .filter(
            AvailableSlot.doctor_id == user.uid,
            or_(
                AvailableSlot.date > today,
                and_(
                    AvailableSlot.date == today,
                    AvailableSlot.time >= now.time()
                )
            )
        )
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .all()
    )

    appointments = Appointment.query.filter_by(doctor_id=user.uid).all()

    today_upcoming = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(
            Appointment.doctor_id == user.uid,
            Appointment.status == "booked",
            AvailableSlot.date == today,
            AvailableSlot.time >= now.time()
        )
        .order_by(AvailableSlot.time)
        .all()
    )

    week_upcoming = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(
            Appointment.doctor_id == user.uid,
            Appointment.status == "booked",
            or_(
                and_(AvailableSlot.date == today, AvailableSlot.time >= now.time()),
                AvailableSlot.date > today
            ),
            AvailableSlot.date <= week_end
        )
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .all()
    )

    patients_assigned = (
        db.session.query(User)
        .join(Appointment, Appointment.patient_id == User.uid)
        .filter(Appointment.doctor_id == user.uid)
        .distinct()
        .order_by(User.name)
        .all()
    )

    next7_free_slots = (
        AvailableSlot.query
        .filter(
            AvailableSlot.doctor_id == user.uid,
            AvailableSlot.date >= today,
            AvailableSlot.date <= week_end,
            AvailableSlot.is_booked == False
        )
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .all()
    )

    return render_template(
        "doctordashboard.html",
        doctor=user,
        slots=slots,
        appointments=appointments,
        today_upcoming=today_upcoming,
        week_upcoming=week_upcoming,
        patients_assigned=patients_assigned,
        next7_free_slots=next7_free_slots
    )


@app.route("/doctor/patient/<int:pid>")
def doctor_patient_profile(pid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    doctor = User.query.get(session["uid"])
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Access denied.")
        return redirect("/login")

    patient = User.query.get_or_404(pid)

    if patient.role.role_name != "Patient":
        flash("Not a patient.")
        return redirect("/doctordashboard")

    seen_once = Appointment.query.filter_by(
        doctor_id=doctor.uid,
        patient_id=patient.uid
    ).first()

    if not seen_once:
        flash("You can view only patients assigned to you.")
        return redirect("/doctordashboard")

    history = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(
            Appointment.patient_id == patient.uid,
            Appointment.doctor_id == doctor.uid
        )
        .order_by(AvailableSlot.date.desc(), AvailableSlot.time.desc())
        .all()
    )

    return render_template("doctor_patient_profile.html",
                           patient=patient,
                           history=history)


@app.route('/doctor/slots', methods=['GET', 'POST'])
def manage_slots():
    if 'uid' not in session:
        flash('Please login first', 'danger')
        return redirect('/login')

    doctor = User.query.get(session['uid'])
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Access denied. Only doctors can manage slots.", "danger")
        return redirect('/login')

    doctor_id = doctor.uid

    ensure_future_slots(doctor_id, 7)
    cleanup_old_slots(doctor_id)

    if request.method == 'POST' and request.form.get('manual_slot') == 'true':
        date_str = request.form.get('date')
        time_str = request.form.get('time')

        if not date_str or not time_str:
            flash("Please provide both date and time for manual slot.", "warning")
        else:
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                time_obj = datetime.strptime(time_str, '%H:%M').time()
            except ValueError:
                flash("Invalid date or time format.", "warning")
            else:
                existing = AvailableSlot.query.filter_by(
                    doctor_id=doctor_id,
                    date=date_obj,
                    time=time_obj
                ).first()
                if existing:
                    flash('Slot already exists for that time!', 'warning')
                else:
                    new_slot = AvailableSlot(
                        doctor_id=doctor_id,
                        date=date_obj,
                        time=time_obj,
                        is_booked=False
                    )
                    db.session.add(new_slot)
                    db.session.commit()
                    flash('New slot added successfully!', 'success')

    now = datetime.now()
    today = now.date()

    slots = (
        AvailableSlot.query
        .filter(
            AvailableSlot.doctor_id == doctor_id,
            or_(
                AvailableSlot.date > today,
                and_(
                    AvailableSlot.date == today,
                    AvailableSlot.time >= now.time()
                )
            )
        )
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .all()
    )

    return render_template('doctor_slots.html', slots=slots)


@app.route('/toggle_slot/<int:slot_id>')
def toggle_slot(slot_id):
    if 'uid' not in session:
        flash("Please login first.", "danger")
        return redirect('/login')

    doctor = User.query.get(session['uid'])
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Access denied. Only doctors can manage slots.", "danger")
        return redirect('/login')

    slot = AvailableSlot.query.get_or_404(slot_id)

    if slot.doctor_id != doctor.uid:
        flash("You can only modify your own slots.", "danger")
        return redirect(url_for('manage_slots'))

    has_active_appt = (
        Appointment.query
        .filter(
            Appointment.slot_id == slot.sid,
            Appointment.status != "cancelled"
        )
        .first()
    )

    if has_active_appt:
        flash("This slot has an active appointment and cannot be toggled.", "warning")
        return redirect(url_for('manage_slots'))

    slot.is_booked = not slot.is_booked
    db.session.commit()

    return redirect(url_for('manage_slots'))


@app.route('/doctor/add_slot', methods=['POST'])
def add_slot():
    if 'uid' not in session:
        flash("Please login first.", "danger")
        return redirect('/login')

    doctor = User.query.get(session['uid'])
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Access denied. Only doctors can add slots.", "danger")
        return redirect('/login')

    doctor_id = doctor.uid

    date = request.form.get('date')
    time_str = request.form.get('time')

    if not date or not time_str:
        flash("Please provide both date and time.", "warning")
        return redirect('/doctor/slots')

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        time_obj = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        flash("Invalid date or time format.", "warning")
        return redirect('/doctor/slots')

    existing_slot = AvailableSlot.query.filter_by(
        doctor_id=doctor_id, date=date_obj, time=time_obj
    ).first()
    if existing_slot:
        flash("Slot already exists for that time.", "warning")
        return redirect('/doctor/slots')

    new_slot = AvailableSlot(
        doctor_id=doctor_id,
        date=date_obj,
        time=time_obj,
        is_booked=False
    )
    db.session.add(new_slot)
    db.session.commit()

    flash("New slot added successfully!", "success")
    return redirect('/doctor/slots')


@app.route("/doctor/appointment/<int:aid>")
def doctor_appointment_detail(aid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    doctor = User.query.get(session["uid"])
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Access denied. Only doctors can access this page.")
        return redirect("/login")

    appt = Appointment.query.get_or_404(aid)
    if appt.doctor_id != doctor.uid:
        flash("You can only view your own appointments.")
        return redirect(url_for("doctordashboard"))

    if appt.status.lower() == "cancelled":
        flash("This appointment is cancelled.")
        return redirect(url_for("doctordashboard"))

    return render_template("doctor_complete_appointment.html", appt=appt)


@app.post("/doctor/appointment/<int:aid>/complete")
def doctor_complete_appointment(aid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    doctor = User.query.get(session["uid"])
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Access denied. Only doctors can complete.")
        return redirect("/login")

    appt = Appointment.query.get_or_404(aid)
    if appt.doctor_id != doctor.uid:
        flash("You can only complete your own appointments.")
        return redirect(url_for("doctordashboard"))

    if appt.status.lower() in ("completed", "cancelled"):
        flash(f"Appointment already {appt.status}.")
        return redirect(url_for("doctordashboard"))

    appt.diagnosis = request.form.get("diagnosis", "").strip()
    appt.prescription = request.form.get("prescription", "").strip()
    appt.notes = request.form.get("notes", "").strip()
    appt.status = "completed"

    db.session.commit()

    flash("Appointment marked as completed and notes saved.")
    return redirect(url_for("doctordashboard"))


@app.post("/doctor/appointment/<int:aid>/cancel")
def doctor_cancel_appointment(aid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    doctor = User.query.get(session["uid"])
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Access denied. Only doctors can cancel.")
        return redirect("/login")

    appt = Appointment.query.get_or_404(aid)
    if appt.doctor_id != doctor.uid:
        flash("You can only cancel your own appointments.")
        return redirect(url_for("doctordashboard"))

    if appt.status.lower() in ("completed", "cancelled"):
        flash(f"Appointment already {appt.status}.")
        return redirect(url_for("doctordashboard"))

    slot_dt = datetime.combine(appt.slot.date, appt.slot.time)
    if slot_dt >= datetime.now():
        appt.slot.is_booked = False

    appt.status = "cancelled"
    db.session.commit()

    flash("Appointment cancelled.")
    return redirect(url_for("doctordashboard"))



# ADMIN ROUTES


@app.route("/admindashboard")
def admindashboard():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Admin":
        flash("You are not an admin. Access Denied!!!!")
        return redirect("/login")

    auto_mark_missed()

    doctors = User.query.join(Role).filter(Role.role_name == "Doctor").all()

    doctor_count = len(doctors)
    patient_count = (
        User.query.join(Role).filter(Role.role_name == "Patient").count()
    )
    appointment_count = Appointment.query.count()

    return render_template(
        "admindashboard.html",
        doctors=doctors,
        doctor_count=doctor_count,
        patient_count=patient_count,
        appointment_count=appointment_count,
    )


@app.route("/admin/appointments")
def admin_appointments():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin = User.query.get(session["uid"])
    if not admin or admin.role.role_name != "Admin":
        flash("Access denied. Only admins.")
        return redirect("/login")

    today = date.today()

    upcoming = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .order_by(AvailableSlot.date, AvailableSlot.time)
        .filter(AvailableSlot.date >= today)
        .all()
    )

    past = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .order_by(AvailableSlot.date.desc(), AvailableSlot.time.desc())
        .filter(AvailableSlot.date < today)
        .all()
    )

    return render_template("admin_appointments.html", upcoming=upcoming, past=past, today=today)


@app.route("/admin/patients")
def admin_patients():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Admin":
        flash("Access denied.")
        return redirect("/login")

    patients = (
        User.query.join(Role)
        .filter(Role.role_name == "Patient")
        .order_by(User.name)
        .all()
    )
    return render_template("admin_patients.html", patients=patients)


@app.route("/admin/update_patient/<int:uid>", methods=["GET", "POST"])
def admin_update_patient(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    patient = User.query.get(uid)
    if not patient or patient.role.role_name != "Patient":
        flash("Patient not found.")
        return redirect("/admin/patients")

    if request.method == "GET":
        return render_template("update_patient.html", patient=patient)

    name = (request.form.get("name") or "").strip()
    age_str = (request.form.get("age") or "").strip()
    gender = (request.form.get("gender") or "").strip()
    email = (request.form.get("email") or "").strip()

    if not name or not email:
        flash("Name and email are required.")
        return redirect(f"/admin/update_patient/{uid}")

    try:
        age_val = int(age_str)
    except ValueError:
        flash("Age must be a number.")
        return redirect(f"/admin/update_patient/{uid}")

    existing = User.query.filter_by(email=email).first()
    if existing and existing.uid != patient.uid:
        flash("This email is already used by another user.")
        return redirect(f"/admin/update_patient/{uid}")

    patient.name = name
    patient.age = age_val
    patient.gender = gender
    patient.email = email

    db.session.commit()
    flash(f"Patient {patient.name}'s information updated successfully.")
    return redirect("/admin/patients")


@app.route("/blacklist_patient/<int:uid>")
def blacklist_patient(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    patient = User.query.get(uid)
    if not patient or patient.role.role_name != "Patient":
        flash("Patient not found.")
        return redirect("/admin/patients")

    patient.is_blacklisted = True
    db.session.commit()
    flash(f"Patient {patient.name} has been blacklisted.")
    return redirect("/admin/patients")


@app.route("/unblacklist_patient/<int:uid>")
def unblacklist_patient(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    patient = User.query.get(uid)
    if not patient or patient.role.role_name != "Patient":
        flash("Patient not found.")
        return redirect("/admin/patients")

    patient.is_blacklisted = False
    db.session.commit()
    flash(f"Patient {patient.name} has been unblacklisted.")
    return redirect("/admin/patients")


@app.route("/delete_patient/<int:uid>")
def delete_patient(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    patient = User.query.get(uid)
    if not patient or patient.role.role_name != "Patient":
        flash("Patient not found.")
        return redirect("/admin/patients")

    return render_template("delete_patient.html", patient=patient)


@app.route("/confirm_delete_patient/<int:uid>")
def confirm_delete_patient(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    patient = User.query.get(uid)
    if not patient or patient.role.role_name != "Patient":
        flash("Patient not found.")
        return redirect("/admin/patients")

    appt_count = Appointment.query.filter_by(patient_id=patient.uid).count()
    if appt_count > 0:
        flash("Cannot delete patient with existing appointments. Cancel/delete appointments first.")
        return redirect("/admin/patients")

    db.session.delete(patient)
    db.session.commit()
    flash(f"Patient {patient.name} deleted successfully.")
    return redirect("/admin/patients")


@app.route("/admin/doctors")
def admin_doctors():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Admin":
        flash("Access denied.")
        return redirect("/login")

    doctors = User.query.join(Role).filter(Role.role_name == "Doctor").all()
    return render_template("admin_doctors.html", doctors=doctors)


@app.route("/add_doctor", methods=["GET", "POST"])
def add_doctor():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    user = User.query.get(session["uid"])
    if not user or user.role.role_name != "Admin":
        flash("Not an Admin. Access Denied")
        return redirect("/login")

    if request.method == "GET":
        return render_template("add_doctor.html")

    name = (request.form.get("name") or "").strip()
    age_str = (request.form.get("age") or "").strip()
    gender = (request.form.get("gender") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = (request.form.get("password") or "").strip()
    specialization = (request.form.get("specialization") or "").strip()

    if not name or not age_str or not gender or not email or not password:
        flash("Name, age, gender, email, and password are required.")
        return redirect("/add_doctor")

    try:
        age_val = int(age_str)
    except ValueError:
        flash("Age must be a number.")
        return redirect("/add_doctor")

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("Doctor with this email already exists.")
        return redirect("/add_doctor")

    doctor_role = Role.query.filter_by(role_name="Doctor").first()
    if not doctor_role:
        flash("Doctor role not found in database.")
        return redirect("/add_doctor")

    new_doctor = User(
        name=name,
        age=age_val,
        gender=gender,
        email=email,
        password=password,
        specialization=specialization,
        role=doctor_role
    )

    db.session.add(new_doctor)
    db.session.commit()

    flash(f"Doctor {name} added successfully!")
    return redirect("/admindashboard")


@app.route("/blacklist/<int:uid>")
def blacklist(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    doctor = User.query.get(uid)
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Doctor not found.")
        return redirect("/admindashboard")

    doctor.is_blacklisted = True
    db.session.commit()
    flash(f"Doctor {doctor.name} has been blacklisted.")
    return redirect("/admindashboard")


@app.route("/unblacklist/<int:uid>")
def unblacklist(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    doctor = User.query.get(uid)
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Doctor not found.")
        return redirect("/admindashboard")

    doctor.is_blacklisted = False
    db.session.commit()
    flash(f"Doctor {doctor.name} has been unblacklisted.")
    return redirect("/admindashboard")


@app.route("/update_doctor/<int:uid>", methods=["GET", "POST"])
def update_doctor(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    doctor = User.query.get(uid)
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Doctor not found.")
        return redirect("/admindashboard")

    if request.method == "GET":
        return render_template("update_doctor.html", doctor=doctor)

    name = (request.form.get("name") or "").strip()
    age_str = (request.form.get("age") or "").strip()
    gender = (request.form.get("gender") or "").strip()
    email = (request.form.get("email") or "").strip()
    specialization = (request.form.get("specialization") or "").strip()

    if not name or not email:
        flash("Name and email are required.")
        return redirect(f"/update_doctor/{uid}")

    try:
        age_val = int(age_str)
    except ValueError:
        flash("Age must be a number.")
        return redirect(f"/update_doctor/{uid}")

    existing = User.query.filter_by(email=email).first()
    if existing and existing.uid != doctor.uid:
        flash("This email is already used by another user.")
        return redirect(f"/update_doctor/{uid}")

    doctor.name = name
    doctor.age = age_val
    doctor.gender = gender
    doctor.email = email
    doctor.specialization = specialization

    db.session.commit()
    flash(f"Doctor {doctor.name}'s information updated successfully.")
    return redirect("/admindashboard")


@app.route("/delete_doctor/<int:uid>")
def delete_doctor(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    doctor = User.query.get(uid)
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Doctor not found.")
        return redirect("/admindashboard")

    return render_template("delete_doctor.html", doctor=doctor)


@app.route("/confirm_delete_doctor/<int:uid>")
def confirm_delete_doctor(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin_user = User.query.get(session["uid"])
    if not admin_user or admin_user.role.role_name != "Admin":
        flash("Unauthorized access.")
        return redirect("/login")

    doctor = User.query.get(uid)
    if not doctor or doctor.role.role_name != "Doctor":
        flash("Doctor not found.")
        return redirect("/admindashboard")

    active_or_past_count = (
        Appointment.query
        .filter(
            Appointment.doctor_id == doctor.uid,
            Appointment.status != "cancelled"
        )
        .count()
    )

    if active_or_past_count > 0:
        flash(
            "Cannot delete this doctor because they have appointments"
        )
        return redirect("/admindashboard")

    cancelled_appts = Appointment.query.filter_by(
        doctor_id=doctor.uid,
        status="cancelled"
    ).all()
    for appt in cancelled_appts:
        db.session.delete(appt)

    slots = AvailableSlot.query.filter_by(doctor_id=doctor.uid).all()
    for slot in slots:
        db.session.delete(slot)

    db.session.delete(doctor)
    db.session.commit()

    flash(f"Doctor {doctor.name} deleted successfully.")
    return redirect("/admindashboard")


@app.route("/admin/analytics")
def admin_analytics():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin = User.query.get(session["uid"])
    if not admin or admin.role.role_name != "Admin":
        flash("Access denied. Only admins can view analytics.")
        return redirect("/login")

    auto_mark_missed()

    doctor_count = (
        User.query.join(Role)
        .filter(Role.role_name == "Doctor")
        .count()
    )
    patient_count = (
        User.query.join(Role)
        .filter(Role.role_name == "Patient")
        .count()
    )
    appointment_count = Appointment.query.count()

    today = date.today()
    today_appointments = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(AvailableSlot.date == today)
        .count()
    )

    first_day = today.replace(day=1)
    next_month_first = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = next_month_first - timedelta(days=1)

    month_appointments = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(AvailableSlot.date.between(first_day, last_day))
        .count()
    )

    completed_count = Appointment.query.filter_by(status="completed").count()
    cancelled_count = Appointment.query.filter_by(status="cancelled").count()
    booked_upcoming = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(Appointment.status == "booked", AvailableSlot.date >= today)
        .count()
    )

    top_departments = (
        db.session.query(User.specialization, db.func.count(Appointment.aid))
        .join(Appointment, Appointment.doctor_id == User.uid)
        .filter(User.specialization.isnot(None))
        .group_by(User.specialization)
        .order_by(db.func.count(Appointment.aid).desc())
        .limit(5)
        .all()
    )

    recent = (
        Appointment.query
        .join(User, Appointment.doctor_id == User.uid)
        .order_by(Appointment.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "admin_analytics.html",
        doctor_count=doctor_count,
        patient_count=patient_count,
        appointment_count=appointment_count,
        today_appointments=today_appointments,
        month_appointments=month_appointments,
        completed_count=completed_count,
        cancelled_count=cancelled_count,
        booked_upcoming=booked_upcoming,
        top_departments=top_departments,
        recent=recent,
        today=today,
        first_day=first_day,
        last_day=last_day
    )


@app.route("/admin/patient/<int:uid>/appointments")
def admin_patient_appointments(uid):
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin = User.query.get(session["uid"])
    if not admin or admin.role.role_name != "Admin":
        flash("Access denied. Only admins can view this page.")
        return redirect("/login")

    patient = User.query.get_or_404(uid)
    if patient.role.role_name != "Patient":
        flash("Not a patient.")
        return redirect("/admin/patients")

    appointments = (
        Appointment.query
        .join(AvailableSlot, Appointment.slot_id == AvailableSlot.sid)
        .filter(Appointment.patient_id == patient.uid)
        .order_by(AvailableSlot.date.desc(), AvailableSlot.time.desc())
        .all()
    )

    return render_template(
        "admin_patient_appointments.html",
        patient=patient,
        appointments=appointments
    )


@app.route("/admin/search/doctors")
def admin_search_doctors():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin = User.query.get(session["uid"])
    if not admin or admin.role.role_name != "Admin":
        flash("Access denied.")
        return redirect("/login")

    q = (request.args.get("q") or "").strip()
    doctors = []
    if q:
        like = f"%{q.lower()}%"
        doctors = (
            User.query.join(Role)
            .filter(
                Role.role_name == "Doctor",
                or_(
                    func.lower(User.name).like(like),
                    func.lower(User.specialization).like(like),
                    func.lower(User.email).like(like),
                )
            )
            .order_by(User.name)
            .all()
        )

    return render_template("admin_search_doctors.html", q=q, doctors=doctors)


@app.route("/admin/search/patients")
def admin_search_patients():
    if not session.get("uid"):
        flash("Please login first.")
        return redirect("/login")

    admin = User.query.get(session["uid"])
    if not admin or admin.role.role_name != "Admin":
        flash("Access denied.")
        return redirect("/login")

    q = (request.args.get("q") or "").strip()
    pid = request.args.get("pid", "").strip()
    patients = []

    base = User.query.join(Role).filter(Role.role_name == "Patient")

    conds = []
    if q:
        like = f"%{q.lower()}%"
        conds.append(
            or_(
                func.lower(User.name).like(like),
                func.lower(User.email).like(like)
            )
        )
    if pid.isdigit():
        conds.append(User.uid == int(pid))

    if conds:
        patients = base.filter(and_(*conds)).order_by(User.name).all()

    return render_template("admin_search_patients.html", q=q, pid=pid, patients=patients)





if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        roles = {
            "Admin": "Manages the hospital.",
            "Doctor": "Doctor registered in the hospital",
            "Patient": "Those who came for treatment in hospital"
        }

        for role_name, desc in roles.items():
            if not Role.query.filter_by(role_name=role_name).first():
                db.session.add(Role(role_name=role_name, description=desc))
                print(f"Added role: {role_name}")
        db.session.commit()

        admin_role = Role.query.filter_by(role_name="Admin").first()

        admin = User.query.filter_by(email="admin@hospital.com").first()

        if not admin:
            admin = User(
                email="admin@hospital.com",
                password="admin123",
                name="Admin",
                age=35,
                gender="Female",
                role=admin_role
            )
            db.session.add(admin)
            db.session.commit()
            print("Created admin user.")
        else:
            if not admin.role_id:
                admin.role_id = admin_role.rid
                db.session.commit()
                print("Fixed missing admin role link.")

    app.run(debug=True)
